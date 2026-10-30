"""Contract for the Simulation After-Action Record (``simulation-record/v1``).

ADR 0003 makes simulation output a ``simulated`` record class that reaches the
forecast report only through one deterministic, fenced bridge section.  This
module is the shared anchor for the three parties that must agree on the
record's shape without seeing each other's code:

* the Stage 5 compiler (``simulation_record.py``) that writes it,
* the deterministic gate (``simulation_record_gate.py``) that audits it, and
* the Stage 6 bridge renderer in ``report_agent`` that reads it.

It contains no LLM calls. Enabled World Anchor reads also authenticate the
externally pinned research generation through the host runtime loader. Field-level
semantics are in docs/handoff/simulation-after-action-record/design.md §4;
the gate's checks G1–G9 are in §3.2.

Invariants the compiler MUST honour (the gate checks them):

* ``record_class == "simulated"`` and ``epistemic_status == "elicited_model_projection"``.
* ``banner`` is byte-equal to ``sim_provenance.SIM_BANNER_EN`` or ``SIM_BANNER_ZH``
  according to ``language``.
* ``periods`` has exactly one entry per committed round, in round order.
* No ``[S#]`` / ``【S#】`` citation marker anywhere in the record text.
* No text taken from ``world_actions.jsonl``'s ``private_rationale`` field.
* Per-period sections carry no scenario shares; shares live only under ``overall``.
* Every quoted statement is a substring of a stored ``public_statement``.
"""
from __future__ import annotations

import json
import os
import hashlib
import math
import stat
import tempfile
from typing import Any, Dict, Final, List, Optional

from . import sim_provenance as _sp

SCHEMA: Final = _sp.RECORD_SCHEMA                      # "simulation-record/v1"
RECORD_CLASS: Final = _sp.RECORD_CLASS                 # "simulated"
EPISTEMIC_STATUS: Final = _sp.EPISTEMIC_STATUS         # "elicited_model_projection"

# File names under uploads/simulations/<sim_id>/
RECORD_JSON: Final = "simulation_record.json"
RECORD_MD: Final = "simulation_record.md"
RECORD_MD_ZH: Final = "simulation_record.zh.md"
RECORD_AUDIT_JSON: Final = "simulation_record_audit.json"
ARTIFACT_FILES: Final = (
    "world_state.json", "world_state_history.jsonl", "world_digest.jsonl", "world_actions.jsonl",
    "decisions.jsonl", "world_state_trajectory.json", "world_paths.json", "run_summary.json",
    "simulation_config.json", "simulation_config_manifest.json", "actor_cast_manifest.json",
    "state.json", "world_result.json", "world_spec.json", "world_input_manifest.json",
    "world_result_manifest.json",
)

ENGINES: Final = ("oasis-reflexive", "world-v1", "oasis-inband", "oasis-hours")
HEALTH_STUB_VALUES: Final = frozenset({"hollow", "errored", "truncated"})
GENERATORS: Final = ("deterministic", "llm")
PUBLICATION_STATUSES: Final = ("passed", "failed", "not_audited")

# Fields the compiler may read from a world_actions.jsonl row.  ``private_rationale``
# is excluded by allowlist, never filtered after the fact.
ACTION_PUBLIC_FIELDS: Final = frozenset({
    "round", "period_end", "period_label", "agent_id", "actor_name", "option", "targets",
    "magnitude", "public_statement", "terms", "commitment", "alliance_moves",
    "expected_reactions", "scenario", "scenario_confidence", "status",
})

# Top-level keys, in the order the renderer emits them.
TOP_LEVEL_KEYS: Final = (
    "schema", "record_class", "epistemic_status", "simulation_id", "pipeline_id",
    "config_hash", "engine", "language", "as_of", "horizon_date", "calendar_unit",
    "rounds_planned", "rounds_committed", "health", "banner", "setup", "periods",
    "overall", "limits", "entities_declared", "generated_at", "generator_version",
)
_OPTIONAL_TOP_LEVEL: Final = ("pipeline_id", "config_hash", "as_of", "horizon_date", "calendar_unit")
REQUIRED_TOP_LEVEL: Final = frozenset(k for k in TOP_LEVEL_KEYS if k not in _OPTIONAL_TOP_LEVEL)

PERIOD_KEYS: Final = (
    "round", "label", "period_start", "period_end", "arbiter_status", "arbiter_problems",
    "narrative", "moves", "held_position", "facts_changed", "events", "shocks_fired",
    "red_lines_crossed", "offers", "alliances", "behaviour", "refs",
)
REQUIRED_PERIOD_KEYS: Final = frozenset({"round", "label", "arbiter_status", "narrative",
                                        "moves", "facts_changed", "events", "refs"})

HEALTH_KEYS: Final = ("simulation_health", "validity", "arbiter_failed_rounds",
                      "seed_gaps", "organic_actions")
OVERALL_KEYS: Final = ("final_variables", "shares", "turning_points", "track_records", "synthesis")


class RecordContractError(ValueError):
    """The record does not satisfy the structural contract."""


