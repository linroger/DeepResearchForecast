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
_BINDING_KEYS = {"schema_version", "simulation_id", "pipeline_id", "handoff_dir", "files"}
# Schema 2 stores the handoff relative to the pipelines root, so a relocated
# install (repo rename, backup restore) keeps every bound simulation valid.
_BINDING_SCHEMA = 2
_GENERATION_FILES = ("research_report.md", "actors.json", "sources.json", "actor_dossier.md",
                     "research_contract_manifest.json", "data/datasets.json")


class ResearchBindingConflict(ValueError):
    """The simulation already pins a different research generation (provenance guard)."""


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
    # Keep genuinely old/off generations byte-compatible: the optional key is
    # absent until a sealed contextual snapshot exists. A later addition then
    # changes the generation instead of being silently adopted by an old run.
    context_path = Path(handoff) / "news_market_context.json"
    if os.path.lexists(context_path):
        from .news_market_context import load_context
        load_context(handoff)
        result["news_market_context.json"] = hashlib.sha256(
            _contained_bytes(Path(handoff), "news_market_context.json", limit=2_000_000)
        ).hexdigest()
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


def _pipelines_root():
    from ..config import Config
    return Path(os.path.realpath(Config.PIPELINE_DATA_DIR))


def _stored_handoff(handoff: Path) -> str:
    """Pipelines-root-relative POSIX path when contained, else the absolute path."""
    try:
        relative = handoff.relative_to(_pipelines_root())
    except ValueError:
        return str(handoff)
    return relative.as_posix() if relative.parts else str(handoff)


def _bound_handoff(stored: str) -> Path:
    path = Path(stored)
    if path.is_absolute():
        return path
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Invalid relative research binding path")
    return _pipelines_root() / path


def _same_generation(existing, binding) -> bool:
    """A schema-1 (absolute) and a schema-2 (relative) record of one generation are equal."""
    try:
        return (isinstance(existing, dict) and set(existing) == _BINDING_KEYS
                and existing.get("schema_version") in (1, _BINDING_SCHEMA)
                and all(existing.get(key) == binding[key] for key in ("simulation_id", "pipeline_id", "files"))
                and os.path.realpath(_bound_handoff(existing["handoff_dir"]))
                == os.path.realpath(_bound_handoff(binding["handoff_dir"])))
    except (TypeError, ValueError):
        return False


def bind_simulation_research(simulation_id, handoff_dir, *, pipeline_id, expected_generation=None,
                             report=None, sources=None):
    """Pin the research generation before PREPARE, without mutating its parent.

    Raises ResearchBindingConflict when the simulation already pins another
    generation; every other failure is an ordinary ValueError/OSError that the
    pipeline degrades to "official data unavailable".
    """
    directory = _simulation_directory(simulation_id)
    handoff = Path(handoff_dir).resolve()
    if not directory.is_dir() or not handoff.is_dir():
        raise ValueError("Simulation and research directories must already exist")
    generation = capture_research_generation(handoff, report=report, sources=sources)
    if expected_generation is not None and (
        generation["files"] != expected_generation.get("files")
        or os.path.realpath(generation["handoff_dir"]) != os.path.realpath(
            str(expected_generation.get("handoff_dir") or ""))
    ):
        raise ValueError("Consumed research generation changed before simulation binding")
    binding = {"schema_version": _BINDING_SCHEMA, "simulation_id": simulation_id, "pipeline_id": str(pipeline_id),
               "handoff_dir": _stored_handoff(handoff), "files": generation["files"]}
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
            if not _same_generation(existing, binding):
                raise ResearchBindingConflict("Simulation is already bound to different research") from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return binding


def _relocated_handoff(pipeline_id):
    """Schema-1 bindings pinned an absolute path; find the pipeline's current handoff."""
    try:
        from .pipeline_orchestrator import PipelineManager
        return Path(PipelineManager.resolve_handoff_dir(pipeline_id))
    except Exception:  # noqa: BLE001 — an unresolvable pipeline only leaves the binding invalid
        return None


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
        if (not isinstance(binding, dict) or binding.get("schema_version") not in (1, _BINDING_SCHEMA)
                or set(binding) != _BINDING_KEYS
                or binding.get("simulation_id") != simulation_id
                or not isinstance(binding.get("pipeline_id"), str) or not binding["pipeline_id"]
                or not isinstance(binding.get("handoff_dir"), str)
                or binding["schema_version"] == 1 and not Path(binding["handoff_dir"]).is_absolute()):
            raise ValueError("Simulation research binding is malformed")
        handoff = _bound_handoff(binding["handoff_dir"])
        if binding.get("files") != _generation_fingerprints(handoff):
            relocated = _relocated_handoff(binding["pipeline_id"]) if binding["schema_version"] == 1 else None
            if relocated is None or binding.get("files") != _generation_fingerprints(relocated):
                raise ValueError("Simulation research generation changed")
            handoff = relocated
        return {**binding, "handoff_dir": os.path.realpath(handoff), "status": "valid"}
    except (OSError, TypeError, ValueError, KeyError):
        _LOG.warning("Simulation research enrichment unavailable: generation proof failed")
        return {"status": "invalid"}


