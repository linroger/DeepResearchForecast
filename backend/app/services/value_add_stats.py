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
MDE = (1.96 + 0.84) * sd(cluster means of D) / sqrt(n_clusters).

Movement is not accuracy: no label is used, and an ``inert`` verdict is evidence
for an owner decision (``sim_signal_inert_for_model`` / ``graph_block_inert_for_model``),
never applied automatically. Pure (no I/O).
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
EVIDENCE_LABELS = {"S": "sim_signal_inert_for_model", "G": "graph_block_inert_for_model"}

VERDICT_MOVES = "moves"
VERDICT_INERT = "inert"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_UNAVAILABLE = "unavailable"


def arm_means(rows: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """``{(model_key, cluster_id, target_id): {arm: mean p over ok replicates}}``."""
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
    adjusted: Dict[str, Optional[float]] = {name: None for name in p_values}
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
    (how closely the canonical probe reproduces the production forecast)."""
    gaps = []
    for (model, cluster, target), arms in means.items():
        reference = pre_market.get((cluster, target))
        if model == model_key and BLOCK_ARMS["M"] in arms and isinstance(reference, (int, float)):
            gaps.append(abs(arms[BLOCK_ARMS["M"]] - float(reference)))
    return eval_stats.round4(sum(gaps) / len(gaps)) if gaps else None


def score_study(rows: Sequence[Mapping[str, Any]], *, pre_market: Mapping[Tuple[str, str], Any],
                resamples: int, inert_margin: float, fidelity_max: float) -> Dict[str, Any]:
    """Per-model block verdicts, A/A check, probe fidelity and evidence labels."""
    means = arm_means(rows)
    models = sorted({key[0] for key in means})
    out: Dict[str, Any] = {}
    for model in models:
        blocks = {block: block_stats(movement_rows(means, model, block), resamples=resamples)
                  for block in BLOCKS}
        adjusted = holm({block: stats["p_one_sided"] for block, stats in blocks.items()})
        fidelity = probe_fidelity(means, model, pre_market)
        advisory = fidelity is not None and fidelity > fidelity_max
        evidence: List[str] = []
        for block, stats in blocks.items():
            stats["p_holm"] = eval_stats.round4(adjusted[block]) if adjusted[block] is not None else None
            stats["verdict"] = verdict(adjusted[block], stats["ci"], inert_margin)
            if advisory:
                stats["advisory"] = True
            if stats["verdict"] == VERDICT_INERT and block in EVIDENCE_LABELS:
                evidence.append(EVIDENCE_LABELS[block])
        out[model] = {
            "blocks": blocks,
            "aa": aa_stats(means, model, resamples=resamples),
            "probe_fidelity": fidelity,
            "probe_not_representative": advisory,
            "evidence": evidence,
        }
    return out
