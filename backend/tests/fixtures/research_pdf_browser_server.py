#!/usr/bin/env python3
"""Real PDF jobs/agents/renderers behind one guarded loopback test listener.

Only model decisions are scripted. No live provider, source report, credential,
shared service, or canonical pipeline is touched. The base offline boundary stays
active; this fixture admits only its exact listener and accepted stream sockets.
"""
from __future__ import annotations

import argparse
import atexit
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
GUARD_PATH = REPO / "backend/scripts/main_offline_pytest.py"
spec = importlib.util.spec_from_file_location("pdf_browser_base_guard", GUARD_PATH)
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


class BrowserGuard(base.Guard):
    def __init__(self, root, port):
        super().__init__(root)
        self.endpoint = ("127.0.0.1", port)
        self.listener_bound = False

    def audit(self, event, args):
        if event == "socket.__new__" and args[1] == 2 and args[2] & 0xF == 1:
            self.record("allowed:fixture_stream_socket")
            return
        if event == "socket.bind" and args[1] == self.endpoint and not self.listener_bound:
            self.listener_bound = True
            self.record("allowed:fixture_listener", host=self.endpoint[0], port=self.endpoint[1])
            return
        return super().audit(event, args)


def negative_controls(guard):
    import socket
    checks = {}
    def denied(name, action):
        try:
            action()
        except base.GuardViolation:
            checks[name] = "blocked"
        else:
            raise AssertionError("Isolation negative control escaped: " + name)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied("outbound_connection", lambda: sock.connect(("203.0.113.1", 443)))
    denied("outbound_dns", lambda: socket.getaddrinfo("fixture.invalid", 443))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied("wildcard_bind", lambda: sock.bind(("0.0.0.0", guard.endpoint[1])))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied("other_listener", lambda: sock.bind(("127.0.0.1", guard.endpoint[1] + 1)))
    denied("saved_data_write", lambda: (REPO / "backend/uploads/pdf_browser_forbidden.json").write_text("forbidden"))
    denied("external_write", lambda: (guard.root.parent / "pdf_browser_forbidden.txt").write_text("forbidden"))
    denied("credential_read", lambda: (REPO / ".env").read_bytes())
    (guard.root / "negative-controls.json").write_text(json.dumps(checks, indent=2) + "\n")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=18783)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site:
        parser.error("Use the project interpreter with -I -S -B")
    root = args.evidence_dir.absolute()
    if root.exists() or root.is_symlink() or root.parent.resolve() != root.parent:
        parser.error("Use a new directory under a canonical existing parent")
    if args.port != 18783:
        parser.error("This fixture admits only 127.0.0.1:18783")
    guard = BrowserGuard(root, args.port)
    if guard.protected_reason(root):
        parser.error("Evidence directory overlaps protected data")
    root.mkdir(mode=0o700)
    sys.modules["main_offline_guard"] = guard
    sys.addaudithook(guard.audit)
    guard.configure()
    atexit.register(guard.finish, parent=True, shutdown_complete=False)
    controls = negative_controls(guard)
    if args.self_test:
        guard.exit_code = 0
        atexit.unregister(guard.finish)
        guard.finish(parent=True, shutdown_complete=True)
        print(json.dumps({"negative_controls": controls, "root": str(root)}), flush=True)
        return

    import hashlib
    import re
    import threading
    import time
    from socketserver import TCPServer, ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer
    from flask import jsonify, request

    sys.path.insert(0, str(REPO / "backend/tests"))
    from test_research_pdf_agent import Driver
    from app import create_app
    from app.config import Config
    from app.services.pipeline_orchestrator import PipelineManager
    from app.services.report_agent import ReportManager
    from app.services.research_pdf import agent, sources
    from app.services.research_pdf.jobs import PdfExportJobs
    from app.api import research_pdf as pdf_routes
    from app.utils.atomic import write_json_atomic

    for name, value in {"TESTING": True, "DEBUG": False, "APP_CORS_ORIGINS": "*",
                        "LLM_PROVIDER": "openai", "LLM_MODEL_NAME": "fixture-vision",
                        "LLM_BASE_URL": "https://fixture.invalid/v1", "LLM_API_KEY": "fixture-only-not-a-real-key",
                        "RESEARCH_PDF_REVIEW_PROVIDER": "", "RESEARCH_PDF_REVIEW_MODEL": "",
                        "RESEARCH_PDF_REVIEW_BASE_URL": "", "RESEARCH_PDF_REVIEW_API_KEY": "",
                        "RESEARCH_PDF_EXPORT_ENABLED": True, "REPORT_PDF_EXPORT": True,
                        "RESEARCH_PDF_MAX_CALLS": 48, "RESEARCH_PDF_TIMEOUT_SECONDS": 60}.items():
        setattr(Config, name, value)

    bodies = {}
    for kind, prefix in (("dossier", "pipe_pdf"), ("forecast", "report_pdf")):
        for language in ("en", "zh"):
            ident = f"{prefix}_{language}"
            if language == "en":
                markdown = (f"# {'Deep research' if kind == 'dossier' else 'Forecast'} export fixture\n\n"
                    "This complete report is a fictional browser acceptance fixture. Demand and policy remain uncertain.\n\n"
                    "## Evidence and assumptions\n\nThe base estimate is 12.5%; the downside remains -3.0%. No result is guaranteed.\n\n"
                    "| Scenario | Probability |\n|---|---:|\n| Base | 60% |\n| Downside | 40% |\n\n"
                    "Source: fictional fixture data.\n\n## Limitations\n\nThe figures are illustrative and are not investment advice.\n")
            else:
                markdown = (f"# {'深度研究' if kind == 'dossier' else '预测报告'}导出测试\n\n"
                    "这是用于浏览器验收的完整虚构报告。需求与政策仍有不确定性。\n\n"
                    "## 证据与假设\n\n基准估计为12.5%；下行情景仍为-3.0%。结果没有保证。\n\n"
                    "| 情景 | 概率 |\n|---|---:|\n| 基准 | 60% |\n| 下行 | 40% |\n\n"
                    "来源：虚构测试数据。\n\n## 局限\n\n这些数字仅供示例，不构成投资建议。\n")
            bodies[ident] = markdown
            if kind == "dossier":
                folder = Path(PipelineManager.handoff_dir(ident))
                folder.mkdir(parents=True)
                (folder / "research_report.md").write_text(markdown)
                write_json_atomic(str(folder / "sources.json"), [])
                write_json_atomic(str(folder.parent / "pipeline_state.json"),
                                  {"pipeline_id": ident, "created_at": "2026-10-26T00:00:00Z"})
            else:
                folder = Path(ReportManager._get_report_folder(ident))
                folder.mkdir(parents=True)
                (folder / "full_report.md").write_text(markdown)
                write_json_atomic(str(folder / "meta.json"), {"report_id":ident, "status":"completed", "created_at":"2026-10-26T00:00:00Z"})
                write_json_atomic(str(folder / "final_audit.json"), {"hard_passed":True,
                    "policy_version":Config.REPORT_FINAL_AUDIT_POLICY_VERSION, "markdown_sha256":sources.sha(markdown.encode())})

    state_lock = threading.Lock()
    events = []
    drivers = []

    def policy():
        result = agent.policy_fingerprint()
        result["model_policy"] = {role: {"provider":"controlled", "model":role, "api":"chat_completions", "fallback":False}
                                  for role in ("planner", "reviewer")}
        return result

    def run(snapshot, work_dir, *, progress, is_cancelled):
        driver = Driver()
        driver.expected_markers = ("Equity Research PDF", "Selected-language application integration")
        def observe(call):
            time.sleep(.08)
            row = {"resource_id":snapshot["resource_id"], "role":call["role"],
                   "source_digest":snapshot["source_digest"], "system_sha256":sources.sha(call["system"].encode()),
                   "images":[image["sha256"] for image in call["images"]],
                   "source_part":call["payload"].get("source_part"), "page":call["payload"].get("page"),
                   "task":call["payload"].get("task"), "transport":"scripted; no provider"}
            with state_lock:
                events.append(row)
                with (root / "controlled-model-events.jsonl").open("a") as output:
                    output.write(json.dumps(row) + "\n")
        driver.hook = observe
        with state_lock:
            drivers.append(driver)
        return agent.run_export(snapshot, work_dir, progress=progress, is_cancelled=is_cancelled, model_factory=driver.factory)

    service = PdfExportJobs(root / "exports", runner=run, policy=policy)
    pdf_routes.get_jobs = lambda: service
    app = create_app()
    requests_seen = []

    @app.before_request
    def fixture_display():
        if request.path.startswith("/api/"):
            requests_seen.append({"method":request.method,"path":request.path})
        if request.method != "GET":
            return None
        match = re.fullmatch(r"/api/research/(pipe_pdf_(?:en|zh))/dossier", request.path)
        if match:
            return jsonify(success=True, data={"report":bodies[match[1]],"has_report":True,"sealed":True,
                                              "actors":None,"sources":[],"timeline":None,"charts":[]})
        match = re.fullmatch(r"/api/report/(report_pdf_(?:en|zh))(?:/(viz-manifest|forecast|official-data))?", request.path)
        if not match:
            return None
        ident, part = match.groups()
        if part == "viz-manifest":
            return jsonify(success=True, data=[], count=0)
        if part in {"forecast","official-data"}:
            return jsonify(success=True, data={"report_id":ident,"forecast":None,"available":False,"indicators":[]})
        return jsonify(success=True, data={"report_id":ident,"status":"completed","markdown_content":bodies[ident],
                                          "translation_status":{"source_lang":"zh" if ident.endswith("zh") else "en"}})

    @app.get("/__fixture/receipt")
    def receipt_route():
        jobs = [json.loads(path.read_text()) for path in service.root.glob("pdf_*/job.json")]
        return jsonify({"jobs":[service._public(job) for job in jobs], "controlled_model_calls":len(events),
                        "requests":requests_seen,"negative_controls":controls,"guard":guard.receipt("serving")})

    @app.post("/__fixture/stop")
    def stop():
        threading.Thread(target=server.shutdown, daemon=True).start()
        return jsonify(stopping=True)

    for directory in (REPO / "backend/app/services/research_pdf", REPO / "backend/app/skills/equity-research-pdf"):
        for path in directory.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (Path(__file__), GUARD_PATH, REPO / "backend/app/api/research_pdf.py", REPO / "backend/tests/test_research_pdf_agent.py"):
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name, self.server_port = guard.endpoint
            self.setup_environ()

    class Handler(WSGIRequestHandler):
        def log_message(self, fmt, *values):
            print("HTTP " + (fmt % values), flush=True)

    server = Server(guard.endpoint, Handler)
    server.set_app(app)
    print(json.dumps({"ready":True,"url":f"http://127.0.0.1:{args.port}","root":str(root),"resources":list(bodies)}), flush=True)
    clean = False
    try:
        server.serve_forever(poll_interval=.1)
        clean = True
    finally:
        server.server_close()
        with service._thread_guard:
            pending = list(service._threads)
        quiet = all(service.wait(job, 15) for job in pending)
        final = {"schema":"research-pdf-browser-server/v1", "controlled_model_calls":len(events),
                 "requests":requests_seen, "negative_controls":controls, "clean_shutdown":clean and quiet,
                 "limitations":["Scripted model decisions, real source/API/job/agent/PDF renderer", "No live model quality claim"]}
        (root / "server-receipt.json").write_text(json.dumps(final,indent=2)+"\n")
        guard.exit_code = 0 if clean and quiet else 1
        atexit.unregister(guard.finish)
        guard.finish(parent=True, shutdown_complete=clean and quiet)


if __name__ == "__main__":
    main()