def _anchor_public_policy(context):
    pack = context.pack
    requirements = context.requirements["requirements"]
    by_origin = {r["origin_pointer"]: r for r in requirements}
    bindings = {b["requirement_id"]: b for b in pack["bindings"]}
    observations = {o["observation_id"]: o for o in pack["observations"]}
    refs = {r["ref_id"]: r for r in pack["references"]}
    sources = {s["source_key"]: s for s in context.index.snapshot()["sources"]}

    def public_observation(obs):
        if (obs["audience"] != {"kind": "public", "actor_refs": []}
                or obs["producer_class"] not in {"official_observation", "primary_statement", "secondary_report", "external_forecast"}
                or obs["value_kind"] not in {"observed", "reported", "third_party_forecast"}):
            return False
        # Conservative day precision: do not expose a release before its day ends.
        cutoff = pack["scope"]["cutoff"]
        for field in ("known_by", "visible_at"):
            time = obs[field]
            value = time["value"]
            if time["precision"] == "day" and value:
                value = value[:10] + "T23:59:59Z"
            if value is None or value > cutoff:
                return False
        return bool(obs["ref_ids"]) and all(
            sources[refs[r]["source_key"]]["audience"] == {"kind": "public", "actor_refs": []}
            for r in obs["ref_ids"])

    def public_binding(req):
        binding = bindings.get(req["requirement_id"], {})
        rows = [observations[o] for o in binding.get("observation_ids", [])]
        return (binding.get("status") == "bound" and not binding.get("assumption")
                and bool(rows) and all(public_observation(o) for o in rows))

    def provenance(req):
        binding = bindings[req["requirement_id"]]
        out = []
        for oid in binding["observation_ids"]:
            obs = observations[oid]
            # No locator, quote, note, owner, raw ID, private pack hash or count.
            row = {"status": binding["status"], "value_kind": obs["value_kind"],
                   "value": obs["value"], "vintage": obs["vintage"]["value"],
                   "identity": ({k: obs["identity"][k] for k in (
                       "entity_id", "metric_id", "denominator_id", "geography_id", "unit", "reference_period")}
                       if obs["identity"] is not None else None),
                   "reference_period": (obs["identity"] or {}).get("reference_period"),
                   "source_hashes": sorted({refs[r]["content_hash"] for r in obs["ref_ids"]})}
            out.append({**row, "anchor_hash": record_sha256(row)})
        return sorted(out, key=lambda r: r["anchor_hash"])

    return pack, requirements, by_origin, bindings, public_binding, provenance


def _anchor_public_nodes(context, nodes, *, native_outputs=()):
    pack, requirements, by_origin, bindings, public_binding, provenance = _anchor_public_policy(context)
    variables = {v["node_id"]: v for v in pack["variables"] if v["node_id"] in nodes}
    # Native target definitions are diagnostic consumers, so their derived
    # outputs need not be in pack.variables. Callers may add only outputs from
    # the native case after validate_anchored_case has authenticated its graph.
    outputs = set(variables) | (set(native_outputs) & set(nodes))
    by_binding = {b["binding_id"]: b for b in pack["bindings"]}
    by_requirement = {r["requirement_id"]: r for r in requirements}
    admitted, origins, derivations = set(), {}, {}
    for nid, variable in variables.items():
        binding = by_binding.get(variable["binding_id"])
        req = by_requirement.get(binding["requirement_id"]) if binding else None
        if req and req["actor_ref"] is None and public_binding(req):
            admitted.add(nid)
            origins[nid] = provenance(req)
    # A derived public node needs a public dependency closure. A public label
    # alone cannot disclose a result derived from private/prior information.
    for _ in nodes:
        for mechanism in pack["mechanisms"]:
            nid = mechanism["output_node_id"]
            req_origins = [p["requirement_origin"] for p in mechanism["parameters"]]
            req_origins += mechanism["applicability_requirement_origins"]
            if mechanism["lag_requirement_origin"]:
                req_origins.append(mechanism["lag_requirement_origin"])
            if (nid in outputs and nid not in admitted
                    and set(mechanism["input_node_ids"]) <= admitted
                    and all(public_binding(by_origin[o]) for o in req_origins)):
                admitted.add(nid)
                inherited = [p for source in mechanism["input_node_ids"] for p in origins[source]]
                inherited += [p for origin in req_origins for p in provenance(by_origin[origin])]
                origins[nid] = sorted({p["anchor_hash"]: p for p in inherited}.values(), key=lambda p: p["anchor_hash"])
                derivations[nid] = {"template": mechanism["template"], "input_node_ids": mechanism["input_node_ids"]}
    return variables, admitted, origins, derivations


def _optional_json(sim_dir, name):
    try:
        value = json.loads(read_regular(os.path.join(sim_dir, name)))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise RecordContractError("invalid anchor artifact object")
    return value