def research_binding_has_news_context(simulation_id):
    """Whether a binding declares the new optional proof, without accepting it.

    Used solely to preserve the historical official-only dossier degradation.
    Returning False never authorizes serving contextual data from another path.
    """
    try:
        directory = _simulation_directory(simulation_id)
        binding = json.loads(_contained_bytes(directory, _BINDING_FILE, limit=65536))
        if not isinstance(binding, dict) or not isinstance(binding.get("files"), dict):
            return False
        if "news_market_context.json" in binding["files"]:
            return True
        # A newly present capture must not be silently dropped when an older
        # consumed generation lacked it. This check never accepts its contents.
        stored = binding.get("handoff_dir")
        return isinstance(stored, str) and os.path.lexists(
            _bound_handoff(stored) / "news_market_context.json")
    except (OSError, TypeError, ValueError):
        return False


def bridge_module(name):
    """Import ``deerflow_bridge.<name>`` from the fixed repository namespace without changing sys.path."""
    with _IMPORT_LOCK:
        if "deerflow_bridge" not in sys.modules:
            spec = importlib.machinery.ModuleSpec("deerflow_bridge", loader=None, is_package=True)
            spec.submodule_search_locations = [str(_BRIDGE)]
            sys.modules["deerflow_bridge"] = importlib.util.module_from_spec(spec)
        return importlib.import_module("deerflow_bridge." + name)


def data_api():
    """Load the fixed repository namespace without changing sys.path."""
    try:
        return bridge_module("data_sources")
    except (ImportError, OSError) as exc:
        _LOG.warning("Official-data module unavailable (%s)", type(exc).__name__)
        return None


def _max_series():
    from ..config import Config
    value = getattr(Config, "DATA_SOURCES_MAX_SERIES", 24)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 24


def load_official_data(handoff_dir, *, max_series=None, anchored=()):
    """Bounded carrier; ``max_series`` defaults to Config.DATA_SOURCES_MAX_SERIES."""
    if not handoff_dir:
        return None
    api = data_api()
    if api is None:
        return None
    try:
        kwargs = {"max_series": _max_series() if max_series is None else max_series}
        if anchored:
            kwargs["anchored"] = tuple(anchored)
        return api.load_official_data(handoff_dir, **kwargs)
    except Exception as exc:  # optional, persisted enrichment only
        _LOG.warning("Official-data snapshot unavailable (%s)", type(exc).__name__)
        return None


def research_run_window(handoff_dir):
    """The research run's ``{started_at, finished_at}`` from its meta.json, else None."""
    try:
        meta = json.loads(_contained_bytes(Path(handoff_dir), "meta.json", limit=4_000_000))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    window = {}
    for key in ("started_at", "finished_at"):
        try:
            resolution_instant(meta.get(key), date_end=False)
        except (TypeError, ValueError, OverflowError):
            continue
        window[key] = str(meta[key])
    return window if "started_at" in window else None


def research_window_for_simulation(simulation_id):
    """The bound generation's research window; None for unbound or invalid bindings."""
    binding = simulation_research_binding(simulation_id)
    return research_run_window(binding["handoff_dir"]) if binding["status"] == "valid" else None


