"""EVAL-20 (P07 part 2/2): label-free block-movement study over frozen evaluation bundles.

    python backend/scripts/value_add_eval.py plan  --bundle DIR [--bundle DIR ...] --model P:M [...]
    python backend/scripts/value_add_eval.py run   (same inputs) [--live] [--max-calls N] [--allow-unpinned]
    python backend/scripts/value_add_eval.py score --study-id ID

Each target of each bundle (EVAL-19, re-hashed on load) is re-asked under the arms
floor (question + criteria + as_of), floor_sc (K=3 closed-book samples at temperature
0.7, pooled: a compute-matched cheap control), R (dossier + brief + forecast inputs),
R+Q / R+G / R+S / R+M (one extra block), FULL (R + every available extra block) and
FULL_AA (an independent replicate of FULL), EVAL_ARM_REPLICATES times each, with one
canonical probe prompt (temperature 0.25, max_tokens 1024). An arm that needs a block
the bundle marks unavailable is skipped with the reason, never substituted.
app/services/value_add_stats scores how far each block moves the forecast beyond the
A/A noise floor; nothing is applied or promoted.

plan prints the exact call count and makes no call. run needs VALUE_ADD_EVAL_ENABLED or
--live, refuses a plan over EVAL_STUDY_MAX_CALLS unless --max-calls covers it, disables
the LLM cache, pre-registers study.json before the first call (its sha is stamped on
every row) and resumes ok rows with the same prompt hash. score refuses an edited
study.json and marks the study invalid when any elicitation was served from a cache.
Outputs only under evaluation_ledger_dir()/value_add/<study_id>/: study.json,
elicitations.jsonl, run_meter.jsonl, scores.json, report.md.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import eval_bundle, value_add_stats as vas  # noqa: E402
from app.utils.atomic import write_json_atomic, write_text_atomic  # noqa: E402
from app.utils.canonical_json import canonical_json_sha256  # noqa: E402

STUDY_SCHEMA = "drf.value_add_study.v1"
SCORES_SCHEMA = "drf.value_add_scores.v1"
PROMPT_VERSION = "drf-value-add-probe/v1"
ARMS = (vas.ARM_FLOOR, vas.ARM_FLOOR_SC, vas.ARM_R, "R+Q", "R+G", "R+S", "R+M", vas.ARM_FULL, vas.ARM_FULL_AA)
R_BLOCKS = ("dossier", "brief", "forecast_inputs")
EXTRA_BLOCKS = {"Q": "quant", "G": "graph", "S": "sim", "M": "market"}
BLOCK_ORDER = ("dossier", "brief", "forecast_inputs", "quant", "graph", "sim", "market")
BLOCK_TITLES = {"dossier": "Research dossier", "brief": "Situation brief", "forecast_inputs": "Forecast inputs",
                "quant": "Quantitative facts", "graph": "Knowledge-graph facts as of the date",
                "sim": "Simulation signals (model projection, not evidence)",
                "market": "Prediction-market signals"}
FLOOR_SC_K = 3
TEMPERATURE = 0.25
FLOOR_SC_TEMPERATURE = 0.7
MAX_TOKENS = 1024
P_MIN, P_MAX = 0.01, 0.99
MIN_REPLICATES = 3
EXIT_REFUSED = 2
EXIT_STUDY_MISMATCH = 3
_PINNED_CLI_MODEL_RE = re.compile(r"^(?:claude|opus|sonnet|haiku)", re.I)


# ------------------------------------------------------------------ study plan
def _out_root(args: argparse.Namespace) -> str:
    if getattr(args, "out_root", None):
        return args.out_root
    from app.services.forecast_ledger import evaluation_ledger_dir
    return os.path.join(evaluation_ledger_dir(), "value_add")


def _bundle_dirs(args: argparse.Namespace) -> List[str]:
    dirs = list(args.bundle or [])
    root = getattr(args, "bundles_root", None)
    if root:
        for report in sorted(os.listdir(root)):
            candidate = os.path.join(root, report, eval_bundle.BUNDLE_DIRNAME)
            if os.path.exists(os.path.join(candidate, eval_bundle.MANIFEST_NAME)):
                dirs.append(candidate)
    return dirs


def arm_blocks(arm: str, statuses: Dict[str, str]) -> Tuple[Optional[Tuple[str, ...]], Optional[str]]:
    """The blocks an arm shows, in canonical order, or ``(None, reason)`` when it needs an
    unavailable block. FULL / FULL_AA show R plus every available extra block."""
    ok = {name for name, status in statuses.items() if status == eval_bundle.STATUS_OK}
    if arm in (vas.ARM_FLOOR, vas.ARM_FLOOR_SC):
        return (), None
    missing = [b for b in R_BLOCKS if b not in ok]
    if missing:
        return None, "unavailable:" + ",".join(missing)
    if arm == vas.ARM_R:
        chosen = set(R_BLOCKS)
    elif arm.startswith("R+"):
        block = EXTRA_BLOCKS[arm[2:]]
        if block not in ok:
            return None, f"unavailable:{block}"
        chosen = set(R_BLOCKS) | {block}
    else:
        chosen = set(R_BLOCKS) | {b for b in EXTRA_BLOCKS.values() if b in ok}
    return tuple(b for b in BLOCK_ORDER if b in chosen), None


def build_study(args: argparse.Namespace) -> Dict[str, Any]:
    """The pre-registered study: arms, models, replicates, bundles with their target ids
    and pre-market probabilities (every bundle re-hashed: a tampered one aborts)."""
    replicates = int(getattr(args, "replicates", None) or getattr(Config, "EVAL_ARM_REPLICATES", 3))
    per_bundle = int(getattr(args, "targets_per_bundle", None) or getattr(Config, "EVAL_TARGETS_PER_BUNDLE", 2))
    bundles = []
    for path in _bundle_dirs(args):
        manifest = eval_bundle.load_bundle(path)[0]
        targets = (manifest.get("targets") or [])[:per_bundle]
        bundles.append({
            "bundle_dir": os.path.abspath(path),
            "bundle_sha256": manifest["bundle_sha256"],
            "report": (manifest.get("ids") or {}).get("report"),
            "as_of": manifest.get("as_of"),
            "statuses": {name: meta.get("status") for name, meta in manifest["blocks"].items()},
            "targets": [t["target_id"] for t in targets],
            "pre_market": {t["target_id"]: t.get("pre_market_probability") for t in targets},
        })
    study = {
        "schema": STUDY_SCHEMA,
        "prompt_version": PROMPT_VERSION,
        "arms": list(ARMS),
        "models": sorted(dict.fromkeys(args.model or [])),
        "replicates": replicates,
        "floor_sc_k": FLOOR_SC_K,
        "seed": vas.BOOTSTRAP_SEED,
        "bundles": bundles,
    }
    study["study_id"] = getattr(args, "study_id", None) or "va_" + canonical_json_sha256(study)[:12]
    return study


def planned_calls(study: Dict[str, Any]) -> Dict[str, Any]:
    """Exact model calls of a study and the arms skipped (with reasons)."""
    total, skipped = 0, []
    for bundle in study["bundles"]:
        for target in bundle["targets"]:
            for arm in study["arms"]:
                blocks, reason = arm_blocks(arm, bundle["statuses"])
                if blocks is None:
                    skipped.append({"bundle": bundle["bundle_sha256"][:12], "target": target, "arm": arm,
                                    "reason": reason})
                    continue
                per = study["floor_sc_k"] if arm == vas.ARM_FLOOR_SC else 1
                total += per * study["replicates"] * len(study["models"])
    return {"calls": total, "skipped_arms": skipped}


def study_sha(study: Dict[str, Any]) -> str:
    return canonical_json_sha256({k: v for k, v in study.items() if k != "created_at"})


# ------------------------------------------------------------------ prompt and parse
def build_messages(target: Dict[str, Any], as_of: Any, texts: Dict[str, Optional[str]],
                   blocks: Sequence[str]) -> List[Dict[str, str]]:
    """The canonical probe: question first, then the arm's blocks in canonical order."""
    parts = [f"Question: {target.get('statement')}",
             f"Resolution criteria: {target.get('resolution_criteria')}",
             f"Resolution date: {target.get('resolution_date') or 'not stated'}"]
    for name in blocks:
        parts.append(f"[{BLOCK_TITLES[name]}]\n{texts[name]}")
    parts.append('Reply with JSON only: {"probability": <probability between 0 and 1 that the question '
                 'resolves YES>, "rationale": "<at most 120 words>"}')
    system = (f"You are a careful forecaster. Today is {as_of}. Use only the material given and "
              "information available on that date.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def parse_probability(reply: Any) -> Optional[float]:
    """``reply['probability']`` clamped to [0.01, 0.99]; None (parse_failed) otherwise, never 0.5."""
    value = reply.get("probability") if isinstance(reply, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        scale = 100.0 if text.endswith("%") else 1.0
        try:
            value = float(text.rstrip("%").strip()) / scale
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return None
    if not 0.0 <= float(value) <= 1.0:
        return None
    return min(P_MAX, max(P_MIN, float(value)))


# ------------------------------------------------------------------ clients
def build_client(model_spec: str) -> Any:
    """``provider:model`` → a pinned, cache-free client (critic amendment: keywords only;
    the default provider keeps its configured key and endpoint)."""
    from app.utils.llm_client import LLMClient
    provider, _, model = str(model_spec).partition(":")
    provider = provider.strip().lower()
    if not provider or provider == str(Config.LLM_PROVIDER or "").strip().lower():
        return LLMClient(model=model or None, pinned=True, use_cache=False)
    from app.services.forecast_extractor import _build_ensemble_client
    client = _build_ensemble_client(provider)
    if model:
        client.model = model
    client._pinned = True
    client.use_cache = False
    return client


def _is_cli_provider(provider: str) -> bool:
    meta = (getattr(Config, "PROVIDER_META", {}) or {}).get(provider) or {}
    return bool(meta) and not meta.get("openai_compat")


def _cached(client: Any) -> bool:
    meta_fn = getattr(client, "last_call_meta", None)
    meta = meta_fn() if callable(meta_fn) else None
    return isinstance(meta, dict) and meta.get("served_by") == "cache"


def _usage(client: Any) -> Tuple[Optional[int], Optional[int]]:
    meta_fn = getattr(client, "last_call_meta", None)
    meta = meta_fn() if callable(meta_fn) else None
    usage = meta.get("usage") if isinstance(meta, dict) else None
    if not isinstance(usage, dict):
        return None, None
    return usage.get("prompt_tokens"), usage.get("completion_tokens")


# ------------------------------------------------------------------ files
def _study_dir(args: argparse.Namespace, study_id: str) -> str:
    return os.path.join(_out_root(args), study_id)


def _append_row(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_rows(path: str) -> List[Dict[str, Any]]:
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


# ------------------------------------------------------------------ commands
def cmd_plan(args: argparse.Namespace) -> int:
    study = build_study(args)
    if not study["bundles"]:
        print("value_add_eval: no evaluation bundle given (--bundle / --bundles-root)", file=sys.stderr)
        return EXIT_REFUSED
    plan = planned_calls(study)
    print(json.dumps({"study_id": study["study_id"], "planned_calls": plan["calls"],
                      "max_calls": int(getattr(Config, "EVAL_STUDY_MAX_CALLS", 600)),
                      "skipped_arms": plan["skipped_arms"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace, *, client_factory: Callable[[str], Any] = build_client) -> int:
    if not (getattr(Config, "VALUE_ADD_EVAL_ENABLED", False) or args.live):
        print("value_add_eval: the study makes paid model calls; set VALUE_ADD_EVAL_ENABLED=true or pass "
              "--live. No call was made.")
        return 0
    study = build_study(args)
    if not study["bundles"]:
        print("value_add_eval: no evaluation bundle given (--bundle / --bundles-root)", file=sys.stderr)
        return EXIT_REFUSED
    plan = planned_calls(study)
    cap = int(getattr(Config, "EVAL_STUDY_MAX_CALLS", 600))
    if args.max_calls is not None:
        cap = int(args.max_calls)
    if plan["calls"] > cap:
        print(f"value_add_eval: the plan needs {plan['calls']} calls, over the cap {cap}; pass --max-calls "
              f"{plan['calls']} to allow it.", file=sys.stderr)
        return EXIT_REFUSED
    clients: Dict[str, Any] = {}
    unpinned: Dict[str, bool] = {}
    for spec in study["models"]:
        provider, _, model = spec.partition(":")
        is_unpinned = _is_cli_provider(provider.strip().lower()) and not _PINNED_CLI_MODEL_RE.match(model.strip())
        if is_unpinned and not args.allow_unpinned:
            print(f"value_add_eval: {spec}: a CLI provider needs an explicit claude/opus/sonnet/haiku model "
                  "(or --allow-unpinned)", file=sys.stderr)
            return EXIT_REFUSED
        try:
            clients[spec] = client_factory(spec)
        except ValueError as exc:   # unknown provider / no API key for it
            print(f"value_add_eval: {spec}: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        unpinned[spec] = is_unpinned

    Config.LLM_CACHE_ENABLED = False
    from app.utils.telemetry import LLMMeter, set_run_context
    run_id = "valueadd__" + study["study_id"]
    set_run_context(run_id, "eval")
    out_dir = _study_dir(args, study["study_id"])
    study_path = os.path.join(out_dir, "study.json")
    if os.path.exists(study_path):
        with open(study_path, encoding="utf-8") as f:
            existing = json.load(f)
        if study_sha(existing) != study_sha(study):
            print("value_add_eval: study.json differs from this plan; use a new --study-id", file=sys.stderr)
            return EXIT_STUDY_MISMATCH
        study = existing
    else:
        study["created_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(study_path, study)
    made = [0]
    try:
        code = _elicit(study, clients, unpinned, cap, os.path.join(out_dir, "elicitations.jsonl"), made)
    finally:
        # Every run, finished or not, records what the meter saw: score invalidates the study on
        # any call the meter counted as cached, even one whose row was never written.
        meter = LLMMeter.snapshot(run_id)
        _append_row(os.path.join(out_dir, "run_meter.jsonl"),
                    {"run_id": run_id, "at": datetime.now(timezone.utc).isoformat(), "calls_made": made[0],
                     "meter_cached_calls": int(((meter or {}).get("total") or {}).get("cached") or 0)})
    if code == 0:
        print(json.dumps({"study_id": study["study_id"], "calls_made": made[0], "out_dir": out_dir}, indent=2))
    return code


def _elicit(study: Dict[str, Any], clients: Dict[str, Any], unpinned: Dict[str, bool], cap: int,
            rows_path: str, made: List[int]) -> int:
    """Ask every (bundle, target, available arm, model, replicate) not already answered ok
    under this study's sha; one row per replicate (floor_sc pools its K samples)."""
    sha = study_sha(study)
    done = {(r.get("model_key_spec"), r.get("bundle_sha256"), r.get("target_id"), r.get("arm"),
             r.get("replicate"), r.get("prompt_sha256"))
            for r in _read_rows(rows_path) if r.get("status") == "ok" and r.get("study_sha") == sha}
    for bundle in study["bundles"]:
        manifest, texts = eval_bundle.load_bundle(bundle["bundle_dir"])
        if manifest["bundle_sha256"] != bundle["bundle_sha256"]:
            print(f"value_add_eval: bundle {bundle['bundle_dir']} changed since the study was registered",
                  file=sys.stderr)
            return EXIT_STUDY_MISMATCH
        targets = {t["target_id"]: t for t in manifest.get("targets") or []}
        for target_id in bundle["targets"]:
            target = targets[target_id]
            for arm in study["arms"]:
                blocks, _reason = arm_blocks(arm, bundle["statuses"])
                if blocks is None:
                    continue
                messages = build_messages(target, bundle["as_of"], texts, blocks)
                prompt_sha = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True)
                                            .encode("utf-8")).hexdigest()
                for spec in study["models"]:
                    client = clients[spec]
                    for replicate in range(study["replicates"]):
                        if (spec, bundle["bundle_sha256"], target_id, arm, replicate, prompt_sha) in done:
                            continue
                        samples = study["floor_sc_k"] if arm == vas.ARM_FLOOR_SC else 1
                        temperature = FLOOR_SC_TEMPERATURE if arm == vas.ARM_FLOOR_SC else TEMPERATURE
                        ps, raw, cached, tokens_in, tokens_out, failed = [], [], False, 0, 0, None
                        for _ in range(samples):
                            if made[0] >= cap:
                                print("value_add_eval: call cap reached; resume to continue", file=sys.stderr)
                                return EXIT_REFUSED
                            made[0] += 1
                            try:
                                reply = client.chat_json(messages, temperature=temperature, max_tokens=MAX_TOKENS,
                                                         label=f"value_add:{arm}")
                            except Exception as exc:  # noqa: BLE001 — recorded as a failed call
                                failed = f"call_failed:{type(exc).__name__}"
                                break
                            cached = cached or _cached(client)
                            t_in, t_out = _usage(client)
                            tokens_in += t_in or 0
                            tokens_out += t_out or 0
                            raw.append(json.dumps(reply, ensure_ascii=False, sort_keys=True))
                            p = parse_probability(reply)
                            if p is not None:
                                ps.append(p)
                        status = failed or ("ok" if ps else "parse_failed")
                        row = {
                            "study_sha": sha, "bundle_sha256": bundle["bundle_sha256"], "target_id": target_id,
                            "cluster_id": bundle["report"] or bundle["bundle_sha256"],
                            "model_key": f"{getattr(client, 'provider', spec.partition(':')[0])}:"
                                         f"{getattr(client, 'model', spec.partition(':')[2])}",
                            "model_key_spec": spec, "arm": arm, "replicate": replicate,
                            "p": round(sum(ps) / len(ps), 6) if ps and status == "ok" else None,
                            "raw_sha256": hashlib.sha256("\n".join(raw).encode("utf-8")).hexdigest(),
                            "prompt_sha256": prompt_sha, "tokens_in": tokens_in, "tokens_out": tokens_out,
                            "cached": bool(cached), "status": status,
                        }
                        if unpinned[spec]:
                            row["model_unpinned"] = True
                        _append_row(rows_path, row)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    out_dir = _study_dir(args, args.study_id)
    with open(os.path.join(out_dir, "study.json"), encoding="utf-8") as f:
        study = json.load(f)
    sha = study_sha(study)
    rows = _read_rows(os.path.join(out_dir, "elicitations.jsonl"))
    if any(r.get("study_sha") != sha for r in rows):
        print("value_add_eval: study.json was edited after elicitation (its sha no longer matches the "
              "rows); refusing to score.", file=sys.stderr)
        return EXIT_STUDY_MISMATCH
    reasons: List[str] = []
    if any(r.get("cached") for r in rows):
        reasons.append("cached_elicitation")
    if any(int(m.get("meter_cached_calls") or 0) > 0
           for m in _read_rows(os.path.join(out_dir, "run_meter.jsonl"))):
        reasons.append("meter_reported_cached_calls")
    pre_market = {}
    for bundle in study["bundles"]:
        cluster = bundle["report"] or bundle["bundle_sha256"]
        for target_id, p in (bundle.get("pre_market") or {}).items():
            pre_market[(cluster, target_id)] = p
    models = vas.score_study(
        rows, pre_market=pre_market,
        resamples=int(getattr(Config, "EVAL_BOOTSTRAP_RESAMPLES", 2000)),
        inert_margin=float(getattr(Config, "EVAL_INERT_MARGIN", 0.02)),
        fidelity_max=float(getattr(Config, "EVAL_PROBE_FIDELITY_MAX", 0.10)))
    scores = {
        "schema": SCORES_SCHEMA, "study_id": study["study_id"], "study_sha": sha,
        "valid": not reasons, "invalid_reasons": reasons,
        "characterization_only": int(study.get("replicates") or 0) < MIN_REPLICATES,
        "rows": len(rows), "models": models,
        "note": "Movement, not accuracy: inert verdicts are evidence for an owner decision, never applied.",
    }
    write_json_atomic(os.path.join(out_dir, "scores.json"), scores)
    write_text_atomic(os.path.join(out_dir, "report.md"), render_report(scores))
    print(json.dumps({"study_id": study["study_id"], "valid": scores["valid"],
                      "invalid_reasons": reasons}, indent=2))
    return 0


def render_report(scores: Dict[str, Any]) -> str:
    lines = [f"# Value-add study {scores['study_id']}", "",
             f"Valid: {scores['valid']}" + (f" ({', '.join(scores['invalid_reasons'])})"
                                             if scores["invalid_reasons"] else ""),
             f"Characterization only: {scores['characterization_only']}", "", scores["note"], ""]
    for model, block in scores["models"].items():
        lines += [f"## {model}", "",
                  f"Probe fidelity: {block['probe_fidelity']}"
                  + (" (probe not representative: verdicts are advisory)" if block["probe_not_representative"]
                     else ""),
                  f"A/A: mean {block['aa']['mean_signed']}, CI {block['aa']['ci']}", "",
                  "| Block | n targets | mean D | CI | p (Holm) | MDE | verdict |", "|---|---|---|---|---|---|---|"]
        for name, stats in block["blocks"].items():
            lines.append(f"| {name} | {stats['n_targets']} | {stats['mean_d']} | {stats['ci']} | "
                         f"{stats['p_holm']} | {stats['mde']} | {stats['verdict']} |")
        if block["evidence"]:
            lines += ["", "Evidence: " + ", ".join(block["evidence"])]
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EVAL-20 block-movement study over frozen bundles")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", cmd_plan), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--bundle", action="append", default=[], help="an eval_bundle directory (repeatable)")
        p.add_argument("--bundles-root", default=None, help="a reports directory: every <report>/eval_bundle")
        p.add_argument("--model", action="append", required=True, help="provider:model (repeatable)")
        p.add_argument("--replicates", type=int, default=None)
        p.add_argument("--targets-per-bundle", type=int, default=None)
        p.add_argument("--study-id", default=None)
        p.add_argument("--out-root", default=None)
        if name == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-calls", type=int, default=None)
            p.add_argument("--allow-unpinned", action="store_true")
        p.set_defaults(func=func)
    s = sub.add_parser("score")
    s.add_argument("--study-id", required=True)
    s.add_argument("--out-root", default=None)
    s.set_defaults(func=cmd_score)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except eval_bundle.BundleIntegrityError as exc:
        print(f"value_add_eval: bundle integrity check failed ({exc}); nothing was scored or asked.",
              file=sys.stderr)
        return EXIT_STUDY_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
