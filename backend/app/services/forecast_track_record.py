"""Deterministic presentation of a frozen, typed forecast track record."""
from __future__ import annotations

import hashlib
import json
import math
import re

START = "<!-- forecast-track-record:start -->"
END = "<!-- forecast-track-record:end -->"
_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
_KINDS = ("scenario", "market_binary", "official_data_binary", "unanchored_binary")


def snapshot(forecast: dict) -> dict | None:
    history = forecast.get("historical_calibration")
    value = history.get("forecast_track_record") if isinstance(history, dict) else None
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Invalid forecast track record schema")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("source_digest") or "")):
        raise ValueError("Forecast track record has no source digest")
    tracks = value.get("tracks")
    if not isinstance(tracks, dict) or any(kind not in tracks for kind in _KINDS):
        raise ValueError("Forecast track record has missing tracks")
    for kind in _KINDS:
        row = tracks[kind]
        if not isinstance(row, dict):
            raise ValueError("Invalid forecast track record row")
        counts = [row.get(key) for key in ("n_forecasts", "n_resolved", "n_outstanding")]
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError("Invalid forecast track record counts")
        if counts[0] != counts[1] + counts[2]:
            raise ValueError("Forecast track record denominator mismatch")
        score = row.get("mean_brier")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))
                                  or not math.isfinite(score) or not 0 <= score <= 2):
            raise ValueError("Invalid forecast track record score")
        if (counts[1] == 0) != (score is None):
            raise ValueError("Forecast track record score/count mismatch")
    return value


def render(value: dict, language: str = "English") -> str:
    """Render counts and scores as ledger metadata, never pooled across types."""
    zh = str(language).lower() in ("chinese", "zh", "zh-cn", "中文")
    labels = (
        ("情景预测（多类别）", "市场二元预测", "官方数据二元预测", "无锚定二元预测")
        if zh else
        ("Scenarios (multiclass)", "Market binaries", "Official-data binaries", "Unanchored binaries")
    )
    lines = [START, "## 历史预测记录" if zh else "## Historical forecasting track record", "",
             ("这些分数描述已保存预测的实际判定记录；样本有限时不能据此声称模型已校准。"
              if zh else
              "These scores describe retained forecasts with recorded outcomes. "
              "A limited record does not establish calibration."), "",
             "| 类型 | 预测数 | 已判定 | 待判定 | 平均 Brier |" if zh else
             "| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |",
             "|---|---:|---:|---:|---:|"]
    for kind, label in zip(_KINDS, labels):
        row = value["tracks"][kind]
        score = row.get("mean_brier")
        score_text = "—" if score is None else f"{score:.4f}"
        lines.append(f"| {label} | {row['n_forecasts']} | {row['n_resolved']} | "
                     f"{row['n_outstanding']} | {score_text} |")
    lines += ["", ("情景分数与二元分数分别统计；本报告不计入自身的历史记录。"
                   if zh else
                   "Scenario and binary scores have separate denominators. "
                   "This report is excluded from its own history."), END]
    return "\n".join(lines)


def audit_and_strip(markdown: str, forecast: dict) -> tuple[str, dict]:
    """Exclude only an exact canonical block whose payload is sealed in forecast.json."""
    try:
        value = snapshot(forecast)
    except ValueError as exc:
        return markdown, {"required": True, "passed": False, "reason": str(exc)}
    marked = START in markdown or END in markdown
    if value is None:
        return markdown, {"required": False, "passed": not marked,
                          "reason": "unbound track record block" if marked else None}
    valid = (markdown.count(START) == 1 and markdown.count(END) == 1)
    matches = list(_BLOCK.finditer(markdown))
    valid = valid and len(matches) == 1 and matches[0].group() in {
        render(value, "English"), render(value, "Chinese")}
    audit = {"required": True, "passed": valid, "source_digest": value["source_digest"],
             "snapshot_sha256": hashlib.sha256(json.dumps(
                 value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                 separators=(",", ":")).encode()).hexdigest()}
    if not valid:
        audit["reason"] = "track record Markdown differs from its frozen snapshot"
        return markdown, audit
    match = matches[0]
    before, after = markdown[:match.start()].rstrip(), markdown[match.end():].lstrip()
    prose = before + ("\n\n" if before and after else "") + after
    return prose.rstrip() + "\n", audit


def insert(markdown: str, forecast: dict, language: str = "English") -> str:
    value = snapshot(forecast)
    if value is None:
        return markdown
    if START in markdown or END in markdown:
        _, audit = audit_and_strip(markdown, forecast)
        if not audit["passed"]:
            raise ValueError(audit["reason"])
        return markdown
    # Keep References last, preserving their existing citation namespace.
    heading = re.search(r"(?m)^## (?:References|参考文献|参考资料)\s*$", markdown)
    position = heading.start() if heading else len(markdown)
    return (markdown[:position].rstrip() + "\n\n" + render(value, language)
            + "\n\n" + markdown[position:].lstrip()).rstrip() + "\n"