def load_anchor_diagnostics(sim_dir, *, config=None, world_state=None, expected_case=None,
                            expected_simulation=None, report_evidence=None):
    """Read authenticated saved runtime, then project a public diagnostic allowlist.

    Absence of the config pin is off, even if loose anchor files exist. The host
    loader owns the external seals. Neither saved metadata nor a candidate spec
    can grant audience permission. Global pack hashes/counts and raw evidence
    references stay privileged. Each public anchor hash names exactly the
    emitted public provenance object (without its own hash), not the raw pack.
    """
    # Native target generations have no OASIS config/state file. Discover only
    # their fixed artifact names; the host owns external preparation admission.
    target_input = _optional_json(sim_dir, "target_input.json")
    target_files = (bool(target_input) or os.path.lexists(os.path.join(sim_dir, "target_case.json"))
                    or (expected_case is not None
                        and not os.path.lexists(os.path.join(sim_dir, "simulation_config.json"))
                        and not os.path.lexists(os.path.join(sim_dir, "world_input_manifest.json"))))
    if target_files:
        from .world_anchor import load_target_anchor
        from .official_data import bridge_module
        # Mode, owner root, lifecycle and research/prepare seals belong to the
        # native host loader, including the absent-pin/disabled distinction.
        expected_hash = bridge_module("forecast_case").case_hash(expected_case) if expected_case is not None else None
        context = load_target_anchor(sim_dir, expected_case_hash=expected_hash)
        if context is None:
            return None
        return _target_anchor_diagnostics(sim_dir, context, expected_case, expected_simulation,
                                          report_evidence=report_evidence)
    if config is None:
        config = _optional_json(sim_dir, "simulation_config.json")
    state = _optional_json(sim_dir, "state.json")
    engine = state.get("simulation_engine")
    native = _optional_json(sim_dir, "world_input_manifest.json")
    if "worldAnchor" in native and engine != "world-v1":
        raise RecordContractError("native anchor engine binding is missing or changed")
    if engine == "world-v1":
        manifest_pin = state.get("world_input_manifest_sha256")
        if manifest_pin and hashlib.sha256(read_regular(os.path.join(sim_dir, "world_input_manifest.json"))).hexdigest() != manifest_pin:
            raise RecordContractError("native world manifest differs from external state pin")
        if "worldAnchor" not in native:
            if "worldAnchor" in _optional_json(sim_dir, "world_spec.json").get("sourceBindings", {}):
                raise RecordContractError("native anchor input pin is missing")
            return None
        from .world_anchor import load_runtime_anchor
        context = load_runtime_anchor({"simulation_id": state.get("simulation_id"),
                                       "world_anchor": native["worldAnchor"]}, sim_dir)
        return _world_anchor_diagnostics(sim_dir, state, context)
    if "world_anchor" not in config:
        # An actual anchored seed/runtime cannot be downgraded by stripping its
        # outer pin. Loose world_anchor.json files still do not enable old runs.
        saved_world = (world_state if world_state is not None else _optional_json(sim_dir, "world_state.json")).get("world", {})
        seed = config.get("world_model", {})
        if any(isinstance(value, dict) and any(key in value for key in ("world_anchor", "anchor_runtime"))
               for value in (saved_world, seed)):
            raise RecordContractError("anchored runtime configuration pin is missing")
        return None
    from .world_anchor import load_runtime_anchor
    from .world_model import WorldModel, slugify

    context = load_runtime_anchor(config, sim_dir)
    if world_state is None:
        world_state = json.loads(read_regular(os.path.join(sim_dir, "world_state.json")))
    saved = world_state.get("world", {})
    seed = config.get("world_model", {})
    if expected_case is not None:
        from .official_data import bridge_module
        if seed.get("target_projection") != bridge_module("forecast_case").simulation_projection(expected_case):
            raise RecordContractError("anchor report case differs from sealed runtime")
    if (saved.get("target_projection") != seed.get("target_projection")
            or saved.get("anchor_runtime") != seed.get("anchor_runtime")):
        raise RecordContractError("anchor runtime differs from sealed seed")
    world = WorldModel.from_dict(saved, anchor_context=context)
    pack, requirements, by_origin, bindings, public_binding, provenance = _anchor_public_policy(context)
    nodes = {n["nodeId"]: n for n in seed["target_projection"]["nodes"] if n.get("visibility") == "public"}
    by_requirement = {r["requirement_id"]: r for r in requirements}
    variables, admitted, origins, derivations = _anchor_public_nodes(context, nodes)
    def finite(value):
        return value if type(value) in (int, float) and math.isfinite(value) else None

    values = world.public_target_values() if world.round == world.committed_round else {}
    rows = []
    for nid in sorted(admitted):
        variable = world.variables.get(slugify(nid))
        history = variable.history if variable else []
        derived = variables[nid]["producer_mechanism_id"] is not None
        # A derived seed placeholder is not an initial simulated result. Use
        # the earliest actually propagated saved value, with its round shown.
        initial = next((h for h in history if type(h.get("round")) is int
                        and 0 <= h["round"] <= world.committed_round
                        and (not derived or h.get("source") == "mechanism")
                        and finite(h.get("value")) is not None), None)
        rows.append({"node_id": nid, "unit": nodes[nid]["units"],
                     "status": "available" if nid in values else "unavailable",
                     "initial": finite(initial["value"]) if initial else None,
                     "initial_round": initial.get("round") if initial else None,
                     "initial_value_kind": "simulated" if derived else origins[nid][0]["value_kind"],
                     "final": finite(values.get(nid)), "final_value_kind": "simulated",
                     "derivation": derivations.get(nid),
                     "provenance": origins[nid]})
    indicators = {i["indicator_id"]: i for i in pack["indicators"]
                  if i["node_id"] in admitted and public_binding(by_origin[i["requirement_origin"]])}
    signposts = []
    for row in saved.get("anchor_signposts", []):
        indicator = indicators.get(row.get("indicator_id"))
        if (indicator is None or row.get("node_id") != indicator["node_id"]
                or type(row.get("round")) is not int or not 0 <= row["round"] <= world.committed_round
                or (row.get("triggered") is not None and type(row.get("triggered")) is not bool)):
            continue
        signposts.append({"round": row["round"], "node_id": indicator["node_id"],
                          "value": finite(row.get("value")), "triggered": row.get("triggered"),
                          "value_kind": "simulated", "provenance": provenance(by_origin[indicator["requirement_origin"]])})
    gaps = []
    for gap in pack["gaps"]:
        req = by_requirement.get(gap["requirement_id"])
        if req is None or req["actor_ref"] is not None or req["kind"] not in {"baseline", "target_definition", "indicator"}:
            continue
        for consumer in req["consumers"]:
            if consumer["object_id"] in nodes and consumer["role"] in {"initial_state", "observation"}:
                gaps.append({"node_id": consumer["object_id"], "status": bindings[req["requirement_id"]]["status"],
                             "code": gap["code"]})
    return {"schema": "world-anchor-diagnostics/v1", "audience": "public",
            "hash_scope": "public-anchor-provenance/v1", "simulationWeight": 0.0,
            "target_node_id": seed["target_projection"]["resolution"]["targetNodeId"]
                if seed["target_projection"]["resolution"]["targetNodeId"] in admitted else None,
            "variables": rows, "signposts": signposts, "gaps": gaps}


