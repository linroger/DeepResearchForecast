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
--live, refuses a plan over EVAL_STUDY_MAX_CALLS unless --max-calls covers it, refuses a
CLI model the CLI would not be given (it would run the account default) unless
--allow-unpinned, disables the LLM cache and keeps the LLM meter on (this process only),
pre-registers study.json before the first call (the sha of every probe prompt, the model
each --model spec resolves to, the bootstrap seed and the scoring parameters
EVAL_INERT_MARGIN / EVAL_PROBE_FIDELITY_MAX / EVAL_BOOTSTRAP_RESAMPLES), stamps its sha on
every row, stops when the run budget (LLM_RUN_BUDGET_*) is spent and resumes ok rows with
the same prompt hash; a resume whose registration would differ (another resolved model,
other scoring knobs) is refused before any call. score refuses an edited study.json and
scores only rows of the registered design with the registered seed. It marks the study
invalid (exit 4) when any elicitation was served from a cache, the meter cannot vouch for
every answered call, or a model changed identity mid-study; a model characterization-only
when any of its registered elicitations has no ok row (every model when replicates are
below 3); and a model's verdicts advisory when a scoring knob differs from its registered
value (recorded as an override) or the provider reported more than one served model.
Outputs only under evaluation_ledger_dir()/value_add/<study_id>/ (the id is one safe path
component): study.json, elicitations.jsonl, run_meter.jsonl, scores.json, report.md.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import eval_bundle, value_add_stats as vas  # noqa: E402
from app.utils.atomic import write_json_atomic, write_text_atomic  # noqa: E402
from app.utils.canonical_json import canonical_json_sha256  # noqa: E402
from app.utils.model_provenance import CLI_DEFAULT_LABEL, MAX_SERVED_IDS, effective_model_label  # noqa: E402

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
JSON_RESPONSE_FORMAT = {"type": "json_object"}
P_MIN, P_MAX = 0.01, 0.99
MIN_REPLICATES = 3
EXIT_REFUSED = 2
EXIT_STUDY_MISMATCH = 3
EXIT_INVALID = 4
STATUS_OK = "ok"
STATUS_PARSE_FAILED = "parse_failed"
STATUS_CALL_FAILED_PREFIX = "call_failed:"
# One safe path component, so a study never writes outside evaluation_ledger_dir()/value_add/.
STUDY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# Why score marks the whole study invalid (exit 4).
INVALID_CACHED = "cached_elicitation"
INVALID_METER_CACHED = "meter_reported_cached_calls"
INVALID_METER_UNAVAILABLE = "meter_unavailable"
INVALID_IDENTITY_DRIFT = "model_identity_drift"
# Why verdicts are characterization-only: for every model, or for one model.
CHAR_REPLICATES = "replicates_below_min"
CHAR_INCOMPLETE = "incomplete"
# Why a model's verdicts are advisory (on top of value_add_stats' own reasons).
ADVISORY_SCORING_OVERRIDE = "scoring_not_preregistered"
ADVISORY_SERVED_MODEL_DRIFT = "served_model_drift"


class StudyRefused(Exception):
    """The inputs cannot form a valid study (nothing is asked or written)."""


# ------------------------------------------------------------------ study plan
def _out_root() -> str:
    """evaluation_ledger_dir()/value_add: the only directory a study writes under."""
    from app.services.forecast_ledger import evaluation_ledger_dir
    return os.path.join(evaluation_ledger_dir(), "value_add")


def checked_study_id(study_id: Any) -> str:
    """``study_id`` when it is one safe path component (1-64 letters, digits, '_', '.' or '-',
    starting with a letter or digit); StudyRefused otherwise, since an absolute or '..' id
    would put the outputs outside evaluation_ledger_dir()/value_add/."""
    text = str(study_id)
    if not STUDY_ID_PATTERN.fullmatch(text):
        raise StudyRefused(f"--study-id must be 1-64 letters, digits, '_', '.' or '-' starting with a letter "
                           f"or digit, got {study_id!r}")
    return text


def _bundle_dirs(args: argparse.Namespace) -> List[str]:
    dirs = list(args.bundle or [])
    root = getattr(args, "bundles_root", None)
    if root:
        if not os.path.isdir(root):
            raise StudyRefused(f"--bundles-root {root} is not a directory")
        for report in sorted(os.listdir(root)):
            candidate = os.path.join(root, report, eval_bundle.BUNDLE_DIRNAME)
            if os.path.exists(os.path.join(candidate, eval_bundle.MANIFEST_NAME)):
                dirs.append(candidate)
    return dirs


