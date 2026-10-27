#!/usr/bin/env python3
"""Explicit, bounded live smoke using the existing official BigModel configuration.

This is never a pytest test. --execute is required. Credentials are read once from
the specified existing environment file, kept in memory, and never logged. Only
two fictional source snapshots are sent. The ordinary offline guard is extended
to the configured HTTPS provider's DNS results; all other network paths and saved
application-data writes remain denied. No retries are initiated by this script.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[3]
GUARD_PATH = REPO / "backend/scripts/main_offline_pytest.py"
spec = importlib.util.spec_from_file_location("pdf_live_base_guard", GUARD_PATH)
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


class LiveGuard(base.Guard):
    def __init__(self, root, hostname):
        super().__init__(root)
        self.hostname = hostname
        self.addresses = set()

    def audit(self, event, args):
        if event == "socket.__new__" and args[1] in {2, 10} and args[2] & 0xF == 1:
            self.record("allowed:provider_stream_socket")
            return
        if event == "socket.getaddrinfo":
            hostname = args[0].decode() if isinstance(args[0], bytes) else args[0]
            if hostname == self.hostname and args[1] == 443:
                self.record("allowed:provider_dns", hostname=self.hostname)
                return
        if event == "socket.connect" and isinstance(args[1], tuple):
            address = args[1]
            if address[0] in self.addresses and address[1] == 443:
                self.record("allowed:provider_connection", hostname=self.hostname)
                return
        return super().audit(event, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--settings-env", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--max-calls", type=int, choices=range(4, 9), default=8)
    args = parser.parse_args()
    if not args.execute or not sys.flags.isolated or not sys.flags.no_site:
        parser.error("Explicit --execute and the project interpreter with -I -S -B are required")
    root = args.evidence_dir.absolute()
    if root.exists() or root.is_symlink() or root.parent.resolve() != root.parent:
        parser.error("Evidence directory must be new under a canonical existing parent")
    # Bootstrap the installed parser only; do not run .pth files or import the app.
    site = Path(sys.executable).absolute().parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    sys.path.append(str(site))
    from dotenv import dotenv_values
    values = dotenv_values(args.settings_env)
    provider = str(values.get("LLM_PROVIDER") or "")
    model = str(values.get("LLM_MODEL_NAME") or "")
    endpoint = str(values.get("LLM_BASE_URL") or "")
    key = values.get("LLM_API_KEY") or values.get("ZHIPUAI_API_KEY")
    parsed = urlsplit(endpoint)
    if (provider != "glm" or model.lower() != "glm-5.3" or not key or parsed.scheme != "https"
            or parsed.hostname != "open.bigmodel.cn" or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.port not in (None, 443)):
        parser.error("The selected configuration does not match the authorized existing official GLM route")
    values.clear()
    guard = LiveGuard(root, parsed.hostname)
    if guard.protected_reason(root):
        parser.error("Evidence directory overlaps protected data")
    root.mkdir(mode=0o700)
    sys.modules["main_offline_guard"] = guard
    sys.addaudithook(guard.audit)
    guard.configure()
    atexit.register(guard.finish, parent=True, shutdown_complete=False)
    os.environ.update({"LLM_PROVIDER":provider, "LLM_MODEL_NAME":model, "LLM_BASE_URL":endpoint,
                       "LLM_API_KEY":key, "LLM_DISABLE_THINKING":"true"})
    del key
    original_gai = socket.getaddrinfo

    def approved_resolution(host, port, *positional, **kwargs):
        results = original_gai(host, port, *positional, **kwargs)
        host_text = host.decode() if isinstance(host, bytes) else host
        if host_text == guard.hostname and port == 443:
            guard.addresses.update(row[4][0] for row in results)
        return results
    socket.getaddrinfo = approved_resolution

    from app.config import Config
    from app.services.research_pdf import agent, model as model_module
    from app.services.research_pdf.contracts import PdfExportError
    Config.RESEARCH_PDF_MAX_CALLS = args.max_calls
    Config.RESEARCH_PDF_TIMEOUT_SECONDS = 240
    Config.RESEARCH_PDF_CALL_TIMEOUT_SECONDS = 90
    Config.RESEARCH_PDF_MAX_PAGES = 4
    Config.RESEARCH_PDF_MAX_CONCURRENT = 1
    for folder in (REPO / "backend/app/services/research_pdf", REPO / "backend/app/skills/equity-research-pdf"):
        for path in folder.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    guard.source_hashes[str(Path(__file__))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary = {"schema":"research-pdf-live-smoke/v1", "provider":provider, "planner":model,
               "routes":model_module.policy_identity(), "maximum_jobs":2, "max_calls_per_job":args.max_calls,
               "credential_values_recorded":False, "cases":[],
               "limits":["Fictional short sources; not live research quality or long-report latency proof",
                         "Explicit HTTPS provider access; this is not an offline run"]}
    success = False
    try:
        cases = [
            ("dossier", "en", "# Live export smoke\n\nThis is a fictional research document for export validation.\n\n## Assumptions\n\nRevenue is 12.5 and the downside is -3.0. These figures are illustrative.\n\n| Case | Weight |\n|---|---:|\n| Base | 60% |\n| Downside | 40% |\n\nSource: fictional validation data.\n"),
            ("forecast", "zh-CN", "# 实时导出验证\n\n这是用于导出验证的虚构预测报告。\n\n## 假设\n\n收入为12.5，下行情景为-3.0。所有数字仅供示例。\n\n| 情景 | 权重 |\n|---|---:|\n| 基准 | 60% |\n| 下行 | 40% |\n\n来源：虚构验证数据。\n"),
        ]
        for kind, language, markdown in cases:
            case_dir = root / f"{kind}-{language}"
            snapshot_dir = case_dir / "snapshot"
            snapshot_dir.mkdir(parents=True)
            source = snapshot_dir / "source.md"
            source.write_text(markdown)
            sha = hashlib.sha256(markdown.encode()).hexdigest()
            snapshot = {"schema":"research-pdf-source/v1", "kind":kind, "resource_id":f"live_{kind}",
                        "requested_lang":None, "language":language, "source_digest":sha,
                        "markdown_sha256":sha, "markdown":markdown, "folder":str(snapshot_dir),
                        "markdown_path":str(source), "title":markdown.splitlines()[0][2:],
                        "publisher":"DeepResearchForecast", "report_type":"Export smoke" if language=="en" else "导出验证",
                        "date":"2026-10-27", "citations":{}, "assets":[], "chart_manifest":[],
                        "admission":{"rule":"explicit fictional smoke fixture"}}
            started = time.monotonic()
            phases = []
            def progress(phase, detail=None, *, phases=phases, kind=kind, language=language):
                phases.append(phase)
                print(json.dumps({"case":kind,"language":language,"phase":phase}), flush=True)
            result = agent.run_export(snapshot, case_dir / "work", progress=progress, is_cancelled=lambda:False)
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise RuntimeError("Fixture source changed")
            row = {"kind":kind,"language":language,"status":"passed", "pages":len(result["pages"]),
                   "calls_used":result["calls_used"],"elapsed_seconds":round(time.monotonic()-started,2),
                   "pdf_path":result["pdf_path"],"pdf_sha256":result["pdf_sha256"],
                   "review_path":result["review_path"],"review_sha256":result["review_sha256"],
                   "source_unchanged":True,"phases":phases}
            summary["cases"].append(row)
            print(json.dumps(row), flush=True)
        success = True
    except PdfExportError as exc:
        summary["error"] = exc.public()
        print(json.dumps({"status":"stopped","error":exc.public()}), flush=True)
    except Exception as exc:
        summary["error"] = {"type":type(exc).__name__,"message":"Live smoke stopped; no automatic retry was attempted."}
        print(json.dumps({"status":"stopped","error_type":type(exc).__name__}), flush=True)
    finally:
        with model_module._DISPATCH_LOCK:
            outstanding = len(model_module._DISPATCHES)
        summary.update(success=success, outstanding_requests=outstanding, retries_attempted=0)
        (root / "live-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
        guard.exit_code = 0 if success and outstanding == 0 else 1
        atexit.unregister(guard.finish)
        guard.finish(parent=True, shutdown_complete=outstanding == 0)
    return guard.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