def bind_project_simulation(simulation_id, project_id):
    """Bind a simulation created outside the pipeline to its project's research.

    Only a pipeline owning ``project_id`` whose research stage completed
    qualifies; pipelines sharing one handoff (forks) count once, and several
    distinct research generations are ambiguous, so the simulation stays unbound.
    A bound simulation receives the research dossier and official data like a
    pipeline simulation. Never raises: returns ``{"status": "bound" | "unbound", ...}``.
    """
    try:
        from .pipeline_orchestrator import STAGE_RESEARCH, PipelineManager
        candidates = {}
        for entry in PipelineManager.list_pipelines():  # newest first
            pid = entry.get("pipeline_id")
            data = PipelineManager.load(pid) if pid else None
            stage = ((data.get("stages") or {}).get(STAGE_RESEARCH) or {}) if isinstance(data, dict) else {}
            if (not project_id or not isinstance(data, dict) or data.get("project_id") != project_id
                    or not isinstance(stage, dict) or stage.get("status") != "completed"):
                continue
            candidates.setdefault(os.path.realpath(PipelineManager.resolve_handoff_dir(pid)), pid)
        if len(candidates) != 1:
            reason = "ambiguous pipeline research" if candidates else "no completed pipeline research"
            return {"status": "unbound", "reason": reason}
        handoff, pid = next(iter(candidates.items()))
        bind_simulation_research(simulation_id, handoff, pipeline_id=pid)
        return {"status": "bound", "pipeline_id": pid}
    except Exception as exc:  # noqa: BLE001 — an unbound simulation simply lacks enrichment
        _LOG.warning("Manual simulation research binding unavailable (%s)", type(exc).__name__)
        return {"status": "unbound", "reason": type(exc).__name__}


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


# Feeds that strip observation status: any status shown for them is inferred by rule.
_STATUS_INFERRED_PREFIXES = ("wb:", "imf:WEO/", "imf:WEO_")
# Reader-facing snapshot wording per language. Values, periods, units, sources and
# [S#] markers are language-neutral; "zh" uses the report's Chinese vocabulary
# (report_agent _OFFICIAL_TABLE_HEADERS / _official_daily_basis) with ASCII
# punctuation, because the world brief's untrusted-data boundary NFKC-normalizes
# full-width brackets and colons anyway (the agents read exactly this text).
_SNAPSHOT_TEXT = {
    "en": {
        "title": "## Official historical data",
        "columns": "Indicator | Value | Period | YoY change | 5y range | Units | Source",
        "unclassified_title": "Publisher status unclassified (may include estimates; not confirmed history):",
        "unclassified_columns": "Indicator | Value | Period | Units | Source",
        "none": "n/a", "range": "{low} to {high}", "points": " pp",
        "preliminary": "preliminary", "eop": "end-of-month value of daily data",
        "avg": "monthly mean of daily data", "daily": "latest daily {date}: {value}",
        "inferred": "status inferred; publisher feed omits observation status",
        "estimate": "publisher estimate", "unsupplied": "status not supplied",
        "notes": " ({})", "joiner": "; ",
    },
    "zh": {
        "title": "## 官方历史数据",
        "columns": "指标 | 数值 | 期间 | 同比变化 | 五年区间 | 单位 | 来源",
        "unclassified_title": "发布方未标注状态 (可能含估计值; 并非已确认的历史):",
        "unclassified_columns": "指标 | 数值 | 期间 | 单位 | 来源",
        "none": "无", "range": "{low} 至 {high}", "points": " 个百分点",
        "preliminary": "初值", "eop": "日度数据的月末值",
        "avg": "日度数据的月均值", "daily": "最新日度值 {date}: {value}",
        "inferred": "状态为推断: 发布方数据未提供观测状态",
        "estimate": "发布方估计值", "unsupplied": "未提供状态",
        "notes": " ({})", "joiner": "; ",
    },
}


def _snapshot_lang(language) -> str:
    """'zh' for a Chinese snapshot (zh*, Chinese, 中文); every other value is English."""
    text = str(language or "").strip().lower()
    return "zh" if text.startswith(("zh", "chinese", "中文")) else "en"


def _snapshot_cutoff(as_of, window):
    """Availability cutoff. A live forecast (as_of on or after its research run's
    start day) admits that run's own captures up to the run's completion, so a run
    crossing UTC midnight keeps its data; a historical as_of stays strict."""
    cutoff = resolution_instant(as_of) if as_of is not None else datetime.now(timezone.utc)
    if as_of is None or not isinstance(window, Mapping):
        return cutoff
    try:
        started = resolution_instant(window.get("started_at"), date_end=False)
        finished = resolution_instant(window.get("finished_at"))
    except (TypeError, ValueError, OverflowError):
        return cutoff
    return finished if cutoff.date() >= started.date() and finished > cutoff else cutoff


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def _value_cell(api, value, units, lang="en"):
    rendered = format_value(value, units)
    scaled = api.scaled_value(value, units, lang)
    return f"{rendered} ({scaled})" if scaled else rendered