def _positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StudyRefused(f"{name} must be an integer >= 1, got {value!r}") from None
    if number < 1:
        raise StudyRefused(f"{name} must be >= 1, got {number}")
    return number


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
    """The pre-registered study: arms, models, replicates, bootstrap seed, scoring parameters
    and per bundle its target ids, pre-market probabilities and the sha of every probe prompt
    (every bundle re-hashed: a tampered one aborts). The same bundle given twice is kept once;
    two bundles of one report, a bundle without as_of, no bundle, no target at all, a count
    below 1, a scoring knob out of range and a path-like --study-id are refused."""
    study_id = getattr(args, "study_id", None)
    if study_id is not None:
        study_id = checked_study_id(study_id)
    scoring = _score_knobs()
    replicates = _positive_int(Config.EVAL_ARM_REPLICATES if getattr(args, "replicates", None) is None
                               else args.replicates, "replicates (--replicates / EVAL_ARM_REPLICATES)")
    per_bundle = _positive_int(Config.EVAL_TARGETS_PER_BUNDLE if getattr(args, "targets_per_bundle", None) is None
                               else args.targets_per_bundle,
                               "targets per bundle (--targets-per-bundle / EVAL_TARGETS_PER_BUNDLE)")
    bundles: List[Dict[str, Any]] = []
    seen_sha: Dict[str, str] = {}
    seen_report: Dict[str, str] = {}
    for path in _bundle_dirs(args):
        manifest, texts = eval_bundle.load_bundle(path)
        sha = manifest["bundle_sha256"]
        if sha in seen_sha:
            continue
        seen_sha[sha] = path
        report = (manifest.get("ids") or {}).get("report")
        if report is not None:
            if report in seen_report:
                raise StudyRefused(f"bundles {seen_report[report]} and {path} are both of report {report}; "
                                   "a study takes one bundle per report")
            seen_report[report] = path
        as_of = manifest.get("as_of")
        if not as_of:
            raise StudyRefused(f"bundle {path} has no as_of; the probe cannot state the date")
        statuses = {name: meta.get("status") for name, meta in manifest["blocks"].items()}
        targets = (manifest.get("targets") or [])[:per_bundle]
        prompts: Dict[str, Dict[str, str]] = {}
        for target in targets:
            for arm in ARMS:
                blocks, _reason = arm_blocks(arm, statuses)
                if blocks is not None:
                    prompts.setdefault(target["target_id"], {})[arm] = prompt_sha256(
                        build_messages(target, as_of, texts, blocks))
        bundles.append({
            "bundle_dir": os.path.abspath(path),
            "bundle_sha256": sha,
            "report": report,
            "as_of": as_of,
            "statuses": statuses,
            "targets": [t["target_id"] for t in targets],
            "pre_market": {t["target_id"]: t.get("pre_market_probability") for t in targets},
            "prompt_sha256": prompts,
        })
    if not bundles:
        raise StudyRefused("no evaluation bundle given (--bundle / --bundles-root)")
    if not any(bundle["targets"] for bundle in bundles):
        raise StudyRefused("the bundles hold no target to ask")
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
    # The auto id covers the elicitation design only. The scoring parameters here (and the
    # resolved model keys cmd_run adds) are registered in study.json and so in its sha, but not
    # in the id: a resume under changed knobs or a changed model environment meets the existing
    # study.json and is refused before any call instead of silently starting a new paid study.
    study["study_id"] = study_id or "va_" + canonical_json_sha256(study)[:12]
    study["scoring"] = scoring
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
def build_messages(target: Dict[str, Any], as_of: Any, texts: Mapping[str, Optional[str]],
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


def prompt_sha256(messages: Sequence[Mapping[str, str]]) -> str:
    return hashlib.sha256(json.dumps(list(messages), ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()


def parse_reply(text: Any) -> Optional[Dict[str, Any]]:
    """The reply's JSON object (LLMClient's own extraction: code fences, surrounding prose,
    a cut-off tail), or None."""
    from app.utils.llm_client import LLMClient
    value = LLMClient._parse_json_response(text if isinstance(text, str) else "")
    return value if isinstance(value, dict) else None


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
def _default_provider() -> str:
    return str(Config.LLM_PROVIDER or "claude-cli").strip().lower()


def split_model_spec(model_spec: str) -> Tuple[str, str]:
    """``provider:model`` → (provider, model); an empty provider is the configured LLM_PROVIDER."""
    provider, _, model = str(model_spec).partition(":")
    return provider.strip().lower() or _default_provider(), model.strip()


def build_client(model_spec: str) -> Any:
    """``provider:model`` → a pinned, cache-free client (critic amendment: keywords only;
    the default provider keeps its configured key and endpoint)."""
    from app.utils.llm_client import LLMClient
    provider, model = split_model_spec(model_spec)
    if provider == _default_provider():
        return LLMClient(model=model or None, pinned=True, use_cache=False)
    from app.services.forecast_extractor import _build_ensemble_client
    client = _build_ensemble_client(provider)
    if model:
        client.model = model
    client._pinned = True
    client.use_cache = False
    return client


def sampling_params_ignored(model_key: str) -> bool:
    """True for a CLI transport (claude-cli, codex-cli): it ignores temperature and max_tokens,
    so neither the probe's 0.25 / 1024 nor floor_sc's 0.7 is applied to its calls."""
    from app.utils.llm_client import CLI_PROVIDERS
    return str(model_key).partition(":")[0] in CLI_PROVIDERS


def model_identity(client: Any) -> Tuple[str, bool]:
    """``(provider:requested model, unpinned)`` of a built client. The model is what the
    transport actually requests (model_provenance.effective_model_label): a CLI client whose
    model the CLI is not given (codex-cli always; claude-cli unless the name passes
    claude_cli_model_arg) runs the account default, so it is keyed 'cli-default' and unpinned,
    never under the name it was configured with."""
    from app.utils.llm_client import CLI_PROVIDERS
    provider = str(getattr(client, "provider", "") or "").strip().lower()
    label = effective_model_label(provider, getattr(client, "model", None))
    return f"{provider}:{label}", provider in CLI_PROVIDERS and label == CLI_DEFAULT_LABEL


def _call_meta(client: Any) -> Dict[str, Any]:
    meta_fn = getattr(client, "last_call_meta", None)
    meta = meta_fn() if callable(meta_fn) else None
    return meta if isinstance(meta, dict) else {}


# ------------------------------------------------------------------ files
def _study_dir(study_id: str) -> str:
    return os.path.join(_out_root(), study_id)


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
    plan = planned_calls(study)
    print(json.dumps({"study_id": study["study_id"], "planned_calls": plan["calls"],
                      "max_calls": int(Config.EVAL_STUDY_MAX_CALLS), "seed": study["seed"],
                      "scoring": study["scoring"], "skipped_arms": plan["skipped_arms"]},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace, *, client_factory: Callable[[str], Any] = build_client) -> int:
    if not (Config.VALUE_ADD_EVAL_ENABLED or args.live):
        print("value_add_eval: the study makes paid model calls; set VALUE_ADD_EVAL_ENABLED=true or pass "
              "--live. No call was made.", file=sys.stderr)
        return EXIT_REFUSED
    study = build_study(args)
    plan = planned_calls(study)
    cap = int(Config.EVAL_STUDY_MAX_CALLS) if args.max_calls is None else int(args.max_calls)
    if plan["calls"] > cap:
        print(f"value_add_eval: the plan needs {plan['calls']} calls, over the cap {cap}; pass --max-calls "
              f"{plan['calls']} to allow it.", file=sys.stderr)
        return EXIT_REFUSED
    clients: Dict[str, Any] = {}
    identities: Dict[str, Tuple[str, bool]] = {}
    for spec in study["models"]:
        try:
            client = client_factory(spec)
        except ValueError as exc:   # unknown provider / no API key for it
            print(f"value_add_eval: {spec}: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        model_key, unpinned = model_identity(client)
        if unpinned and not args.allow_unpinned:
            print(f"value_add_eval: {spec}: the CLI would not be given this model and would run the account "
                  "default; name a claude*/opus/sonnet/haiku model for claude-cli (codex-cli is never "
                  "pinned) or pass --allow-unpinned", file=sys.stderr)
            return EXIT_REFUSED
        twin = next((other for other, (key, _) in identities.items() if key == model_key), None)
        if twin is not None:
            print(f"value_add_eval: {twin} and {spec} both resolve to {model_key}; pass it once",
                  file=sys.stderr)
            return EXIT_REFUSED
        clients[spec] = client
        identities[spec] = (model_key, unpinned)
    # Registered with the study: what each spec resolved to in this environment. A resume that
    # resolves a spec to another model (LLM_PROVIDER / LLM_MODEL_NAME changed) is refused below.
    study["model_keys"] = {spec: {"model_key": key, "unpinned": unpinned,
                                  "sampling_params_ignored": sampling_params_ignored(key)}
                           for spec, (key, unpinned) in identities.items()}

    Config.LLM_CACHE_ENABLED = False
    # The meter is the second witness that no call was served from a cache (score checks that
    # it saw every answered call), so it is on for this process whatever LLM_TELEMETRY_ENABLED says.
    Config.LLM_TELEMETRY_ENABLED = True
    from app.utils.telemetry import LLMMeter, set_run_context
    run_id = "valueadd__" + study["study_id"]
    out_dir = _study_dir(study["study_id"])
    study_path = os.path.join(out_dir, "study.json")
    if os.path.exists(study_path):
        try:
            with open(study_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"value_add_eval: the registered {study_path} is unreadable ({exc}); use a new --study-id",
                  file=sys.stderr)
            return EXIT_STUDY_MISMATCH
        if not isinstance(existing, dict) or study_sha(existing) != study_sha(study):
            differing = _differing_keys(existing, study) if isinstance(existing, dict) else ["the whole file"]
            print(f"value_add_eval: study.json differs from this plan in {', '.join(differing)} (inputs, probe "
                  "prompt, resolved model, scoring knobs or an edited file); restore them or use a new --study-id",
                  file=sys.stderr)
            return EXIT_STUDY_MISMATCH
        study = existing
    else:
        study["created_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(study_path, study)
    attempt = uuid.uuid4().hex
    counters = {"made": 0, "answered": 0}
    LLMMeter.reset(run_id)   # this attempt's meter record counts this attempt's calls only
    set_run_context(run_id, "eval")
    try:
        code = _elicit(study, clients, identities, cap, os.path.join(out_dir, "elicitations.jsonl"),
                       counters, attempt)
    finally:
        # Every attempt, finished or not, records what the meter saw: score invalidates the study
        # on any call the meter counted as cached, even one whose row was never written, and on
        # any attempt the meter cannot vouch for.
        total = (LLMMeter.snapshot(run_id) or {}).get("total") or {}
        _append_row(os.path.join(out_dir, "run_meter.jsonl"),
                    {"run_id": run_id, "attempt": attempt, "at": datetime.now(timezone.utc).isoformat(),
                     "calls_made": counters["made"], "calls_answered": counters["answered"],
                     "meter_calls": int(total.get("calls") or 0),
                     "meter_cached_calls": int(total.get("cached") or 0),
                     "telemetry_enabled": bool(Config.LLM_TELEMETRY_ENABLED)})
        set_run_context(None)
    if code == 0:
        print(json.dumps({"study_id": study["study_id"], "calls_made": counters["made"], "out_dir": out_dir},
                         indent=2))
    return code


def _differing_keys(registered: Mapping[str, Any], planned: Mapping[str, Any]) -> List[str]:
    """Top-level study.json keys whose registered value differs from this plan's."""
    keys = (set(registered) | set(planned)) - {"created_at"}
    return sorted(key for key in keys if registered.get(key) != planned.get(key))


def _elicit(study: Dict[str, Any], clients: Dict[str, Any], identities: Dict[str, Tuple[str, bool]], cap: int,
            rows_path: str, counters: Dict[str, int], attempt: str) -> int:
    """Ask every (bundle, target, available arm, model, replicate) not already answered ok
    under this study's sha; one row per replicate (floor_sc pools its K samples, and is ok
    only when every sample parsed), stamped with this run ``attempt``. One chat() call per
    sample and no JSON repair turn, so the cap counts one call per sample (chat()'s own
    transient-error retries aside) and every p answers the registered prompt. A spent run
    budget (BudgetExceeded, raised after the call that crossed it) stops the attempt."""
    from app.utils.telemetry import BudgetExceeded
    sha = study_sha(study)
    done = {(r.get("model_key_spec"), r.get("bundle_sha256"), r.get("target_id"), r.get("arm"),
             r.get("replicate"), r.get("prompt_sha256"))
            for r in _read_rows(rows_path) if r.get("status") == STATUS_OK and r.get("study_sha") == sha}
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
                prompt_sha = prompt_sha256(messages)
                for spec in study["models"]:
                    client = clients[spec]
                    model_key, unpinned = identities[spec]
                    for replicate in range(study["replicates"]):
                        if (spec, bundle["bundle_sha256"], target_id, arm, replicate, prompt_sha) in done:
                            continue
                        samples = study["floor_sc_k"] if arm == vas.ARM_FLOOR_SC else 1
                        temperature = FLOOR_SC_TEMPERATURE if arm == vas.ARM_FLOOR_SC else TEMPERATURE
                        ps, raw, served = [], [], set()
                        cached, tokens_in, tokens_out, failed = False, 0, 0, None
                        for _ in range(samples):
                            if counters["made"] >= cap:
                                print("value_add_eval: call cap reached; resume to continue", file=sys.stderr)
                                return EXIT_REFUSED
                            counters["made"] += 1
                            try:
                                text = client.chat(messages, temperature=temperature, max_tokens=MAX_TOKENS,
                                                   response_format=dict(JSON_RESPONSE_FORMAT))
                            except BudgetExceeded as exc:
                                print(f"value_add_eval: the run budget is spent ({exc}); stopped before the next "
                                      "call. Raise LLM_RUN_BUDGET_TOKENS / LLM_RUN_BUDGET_USD and resume to "
                                      "continue", file=sys.stderr)
                                return EXIT_REFUSED
                            except Exception as exc:  # noqa: BLE001 — recorded as a failed call
                                failed = f"{STATUS_CALL_FAILED_PREFIX}{type(exc).__name__}"
                                break
                            counters["answered"] += 1
                            meta = _call_meta(client)
                            cached = cached or meta.get("served_by") == "cache"
                            usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
                            tokens_in += usage.get("prompt_tokens") or 0
                            tokens_out += usage.get("completion_tokens") or 0
                            if meta.get("served_model"):
                                served.add(str(meta["served_model"]))
                            raw.append(text if isinstance(text, str) else "")
                            p = parse_probability(parse_reply(text))
                            if p is not None:
                                ps.append(p)
                        status = failed or (STATUS_OK if len(ps) == samples else STATUS_PARSE_FAILED)
                        row = {
                            "study_sha": sha, "attempt": attempt, "bundle_sha256": bundle["bundle_sha256"],
                            "target_id": target_id, "cluster_id": bundle["report"] or bundle["bundle_sha256"],
                            "model_key": model_key, "model_key_spec": spec, "served_models": sorted(served),
                            "arm": arm, "replicate": replicate,
                            "p": round(sum(ps) / len(ps), 6) if status == STATUS_OK else None,
                            "raw_sha256": hashlib.sha256("\n".join(raw).encode("utf-8")).hexdigest(),
                            "prompt_sha256": prompt_sha, "tokens_in": tokens_in, "tokens_out": tokens_out,
                            "cached": bool(cached), "status": status,
                        }
                        if unpinned:
                            row["model_unpinned"] = True
                        if sampling_params_ignored(model_key):
                            row["sampling_params_ignored"] = True
                        _append_row(rows_path, row)
    return 0


def _registered_model_keys(study: Mapping[str, Any]) -> Dict[str, str]:
    """``{model spec: model key}`` as the study registered them at run ({} when it did not)."""
    registered = study.get("model_keys")
    if not isinstance(registered, dict):
        return {}
    return {spec: str(entry["model_key"]) for spec, entry in registered.items()
            if isinstance(entry, dict) and entry.get("model_key")}


def select_rows(study: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The rows score uses and how much of the registered design they cover.

    Kept: ok rows of a registered (model spec, bundle, target, arm, replicate) cell whose
    prompt hash is the registered one; when a cell was answered twice the later row wins.
    Per model spec: expected cells, ok cells, missing cells, failed and parse-failed attempts
    (a later resume may have answered the cell), ok rows under another prompt
    (stale_prompt), the model keys the kept rows carry and the model ids the provider
    reported serving them (rows that report none are left out; at most MAX_SERVED_IDS are
    listed, served_model_count counts them all). identity_drift lists the specs whose kept
    rows carry more than one model key or another key than the registered one (the model
    changed mid-study); served_model_drift those whose rows report more than one served model
    (an alias such as 'sonnet' or 'gpt-4o' moved to a new snapshot, pooling two models)."""
    replicates = int(study.get("replicates") or 0)
    registered: Dict[Tuple[Any, Any, Any], str] = {}
    for bundle in study.get("bundles") or []:
        for target_id, arms in (bundle.get("prompt_sha256") or {}).items():
            for arm, sha in arms.items():
                registered[(bundle["bundle_sha256"], target_id, arm)] = sha
    counts = {spec: {"expected": len(registered) * replicates, "ok": 0, "missing": 0, "call_failed": 0,
                     "parse_failed": 0, "stale_prompt": 0, "model_keys": set(), "served_models": set()}
              for spec in study.get("models") or []}
    kept: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
    for row in rows:
        spec = row.get("model_key_spec")
        if spec not in counts:
            continue
        status = str(row.get("status") or "")
        if status.startswith(STATUS_CALL_FAILED_PREFIX):
            counts[spec]["call_failed"] += 1
            continue
        if status == STATUS_PARSE_FAILED:
            counts[spec]["parse_failed"] += 1
            continue
        cell = (row.get("bundle_sha256"), row.get("target_id"), row.get("arm"))
        replicate = row.get("replicate")
        if (status != STATUS_OK or cell not in registered or isinstance(replicate, bool)
                or not isinstance(replicate, int) or not 0 <= replicate < replicates):
            continue
        if row.get("prompt_sha256") != registered[cell]:
            counts[spec]["stale_prompt"] += 1
            continue
        kept[(spec, *cell, replicate)] = row
    for key, row in kept.items():
        entry = counts[key[0]]
        entry["ok"] += 1
        entry["model_keys"].add(str(row.get("model_key")))
        served = row.get("served_models")
        if isinstance(served, list):
            entry["served_models"].update(s for s in served if isinstance(s, str) and s)
    registered_keys = _registered_model_keys(study)
    drift, served_drift = [], []
    for spec, entry in counts.items():
        entry["missing"] = entry["expected"] - entry["ok"]
        expected_key = registered_keys.get(spec)
        if len(entry["model_keys"]) > 1 or (expected_key and entry["model_keys"]
                                            and entry["model_keys"] != {expected_key}):
            drift.append(spec)
        entry["model_keys"] = sorted(entry["model_keys"])
        served_ids = sorted(entry["served_models"])
        entry["served_models"] = served_ids[:MAX_SERVED_IDS]
        entry["served_model_count"] = len(served_ids)
        if len(served_ids) > 1:
            served_drift.append(spec)
    return {"rows": list(kept.values()), "completeness": counts,
            "complete": all(entry["missing"] == 0 for entry in counts.values()), "identity_drift": drift,
            "served_model_drift": served_drift}


def _score_knobs() -> Dict[str, Any]:
    """The scoring parameters from Config: ``{alpha, inert_margin, fidelity_max, resamples}``
    (alpha is value_add_stats.ALPHA, a code constant); StudyRefused when a knob is out of range."""
    resamples = _positive_int(Config.EVAL_BOOTSTRAP_RESAMPLES, "EVAL_BOOTSTRAP_RESAMPLES")
    margins = {"EVAL_INERT_MARGIN": float(Config.EVAL_INERT_MARGIN),
               "EVAL_PROBE_FIDELITY_MAX": float(Config.EVAL_PROBE_FIDELITY_MAX)}
    for name, value in margins.items():
        if not 0.0 <= value <= 1.0:
            raise StudyRefused(f"{name} must be within [0, 1], got {value}")
    return {"alpha": vas.ALPHA, "inert_margin": margins["EVAL_INERT_MARGIN"],
            "fidelity_max": margins["EVAL_PROBE_FIDELITY_MAX"], "resamples": resamples}


def scoring_parameters(study: Mapping[str, Any]) -> Dict[str, Any]:
    """What score uses: the current scoring knobs (validated) and the study's registered
    bootstrap seed, with ``overrides`` ({name: {registered, used}}) for every parameter that
    differs from the study's pre-registration or that it did not register; ``preregistered``
    is True only when there is none. StudyRefused when the study registers no integer seed."""
    used = _score_knobs()
    seed = study.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise StudyRefused(f"study.json registers no integer bootstrap seed (got {seed!r})")
    registered = study.get("scoring") if isinstance(study.get("scoring"), dict) else {}
    overrides = {name: {"registered": registered.get(name), "used": value}
                 for name, value in used.items() if registered.get(name) != value}
    return {**used, "seed": seed, "preregistered": not overrides, "overrides": overrides}


def meter_unavailable(rows: Sequence[Mapping[str, Any]], meters: Sequence[Mapping[str, Any]]) -> bool:
    """True when the LLM meter cannot vouch for every answered call: an attempt recorded with
    the meter off, a meter that counted fewer calls than the attempt answered (or a record
    without those counts), or elicitation rows of an attempt that left no meter record (a run
    killed before its finally block)."""
    metered = set()
    for meter in meters:
        calls, answered = meter.get("meter_calls"), meter.get("calls_answered")
        if (meter.get("telemetry_enabled") is not True or not isinstance(calls, int)
                or not isinstance(answered, int) or calls < answered):
            return True
        metered.add(meter.get("attempt"))
    return any(row.get("attempt") not in metered for row in rows)


def cmd_score(args: argparse.Namespace) -> int:
    study_id = checked_study_id(args.study_id)
    out_dir = _study_dir(study_id)
    try:
        with open(os.path.join(out_dir, "study.json"), encoding="utf-8") as f:
            study = json.load(f)
        if not isinstance(study, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        print(f"value_add_eval: no readable study.json for study {study_id} under {out_dir} ({exc})",
              file=sys.stderr)
        return EXIT_REFUSED
    sha = study_sha(study)
    rows = _read_rows(os.path.join(out_dir, "elicitations.jsonl"))
    if any(r.get("study_sha") != sha for r in rows):
        print("value_add_eval: study.json was edited after elicitation (its sha no longer matches the "
              "rows); refusing to score.", file=sys.stderr)
        return EXIT_STUDY_MISMATCH
    scoring = scoring_parameters(study)
    selection = select_rows(study, rows)
    meters = _read_rows(os.path.join(out_dir, "run_meter.jsonl"))
    reasons: List[str] = []
    if any(r.get("cached") for r in rows):
        reasons.append(INVALID_CACHED)
    if any(int(m.get("meter_cached_calls") or 0) > 0 for m in meters):
        reasons.append(INVALID_METER_CACHED)
    if meter_unavailable(rows, meters):
        reasons.append(INVALID_METER_UNAVAILABLE)
    if selection["identity_drift"]:
        reasons.append(INVALID_IDENTITY_DRIFT)
    characterization = [CHAR_REPLICATES] if int(study.get("replicates") or 0) < MIN_REPLICATES else []
    registered_keys = _registered_model_keys(study)

    def keys_of(spec: str) -> List[str]:
        entry = selection["completeness"][spec]
        return sorted(set(entry["model_keys"]) | ({registered_keys[spec]} if spec in registered_keys else set()))

    incomplete = [spec for spec, entry in selection["completeness"].items() if entry["missing"] > 0]
    model_characterization = {key: [CHAR_INCOMPLETE] for spec in incomplete for key in keys_of(spec)}
    model_advisory = {key: [ADVISORY_SERVED_MODEL_DRIFT]
                      for spec in selection["served_model_drift"] for key in keys_of(spec)}
    pre_market = {}
    for bundle in study.get("bundles") or []:
        cluster = bundle["report"] or bundle["bundle_sha256"]
        for target_id, p in (bundle.get("pre_market") or {}).items():
            pre_market[(cluster, target_id)] = p
    model_keys = {str(row.get("model_key")) for row in selection["rows"]}
    models = vas.score_study(selection["rows"], pre_market=pre_market, resamples=scoring["resamples"],
                             inert_margin=scoring["inert_margin"], fidelity_max=scoring["fidelity_max"],
                             seed=scoring["seed"], invalid=bool(reasons),
                             characterization_only=bool(characterization),
                             model_characterization=model_characterization,
                             advisory=[] if scoring["preregistered"] else [ADVISORY_SCORING_OVERRIDE],
                             model_advisory=model_advisory,
                             sampling_params_ignored={key for key in model_keys if sampling_params_ignored(key)})
    scores = {
        "schema": SCORES_SCHEMA, "study_id": study.get("study_id"), "study_sha": sha,
        "valid": not reasons, "invalid_reasons": reasons,
        "characterization_only": bool(characterization), "characterization_reasons": characterization,
        "incomplete_models": incomplete, "served_model_drift": selection["served_model_drift"],
        "scoring": scoring, "completeness": selection["completeness"],
        "rows": len(rows), "rows_scored": len(selection["rows"]), "models": models,
        "note": "Movement, not accuracy: inert verdicts are evidence for an owner decision, never applied.",
    }
    write_json_atomic(os.path.join(out_dir, "scores.json"), scores)
    write_text_atomic(os.path.join(out_dir, "report.md"), render_report(scores))
    print(json.dumps({"study_id": scores["study_id"], "valid": scores["valid"], "invalid_reasons": reasons,
                      "characterization_only": scores["characterization_only"],
                      "characterization_reasons": characterization, "incomplete_models": incomplete,
                      "scoring_preregistered": scoring["preregistered"]}, indent=2))
    return EXIT_INVALID if reasons else 0


def _scoring_line(scoring: Mapping[str, Any]) -> str:
    text = (f"Scoring: alpha {scoring['alpha']}, inert margin {scoring['inert_margin']}, probe-fidelity max "
            f"{scoring['fidelity_max']}, bootstrap resamples {scoring['resamples']}, seed {scoring['seed']}")
    if scoring["preregistered"]:
        return text + " (as pre-registered)"
    changed = "; ".join(f"{name} registered {entry['registered']}, used {entry['used']}"
                        for name, entry in scoring["overrides"].items())
    return text + f" (NOT as pre-registered: {changed}; every verdict is advisory)"


def render_report(scores: Dict[str, Any]) -> str:
    lines = [f"# Value-add study {scores['study_id']}", "",
             f"Valid: {scores['valid']}" + (f" ({', '.join(scores['invalid_reasons'])})"
                                             if scores["invalid_reasons"] else ""),
             f"Characterization only: {scores['characterization_only']}"
             + (f" ({', '.join(scores['characterization_reasons'])})" if scores["characterization_reasons"] else ""),
             "Incomplete models (characterization only): " + (", ".join(scores["incomplete_models"]) or "none"),
             _scoring_line(scores["scoring"]),
             "", scores["note"], "", "## Completeness", "",
             "| Model spec | expected | ok | missing | call_failed attempts | parse_failed attempts "
             "| stale prompt | model keys | served models |", "|---|---|---|---|---|---|---|---|---|"]
    for spec, entry in scores["completeness"].items():
        served = ", ".join(entry["served_models"])
        if entry["served_model_count"] > len(entry["served_models"]):
            served += f" (+{entry['served_model_count'] - len(entry['served_models'])} more)"
        lines.append(f"| {spec} | {entry['expected']} | {entry['ok']} | {entry['missing']} | "
                     f"{entry['call_failed']} | {entry['parse_failed']} | {entry['stale_prompt']} | "
                     f"{', '.join(entry['model_keys'])} | {served} |")
    lines.append("")
    for model, block in scores["models"].items():
        lines += [f"## {model}", "",
                  f"Probe fidelity: {block['probe_fidelity']} ({block['probe_fidelity_status']})",
                  f"Model unpinned: {block['model_unpinned']}",
                  f"Sampling parameters ignored by the transport: {block['sampling_params_ignored']}"
                  + (" (a CLI: temperature and max_tokens are not applied, so floor_sc is not "
                     "temperature-matched)" if block["sampling_params_ignored"] else ""),
                  "Characterization only: " + (", ".join(block["characterization_reasons"]) or "no"),
                  "Advisory: " + (", ".join(block["advisory_reasons"]) if block["advisory_reasons"] else "no"),
                  f"A/A: mean {block['aa']['mean_signed']}, CI {block['aa']['ci']}, "
                  f"CI contains 0: {block['aa']['ci_contains_zero']}"]
        for floor_arm, stats in block["floor"].items():
            lines.append(f"R vs {floor_arm} (descriptive): mean |dp| {stats['mean_abs_diff']}, CI {stats['ci']}, "
                         f"n targets {stats['n_targets']}")
        lines += ["", "| Block | n targets | mean D | CI | p (Holm) | MDE | verdict | would-be verdict |",
                  "|---|---|---|---|---|---|---|---|"]
        for name, stats in block["blocks"].items():
            verdict_text = stats["verdict"] + (" (advisory)" if stats.get("advisory") else "")
            lines.append(f"| {name} | {stats['n_targets']} | {stats['mean_d']} | {stats['ci']} | "
                         f"{stats['p_holm']} | {stats['mde']} | {verdict_text} | "
                         f"{stats.get('would_be_verdict', '')} |")
        if block["evidence"]:
            lines += ["", "Evidence: " + ", ".join(block["evidence"])]
        if block["withheld_evidence"]:
            lines += ["", "Withheld (not evidence): " + ", ".join(block["withheld_evidence"])]
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
        if name == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-calls", type=int, default=None)
            p.add_argument("--allow-unpinned", action="store_true")
        p.set_defaults(func=func)
    s = sub.add_parser("score")
    s.add_argument("--study-id", required=True)
    s.set_defaults(func=cmd_score)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except StudyRefused as exc:
        print(f"value_add_eval: {exc}; nothing was asked or written.", file=sys.stderr)
        return EXIT_REFUSED
    except eval_bundle.BundleIntegrityError as exc:
        print(f"value_add_eval: bundle integrity check failed ({exc}); nothing was scored or asked.",
              file=sys.stderr)
        return EXIT_STUDY_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
