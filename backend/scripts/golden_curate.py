#!/usr/bin/env python3
"""Golden-set curation CLI (EVAL-9, candidate P17).

``audit`` checks a golden file against the schema v2 data contract
(``app/services/golden_set.py``) without scoring anything:

    python backend/scripts/golden_curate.py audit [--golden PATH] [--strict] \
        [-o golden_audit.json] [--markdown [PATH]]

- validation: ``golden_set.validate_question`` per row; ``--strict`` also
  requires verification 'verified' and non-empty resolution_evidence;
- leak lint: ``golden_set.leak_findings`` over the forecaster-visible text;
- recompute: ``golden_set.recompute_label`` for every evidence-backed row, and
  each disagreement with the recorded outcome;
- scoring status: how many rows are scored and which are ambiguous (never
  scored by golden_eval), each with its evidence, recomputed label and reason;
- balance: ``golden_set.balance_audit`` (advisory, never gates).

A v1 file is audited against the v2 contract too, which lists the rows whose
visible text leaks and what its migration still needs.

Exit status: 0 = audited (without ``--strict`` the audit is report-only);
1 = nothing audited: the golden file cannot be read or declares an unsupported
schema, or the JSON and markdown outputs name the same file;
2 = ``--strict`` and at least one violation (a row with validation errors,
leak findings or a recompute mismatch, or a duplicate id).

``--markdown`` without a path writes the markdown next to ``-o`` (same name,
``.md``), or ``golden_audit.md`` without ``-o``. When the markdown path is the
``-o`` file itself (``-o audit.md --markdown``) nothing is written (exit 1), so the
summary never replaces the JSON report. With neither output the JSON report goes
to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import golden_set  # noqa: E402
from app.utils.atomic import write_json_atomic, write_text_atomic  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_PATH = os.path.join(REPO_ROOT, "backend", "tests", "eval", "golden_questions.json")
DEFAULT_MARKDOWN = "golden_audit.md"

EXIT_OK = 0
EXIT_UNREADABLE = 1
EXIT_STRICT_VIOLATIONS = 2

_MARKDOWN_BESIDE_JSON = ""   # --markdown given without a path


def _row_key(q: Any, index: int) -> str:
    qid = str(q.get("id") or "").strip() if isinstance(q, dict) else ""
    return qid or f"#{index}"


def _scoring_status(q: Dict[str, Any]) -> str:
    """The row's scoring status as golden_eval applies it: a missing status is scored."""
    if golden_set.is_ambiguous(q):
        return golden_set.SCORING_AMBIGUOUS
    status = q.get("scoring_status")
    return golden_set.SCORING_SCORED if status is None else str(status)