def _native_anchor_envelope(engine, target, variables, signposts, gaps):
    return {"schema": "world-anchor-diagnostics/v1", "audience": "public", "engine": engine,
            "hash_scope": "public-anchor-provenance/v1", "simulationWeight": 0.0,
            "target_node_id": target, "variables": variables, "signposts": signposts, "gaps": gaps}


def _native_signposts(context, admitted, samples):
    """Compare saved public values to admitted predicates, without running a model.

    These are explicitly diagnostic comparisons, not claims that a native engine
    executed the reflexive indicator hook. Private predicates have no output.
    """
    from decimal import Decimal, InvalidOperation
    pack, _, by_origin, _, public_binding, provenance = _anchor_public_policy(context)
    out = []
    for indicator in pack["indicators"]:
        req = by_origin[indicator["requirement_origin"]]
        predicate = indicator["trigger"]
        if (indicator["node_id"] not in admitted or not public_binding(req) or predicate is None
                or predicate["node_id"] not in admitted):
            continue
        for sample in samples:
            value = sample["values"].get(predicate["node_id"])
            try:
                number = Decimal(str(value))
                if not number.is_finite():
                    continue
                op = predicate["operator"]
                if op == "between":
                    triggered = Decimal(predicate["low"]) <= number <= Decimal(predicate["high"])
                else:
                    threshold = Decimal(predicate["value"])
                    triggered = {"lt": number < threshold, "lte": number <= threshold,
                                 "gt": number > threshold, "gte": number >= threshold}[op]
            except (InvalidOperation, ValueError, TypeError):
                continue
            out.append({"round": sample["round"], "node_id": indicator["node_id"],
                        "value": value, "triggered": triggered, "value_kind": "simulated",
                        "evaluation": "diagnostic_predicate_on_saved_values",
                        **({"path_id": sample["path_id"]} if "path_id" in sample else {}),
                        "provenance": provenance(req)})
    return out


def _world_anchor_diagnostics(sim_dir, state, context):
    from pathlib import Path
    from .world_simulation.artifacts import load_inputs
    from .world_simulation.results import load_frozen_result
    spec, _ = load_inputs(Path(sim_dir), simulation_id=state["simulation_id"],
        expected_manifest_sha256=state["world_input_manifest_sha256"], anchor_context=context)
    # Verify the export against the actual committed store, not a self-hashed
    # loose result. This reader never starts a child or repairs an export.
    result = load_frozen_result(Path(sim_dir), require_complete=False)
    pack, requirements, _, bindings, public_binding, provenance = _anchor_public_policy(context)
    by_requirement = {r["requirement_id"]: r for r in requirements}
    rows, selected = [], {}
    for ref in spec["sourceBindings"]["worldAnchor"]["references"]:
        parts = ref["target"].split("/")
        if len(parts) != 5 or parts[1] != "initialState" or parts[2] not in {"accounts", "metrics", "rules", "relations"}:
            continue
        bucket, key, field = parts[2], parts[3].replace("~1", "/").replace("~0", "~"), parts[4]
        if field != ("balance" if bucket == "accounts" else "value"):
            continue
        initial = spec["initialState"][bucket][key]
        req = by_requirement[ref["requirement_id"]]
        if initial.get("visibility", {}).get("kind") != "public" or not public_binding(req):
            continue
        nid = ref["target_object_id"]
        final = result["world"].get(bucket, {}).get(key, {}).get(field)
        rows.append({"node_id": nid, "unit": req["identity"]["unit"]["id"],
                     "status": "available" if final is not None else "unavailable",
                     "initial": initial[field], "initial_round": 0,
                     "initial_value_kind": provenance(req)[0]["value_kind"],
                     "final": final, "final_value_kind": "simulated", "derivation": None,
                     "provenance": provenance(req), "native_field": {"section": bucket, "id": key, "field": field}})
        selected[nid] = (bucket, key, field)
    samples = [{"round": row["round"], "values": {
        nid: row.get(bucket, {}).get(key, {}).get(field) for nid, (bucket, key, field) in selected.items()}}
        for row in result["trajectory"]]
    gaps = []
    for gap in pack["gaps"]:
        req = by_requirement.get(gap["requirement_id"])
        if req and req["actor_ref"] is None:
            for consumer in req["consumers"]:
                if consumer["engine"] == "world-v1" and consumer["object_id"] in selected:
                    gaps.append({"node_id": consumer["object_id"], "status": bindings[req["requirement_id"]]["status"], "code": gap["code"]})
    target = context.requirements["contract"]["settlement"]["target_node_id"]
    if target not in selected:
        target = None
        gaps.append({"node_id": None, "status": "gap", "code": "target_not_produced_by_native_world"})
    return _native_anchor_envelope("world-v1", target, sorted(rows, key=lambda r: r["node_id"]),
        _native_signposts(context, selected, samples), gaps)


