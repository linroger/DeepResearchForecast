"""EVAL-20 (P07 part 2/2): label-free block-movement statistics over frozen bundles.

For one model, each target question of a frozen evaluation bundle (EVAL-19) is
re-asked under several input arms; a block X (Q quant, G graph, S simulation, M
market) "moves" the forecast when adding it to the research arm R shifts the mean
probability by more than two identical full arms already differ by (the A/A noise
floor):

    dq(X)  = |mean p(R+X) - mean p(R)|
    dq_AA  = |mean p(FULL) - mean p(FULL_AA)|
    D      = dq(X) - dq_AA          (one value per target)

The mean of D is tested with a cluster bootstrap (cluster = the bundle, so a
report's targets move together; eval_stats.cluster_bootstrap_replicates, fixed
seed): one-sided p = share of bootstrap means <= 0, Holm-adjusted across the four
blocks of a model. Verdict: ``moves`` iff Holm p < 0.05 and the CI lower bound > 0;
``inert`` iff the CI upper bound < EVAL_INERT_MARGIN; else ``inconclusive``.
MDE = (1.96 + 0.84) * sd(cluster means of D) / sqrt(n_clusters). A block with fewer
than MIN_CLUSTERS clusters gets no scored verdict: it is ``characterization_only``
(reason ``too_few_clusters``), since with few clusters the percentile bootstrap does
not hold its error rates.

Movement is not accuracy: no label is used, and an ``inert`` verdict is evidence
for an owner decision (``sim_signal_inert_for_model`` / ``graph_block_inert_for_model``),
never applied automatically.

Fail closed: a model's verdicts are advisory and its evidence labels are withheld
(``withheld_evidence``, never ``evidence``) when the probe's fidelity is over
EVAL_PROBE_FIDELITY_MAX or cannot be measured (no target has both R+M and a
pre-market probability), when the model was unpinned, when its A/A check fails (the
FULL vs FULL_AA CI excludes 0, so the noise floor itself is suspect), when the caller
passes another reason (a scoring parameter that differs from the pre-registered one,
a served-model change), or when the study is invalid (verdict ``invalid``) or
characterization-only for that model (verdict ``characterization_only``); the computed
verdict is then kept as ``would_be_verdict``. A block under MIN_CLUSTERS is advisory
and withholds its own label only. Pure (no I/O).
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import eval_stats

BLOCKS = ("Q", "G", "S", "M")
ARM_R = "R"
ARM_FULL = "FULL"
ARM_FULL_AA = "FULL_AA"
ARM_FLOOR = "floor"
ARM_FLOOR_SC = "floor_sc"
BLOCK_ARMS = {block: f"R+{block}" for block in BLOCKS}
ALPHA = 0.05
Z_ALPHA = 1.96
Z_POWER = 0.84
BOOTSTRAP_SEED = 20261001
# Fewest clusters (bundles) a block needs for a scored verdict. The percentile cluster
# bootstrap is anti-conservative with few clusters: on seeded synthetic null data (2 targets
# per cluster, 3 replicates, every block null, 400-2000 resamples, 1000-3500 studies per
# size) the familywise rate of non-advisory 'moves' across the four blocks was about 15% at
# 6 clusters, 9-11% at 8-10, 7% at 12, 6% at 16 and 5% at 20 (nominal 5%;
# test_value_add_eval.py pins it at this minimum). Below it a block is characterization_only
# and its evidence label withheld. Pre-registered with the scoring parameters (study.json
# "scoring"): a study registered under another minimum is scored as an override, every
# verdict advisory.
MIN_CLUSTERS = 16
EVIDENCE_LABELS = {"S": "sim_signal_inert_for_model", "G": "graph_block_inert_for_model"}

VERDICT_MOVES = "moves"
VERDICT_INERT = "inert"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_UNAVAILABLE = "unavailable"
VERDICT_INVALID = "invalid"
VERDICT_CHARACTERIZATION = "characterization_only"

FIDELITY_OK = "ok"
FIDELITY_NOT_REPRESENTATIVE = "not_representative"
FIDELITY_UNMEASURED = "unmeasured"

# Why a model's verdicts are advisory and its evidence labels withheld.
REASON_STUDY_INVALID = "study_invalid"
REASON_CHARACTERIZATION = "characterization_only"
REASON_PROBE_NOT_REPRESENTATIVE = "probe_not_representative"
REASON_PROBE_FIDELITY_UNMEASURED = "probe_fidelity_unmeasured"
REASON_MODEL_UNPINNED = "model_unpinned"
REASON_AA_FLOOR_NOT_NULL = "aa_floor_not_null"
# Why one block (not the model) is characterization-only.
REASON_TOO_FEW_CLUSTERS = "too_few_clusters"


def arm_means(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """``{(model_key, cluster_id, target_id): {arm: mean p over ok replicates}}``.

    The caller passes one row per registered (model, bundle, target, arm, replicate) cell
    under the registered prompt (value_add_eval.select_rows), and a study holds one bundle
    per report, so (cluster_id, target_id) names a single bundle's target."""
    sums: Dict[Tuple[str, str, str], Dict[str, List[float]]] = {}
    for row in rows:
        if row.get("status") != "ok" or not isinstance(row.get("p"), (int, float)):
            continue
        key = (str(row.get("model_key")), str(row.get("cluster_id")), str(row.get("target_id")))
        sums.setdefault(key, {}).setdefault(str(row.get("arm")), []).append(float(row["p"]))
    return {key: {arm: sum(ps) / len(ps) for arm, ps in arms.items()} for key, arms in sums.items()}