def audit_golden(payload: Any, *, strict: bool = False, golden_path: str = "") -> Dict[str, Any]:
    """Audit a loaded golden file (pure): validation, leak lint, recompute and balance.

    Raises ValueError when the payload has no questions or declares an
    unsupported schema version. ``violation_ids`` lists every row with
    validation errors, leak findings or a recompute mismatch, plus duplicate
    ids; only ``--strict`` turns them into a failing exit status.
    ``scoring_status`` counts the rows per status and lists each ambiguous row
    (golden_eval never scores it) with whether it is evidence-backed, its
    recomputed label and its stated reason (``resolution_note``).
    """
    version = golden_set.schema_version(payload)
    questions = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(questions, list) or not questions:
        raise ValueError("golden file has no 'questions' list")
    keys = [_row_key(q, i) for i, q in enumerate(questions)]
    duplicates = sorted(key for key, n in Counter(keys).items() if n > 1)

    errors: Dict[str, List[str]] = {}
    leaks: Dict[str, List[Dict[str, str]]] = {}
    labels: Dict[str, str] = {}
    mismatches: Dict[str, str] = {}
    verification: Counter = Counter()
    statuses: Counter = Counter()
    ambiguous: Dict[str, Dict[str, Any]] = {}
    for key, q in zip(keys, questions, strict=True):
        row_errors = golden_set.validate_question(q, strict=strict)
        if row_errors:
            errors.setdefault(key, []).extend(row_errors)
        if not isinstance(q, dict):
            verification["(not an object)"] += 1
            statuses["(not an object)"] += 1
            continue
        verification[str(q.get("verification") or "(missing)")] += 1
        statuses[_scoring_status(q)] += 1
        if golden_set.is_ambiguous(q):
            backed = golden_set.is_evidence_backed(q)
            note = q.get("resolution_note")
            ambiguous[key] = {
                "evidence_backed": backed,
                "recomputed_label": golden_set.recompute_label(q) if backed else None,
                "reason": note if isinstance(note, str) and note.strip() else None,
            }
        findings = golden_set.leak_findings(q)
        if findings:
            leaks.setdefault(key, []).extend(findings)
        if golden_set.is_evidence_backed(q):
            labels[key] = golden_set.recompute_label(q)
            mismatch = golden_set.recompute_mismatch(q)
            if mismatch:
                mismatches[key] = mismatch

    violation_ids = sorted(set(errors) | set(leaks) | set(mismatches) | set(duplicates))
    return {
        "mode": "golden-audit",
        "golden_path": golden_path,
        "schema_version": version,
        "strict": strict,
        "n_questions": len(questions),
        "verification": dict(sorted(verification.items())),
        "duplicate_ids": duplicates,
        "validation": {"n_rows_with_errors": len(errors), "errors": errors},
        "leaks": {"n_rows_with_findings": len(leaks), "findings": leaks},
        "recompute": {
            "n_evidence_backed": len(labels),
            "label_counts": dict(sorted(Counter(labels.values()).items())),
            "labels": labels,
            "mismatches": mismatches,
        },
        "scoring_status": {"counts": dict(sorted(statuses.items())), "ambiguous": ambiguous},
        "balance": golden_set.balance_audit(questions),
        "violation_ids": violation_ids,
        "n_violations": len(violation_ids),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_audit_markdown(report: Dict[str, Any]) -> str:
    """Human-readable markdown of an ``audit_golden`` report."""
    gate = "strict (violations fail with exit 2)" if report.get("strict") else "report-only"
    violations = report.get("violation_ids") or []
    lines: List[str] = [
        "# Golden-set audit", "",
        f"- golden: `{report.get('golden_path', '')}` (schema v{report.get('schema_version')}, "
        f"{report.get('n_questions', 0)} questions)",
        f"- mode: {gate}",
        f"- rows with violations: **{len(violations)}**" + (f" ({', '.join(violations)})" if violations else ""),
    ]
    if report.get("duplicate_ids"):
        lines.append(f"- duplicate ids: {', '.join(report['duplicate_ids'])}")
    lines += ["", "## Verification", "", "| state | rows |", "|---|---|"]
    lines += [f"| {_cell(state)} | {n} |" for state, n in (report.get("verification") or {}).items()]

    errors = (report.get("validation") or {}).get("errors") or {}
    lines += ["", "## Validation errors", ""]
    lines += ([f"- `{qid}`: {'; '.join(_cell(e) for e in errs)}" for qid, errs in errors.items()]
              or ["None."])

    findings = (report.get("leaks") or {}).get("findings") or {}
    lines += ["", "## Leak findings (forecaster-visible text)", ""]
    if findings:
        lines += ["| id | code | field | text |", "|---|---|---|---|"]
        lines += [f"| {qid} | {f['code']} | {f['field']} | {_cell(f['text'])} |"
                  for qid, rows in findings.items() for f in rows]
    else:
        lines.append("None.")

    rec = report.get("recompute") or {}
    counts = rec.get("label_counts") or {}
    lines += ["", "## Recompute (evidence-backed rows)", "",
              f"- evidence-backed rows: {rec.get('n_evidence_backed', 0)}"
              + (f" ({', '.join(f'{k} {v}' for k, v in counts.items())})" if counts else "")]
    lines += [f"- mismatch `{qid}`: {_cell(msg)}" for qid, msg in (rec.get("mismatches") or {}).items()]

    scoring = report.get("scoring_status") or {}
    lines += ["", "## Scoring status", "", "| status | rows |", "|---|---|"]
    lines += [f"| {_cell(status)} | {n} |" for status, n in (scoring.get("counts") or {}).items()]
    ambiguous = scoring.get("ambiguous") or {}
    if ambiguous:
        lines += ["", "Ambiguous rows (never scored):", "",
                  "| id | evidence-backed | recomputed label | reason |", "|---|---|---|---|"]
        lines += [f"| {_cell(qid)} | {'yes' if row.get('evidence_backed') else 'no'} | "
                  f"{row.get('recomputed_label') or '-'} | {_cell(row.get('reason') or '(none)')} |"
                  for qid, row in ambiguous.items()]

    bal = report.get("balance") or {}
    lines += ["", "## Balance (advisory only)", "", "| metric | value |", "|---|---|",
              f"| questions | {bal.get('n')} |",
              f"| YES rate | {bal.get('yes_rate')} |",
              f"| event clusters | {bal.get('n_event_clusters')} |",
              "| category shares | " + ", ".join(f"{k} {v}" for k, v in (bal.get("category_shares") or {}).items())
              + " |",
              "| lead buckets | " + ", ".join(f"{k} {v}" for k, v in (bal.get("lead_buckets") or {}).items())
              + " |"]
    multi = bal.get("clusters_with_multiple_questions") or {}
    if multi:
        lines += ["", "Clusters with several questions:", ""]
        lines += [f"- {key}: {', '.join(ids)}" for key, ids in multi.items()]
    advisories = bal.get("advisory_violations") or []
    if advisories:
        lines += ["", "Advisories:", ""]
        lines += [f"- {a['code']}: {_cell(a['detail'])}" for a in advisories]
    lines.append("")
    return "\n".join(lines)


def cmd_audit(args) -> int:
    md_path: Optional[str] = args.markdown
    if md_path == _MARKDOWN_BESIDE_JSON:
        md_path = os.path.splitext(args.out)[0] + ".md" if args.out else DEFAULT_MARKDOWN
    if args.out and md_path and os.path.realpath(args.out) == os.path.realpath(md_path):
        # the markdown would silently replace the JSON report (e.g. -o audit.md --markdown)
        print(f"error: the JSON report (-o) and the markdown summary would both be written to {args.out}; "
              "give -o a .json name or pass --markdown PATH", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        with open(args.golden, encoding="utf-8") as f:
            payload = json.load(f)
        report = audit_golden(payload, strict=args.strict, golden_path=args.golden)
    except (OSError, ValueError) as exc:
        print(f"error: cannot audit {args.golden}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    if args.out:
        write_json_atomic(args.out, report)
        print(f"wrote {args.out}")
    if md_path:
        write_text_atomic(md_path, render_audit_markdown(report))
        print(f"wrote {md_path}")
    if not args.out and not md_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"golden audit: {report['n_questions']} questions, {report['n_violations']} with violations, "
          f"{report['leaks']['n_rows_with_findings']} with leak findings "
          f"({'strict' if args.strict else 'report-only'})", file=sys.stderr)
    return EXIT_STRICT_VIOLATIONS if args.strict and report["violation_ids"] else EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="golden-set curation tools (deterministic, offline)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="validate, leak-lint, recompute and balance-audit a golden file")
    a.add_argument("--golden", default=GOLDEN_PATH, help="golden question set JSON")
    a.add_argument("--strict", action="store_true",
                   help="also require verified evidence; exit 2 on any violation")
    a.add_argument("-o", "--out", default=None, help="write golden_audit.json (default: stdout)")
    a.add_argument("--markdown", nargs="?", const=_MARKDOWN_BESIDE_JSON, default=None, metavar="PATH",
                   help="also write a markdown summary (default path: next to -o, else golden_audit.md)")
    a.set_defaults(func=cmd_audit)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