def _public_case_evidence(case, context):
    """Authorize exact native claim/source uses, never a node's entire dossier.

    The producer reconstructs these privileged joins. Only this ephemeral
    permission map reaches the renderer; the trace and its hashes never enter
    public diagnostic JSON, model prompts or stored report records.
    """
    from .official_data import bridge_module
    trace = bridge_module("world_anchor_case").anchored_case_provenance(
        case, pack=context.pack, requirements=context.requirements, index=context.index, policy=context.policy)
    pack, requirements, _, bindings, public_binding, _ = _anchor_public_policy(context)
    reqs = {r["requirement_id"]: r for r in requirements}
    observations = {o["observation_id"]: o for o in pack["observations"]}
    refs = {r["ref_id"]: r for r in pack["references"]}
    sources = {s["source_key"]: s for s in context.index.snapshot()["sources"]}

    def permitted(link):
        req = reqs.get(link["requirement_id"])
        binding = bindings.get(link["requirement_id"], {})
        obs = observations.get(link["observation_id"])
        if (req is None or obs is None or binding.get("binding_id") != link["binding_id"]
                or link["observation_id"] not in binding.get("observation_ids", []) or not public_binding(req)):
            return False
        # Include metadata/support provenance, not just a display quote's ref.
        closure = set(obs["ref_ids"]) | {s["ref_id"] for s in obs["support"]}
        for field in ("published_at", "available_at", "known_by", "retrieved_at", "effective_at", "visible_at", "vintage"):
            closure.update(obs[field]["basis_ref_ids"])
        closure.update(obs["cadence"]["ref_ids"])
        return bool(closure) and all(ref in refs and sources[refs[ref]["source_key"]]["audience"] ==
                                    {"kind": "public", "actor_refs": []} for ref in closure)

    def allowed_sources(uses):
        return [sid for sid, links in uses.items() if any(permitted(link) for link in links)]

    claims = []
    for claim in case["claims"]:
        link = trace["claims"][claim["claimId"]]
        if not permitted(link):
            continue
        if all(any(permitted(use) and use["observation_id"] == link["observation_id"]
                   and use["binding_id"] == link["binding_id"] for use in trace["sources"][sid])
               for sid in claim["sourceIds"]):
            claims.append(claim["claimId"])
    return {"claim_ids": claims,
            "node_sources": {nid: allowed_sources(uses) for nid, uses in trace["node_sources"].items()},
            "mechanism_sources": {mid: allowed_sources(uses) for mid, uses in trace["mechanism_sources"].items()},
            "parameter_sources": {mid: {slot: allowed_sources(uses) for slot, uses in slots.items()}
                                  for mid, slots in trace["parameter_sources"].items()}}