def movement_rows(means: Mapping[Tuple[str, str, str], Mapping[str, float]], model_key: str,
                  block: str) -> List[Dict[str, Any]]:
    """One ``{cluster, id, d, dq, dq_aa}`` row per target with R, R+X, FULL and FULL_AA."""
    arm = BLOCK_ARMS[block]
    out: List[Dict[str, Any]] = []
    for (model, cluster, target), arms in sorted(means.items()):
        if model != model_key or not all(a in arms for a in (ARM_R, arm, ARM_FULL, ARM_FULL_AA)):
            continue
        dq = abs(arms[arm] - arms[ARM_R])
        dq_aa = abs(arms[ARM_FULL] - arms[ARM_FULL_AA])
        out.append({"cluster": cluster, "id": f"{cluster}:{target}", "d": dq - dq_aa,
                    "dq": dq, "dq_aa": dq_aa})
    return out


def _mean_d(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    return sum(r["d"] for r in rows) / len(rows) if rows else None


def holm(p_values: Mapping[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """Holm step-down adjusted p-values (None stays None and is not counted)."""
    present = sorted(((p, name) for name, p in p_values.items() if p is not None), key=lambda x: (x[0], x[1]))
    m = len(present)
    adjusted: Dict[str, Optional[float]] = dict.fromkeys(p_values)
    running = 0.0
    for rank, (p, name) in enumerate(present):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[name] = running
    return adjusted


def mde(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    """(1.96 + 0.84) * sd(cluster means of D) / sqrt(n_clusters); None under 2 clusters."""
    clusters: Dict[str, List[float]] = {}
    for row in rows:
        clusters.setdefault(str(row["cluster"]), []).append(float(row["d"]))
    means = [sum(v) / len(v) for v in clusters.values()]
    if len(means) < 2:
        return None
    return (Z_ALPHA + Z_POWER) * statistics.stdev(means) / math.sqrt(len(means))


def block_stats(rows: Sequence[Mapping[str, Any]], *, resamples: int,
                seed: int = BOOTSTRAP_SEED) -> Dict[str, Any]:
    """Mean D, cluster-bootstrap CI and one-sided p (share of bootstrap means <= 0)."""
    if not rows:
        return {"n_targets": 0, "n_clusters": 0, "mean_d": None, "ci": None, "p_one_sided": None, "mde": None}
    replicates = eval_stats.cluster_bootstrap_replicates(
        [dict(r) for r in rows], _mean_d, "cluster", B=resamples, seed=seed)
    values = [v for v in (replicates or []) if v is not None]
    interval = eval_stats.percentile_interval(values, ALPHA) if values else None
    return {
        "n_targets": len(rows),
        "n_clusters": len({r["cluster"] for r in rows}),
        "mean_d": eval_stats.round4(_mean_d(rows)),
        "ci": [eval_stats.round4(x) for x in interval] if interval else None,
        "p_one_sided": (round(sum(1 for v in values if v <= 0) / len(values), 6) if values else None),
        "mde": eval_stats.round4(mde(rows)),
    }


def aa_stats(means: Mapping[Tuple[str, str, str], Mapping[str, float]], model_key: str, *,
             resamples: int, seed: int = BOOTSTRAP_SEED) -> Dict[str, Any]:
    """The A/A check: signed mean p(FULL) - p(FULL_AA) with its cluster CI (should contain 0)."""
    rows = [{"cluster": cluster, "id": f"{cluster}:{target}", "d": arms[ARM_FULL] - arms[ARM_FULL_AA]}
            for (model, cluster, target), arms in sorted(means.items())
            if model == model_key and ARM_FULL in arms and ARM_FULL_AA in arms]
    stats = block_stats(rows, resamples=resamples, seed=seed)
    ci = stats["ci"]
    return {"n_targets": stats["n_targets"], "mean_signed": stats["mean_d"], "ci": ci,
            "ci_contains_zero": None if ci is None else ci[0] <= 0 <= ci[1]}


def verdict(holm_p: Optional[float], ci: Optional[Sequence[float]], inert_margin: float) -> str:
    if ci is None or holm_p is None:
        return VERDICT_UNAVAILABLE
    if holm_p < ALPHA and ci[0] > 0:
        return VERDICT_MOVES
    if ci[1] < inert_margin:
        return VERDICT_INERT
    return VERDICT_INCONCLUSIVE


def probe_fidelity(means: Mapping[Tuple[str, str, str], Mapping[str, float]], model_key: str,
                   pre_market: Mapping[Tuple[str, str], Any]) -> Optional[float]:
    """Mean |mean p(R+M) - pre_market_probability| over the model's targets that have both
    (how closely the canonical probe reproduces the production forecast); None when none has."""
    gaps = []
    for (model, cluster, target), arms in means.items():
        reference = pre_market.get((cluster, target))
        if model == model_key and BLOCK_ARMS["M"] in arms and isinstance(reference, (int, float)):
            gaps.append(abs(arms[BLOCK_ARMS["M"]] - float(reference)))
    return eval_stats.round4(sum(gaps) / len(gaps)) if gaps else None


def fidelity_status(fidelity: Optional[float], fidelity_max: float) -> str:
    """'unmeasured' (no target to measure on), 'not_representative' (over the gate) or 'ok'."""
    if fidelity is None:
        return FIDELITY_UNMEASURED
    return FIDELITY_NOT_REPRESENTATIVE if fidelity > fidelity_max else FIDELITY_OK


def floor_movement(means: Mapping[Tuple[str, str, str], Mapping[str, float]], model_key: str, *,
                   resamples: int, seed: int = BOOTSTRAP_SEED) -> Dict[str, Any]:
    """Descriptive only (no verdict, no evidence): how far the research arm R sits from the
    closed-book floor and the compute-matched floor_sc, as the mean over targets of
    |mean p(R) - mean p(floor arm)| with its cluster CI. Being an absolute difference of
    noisy means, it is biased upward by replicate noise (compare the A/A floor)."""
    out: Dict[str, Any] = {}
    for floor_arm in (ARM_FLOOR, ARM_FLOOR_SC):
        rows = [{"cluster": cluster, "id": f"{cluster}:{target}", "d": abs(arms[ARM_R] - arms[floor_arm])}
                for (model, cluster, target), arms in sorted(means.items())
                if model == model_key and ARM_R in arms and floor_arm in arms]
        stats = block_stats(rows, resamples=resamples, seed=seed)
        out[floor_arm] = {"n_targets": stats["n_targets"], "mean_abs_diff": stats["mean_d"], "ci": stats["ci"]}
    return out


def score_study(rows: Sequence[Mapping[str, Any]], *, pre_market: Mapping[Tuple[str, str], Any],
                resamples: int, inert_margin: float, fidelity_max: float, seed: int = BOOTSTRAP_SEED,
                min_clusters: int = MIN_CLUSTERS, invalid: bool = False, characterization_only: bool = False,
                model_characterization: Optional[Mapping[str, Sequence[str]]] = None,
                advisory: Sequence[str] = (), model_advisory: Optional[Mapping[str, Sequence[str]]] = None,
                sampling_params_ignored: Iterable[str] = ()) -> Dict[str, Any]:
    """Per-model block verdicts, A/A check, floor movement, probe fidelity and evidence labels.

    ``seed`` is the study's registered bootstrap seed (every CI of every model uses it).
    A block whose movement rows span fewer than ``min_clusters`` clusters is
    'characterization_only' (reason 'too_few_clusters' in its own ``characterization_reasons``,
    the computed verdict kept as ``would_be_verdict``), advisory, and its evidence label is
    withheld; the model's other blocks are not affected (keeping it in the Holm family can
    only raise their adjusted p-values).
    ``invalid`` / ``characterization_only`` are the study-level gates: every verdict becomes
    'invalid' / 'characterization_only' (the computed one kept as ``would_be_verdict``);
    ``model_characterization`` ({model_key: reasons}, e.g. 'incomplete') applies the second
    gate to one model only. ``advisory`` (every model) and ``model_advisory`` ({model_key:
    reasons}) add caller-side reasons. Any advisory reason (those, the gates, probe fidelity
    not ok, an unpinned model, a failed A/A check) marks every block ``advisory`` and moves the
    evidence labels to ``withheld_evidence``. ``sampling_params_ignored`` names the model keys
    whose transport ignores temperature and max_tokens (the CLIs): informational only, the
    A/A floor is sampled the same way as every other arm."""
    means = arm_means(rows)
    models = sorted({key[0] for key in means})
    ignored = set(sampling_params_ignored)
    out: Dict[str, Any] = {}
    for model in models:
        blocks = {block: block_stats(movement_rows(means, model, block), resamples=resamples, seed=seed)
                  for block in BLOCKS}
        adjusted = holm({block: stats["p_one_sided"] for block, stats in blocks.items()})
        fidelity = probe_fidelity(means, model, pre_market)
        status = fidelity_status(fidelity, fidelity_max)
        unpinned = any(row.get("model_unpinned") for row in rows if str(row.get("model_key")) == model)
        aa = aa_stats(means, model, resamples=resamples, seed=seed)
        characterization = [REASON_CHARACTERIZATION] if characterization_only else []
        characterization += [r for r in (model_characterization or {}).get(model, ()) if r not in characterization]
        reasons: List[str] = []
        if invalid:
            reasons.append(REASON_STUDY_INVALID)
        if characterization:
            reasons.append(REASON_CHARACTERIZATION)
        for reason in (*advisory, *(model_advisory or {}).get(model, ())):
            if reason not in reasons:
                reasons.append(reason)
        if status == FIDELITY_UNMEASURED:
            reasons.append(REASON_PROBE_FIDELITY_UNMEASURED)
        elif status == FIDELITY_NOT_REPRESENTATIVE:
            reasons.append(REASON_PROBE_NOT_REPRESENTATIVE)
        if unpinned:
            reasons.append(REASON_MODEL_UNPINNED)
        if aa["ci_contains_zero"] is False:
            reasons.append(REASON_AA_FLOOR_NOT_NULL)
        labels: List[str] = []
        withheld: List[str] = []
        below_min: List[str] = []
        for block, stats in blocks.items():
            stats["p_holm"] = eval_stats.round4(adjusted[block]) if adjusted[block] is not None else None
            computed = verdict(adjusted[block], stats["ci"], inert_margin)
            too_few = stats["n_targets"] > 0 and stats["n_clusters"] < min_clusters
            if too_few:
                below_min.append(block)
                stats["characterization_reasons"] = [REASON_TOO_FEW_CLUSTERS]
            if invalid or characterization or too_few:
                stats["verdict"] = VERDICT_INVALID if invalid else VERDICT_CHARACTERIZATION
                stats["would_be_verdict"] = computed
            else:
                stats["verdict"] = computed
            if reasons or too_few:
                stats["advisory"] = True
            if computed == VERDICT_INERT and block in EVIDENCE_LABELS:
                (withheld if reasons or too_few else labels).append(EVIDENCE_LABELS[block])
        out[model] = {
            "blocks": blocks,
            "aa": aa,
            "floor": floor_movement(means, model, resamples=resamples, seed=seed),
            "probe_fidelity": fidelity,
            "probe_fidelity_status": status,
            "probe_not_representative": status != FIDELITY_OK,
            "model_unpinned": unpinned,
            "sampling_params_ignored": model in ignored,
            "characterization_reasons": characterization,
            "advisory_reasons": reasons,
            "blocks_below_min_clusters": below_min,
            "evidence": labels,
            "withheld_evidence": withheld,
        }
    return out
