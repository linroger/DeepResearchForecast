"""Lazy backend access to the bridge's persisted official-data contract.

Report/context readers never fetch a replacement for a saved observation. Only
the explicit resolver's get_data_sources accessor can construct the data client.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import logging
import math
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sys
import threading
from typing import Any

_BRIDGE = Path(__file__).resolve().parents[3] / "deerflow_bridge"
_IMPORT_LOCK = threading.RLock()
_LOG = logging.getLogger(__name__)
_BINDING_FILE = "official_research_binding.json"
_GENERATION_FILES = ("research_report.md", "actors.json", "sources.json", "actor_dossier.md",
                     "research_contract_manifest.json", "data/datasets.json")


def _contained_bytes(root: Path, relative: str, *, limit=16_000_000):
    """Read a bounded regular file through pinned, non-symlink directory handles."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("Research binding artifact is not a bounded regular file")
            chunks, size = [], 0
            while chunk := os.read(handle, min(65536, limit + 1 - size)):
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise ValueError("Research binding artifact exceeds its size limit")
            return b"".join(chunks)
        finally:
            os.close(handle)
    finally:
        os.close(descriptor)


def _generation_fingerprints(handoff):
    result = {}
    for name in _GENERATION_FILES:
        try:
            result[name] = hashlib.sha256(_contained_bytes(Path(handoff), name)).hexdigest()
        except FileNotFoundError:
            result[name] = None
    return result


def _simulation_directory(simulation_id):
    from .simulation_manager import SimulationManager
    if not isinstance(simulation_id, str) or not re.fullmatch(r"sim_[A-Za-z0-9_-]{1,100}", simulation_id):
        raise ValueError("Invalid simulation identity")
    root = Path(SimulationManager.SIMULATION_DATA_DIR).resolve()
    directory = root / simulation_id
    if directory.is_symlink():
        raise ValueError("Simulation directory must not be a symlink")
    return directory


def capture_research_generation(handoff_dir, *, report=None, sources=None):
    """Capture the consumed generation before downstream work can outlive it."""
    handoff = Path(handoff_dir).resolve()
    before = _generation_fingerprints(handoff)
    if report is not None and _contained_bytes(handoff, "research_report.md").decode("utf-8") != report:
        raise ValueError("Consumed research report differs from the disk generation")
    if sources is not None and json.loads(_contained_bytes(handoff, "sources.json")) != sources:
        raise ValueError("Consumed research sources differ from the disk generation")
    if before != _generation_fingerprints(handoff):
        raise ValueError("Research generation changed during capture")
    return {"handoff_dir": str(handoff), "files": before}


def bind_simulation_research(simulation_id, handoff_dir, *, pipeline_id, expected_generation=None,
                             report=None, sources=None):
    """Pin the research generation before PREPARE, without mutating its parent."""
    directory = _simulation_directory(simulation_id)
    handoff = Path(handoff_dir).resolve()
    if not directory.is_dir() or not handoff.is_dir():
        raise ValueError("Simulation and research directories must already exist")
    generation = capture_research_generation(handoff, report=report, sources=sources)
    if expected_generation is not None and any(
        generation[key] != expected_generation.get(key) for key in ("handoff_dir", "files")
    ):
        raise ValueError("Consumed research generation changed before simulation binding")
    binding = {"schema_version": 1, "simulation_id": simulation_id, "pipeline_id": str(pipeline_id),
               **generation}
    raw = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".research-binding-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Atomic create-only publication: a retry cannot replace another
            # generation even if two processes race to bind the same simulation.
            os.link(temp, directory / _BINDING_FILE)
        except FileExistsError:
            existing = json.loads(_contained_bytes(directory, _BINDING_FILE, limit=65536))
            if existing != binding:
                raise ValueError("Simulation is already bound to different research") from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return binding


def simulation_research_binding(simulation_id):
    """Read-only lookup; invalid proof never falls back to mutable enrichment."""
    try:
        directory = _simulation_directory(simulation_id)
        raw = _contained_bytes(directory, _BINDING_FILE, limit=65536)
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, TypeError, ValueError):
        return {"status": "invalid"}
    try:
        binding = json.loads(raw)
        if (not isinstance(binding, dict) or binding.get("schema_version") != 1
                or set(binding) != {"schema_version", "simulation_id", "pipeline_id", "handoff_dir", "files"}
                or binding.get("simulation_id") != simulation_id
                or not isinstance(binding.get("pipeline_id"), str) or not binding["pipeline_id"]
                or not isinstance(binding.get("handoff_dir"), str)
                or not Path(binding["handoff_dir"]).is_absolute()
                or binding.get("files") != _generation_fingerprints(binding["handoff_dir"])):
            raise ValueError("Simulation research generation changed")
        return {**binding, "status": "valid"}
    except (OSError, TypeError, ValueError, KeyError):
        _LOG.warning("Simulation research enrichment unavailable: generation proof failed")
        return {"status": "invalid"}