def _target_anchor_diagnostics(sim_dir, context, expected_case, expected_simulation, *, report_evidence=None):
    """Read real sealed target paths; no world-state reconstruction or new run."""
    from pathlib import Path
    from .official_data import bridge_module
    from .pipeline_orchestrator import PipelineManager
    from .target_report import _simulation, canonical_json
    from .world_anchor import validate_anchor_context, anchor_config_pin
    validate_anchor_context(context, engine="target-first-v1")
    directory = Path(sim_dir).resolve()
    simulation_id = directory.name
    inputs = _optional_json(directory, "target_input.json")
    if inputs.get("worldAnchor") != anchor_config_pin(context, require_join=False):
        raise RecordContractError("target input anchor changed after admission")
    owner = PipelineManager.load(inputs.get("pipelineId"))
    if not owner or owner.get("simulation_id") != simulation_id:
        raise RecordContractError("target result owner mismatch")
    def authority(saved):
        if not isinstance(saved, dict):
            return None
        options, stages = saved.get("options", {}), saved.get("stages", {})
        return {"simulation_id": saved.get("simulation_id"),
                "options": {k: options.get(k) for k in (
                    "world_anchor", "world_anchor_lifecycle", "target_case_binding")},
                "stages": {k: (stages.get(k) or {}).get("status") for k in ("research", "prepare", "run")}}
    admitted_authority = authority(owner)
    if admitted_authority["stages"]["run"] != "completed":
        raise RecordContractError("target run stage is not completed")
    manifest = PipelineManager.load_artifact_manifest(inputs["pipelineId"])
    prepared_bytes = {}
    for key, name in (("target_input", "target_input.json"), ("target_case", "target_case.json")):
        path = directory / name
        prepared_bytes[name] = read_regular(str(path))
        proof = manifest.get(key, {})
        if (proof.get("path") != str(path) or proof.get("produced_by_stage") != "prepare"
                or proof.get("sha256") != hashlib.sha256(prepared_bytes[name]).hexdigest()):
            raise RecordContractError("target input differs from external prepare receipt")
    entry = manifest.get("target_simulation", {})
    result_path = directory / "target_simulation.json"
    raw = read_regular(str(result_path))
    if (entry.get("path") != str(result_path) or entry.get("produced_by_stage") != "run"
            or entry.get("sha256") != hashlib.sha256(raw).hexdigest()):
        raise RecordContractError("target result differs from external run receipt")
    api = bridge_module("forecast_case")
    case = api.read_case(directory / "target_case.json", expected_hash=inputs["caseHash"])
    bridge_module("world_anchor_case").validate_anchored_case(case, pack=context.pack,
        requirements=context.requirements, index=context.index, policy=context.policy)
    if inputs.get("structure") != api.simulation_projection(case):
        raise RecordContractError("target input structure differs from sealed case")
    if expected_case is not None and api.case_hash(expected_case) != api.case_hash(case):
        raise RecordContractError("anchor report case differs from sealed runtime")
    result = _simulation(case, json.loads(raw))
    expected_anchor = {"adapterVersion": "world-anchor-target/v1", "packHash": context.pack_hash,
                       "contractHash": context.pack["contract_hash"], "inputHash": context.pack["input_hash"],
                       "caseHash": inputs["caseHash"]}
    if result.get("worldAnchor") != expected_anchor:
        raise RecordContractError("target runtime receipt differs from admitted anchor")
    settings = inputs.get("simulation", {})
    if (len(result["paths"]) != settings.get("paths") or result["seed"] != settings.get("seed")
            or any(path["trajectory"][0]["period"] != 0
                   or path["trajectory"][-1]["period"] != settings.get("periods") for path in result["paths"])):
        raise RecordContractError("target paths differ from prepared run settings")
    if expected_simulation is not None and canonical_json(result) != canonical_json(expected_simulation):
        raise RecordContractError("anchor report result differs from sealed runtime")
    nodes = {n["nodeId"]: n for n in case["nodes"] if n.get("visibility") == "public"}
    pack, requirements, _, bindings, _, _ = _anchor_public_policy(context)
    variables, admitted, origins, derivations = _anchor_public_nodes(context, nodes,
        native_outputs=[m["outputNodeId"] for m in case["mechanisms"]])
    samples, rows = [], []
    for path in result["paths"]:
        trajectory = path["trajectory"]
        samples.extend({"round": step["period"], "path_id": path["pathId"],
                        "values": {nid: step["values"].get(nid) for nid in admitted}} for step in trajectory)
        for nid in sorted(admitted):
            initial, final = trajectory[0]["values"].get(nid), trajectory[-1]["values"].get(nid)
            rows.append({"node_id": nid, "path_id": path["pathId"], "unit": nodes[nid]["units"],
                         "status": "available" if final is not None else "unavailable",
                         "initial": initial, "initial_round": trajectory[0]["period"],
                         "initial_value_kind": "simulated", "final": final, "final_value_kind": "simulated",
                         "derivation": derivations.get(nid), "provenance": origins[nid]})
    by_requirement = {r["requirement_id"]: r for r in requirements}
    gaps = []
    for gap in pack["gaps"]:
        req = by_requirement.get(gap["requirement_id"])
        if req and req["actor_ref"] is None and req["kind"] in {"baseline", "target_definition", "indicator"}:
            for consumer in req["consumers"]:
                if consumer["engine"] == "target-first-v1" and consumer["object_id"] in nodes:
                    gaps.append({"node_id": consumer["object_id"], "status": bindings[req["requirement_id"]]["status"], "code": gap["code"]})
    target = case["resolution"]["targetNodeId"]
    if target != context.requirements["contract"]["settlement"]["target_node_id"]:
        raise RecordContractError("anchor and target settlement differ")
    if target not in admitted:
        target = None
    diagnostic = _native_anchor_envelope("target-first-v1", target, rows,
        _native_signposts(context, admitted, samples), gaps)
    if report_evidence is not None:
        report_evidence.clear()
        report_evidence.update(_public_case_evidence(case, context))
    # Close a read/reseal race at the external owner and result boundaries.
    owner_after = PipelineManager.load(inputs["pipelineId"])
    if (read_regular(str(result_path)) != raw or PipelineManager.load_artifact_manifest(inputs["pipelineId"]) != manifest
            or any(read_regular(str(directory / name)) != data for name, data in prepared_bytes.items())
            or canonical_json(authority(owner_after)) != canonical_json(admitted_authority)):
        raise RecordContractError("target artifacts changed during projection")
    return diagnostic


def anchor_diagnostic_markdown(diagnostic, *, language="en"):
    """Render only the public closed projection; caller owns the ADR0003 fence."""
    import html
    def text(value):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        return " ".join(html.escape(raw).split()).replace("|", "&#124;").replace("[", "［").replace("]", "］")
    title = "世界锚点诊断" if language == "zh" else "World Anchor diagnostics"
    lines = [f"### {title}", "", "SIMULATED — diagnostic only; simulationWeight=0.",
             "Anchor hashes identify the public provenance rows only. Private pack identities are withheld.", "",
             "| Node | Initial value / round | Final simulated value | Unit | Status |",
             "|---|---|---|---|---|"]
    for row in diagnostic["variables"]:
        label = row["node_id"] + (" / " + row["path_id"] if "path_id" in row else "")
        lines.append(f"| {text(label)} | {text(row['initial'])} ({text(row['initial_value_kind'])}) / {text(row['initial_round'])} | {text(row['final'])} | {text(row['unit'])} | {row['status']} |")
    # A blank/prose block ends a Markdown table. Keep every value row above
    # this boundary and label the following provenance independently.
    for row in diagnostic["variables"]:
        label = row["node_id"] + (" / " + row["path_id"] if "path_id" in row else "")
        lines += ["", f"#### {text(label)}"]
        if row["derivation"]:
            lines.append("\nPublic derivation: " + text(row["derivation"]))
        for provenance in row["provenance"]:
            lines.append("\nPublic source provenance: " + text(provenance))
    lines += ["", "Signposts: " + text(diagnostic["signposts"]), "", "Public gaps: " + text(diagnostic["gaps"])]
    return "\n".join(lines)


