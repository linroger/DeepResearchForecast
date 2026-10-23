"""Admit one research generation at PREPARE; runtime uses the sealed projection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .actor_context import actor_id_for, build_actor_context_pack, canonical_json_sha256, text_sha256
from . import official_data
from .research_preparation import compile_preparation_context, load_preparation_context


def admit_research_inputs(simulation_id, *, question, research_report, actors,
                          research_generation_id=None):
    """Bind explicit inputs; optional enrichment is read only from their exact owner.

    Unbound/manual callers can compile their supplied dossier, but never discover
    enrichment from another run. A claimed binding which changed fails closed.
    The effective availability window is captured once, inside the new seal.
    """
    binding = official_data.simulation_research_binding(simulation_id)
    if binding["status"] == "invalid":
        raise ValueError("Research generation changed before preparation")
    if not isinstance(actors, dict):
        if binding["status"] == "valid":
            raise ValueError("Bound research requires its original actor document")
        return None
    sources, data, window, artifacts = None, None, None, {}
    source_binding = {"kind": "supplied_inputs"}
    if binding["status"] == "valid":
        root = Path(binding["handoff_dir"])

        def read(name):
            expected = binding["files"].get(name)
            if not expected:
                return None
            raw = official_data._contained_bytes(root, name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"Research artifact changed during preparation: {name}")
            return raw

        report_bytes, actor_bytes = read("research_report.md"), read("actors.json")
        if (report_bytes is None or report_bytes.decode("utf-8") != research_report
                or actor_bytes is None
                or canonical_json_sha256(json.loads(actor_bytes)) != canonical_json_sha256(actors)):
            raise ValueError("Preparation inputs differ from the bound research generation")
        raw_sources = read("sources.json")
        sources = json.loads(raw_sources) if raw_sources is not None else None
        for name in ("quantitative.json", "contested.json", "timeline.json"):
            raw = read(name)
            if raw is not None:
                artifacts[name] = json.loads(raw)
        data = official_data.load_official_data(root, strict=True)
        window = official_data.research_run_window(root)
        source_binding = {"kind": "bound_research", "pipeline_id": binding["pipeline_id"],
                          "files": dict(binding["files"])}
        if official_data.simulation_research_binding(simulation_id) != binding:
            raise ValueError("Research generation changed during preparation")
    source_binding["research_generation_id"] = research_generation_id or (
        "research_" + canonical_json_sha256({"report_sha256": text_sha256(research_report),
                                            "actors_sha256": canonical_json_sha256(actors),
                                            "binding": source_binding}))
    return dict(question=question, research_report=research_report, actors=actors,
                official_data=data, sources=sources, source_binding=source_binding,
                report_artifacts=artifacts,
                as_of={"as_of": actors.get("as_of_date"), "research_window": window})


def prepare_research_context(simulation_id, *, question, research_report, actors,
                            actor_context_packs=None, research_generation_id=None,
                            allow_sparse_actor_sections=False):
    admitted = admit_research_inputs(simulation_id, question=question, research_report=research_report,
                                    actors=actors, research_generation_id=research_generation_id)
    if admitted is None:
        return None
    packs = actor_context_packs
    if packs is None:
        packs = {actor_id_for(row): build_actor_context_pack(
                     actors, row, research_report, allow_missing_sections=allow_sparse_actor_sections)
                 for row in actors.get("actors", []) if isinstance(row, dict) and row.get("name")}
    return compile_preparation_context(**admitted, actor_context_packs=packs)


def preparation_marker(bundle):
    if bundle is None:
        return None
    return {"schema_version": bundle["schema_version"],
            "content_sha256": bundle["content_sha256"], "source": bundle["source"]}


def load_config_preparation(sim_dir, config):
    """An explicit marker requires complete matching artifacts, including after restart."""
    if "research_preparation" not in config:
        return None
    marker = config["research_preparation"]
    if (not isinstance(marker, dict) or set(marker) != {"schema_version", "content_sha256", "source"}
            or marker["schema_version"] != "research-preparation/v1"
            or not isinstance(marker["content_sha256"], str) or len(marker["content_sha256"]) != 64
            or not isinstance(marker["source"], dict)):
        raise ValueError("Invalid research preparation marker")
    return load_preparation_context(sim_dir, expected_sha256=marker["content_sha256"],
                                    expected_sources=marker["source"])
