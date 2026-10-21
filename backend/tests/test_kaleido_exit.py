"""A failed Kaleido PNG export must not keep the Python process alive.

Kaleido starts headless Chrome through choreographer, and logistro feeds the browser's stderr
into logging on a non-daemon reader thread that stops only at EOF.  When Chrome fails to start
and a process it spawned keeps that stderr pipe open (on 2026-10-21, an orphaned
chrome_crashpad_handler with a pipe as its stderr), EOF never arrives and interpreter exit waits
for the reader forever: the whole plain suite printed its summary and never exited.  Both
renderers run their exports through ``_run_kaleido_export``, a daemon thread whose daemon flag
the reader inherits.

Each case runs the real export code in a child process against a fake browser that exits at
once but leaves a background child holding its stderr, and requires the child to exit by itself.
"""

import importlib.util
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPORT_VISUALIZER = BACKEND / "app" / "services" / "report_visualizer.py"
FORECAST_RENDER = BACKEND.parent / "deerflow_bridge" / "skills" / "forecast-visuals" / "scripts" / "render.py"

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="the fake browser is a POSIX shell script"),
    pytest.mark.skipif(importlib.util.find_spec("plotly") is None or importlib.util.find_spec("kaleido") is None,
                       reason="plotly + kaleido are needed to exercise the PNG export"),
]

# The child loads each renderer from its file, so it never imports the app package (whose
# loggers would write into backend/logs).  It prints the export outcome, then returns from the
# script: the parent measures whether the interpreter can actually exit afterwards.
_CHILD = textwrap.dedent("""
    import importlib.util, sys
    from pathlib import Path

    kind, source, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    spec = importlib.util.spec_from_file_location("kaleido_exit_probe", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(x=["a", "b"], y=[1, 2]))
    if kind == "report_visualizer":
        viz = module.ReportVisualizer()
        viz._batch_mode = True
        viz._queue_png(fig, str(out), "probe", "probe")
        viz._flush_png_jobs()  # batch write_images fails, then the per-figure _save_png fallback
        print("png_done", viz._png_done, flush=True)
    else:
        png_rel, html_rel = module._write_outputs(fig, None, out, "probe")
        print("png_rel", png_rel, "html_rel", html_rel, flush=True)
""")


@pytest.fixture
def leaky_browser(tmp_path):
    """A 'browser' that exits at once and leaves a background child holding its stderr."""
    holder_pid = tmp_path / "holder.pid"
    browser = tmp_path / "leaky-chrome"
    browser.write_text(f"#!/bin/sh\nsleep 120 &\necho $! > '{holder_pid}'\nexit 1\n", encoding="utf-8")
    browser.chmod(0o755)
    yield browser, holder_pid
    try:
        os.kill(int(holder_pid.read_text().strip()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


@pytest.mark.parametrize(("kind", "source"), [
    ("report_visualizer", REPORT_VISUALIZER),
    ("forecast_render", FORECAST_RENDER),
])
def test_failed_kaleido_launch_lets_the_process_exit(kind, source, leaky_browser, tmp_path):
    browser, holder_pid = leaky_browser
    out = tmp_path / "charts"
    out.mkdir()
    env = dict(os.environ, BROWSER_PATH=str(browser), DRF_TEST_PROCESS="1")
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-c", _CHILD, kind, str(source), str(out)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, _ = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        pytest.fail(f"{kind}: process still alive {time.monotonic() - started:.0f}s after a failed "
                    f"Kaleido launch (non-daemon stderr reader?)\n{output[-3000:]}")
    assert proc.returncode == 0, output[-3000:]
    # The export really reached the fake browser and failed there ...
    assert holder_pid.exists(), f"{kind}: Kaleido never launched the fake browser\n{output[-3000:]}"
    assert ("png_done {}" in output) if kind == "report_visualizer" else ("png_rel None" in output), output[-3000:]
    # ... and its child still held the stderr pipe when the process exited.
    os.kill(int(holder_pid.read_text().strip()), 0)
