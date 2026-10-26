"""Opt-in real PDF acceptance; existing main guard + fixture-only native sandbox.

Use the installed environment, no site startup, and a NEW canonical output root:
backend/.venv/bin/python -I -S -B backend/tests/render_translation_pdf_fixture.py \
    --execute-native --output /private/tmp/drf-native-pdf-unique

No production function is extracted, replaced, or mocked. Only the main runner's
storage redirects run before app imports. Native children additionally inherit a
macOS sandbox denying network and writes outside this disposable evidence root.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shlex
import socket
import subprocess
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "backend/scripts/main_offline_pytest.py"
spec = importlib.util.spec_from_file_location("native_pdf_main_guard", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
TOOLS = {
    "pandoc": "/opt/homebrew/bin/pandoc",
    "xelatex": "/Library/TeX/texbin/xelatex",
    "fc-match": "/opt/homebrew/bin/fc-match",
    "pdftoppm": "/opt/homebrew/bin/pdftoppm",
    "pdftotext": "/opt/homebrew/bin/pdftotext",
    "pdfinfo": "/opt/homebrew/bin/pdfinfo",
    "pdfimages": "/opt/homebrew/bin/pdfimages",
    "sandbox": "/usr/bin/sandbox-exec",
}
FAMILIES = ("DejaVu Sans", "Noto Sans", "Arial Unicode MS", "Noto Sans CJK SC",
            "Source Han Sans SC", "PingFang SC", "DejaVu Sans Mono",
            "Noto Sans Mono CJK SC", "Menlo")
FROZEN = {
    "backend/app/services/report_agent.py": "13fd157ed2c7661a2099dad3b927f4173a6f8fcb9abeb242ec21b14e25588583",
    "backend/app/services/translation/artifacts.py": "b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class NativeFixtureGuard(runner.Guard):
    """Do not change production Guard; admit only generated fixture commands."""

    def __init__(self, root):
        super().__init__(root)
        self.exact = set()
        self.documents = {}
        self.native_calls = []
        self.profile = root / "native.sb"
        self.profile_sha = None
        self.tool_hashes = {}
        self.native_groups = set()
        self.group_ticket = None
        self.baseline_denials = None
        self.export_error = None
        self.export_results = {}
        for executable in TOOLS.values():
            self.read_files.add(Path(executable).resolve())
        self.read_roots.append(Path("/opt/homebrew/share/fonts").resolve())

    def prepare_native(self):
        # No HOME substitution. TeX/font caches and temporary files get explicit roots.
        os.environ["PATH"] = "/opt/homebrew/bin:/Library/TeX/texbin:" + os.defpath
        for key, relative in {"TEXMFVAR": "cache/texmf-var", "TEXMFCONFIG": "config/texmf",
                              "TEXMFCACHE": "cache/texmf"}.items():
            target = self.root / relative
            target.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(target)
        os.environ.update({"openin_any": "p", "openout_any": "p", "shell_escape": "f"})
        system_roots = ["/System", "/Library", "/usr", "/bin", "/sbin", "/opt/homebrew",
                        "/private/etc", "/private/var/db/timezone", "/private/var/db/dyld"]
        # Native tools never read repository sources or saved reports. OS metadata
        # reads allow loader/font discovery; actual file reads use explicit roots.
        profile = ['(version 1)', '(allow default)', '(deny network*)',
                   '(deny file-read*)', '(deny file-write*)',
                   '(allow file-read-metadata)', '(allow file-read* (literal "/"))',
                   '(allow file-read* (subpath "/dev"))',
                   '(allow file-write* (literal "/dev/null"))']
        profile += [f'(allow file-read* (subpath {json.dumps(p)}))'
                    for p in [*system_roots, str(self.root)]]
        profile += [f'(allow file-write* (subpath {json.dumps(str(self.root))}))']
        profile += [
            '(deny file-read* (subpath "/Library/Keychains") (subpath "/private/etc/ssh"))',
            '(deny file-read* (regex #"/([.]ssh|[.]aws|[.]gnupg|credentials|keychains|Keychains)(/|$)"))',
            '(deny file-read* (regex #"/([.]env[^/]*|auth[.]json|credentials[.]json|[.]netrc|[.]git-credentials|id_rsa|id_ed25519)$"))',
            f'(deny file-read* (subpath {json.dumps(str(self.root / "native-private-control"))}))',
        ]
        self.profile.write_text("\n".join(profile) + "\n")
        self.profile_sha = digest(self.profile)
        self.tool_hashes = {name: {"path": path, "realpath": str(Path(path).resolve()),
                                   "sha256": digest(path)} for name, path in TOOLS.items()}
        save(self.root / "native-tools.json", self.tool_hashes)
        self.native_env = dict(os.environ)

    def audit(self, event, args):
        if event == "os.killpg" and self.group_ticket == args and args[0] in self.native_groups:
            self.group_ticket = None
            return
        return super().audit(event, args)

    def signal_group(self, pid, sig):
        self.group_ticket = (pid, sig)
        try:
            os.killpg(pid, sig)
            return True
        except ProcessLookupError:
            return False
        finally:
            self.group_ticket = None

    def finish_group(self, pid, *, exceptional=False):
        if pid not in self.native_groups:
            return
        if self.signal_group(pid, 0):
            if not exceptional:
                self.record("unexpected:native_descendant_survived", child_pid=pid)
            self.signal_group(pid, signal.SIGKILL)
            child = self.children.get(pid)
            if child is not None:
                child.wait(timeout=3)
            deadline = time.monotonic() + 3
            while self.signal_group(pid, 0):
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"native process group did not disappear: {pid}")
                time.sleep(0.02)
        self.native_groups.discard(pid)

    def close_children(self):
        for pid in tuple(self.native_groups):
            self.finish_group(pid, exceptional=True)
        super().close_children()

    def finish(self, *, parent=False, shutdown_complete=False):
        try:
            self._finish(parent=parent, shutdown_complete=shutdown_complete)
        except BaseException:
            # atexit normally swallows exceptions and preserves exit 0. Evidence
            # I/O failure must fail closed even when no receipt can be written.
            try:
                traceback.print_exc(file=sys.stderr)
            except BaseException:
                pass
            os._exit(1)

    def _finish(self, *, parent=False, shutdown_complete=False):
        """Registered first, runs last after app shutdown; authoritative verdict."""
        errors = []
        try:
            self.close_children()
            if self.baseline_denials is not None:
                self.verify_denials(self.baseline_denials)
            assert not self.native_groups, self.native_groups
            proof = self.receipt("completed", self.exit_code, shutdown_complete=shutdown_complete)
            assert not proof["source_drift"], proof["source_drift"]
            assert proof["identity_preserved"]
        except Exception:
            errors.append(traceback.format_exc())
            self.exit_code = 1
        proof = self.receipt("completed", self.exit_code, shutdown_complete=shutdown_complete and not self.native_groups)
        save(self.root / "completed.json", proof)
        save(self.root / "native-pdf-receipt.json", {
            "status": "passed" if self.exit_code == 0 else "failed",
            "export_status": "failed" if self.export_error else ("passed" if self.export_results else "incomplete"),
            "safety_status": "failed" if errors else ("passed" if self.baseline_denials is not None else "incomplete"),
            "export_error": self.export_error, "safety_errors": errors,
            "results": self.export_results, "guard": proof,
            "native_sandbox": str(self.profile), "native_sandbox_sha256": self.profile_sha,
            "visual_inspection": "pending separate model inspection of hashed page PNGs",
        })
        if errors:
            # The final hook must not leave an earlier provisional exit 0 in
            # place after discovering late shutdown violations.
            os._exit(1)

    def receipt(self, *args, **kwargs):
        payload = super().receipt(*args, **kwargs)
        payload["boundary"] = "Existing CPython main guard; direct native admission plus inherited macOS sandbox"
        payload["children"] = {
            str(pid): {"exit_code": child.poll(), "receipt": "native-commands.json",
                       "command_index": child.record_id, "process_group_closed": pid not in self.native_groups}
            for pid, child in self.child_snapshot().items()}
        save(self.root / f"process-{os.getpid()}.json", payload)
        return payload

    def verify_denials(self, baseline):
        # Keep these exact expected optional-library probes explicit. Any new
        # caught app network/saved-write denial must fail acceptance.
        for name, count in self.counts.items():
            if name.startswith("blocked:"):
                delta = count - baseline.get(name, 0)
                if name not in {"blocked:font_discovery_process", "blocked:external_read"}:
                    assert delta == 0, (name, delta)
        events = [json.loads(line) for line in (self.root / f"events-{os.getpid()}.jsonl").read_text().splitlines()]
        unexpected_reads = [event for event in events if event["event"] == "blocked:external_read"
                            and event.get("category") != "font_discovery"]
        assert not unexpected_reads, unexpected_reads
        assert self.counts.get("unexpected:native_descendant_survived", 0) == 0

    def register(self, command, cwd):
        """Only harness code registers exact arguments, never external CLI inputs."""
        self.path(cwd, write=True)
        self.exact.add((tuple(map(str, command)), str(Path(cwd).resolve())))

    def admit(self, command, cwd):
        if (tuple(command), str(cwd)) in self.exact:
            return
        if (command[:3] == [TOOLS["fc-match"], "-f", "%{family[0]}|%{file}"]
                and len(command) == 4 and command[3] in FAMILIES and cwd == self.root):
            return
        # Production generates unpredictable mkstemp basenames. Admit only the
        # exact ordered renderer command and exact preprocessed fixture bytes.
        fixture = self.documents.get(str(cwd))
        if fixture and len(command) > 3 and command[0] == TOOLS["pandoc"]:
            source, output = Path(command[1]), Path(command[-1])
            if (source.parent == cwd and output.parent == cwd
                    and re.fullmatch(r"\.pdf-source-[A-Za-z0-9_-]+\.md", source.name)
                    and re.fullmatch(r"\.pdf-building-[A-Za-z0-9_-]+\.pdf", output.name)
                    and not source.is_symlink() and not output.is_symlink()):
                self.path(source)
                self.path(output, write=True)
                if (command == [TOOLS["pandoc"], str(source), *fixture["arguments"], "-o", str(output)]
                        and source.read_text() == fixture["markdown"]):
                    # Production cleans temporary inputs even on failure. Preserve
                    # the actual submitted bytes for repeatability and diagnostics.
                    (self.root / f"submitted-{fixture['language']}.md").write_bytes(source.read_bytes())
                    return
        self.deny("native_command_scope")

    def install_children(self):
        original = subprocess.Popen
        guard = self

        class FixturePopen(original):
            def __init__(self, args, *positional, **kwargs):
                if (positional or not isinstance(args, (list, tuple)) or not args
                        or any(kwargs.get(key) for key in (
                            "shell", "preexec_fn", "executable", "pass_fds", "start_new_session"))
                        or kwargs.get("env") is not None):
                    guard.deny("native_command_scope")
                command = [os.fsdecode(arg) for arg in args]
                if command in (["fc-list", "--help"], ["system_profiler", "-xml", "SPFontsDataType"]):
                    guard.deny("font_discovery_process", program=Path(command[0]).name)
                cwd = guard.path(kwargs.get("cwd") or os.getcwd(), write=True)
                guard.admit(command, cwd)
                if digest(guard.profile) != guard.profile_sha:
                    guard.deny("changed_native_profile")
                for name in ("sandbox", "xelatex"):
                    if digest(TOOLS[name]) != guard.tool_hashes[name]["sha256"]:
                        guard.deny("changed_native_executable")
                tool = next((entry for entry in guard.tool_hashes.values()
                             if entry["path"] == command[0]), None)
                if tool is None or digest(command[0]) != tool["sha256"]:
                    guard.deny("changed_native_executable")
                with guard.child_lock:
                    if guard.spawn_count >= 160 or any(p.poll() is None for p in guard.children.values()):
                        guard.deny("native_process_limit")
                    wrapped = [TOOLS["sandbox"], "-f", str(guard.profile), *command]
                    self.record_id = len(guard.native_calls)
                    self.call_record = {"command": command, "wrapped_command": wrapped,
                                        "shell_command": shlex.join(wrapped), "cwd": str(cwd)}
                    guard.native_calls.append(self.call_record)
                    guard.spawn_ticket.argv = wrapped
                    try:
                        super().__init__(wrapped, **{**kwargs, "cwd": str(cwd),
                                                    "env": guard.native_env, "close_fds": True,
                                                    "start_new_session": True})
                    finally:
                        guard.spawn_ticket.argv = None
                    guard.children[self.pid] = self
                    guard.native_groups.add(self.pid)
                    guard.spawn_count += 1
                    guard.record("allowed:native_fixture", program=Path(command[0]).name, child_pid=self.pid)

            def communicate(self, *args, **kwargs):
                try:
                    stdout, stderr = super().communicate(*args, **kwargs)
                except BaseException as exc:
                    self.call_record["exception"] = type(exc).__name__
                    for label, data in (("stdout", getattr(exc, "output", None)),
                                        ("stderr", getattr(exc, "stderr", None))):
                        path = guard.root / f"command-{self.record_id:03}-{label}.txt"
                        path.write_bytes(data.encode() if isinstance(data, str) else (data or b""))
                        self.call_record[label] = str(path)
                    try:
                        guard.finish_group(self.pid, exceptional=True)
                    finally:
                        self.call_record["returncode"] = self.poll()
                        save(guard.root / "native-commands.json", guard.native_calls)
                    raise
                guard.finish_group(self.pid)
                for label, data in (("stdout", stdout), ("stderr", stderr)):
                    path = guard.root / f"command-{self.record_id:03}-{label}.txt"
                    path.write_bytes(data.encode() if isinstance(data, str) else (data or b""))
                    self.call_record[label] = str(path)
                self.call_record["returncode"] = self.returncode
                command = self.call_record["command"]
                if (command[0] == TOOLS["pandoc"] and "--toc" in command
                        and self.returncode == 0 and Path(command[-1]).is_file()):
                    raw = guard.root / ("raw-" + Path(self.call_record["cwd"]).name + ".pdf")
                    raw.write_bytes(Path(command[-1]).read_bytes())
                    self.call_record["raw_pdf"] = str(raw)
                    self.call_record["raw_pdf_sha256"] = digest(raw)
                save(guard.root / "native-commands.json", guard.native_calls)
                return stdout, stderr

        subprocess.Popen = FixturePopen


def controls(guard):
    outcomes = {}
    def denied(label, action):
        try:
            action()
        except runner.GuardViolation as exc:
            outcomes[label] = str(exc)
        else:
            raise AssertionError("guard control escaped: " + label)
    denied("network_socket", lambda: socket.socket(socket.AF_INET))
    denied("network_dns", lambda: socket.getaddrinfo("fixture.invalid", 443))
    denied("saved_write", lambda: (REPO / "backend/uploads/reports/.native-guard-control").write_text("blocked"))
    denied("saved_read", lambda: (REPO / "backend/uploads/reports/.native-guard-control").read_bytes())
    denied("external_write", lambda: (guard.root.parent / (guard.root.name + "-escape")).write_text("blocked"))
    denied("credential_read", lambda: (guard.root / ".env").read_bytes())
    denied("identity_change", lambda: os.putenv("HOME", str(guard.root)))
    denied("unregistered_process", lambda: subprocess.run(["/bin/echo", "blocked"]))
    denied("pandoc_extra_flag", lambda: subprocess.run([TOOLS["pandoc"], "--version", "--lua-filter=/tmp/no"]))
    denied("xelatex_unregistered", lambda: subprocess.run([TOOLS["xelatex"], "--shell-escape"]))
    denied("fixture_symlink_escape", lambda: (guard.root / "escape").symlink_to(REPO / "backend/uploads"))
    allowed = guard.root / "allowed-control.txt"
    allowed.write_text("fixture-only")
    assert allowed.read_text() == "fixture-only"
    outcomes["fixture_write_read"] = "passed"
    save(guard.root / "negative-controls.json", outcomes)
    return outcomes


def run_native(guard, command, cwd=None, check=True):
    cwd = cwd or guard.root
    guard.register(command, cwd)
    result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=180)
    if check and result.returncode:
        raise AssertionError(f"native command failed: {shlex.join(command)}\n{result.stderr.decode(errors='replace')}")
    return result


def native_controls(guard):
    # This is a deliberately inadmissible loopback resource; no provider or
    # service is used. Require the OS-denial error, not merely connection refused.
    source = guard.root / "network-control.md"
    source.write_text("![blocked](http://127.0.0.1:9/native-fixture-control.png)\n")
    result = run_native(guard, [TOOLS["pandoc"], str(source), "--standalone", "--embed-resources",
                                "--fail-if-warnings", "-t", "html", "-o",
                                str(guard.root / "network-control.html")], check=False)
    error = result.stderr.decode(errors="replace")
    assert (result.returncode and "http://127.0.0.1:9/native-fixture-control.png" in error
            and "Network.Socket.connect" in error and "Operation not permitted" in error), error
    local = guard.root / "local-control.md"
    local.write_text("NATIVE-LOCAL-CONTROL\n")
    positive = guard.root / "local-control.txt"
    run_native(guard, [TOOLS["pandoc"], str(local), "-t", "plain", "-o", str(positive)])
    assert positive.read_text().strip() == "NATIVE-LOCAL-CONTROL"
    native_escape = guard.root.parent / (guard.root.name + "-os-write-escape.txt")
    result = run_native(guard, [TOOLS["pandoc"], str(local), "-t", "plain", "-o", str(native_escape)], check=False)
    error = result.stderr.decode(errors="replace")
    assert result.returncode and str(native_escape) in error and "permission denied" in error.lower(), error
    assert not native_escape.exists()
    private = guard.root / "native-private-control"
    private.mkdir()
    (private / "synthetic.txt").write_text("NATIVE-READ-MUST-NOT-ESCAPE")
    result = run_native(guard, [TOOLS["pandoc"], str(private / "synthetic.txt"), "-f", "markdown", "-t", "plain"], check=False)
    error = result.stderr.decode(errors="replace")
    assert result.returncode and str(private / "synthetic.txt") in error and "permission denied" in error.lower(), error
    assert b"NATIVE-READ-MUST-NOT-ESCAPE" not in result.stdout
    credential_control = guard.root / "credentials.json"
    result = run_native(guard, [TOOLS["pandoc"], str(credential_control), "-f", "markdown", "-t", "plain"], check=False)
    error = result.stderr.decode(errors="replace")
    assert result.returncode and str(credential_control) in error and "permission denied" in error.lower(), error
    assert b"SYNTHETIC-CREDENTIAL-CONTROL" not in result.stdout
    # A TeX log must prove an out-of-root write was rejected. TeX's paranoid
    # openout policy and the inherited OS sandbox both constrain this operation.
    escape = guard.root.parent / (guard.root.name + "-native-escape.txt")
    tex = guard.root / "write-control.tex"
    tex.write_text("\\documentclass{article}\n\\begin{document}\n"
                   "\\newwrite\\probe\n\\immediate\\openout\\probe=" + str(escape) +
                   "\n\\immediate\\write\\probe{FORBIDDEN}\n\\end{document}\n")
    result = run_native(guard, [TOOLS["xelatex"], "-no-shell-escape", "-interaction=nonstopmode",
                                "-halt-on-error", "-output-directory=" + str(guard.root), str(tex)], check=False)
    log = (result.stdout + result.stderr).decode(errors="replace")
    assert result.returncode and not escape.exists() and str(escape) in log and "Not writing to" in log, log
    save(guard.root / "native-negative-controls.json", {"network": "OS permission denial confirmed",
         "external_write": "Pandoc OS permission denial confirmed; no sibling artifact",
         "private_read": "Pandoc OS permission denial confirmed; synthetic secret absent",
         "credential_read": "Pandoc denied synthetic credentials.json by filename rule",
         "tex_external_write": "Exact target rejected by openout_any=p",
         "fixture_positive_control": "Pandoc local read/write passed", "sandbox_sha256": guard.profile_sha})


def fixture_markdown(language):
    zh = language == "zh"
    heading = "产能与需求展望" if zh else "Capacity and demand outlook"
    table_heading = "跨页情景表" if zh else "Multipage scenario table"
    header = "编号 | 情景 | 产能 | 说明" if zh else "Row | Scenario | Capacity | Evidence"
    rows = [f"| R{i:03} | {'基准情景' if zh else 'Base case'} | {i + 10} MW | "
            f"{'逐项核对产能数据' if zh else 'Capacity fixture evidence'} |" for i in range(1, 121)]
    md = f"# {heading}\n\n"
    md += ("需求增长20%，不确定性为± 2%；产能为≥ 10且≤ 25 MW [S1]。中文核对标记。"
           if zh else "Demand grows by 20%, uncertainty is ± 2%; capacity is ≥ 10 and ≤ 25 MW [S1]. Chinese marker 中文核对标记.")
    md += "\n\n" + ("本说明包含真实脚注" if zh else "This statement has a real footnote") + "[^audit].\n\n"
    md += f"![{'产能柱状图' if zh else 'Capacity chart'}](charts/capacity.png)\n\n"
    md += f"## {table_heading}\n\n| {header} |\n|---|---|---:|---|\n" + "\n".join(rows)
    md += "\n\n## " + ("结论与核对" if zh else "Conclusion and verification") + "\n\n"
    md += ("最终核对标记：表格包含120行，图像、引用与脚注均须保留。[S1]"
           if zh else "FINAL-CHECK: all 120 table rows, image, citation and footnote must remain. [S1]")
    md += "\n\n## " + ("参考来源" if zh else "References") + "\n\n[S1] Fixture source.\n\n"
    md += "[^audit]: " + ("脚注核对标记：这是隔离测试说明。" if zh else "FOOTNOTE-CHECK: isolated fixture note.") + "\n"
    return md, heading, table_heading


def verify(guard):
    from app.config import Config
    from app.services.report_agent import ReportManager, ReportAgent
    import pymupdf as fitz

    assert Path(Config.UPLOAD_FOLDER).is_relative_to(guard.root)
    assert Path(ReportManager.REPORTS_DIR).is_relative_to(guard.root)
    assert "app.services.report_agent" in sys.modules
    Config.REPORT_PDF_EXPORT = True
    Config.REPORT_PDF_CITATION_FOOTNOTES = True
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if name.startswith("app.") and path and Path(path).suffix == ".py":
            guard.source_hashes.setdefault(str(Path(path).resolve()), digest(path))
    fonts = ReportManager._resolve_pdf_fonts()
    save(guard.root / "font-resolution.json", fonts)
    assert all(isinstance(fonts.get(key), dict) for key in ("main", "cjk", "mono")), fonts
    results = {}
    rejected = []
    for language in ("en", "zh"):
        folder = guard.root / language
        (folder / "charts").mkdir(parents=True)
        chart = fitz.open()
        page = chart.new_page(width=420, height=190)
        page.insert_text((20, 20), "CAPACITY CHART - FIXTURE", fontsize=12)
        for x, height, label, color in ((60, 65, "10 MW", (.1, .3, .7)), (220, 120, "25 MW", (.1, .6, .3))):
            page.draw_rect(fitz.Rect(x, 165 - height, x + 75, 165), fill=color)
            page.insert_text((x, 182), label, fontsize=11)
        page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(str(folder / "charts/capacity.png"))
        chart.close()
        md, heading, table_heading = fixture_markdown(language)
        source = folder / f"{language}.md"
        source.write_text(md)
        citation_title = "引用核对来源" if language == "zh" else "CITATION-CHECK source"
        citations = {"S1": {"title": citation_title, "domain": "example.test", "date": "2026-10-26",
                            "url": "https://example.test/fixture", "url_valid": True}}
        arguments = [f"--pdf-engine={TOOLS['xelatex']}", "-V", f"mainfont={fonts['main']['family']}",
                     "-V", "geometry:margin=2.5cm", "-V", "papersize:a4", "--toc",
                     "-V", f"CJKmainfont={fonts['cjk']['family']}"]
        if ReportAgent._detect_translation_target(md)[0] == "zh":
            arguments += ["-V", "toc-title=目录", "-V", "header-includes=\\renewcommand{\\figurename}{图}\\renewcommand{\\tablename}{表}"]
        arguments += ["-V", f"monofont={fonts['mono']['family']}", "-V", "colorlinks=true"]
        guard.documents[str(folder)] = {"arguments": arguments, "language": language,
            "markdown": ReportManager._rewrite_citations_for_pdf(ReportManager._rewrite_chart_paths_for_pdf(md, str(folder)), citations)}
        request = {"label": "native-fixture-" + language, "source_path": str(source), "citations": citations}
        target = folder / f"{language}.pdf"
        pdf = ReportManager.export_document_pdf(md, str(folder), str(target), **request)
        if not pdf and (guard.root / f"raw-{language}.pdf").exists():
            rejected.append(language)
            pdf = str(guard.root / f"raw-{language}.pdf")
            audit = ReportManager._validate_pdf_content(pdf, md)
            save(guard.root / f"rejected-{language}-content-audit.json", audit)
            manifest = {"renderer": "pandoc-xelatex-rejected", "content_audit": audit[1]}
        else:
            manifest = json.loads(Path(str(target) + ".manifest.json").read_text()) if pdf else {}
        assert pdf, f"production exporter rejected {language}; inspect native-commands.json and logs"
        if language not in rejected:
            assert manifest["renderer"] == "pandoc-xelatex", manifest
            assert ReportManager._validate_pdf_content(pdf, md)[0]
        run_native(guard, [TOOLS["pdftotext"], "-layout", pdf, str(folder / "extracted.txt")])
        run_native(guard, [TOOLS["pdfinfo"], pdf])
        run_native(guard, [TOOLS["pdfimages"], "-list", pdf])
        extracted = (folder / "extracted.txt").read_text()
        normalized = re.sub(r"\s+", "", extracted)
        with fitz.open(pdf) as document:
            page_texts = [page.get_text() for page in document]
            assert len(document) >= 3, len(document)
            assert re.sub(r"\s+", "", heading) in normalized and "中文核对标记" in normalized
            assert all(symbol in extracted for symbol in "≥≤±") and "\ufffd" not in extracted
            assert citation_title.replace(" ", "") in normalized
            assert ("脚注核对标记" if language == "zh" else "FOOTNOTE-CHECK") in normalized
            assert ("最终核对标记" if language == "zh" else "FINAL-CHECK") in normalized
            for i in range(1, 121):
                assert normalized.count(f"R{i:03}") == 1, (language, i)
                row = f"R{i:03}" + ("基准情景" if language == "zh" else "Basecase") + f"{i + 10}MW"
                assert row in normalized, (language, i, row)
            table_pages = [i + 1 for i, text in enumerate(page_texts) if re.search(r"R\d{3}", text)]
            assert len(table_pages) >= 3, table_pages
            for number in table_pages:
                text = re.sub(r"\s+", "", page_texts[number - 1])
                assert ("编号" if language == "zh" else "Scenario") in text, (language, number)
            image_pages = [i + 1 for i, page in enumerate(document) if page.get_images()]
            assert image_pages, language
            assert any(link.get("uri") == "https://example.test/fixture" for page in document for link in page.get_links())
            page_count = len(document)
            assert "xdvipdfmx" in document.metadata.get("producer", "").lower(), document.metadata
        # Render every page: no hidden unchecked continuation pages.
        run_native(guard, [TOOLS["pdftoppm"], "-r", "90", "-png", pdf, str(folder / "page")])
        assert len(list(folder.glob("page-*.png"))) == page_count
        if language not in rejected:
            before = len([item for item in guard.native_calls if item["command"][0] == TOOLS["pandoc"]])
            assert ReportManager.export_document_pdf(md, str(folder), str(target), **request) == pdf
            after = len([item for item in guard.native_calls if item["command"][0] == TOOLS["pandoc"]])
            assert before == after, "cache hit unexpectedly rerendered"
        results[language] = {"pdf": pdf, "sha256": digest(pdf), "pages": page_count,
                             "table_pages": table_pages, "image_pages": image_pages,
                             "rows": 120, "export_accepted": language not in rejected,
                             "cache_reused_without_pandoc": language not in rejected,
                             "content_audit": manifest["content_audit"],
                             "pngs": {str(p): digest(p) for p in sorted(folder.glob("page-*.png"))}}
        save(guard.root / "native-pdf-results.json", results)
        guard.export_results = results
    assert not rejected, "production export rejected languages: " + ", ".join(rejected)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-native", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or sys.flags.optimize:
        parser.error("invoke with -I -S -B and without -O/-OO before this script")
    root = args.output.absolute()
    if (root.parent != Path("/private/tmp") or root.exists() or root.is_symlink()
            or root.resolve() != root):
        parser.error("output must be a new direct child of canonical /private/tmp")
    root.mkdir(mode=0o700)
    # Synthetic control only; prepared before the guard because the Python
    # credential-name block deliberately forbids even fixture writes afterward.
    (root / "credentials.json").write_text("SYNTHETIC-CREDENTIAL-CONTROL\n")
    guard = NativeFixtureGuard(root)
    sys.modules["main_offline_guard"] = guard
    sys.addaudithook(guard.audit)
    atexit.register(guard.finish, parent=True, shutdown_complete=True)
    guard.configure()
    os.chdir(root)
    save(root / "invocation.json", {"argv": [sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
                                  "actual_orig_argv": sys.orig_argv, "interpreter_flags": repr(sys.flags),
                                  "repo": str(REPO), "original_identity_preserved": True})
    for path in (RUNNER, Path(__file__).resolve(), *(REPO / name for name in FROZEN)):
        guard.source_hashes[str(path)] = digest(path)
    try:
        for relative, expected in FROZEN.items():
            assert digest(REPO / relative) == expected, "owner freeze changed: " + relative
        controls(guard)
        guard.prepare_native()
        for name in ("pandoc", "xelatex", "pdftoppm"):
            run_native(guard, [TOOLS[name], "-v" if name == "pdftoppm" else "--version"])
        native_controls(guard)
        guard.baseline_denials = dict(guard.counts)
        guard.receipt("started")
        results = verify(guard)
        guard.exit_code = 0
        print(json.dumps({"status": "provisional-pass-awaiting-shutdown", "evidence": str(root),
                          "pages": {key: value["pages"] for key, value in results.items()}}, ensure_ascii=False))
        return 0
    except Exception:
        guard.exit_code = 1
        failure = traceback.format_exc()
        guard.export_error = failure
        (root / "failure.txt").write_text(failure)
        save(root / "native-pdf-receipt.json", {"status": "failed", "failure": failure})
        print(failure, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