def record_paths(sim_dir: str) -> Dict[str, str]:
    """Absolute paths of the record files for a simulation directory."""
    return {
        "json": os.path.join(sim_dir, RECORD_JSON),
        "md": os.path.join(sim_dir, RECORD_MD),
        "md_zh": os.path.join(sim_dir, RECORD_MD_ZH),
        "audit": os.path.join(sim_dir, RECORD_AUDIT_JSON),
    }


def banner_for(language: str) -> str:
    return _sp.SIM_BANNER_ZH if str(language or "").lower().startswith("zh") else _sp.SIM_BANNER_EN


def record_bytes(record: Dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def record_sha256(record: Dict[str, Any]) -> str:
    return hashlib.sha256(record_bytes(record)).hexdigest()


def public_world_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only explicit public rows of a public world-v1 export.

    Analyst/actor projections are never record inputs. Missing visibility is
    private, matching world_simulation.contracts.visible_to.
    """
    if result.get("view") != "public":
        return {}

    def visible(row):
        return isinstance(row, dict) and isinstance(row.get("visibility"), dict) and row["visibility"].get("kind") == "public"

    def snapshot(row):
        if not isinstance(row, dict):
            return {}
        out = {k: row[k] for k in ("round", "simulatedAt") if k in row}
        for bucket in ("metrics", "rules", "interactions", "commitments"):
            values = row.get(bucket)
            out[bucket] = {k: v for k, v in values.items() if visible(v)} if isinstance(values, dict) else {}
        return out

    out = {k: result[k] for k in ("schemaVersion", "engine", "simulationId", "completed", "round",
                                "committedRound", "totalRounds", "asOf", "horizon", "view") if k in result}
    out["world"] = snapshot(result.get("world"))
    out["trajectory"] = [snapshot(row) for row in result.get("trajectory", []) if isinstance(row, dict)]
    out["events"] = [row for row in result.get("events", []) if visible(row)]
    return out


def world_result_validity(result: Dict[str, Any]) -> str:
    if not result:
        return "unknown"
    committed, planned = result.get("committedRound"), result.get("totalRounds")
    rows = result.get("trajectory", [])
    if (type(committed) is not int or type(planned) is not int or not 0 <= committed <= planned
            or planned <= 0 or result.get("round") != committed
            or not isinstance(rows, list) or len(rows) != committed + 1
            or any(not isinstance(row, dict) or type(row.get("round")) is not int or row["round"] != i
                   for i, row in enumerate(rows))):
        return "invalid"
    if result.get("completed") is True:
        return "valid" if committed == planned else "invalid"
    return "inconclusive"


def validate_shape(record: Any) -> List[str]:
    """Structural checks only (the gate adds fidelity checks).  Returns a list of
    problems; an empty list means the shape is valid.  Never raises on bad input."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in record:
            problems.append(f"missing top-level key: {key}")
    if set(record) - set(TOP_LEVEL_KEYS):
        problems.append("unknown top-level record fields")
    if record.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}")
    if record.get("record_class") != RECORD_CLASS:
        problems.append(f"record_class must be {RECORD_CLASS!r}")
    if record.get("epistemic_status") != EPISTEMIC_STATUS:
        problems.append(f"epistemic_status must be {EPISTEMIC_STATUS!r}")
    if record.get("engine") not in ENGINES:
        problems.append(f"engine must be one of {ENGINES}")
    lang = str(record.get("language") or "")
    if record.get("banner") != banner_for(lang):
        problems.append("banner is not byte-equal to the sim_provenance banner for its language")
    health = record.get("health")
    if not isinstance(health, dict) or any(k not in health for k in HEALTH_KEYS):
        problems.append(f"health must carry {HEALTH_KEYS}")
    periods = record.get("periods")
    committed = record.get("rounds_committed")
    for key in ("rounds_planned", "rounds_committed"):
        if type(record.get(key)) is not int or record[key] < 0:
            problems.append(f"{key} must be a nonnegative integer")
    if record.get("language") not in ("en", "zh"):
        problems.append("language must be en or zh")
    for key in ("setup", "limits"):
        if not isinstance(record.get(key), dict):
            problems.append(f"{key} must be an object")
    if not isinstance(periods, list):
        problems.append("periods must be a list")
    else:
        if isinstance(committed, int) and len(periods) != committed:
            problems.append(f"periods has {len(periods)} entries for {committed} committed rounds")
        rounds = [p.get("round") for p in periods if isinstance(p, dict)]
        ints = [r for r in rounds if type(r) is int and r > 0]
        if len(ints) != len(rounds) or ints != sorted(ints) or len(set(ints)) != len(ints):
            problems.append("periods must carry integer rounds in order without duplicates")
        for i, p in enumerate(periods):
            if not isinstance(p, dict):
                problems.append(f"periods[{i}] is not an object")
                continue
            for key in sorted(REQUIRED_PERIOD_KEYS):
                if key not in p:
                    problems.append(f"periods[{i}] missing {key}")
            if "shares" in p:
                problems.append(f"periods[{i}] carries scenario shares (allowed only under overall)")
            for key in ("moves", "facts_changed", "events", "refs", "held_position", "offers", "alliances",
                        "shocks_fired", "red_lines_crossed", "arbiter_problems"):
                if key in p and not isinstance(p[key], list):
                    problems.append(f"periods[{i}].{key} must be a list")
    overall = record.get("overall")
    if not isinstance(overall, dict) or any(k not in overall for k in OVERALL_KEYS):
        problems.append(f"overall must carry {OVERALL_KEYS}")
    else:
        synth = overall.get("synthesis")
        if not isinstance(synth, dict) or synth.get("generator") not in GENERATORS:
            problems.append(f"overall.synthesis.generator must be one of {GENERATORS}")
        elif (set(synth) != {"generator", "text", "claims"} or not isinstance(synth.get("text"), str)
              or not isinstance(synth.get("claims"), list)):
            problems.append("overall.synthesis must carry generator, text and claims")
        if set(overall) != set(OVERALL_KEYS):
            problems.append("overall must contain only the contract fields")
    if not isinstance(record.get("entities_declared"), list):
        problems.append("entities_declared must be a list")
    return problems