def _trend_level(api, value, units, lang="en", *, signed=False):
    """Derived trend figures read at magnitude ('≈ 40.17 trillion', zh '≈40.17万亿') when
    the units take a scale companion; the exact stored value stays in the Value cell.
    ``signed`` marks a positive change with '+'."""
    if api.scaled_value(abs(value), units, lang):
        scaled = api.scaled_value(abs(value), "", lang)
        prefix = "≈ " if scaled.startswith("≈ ") else "≈"
        sign = "-" if value < 0 else "+" if signed and value > 0 else ""
        return f"{prefix}{sign}{scaled[len(prefix):]}"
    return format_value(value, units)


def _trend_cells(api, history, frequency, units, lang="en"):
    """Year-on-year change and 5-year range from the same displayable history."""
    text = _SNAPSHOT_TEXT[lang]
    period, value, _ = history[-1]
    yoy = text["none"]
    if frequency in ("M", "Q", "A"):
        prior = next((v for p, v, _ in history if p == _years_before(period, 1)), None)
        if prior is not None:
            delta = value - prior
            yoy = api.format_change(delta, units)
            if yoy.endswith(" pp"):
                yoy = yoy[:-3] + text["points"]
            if api.scaled_value(abs(delta), units, lang):
                yoy = _trend_level(api, delta, units, lang, signed=True)
            if not api.is_percent_units(units) and prior:
                yoy += f" ({delta / abs(prior) * 100:+.1f}%)"  # as series_stats: relative to |prior|
    window = [v for p, v, _ in history if p > _years_before(period, 5)]
    span = (text["range"].format(low=_trend_level(api, min(window), units, lang),
                                 high=_trend_level(api, max(window), units, lang))
            if len(window) > 1 else text["none"])
    return yoy, span


def _snapshot_line(api, row, cutoff, lang="en"):
    """(exclusion reason, main-table line, unclassified-block line) for one carrier row."""
    try:
        series = api.Series.from_dict(dict(row))
    except (TypeError, ValueError, KeyError, OverflowError):
        return "invalid", None, None
    units = series.units.strip()
    if not units:
        return "no_units", None, None
    try:
        retrieved = resolution_instant(series.retrieved_at)
    except (TypeError, ValueError, OverflowError):
        return "no_retrieval", None, None
    if retrieved > cutoff:
        return "after_cutoff", None, None
    provenance = series.provenance
    aggregated = bool(provenance.get("aggregation") or provenance.get("aggregation_method"))
    inferred = series.series.startswith(_STATUS_INFERRED_PREFIXES) or "fidelity_policy_version" in provenance
    # resolution_safe=False means a value cannot settle a forecast; it is shown only
    # for a stated, labelled reason (daily aggregation or a status-stripping feed).
    if provenance.get("resolution_safe") is False and not (aggregated or inferred):
        return "unsafe", None, None
    history, unclassified = [], []
    for obs in series.observations:
        period = _day(obs.date)
        if obs.value is None or not math.isfinite(obs.value) or period is None or period > cutoff.date():
            continue
        kind = api.observation_kind(obs, series)
        if kind in ("observed", "preliminary"):
            history.append((period, obs.value, kind))
        elif kind in ("unknown", "estimate") and period.year < retrieved.year:
            unclassified.append((period, obs.value, kind))
    sid = str(row.get("source_id") or "")
    citation = f" [{sid if sid.startswith('S') else 'S' + sid}]" if re.fullmatch(r"S?\d+", sid) else ""
    provider = (series.provider_name or series.provider).split(" (")[0]
    source = (_cell(provider, 60) + citation if citation
              else _cell(series.source_url or provider, 230))
    text = _SNAPSHOT_TEXT[lang]
    label = _cell(api.series_label(series, lang), 140)
    periods = provenance.get("periods") if isinstance(provenance.get("periods"), Mapping) else {}

    def shown(period):
        # Fiscal years and aggregated months carry a publisher label (FY2026, 2026-09);
        # other periods read at their frequency (2025, 2026-Q3, 2026-09), so a monthly
        # or annual value is never mistaken for a single day's reading.
        meta = periods.get(period.isoformat())
        if isinstance(meta, Mapping) and meta.get("label"):
            return _cell(meta.get("label"), 20)
        if series.frequency == "A" and (period.month, period.day) == (1, 1):
            return str(period.year)
        if series.frequency == "Q" and period.day == 1 and period.month in (1, 4, 7, 10):
            return f"{period.year}-Q{(period.month - 1) // 3 + 1}"
        if series.frequency == "M" and period.day == 1:
            return period.strftime("%Y-%m")
        return period.isoformat()
    if history:
        period, value, kind = history[-1]
        yoy, span = _trend_cells(api, history, series.frequency, units, lang)
        notes = [text["preliminary"]] if kind == "preliminary" else []
        if aggregated:
            notes.append(text["eop"] if provenance.get("aggregation_method") == "eop" else text["avg"])
            daily = provenance.get("latest_daily")
            day = _day(daily.get("date")) if isinstance(daily, Mapping) else None
            if day and day <= cutoff.date() and isinstance(daily.get("value"), (int, float)) \
                    and not isinstance(daily["value"], bool) and math.isfinite(daily["value"]):
                notes.append(text["daily"].format(date=day.isoformat(),
                                                  value=_value_cell(api, daily["value"], units, lang)))
        if inferred:
            notes.append(text["inferred"])
        line = (f"{label} | {_value_cell(api, value, units, lang)} | {shown(period)} | {yoy} | {span} | "
                f"{_cell(units, 80)} | {source}" + (text["notes"].format(text["joiner"].join(notes)) if notes else ""))
        return "", line, None
    if unclassified:
        period, value, kind = unclassified[-1]
        status = text["estimate"] if kind == "estimate" else text["unsupplied"]
        line = (f"{label} | {_value_cell(api, value, units, lang)} | {shown(period)} | {_cell(units, 80)} | "
                f"{source}" + text["notes"].format(status))
        return "", None, line
    return "no_history", None, None