def data_api():
    """Load the fixed repository namespace without changing sys.path."""
    with _IMPORT_LOCK:
        if "deerflow_bridge" not in sys.modules:
            spec = importlib.machinery.ModuleSpec("deerflow_bridge", loader=None, is_package=True)
            spec.submodule_search_locations = [str(_BRIDGE)]
            sys.modules["deerflow_bridge"] = importlib.util.module_from_spec(spec)
        try:
            return importlib.import_module("deerflow_bridge.data_sources")
        except (ImportError, OSError) as exc:
            _LOG.warning("Official-data module unavailable (%s)", type(exc).__name__)
            return None


def load_official_data(handoff_dir, *, max_series=12):
    if not handoff_dir:
        return None
    api = data_api()
    if api is None:
        return None
    try:
        return api.load_official_data(handoff_dir, max_series=max_series)
    except Exception as exc:  # optional, persisted enrichment only
        _LOG.warning("Official-data snapshot unavailable (%s)", type(exc).__name__)
        return None


def load_for_simulation(simulation_id):
    from .pipeline_orchestrator import load_research_dossier_for_simulation
    return load_research_dossier_for_simulation(simulation_id).get("official_data")


def get_data_sources(*, env=None):
    api = data_api()
    return api.get_data_sources(env=env) if api is not None else None


def validate_data_anchor(anchor, official_data):
    api = data_api()
    if api is None:
        return None
    try:
        return api.validate_data_anchor(anchor, official_data)
    except (TypeError, ValueError, KeyError):
        return None


def resolve_data_anchor(anchor, series, *, as_of=None):
    api = data_api()
    if api is None:
        return {"status": "manual", "reason": "Official-data module unavailable", "series": ""}
    return api.resolve_data_anchor(anchor, series, as_of=as_of)


def resolution_instant(value, *, date_end=True):
    """Share the canonical UTC/date-interval semantics with every consumer."""
    api = data_api()
    if api is None:
        raise ValueError("Official-data module unavailable")
    return api.resolution_instant(value, date_end=date_end)


def format_value(value, units):
    api = data_api()
    return api.format_value(value, units) if api is not None else str(value)


def series_stats(series):
    api = data_api()
    if api is None:
        return {}
    if isinstance(series, Mapping):
        series = api.Series.from_dict(dict(series))
    return api.series_stats(series)


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _cell(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("|", "/").split())[:limit]


def historical_snapshot(official_data, *, as_of=None, max_series=8, max_chars=3500):
    """Render bounded public observations, never projections or unknown vintages.

    A historical cutoff requires a captured retrieval at or before that date.
    Unknown vintage availability is not inferred from the observation's date.
    Canonical actor callers retain their own, narrower knowledge authority.
    """
    if not isinstance(official_data, Mapping):
        return ""
    try:
        cutoff = resolution_instant(as_of) if as_of is not None else datetime.now(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return ""
    rows = official_data.get("series")
    if not isinstance(rows, list):
        return ""
    api = data_api()
    if api is None:
        return ""
    header = "## Official historical data\nIndicator | Value | Period | Units | Source"
    lines = []
    for row in rows:
        if not isinstance(row, Mapping) or len(lines) >= max(0, min(12, int(max_series))):
            continue
        try:
            # Reapply current provider/status fidelity even to older carriers;
            # hash integrity alone cannot restore metadata a native tool lost.
            row = {**row, **api.Series.from_dict(dict(row)).to_dict()}
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
        if row["provenance"].get("resolution_safe") is False:
            continue
        units = str(row.get("units") or "").strip()
        if not units:
            continue
        try:
            retrieved = resolution_instant(row.get("retrieved_at"))
        except (TypeError, ValueError, OverflowError):
            continue
        if retrieved > cutoff:
            continue
        projection_start = _day(row.get("projection_from"))
        identity = str(row.get("series") or "")
        if not projection_start and any(tag in identity.upper() for tag in ("WEO", "GEP")):
            continue
        candidates = []
        for observation in row.get("observations") or []:
            if not isinstance(observation, Mapping):
                continue
            period = _day(observation.get("date"))
            value = observation.get("value")
            flag = str(observation.get("flag") or "").strip().lower()
            if (period is None or period > cutoff.date() or (projection_start and period >= projection_start)
                    or flag not in {"", "a", "actual", "observed", "reported", "r", "revised"}
                    or observation.get("is_projection") is True
                    or isinstance(value, bool) or not isinstance(value, (float, int))
                    or not math.isfinite(float(value))):
                continue
            candidates.append((period, float(value), flag))
        if not candidates:
            continue
        period, value, flag = max(candidates, key=lambda item: item[0])
        sid = str(row.get("source_id") or "")
        citation = f" [{sid if sid.startswith('S') else 'S' + sid}]" if re.fullmatch(r"S?\d+", sid) else ""
        label = _cell(row.get("title") or identity, 140)
        rendered = format_value(value, units)
        source = _cell(row.get("source_url") or row.get("provider_name") or row.get("provider"), 230)
        line = f"{label} | {rendered} | {period.isoformat()} | {_cell(units, 80)} | {source}{citation}"
        if flag:
            line += f" (flag: {_cell(flag, 30)})"
        if len(header) + 1 + sum(len(item) + 1 for item in lines) + len(line) > max_chars:
            continue
        lines.append(line)
    return header + "\n" + "\n".join(lines) if lines else ""