def load_record(sim_dir: str) -> Optional[Dict[str, Any]]:
    """Load ``simulation_record.json`` from a regular file, or None when absent or
    unreadable.  Symbolic links are refused, matching the world-state route."""
    path = record_paths(sim_dir)["json"]
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_audit(sim_dir: str) -> Optional[Dict[str, Any]]:
    """Load ``simulation_record_audit.json`` the same way."""
    path = record_paths(sim_dir)["audit"]
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_regular(path: str) -> bytes:
    """Read a regular file without following symlinks, including directory aliases."""
    absolute = os.path.abspath(path)
    if os.path.realpath(absolute) != absolute:
        raise OSError("symlinked artifact path")
    fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("artifact is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def artifact_hashes(sim_dir: str) -> Dict[str, Optional[str]]:
    """Bind both present and absent inputs so additions invalidate old audits too."""
    result = {}
    for name in ARTIFACT_FILES:
        path = os.path.join(sim_dir, name)
        try:
            raw = read_regular(path)
            if name == "state.json":
                # Lifecycle/status/updated_at are written after finalization.
                # Only these three state fields are consumed by the compiler.
                state = json.loads(raw)
                if not isinstance(state, dict):
                    raise ValueError("invalid state object")
                raw = record_bytes({key: state.get(key) for key in
                                    ("simulation_id", "pipeline_id", "simulation_engine")})
            result[name] = hashlib.sha256(raw).hexdigest()
        except FileNotFoundError:
            if os.path.lexists(path):
                raise OSError("unreadable artifact")
            result[name] = None
    return result


def atomic_write(path: str, data: bytes) -> None:
    """Replace an artifact without opening a predictable, possibly linked temp file."""
    parent = os.path.abspath(os.path.dirname(path))
    if os.path.realpath(parent) != parent:
        raise OSError("symlinked simulation directory")
    fd, temporary = tempfile.mkstemp(prefix=".simulation-record-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_published_record(sim_dir: str):
    """Return (verified JSON snapshot, status). All publication consumers share this check.

    An old, incomplete or stale receipt cannot publish. Markdown and source inputs
    are bound as well as canonical JSON; callers must use this returned snapshot.
    """
    paths = record_paths(sim_dir)
    try:
        audit = json.loads(read_regular(paths["audit"]))
    except (OSError, ValueError):
        return None, "not_audited"
    if not isinstance(audit, dict) or audit.get("publication_status") != "passed" or audit.get("hard_issues") != []:
        return None, "failed"
    try:
        raw = read_regular(paths["json"])
        record = json.loads(raw)
        canonical = record_bytes(record)
        if (validate_shape(record) or raw != canonical or hashlib.sha256(raw).hexdigest() != audit.get("sha256")
                or audit.get("schema") != "simulation-record-audit/v1"
                or audit.get("simulation_id") != record.get("simulation_id")
                or artifact_hashes(sim_dir) != audit.get("artifact_sha256")):
            return None, "stale_audit"
        markdown = audit.get("markdown_sha256")
        if not isinstance(markdown, dict) or set(markdown) != {RECORD_MD, RECORD_MD_ZH}:
            return None, "stale_audit"
        for name, digest in markdown.items():
            if hashlib.sha256(read_regular(os.path.join(sim_dir, name))).hexdigest() != digest:
                return None, "stale_audit"
        if "world_anchor" in record.get("setup", {}):
            # The external research generation is not covered by the legacy
            # sim-directory artifact list. Revalidate it on every public read;
            # do not serve a previously audited projection after source drift.
            diagnostic = load_anchor_diagnostics(sim_dir)
            if record_bytes(diagnostic) != record_bytes(record["setup"]["world_anchor"]):
                return None, "stale_audit"
        return record, "passed"
    except (OSError, ValueError, TypeError):
        return None, "stale_audit"


def is_published(sim_dir: str) -> bool:
    return load_published_record(sim_dir)[0] is not None