def _render_snapshot(main, unclassified, lang="en"):
    if not main and not unclassified:
        return ""
    text = _SNAPSHOT_TEXT[lang]
    lines = [text["title"]]
    if main:
        lines += [text["columns"], *main]
    if unclassified:
        lines += [text["unclassified_title"], text["unclassified_columns"], *unclassified]
    return "\n".join(lines)


def historical_snapshot(official_data, *, as_of=None, max_series=8, max_chars=3500,
                        research_window=None, stats=None, language="en"):
    """Render bounded public observations; projections never appear.

    The main table shows each series' newest observed (or preliminary) point with
    its year-on-year change and 5-year range. Points whose status a publisher feed
    does not supply, and publisher estimates, appear only in a separately labelled
    block and only for years before the retrieval year. Partial periods are never
    shown. A historical cutoff requires a captured retrieval at or before that
    date; a live forecast's cutoff extends to its research run's completion
    (``research_window``). ``stats`` (a dict) receives shown/excluded counts.
    ``language`` "zh" (also "Chinese"/"中文") renders headings, series names, notes
    and magnitudes in Chinese; values, periods, published units and [S#] markers are
    unchanged, and any other value keeps the English text byte for byte.
    Canonical actor callers retain their own, narrower knowledge authority.
    """
    lang = _snapshot_lang(language)
    excluded = {}
    main, unclassified = [], []

    def finish(text):
        if isinstance(stats, dict):
            stats.update(shown=len(main) + len(unclassified), excluded=dict(excluded))
        return text

    if not isinstance(official_data, Mapping):
        return finish("")
    try:
        cutoff = _snapshot_cutoff(as_of, research_window)
    except (TypeError, ValueError, OverflowError):
        return finish("")
    rows = official_data.get("series")
    api = data_api()
    if not isinstance(rows, list) or api is None:
        return finish("")
    limit = max(0, min(12, int(max_series)))
    for row in rows:
        try:
            reason, line, extra = ("invalid", None, None) if not isinstance(row, Mapping) else (
                ("max_series", None, None) if len(main) + len(unclassified) >= limit
                else _snapshot_line(api, row, cutoff, lang))
        except (TypeError, ValueError, KeyError, OverflowError, AttributeError):
            reason, line, extra = "invalid", None, None  # one malformed row never fails a stage
        if line and len(_render_snapshot([*main, line], unclassified, lang)) <= max_chars:
            main.append(line)
        elif extra and len(_render_snapshot(main, [*unclassified, extra], lang)) <= max_chars:
            unclassified.append(extra)
        else:
            reason = reason or "budget"
            excluded[reason] = excluded.get(reason, 0) + 1
    return finish(_render_snapshot(main, unclassified, lang))
