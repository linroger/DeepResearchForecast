# Plain-suite exit hang: Kaleido's stderr-reader thread (2026-10-21)

**Status:** Complete on branch `claude/pensive-mccarthy-756ce9`, one commit on `main` 31a3e31 (fast-forwarded from 7b429c8 before committing). Nothing pushed or merged; `main` advances only by compare-and-swap, so merging is the coordinating session's call.

## 1) Request

The backend plain suite (`backend/.venv/bin/python -m pytest -p no:cacheprovider --junitxml=<file>` from `backend/`) printed its summary and then never exited, so every scripted or CI run needed a watcher to kill it. This was reported as pre-existing on `main` in `docs/handoff/main-plain-suite-fixes/handoff.md` §4–§5 (branch `claude/practical-jang-ea953c`). Name the culprit, fix the thread lifecycle in a way that is also right for production, and show the whole suite exiting by itself.

## 2) Method

All runs used frozen `git archive` copies in the session scratchpad (no `deer-flow/` checkout) and the deployment venv's interpreter. A throwaway pytest plugin, loaded with `-p` and kept outside the repo, wrapped `threading.Thread.start` to record each thread's start stack and the running test. In `pytest_unconfigure` it dumped the live threads, and it armed `faulthandler.dump_traceback_later(60)` to capture the stacks during finalization.

## 3) Cause

On frozen `main` 7b429c8 (`8 failed, 7486 passed, 1497 skipped, 11 xfailed, 19 errors in 463.72s`; the 8 are the failures fixed on `claude/practical-jang-ea953c`), the process was still alive 60 s after the summary. The main thread was in `threading._shutdown`, which waits for non-daemon threads. The only threads it was waiting on were two non-daemon `browser_procThread`s, both blocked in `os.read` inside `logistro/_api.py` `read_pipe`:

- Started during `tests/test_forecast_visuals_manifest.py::test_plotly_html_has_stable_div_id_and_is_byte_deterministic` (31.9 s) and `tests/test_world_model_downstream.py::test_world_variables_chart_indexes_numeric_histories` (32.2 s). In both, Kaleido's Chrome launch failed after about 30 s, and the tests pass on the HTML/matplotlib fallback.
- Start stack: `fig.write_image` → `kaleido.calc_fig_sync` → `oneshot_async_run` → `asyncio.run(calc_fig)` → `async with Kaleido()` → `choreographer.Browser.open()` → `logistro.getPipeLogger("browser_proc")`. logistro creates a plain `Thread` (non-daemon) that reads the browser's stderr pipe until EOF. Its docstring tells callers to close the write end themselves. choreographer closes its copy only in `Browser.close()`, which a failed `__aenter__` can skip.
- EOF never came. An orphaned system-Chrome `chrome_crashpad_handler` (parent pid 1), started at 15:37:44 during the first failed launch, was still alive 7.5 minutes later with a pipe as its fd 2. A process Chrome spawns inherits that stderr and can outlive the browser.
- The `kevent` thread seen with `/usr/bin/sample` is the **daemon** `graphiti-loop` (`app/services/graphiti_client/runtime.py`), which does not block exit. An idle `graphiti-llm_0` ThreadPoolExecutor worker was also alive at unconfigure; concurrent.futures' exit hook wakes and joins it, and it was gone in the finalization dump.

**Deterministic reproduction:** set `BROWSER_PATH` to a script that leaves a background `sleep` running and exits 1. `fig.write_image` then raises `BrowserFailedError` within 0.4 s, and the process never exits (killed after 30 s). A script that only runs `exit 1` exits cleanly. So the hang needs a surviving process that holds the stderr pipe, which is what the crashpad handler was. Production has the same failure: the forecast-visuals `render.py` CLI, or any process that exports PNGs, would write its outputs and then hang at exit.

## 4) Fix

Python threads take their daemon flag from the thread that creates them. The three Kaleido call sites now run their export through `_run_kaleido_export`, which starts the export on a daemon thread, joins it, and returns the result or re-raises the exception in the caller. Kaleido's one-shot thread, and through it the logistro reader, become daemon threads, so a leaked reader can no longer keep the interpreter alive. Behavior is otherwise unchanged: same blocking call, same exceptions, same fallbacks and circuit breaker, no timeout added.

- `backend/app/services/report_visualizer.py`: `_save_png` (`fig.write_image`) and `_flush_png_jobs` (`pio.write_images`).
- `deerflow_bridge/skills/forecast-visuals/scripts/render.py`: `_write_outputs` (`fig.write_image`). The script cannot import the backend, so it carries its own copy of the helper. The deployed `deer-flow/skills/public/forecast-visuals/` copy picks it up from the runtime skill sync once the deployment checkout takes this change. Nothing was deployed here.
- `backend/tests/test_kaleido_exit.py` (new): for each renderer, a child process loads the module from its file and exports against the leaky fake browser. The test requires the child to exit by itself, the fake browser to have been launched, the export to have failed into the fallback, and the stderr-holding child to still be alive at that point.

Rejected alternatives: patching logistro or choreographer in site-packages (not ours, and the deployment venv is shared); unregistering the thread from `threading._shutdown_locks` (private and version-specific); marking threads daemon after start (Python forbids it); a conftest-only teardown (would leave the production hang in place).

## 5) Verification

All suite runs used the command above. A scratch watcher would have killed pytest if it was still alive 120 s after the JUnit file appeared. It never fired on the fixed code. Its `PYTHONPATH` held only the diagnostic plugin, which pytest loads only with `-p`.

- **Regression test, before/after.** On frozen `main` 7b429c8 with only the new test added: `2 failed in 180.55s`. Each child had already printed its fallback result (`png_done {}` / `png_rel None html_rel charts/probe.html`) and was still alive at the 90 s limit. With the fix: `2 passed in 3.32s`.
- **Real test modules, every launch forced to fail** (`BROWSER_PATH` set to a script that runs `sleep 600 &` and exits 1), on `test_forecast_visuals_manifest.py`, `test_world_model_downstream.py` and `test_wave9_visualizer.py`:
  - Frozen `main`: `79 passed, 2 skipped in 28.34s`, then still alive 60 s after the JUnit file (killed).
  - Fixed: `79 passed, 2 skipped in 4.75s`, exit 0 after 8 s.
- **Whole plain suite on the final code.** The frozen copy is the tree of `main` 31a3e31 (`cf37b7b`, i.e. 7b429c8 plus the practical-jang fixes) plus this change, byte-identical to the commit. Result: `7496 passed, 1497 skipped, 11 xfailed, 19 errors in 449.63s`, JUnit `tests=9023 failures=0 errors=19`. The process **exited by itself** 3 s after the summary. Exit code 1 is pytest's code for the 19 errors, all of them the known `test_legacy_official_data.py` cases (no `deer-flow/` in a git archive). 9023 tests = the 9021 on frozen 7b429c8 plus the 2 new ones.
- **Same tree with every Kaleido launch forced to fail:** `7495 passed, 1498 skipped, 11 xfailed, 19 errors in 412.36s`, exited 3 s after the summary. Three in-process launches failed, and their stderr holders were still alive at exit. The extra skip is `test_kaleido_png_pair_standalone_builder`, which skips once the process-wide Kaleido circuit breaker has tripped. This run came first on that copy, and the plain run above reused the copy afterwards.
- **Earlier run on a fresh copy of the same merge** (this change before its final docstring wording): `7496 passed, 1497 skipped, 11 xfailed, 19 errors in 568.34s`, exited 3 s after the summary. An orphaned `chrome_crashpad_handler` with a pipe as fd 2 was still alive afterwards (pid 40089, started 15:54:59, while that run was the only process launching real Chrome). That is the condition that hung `main`.
- **Real Chrome still exports** through the fixed code:
  - `_flush_png_jobs` (batch `write_images`) produced `{'x': 'charts/x.png'}`.
  - `_save_png` returned `True` and wrote a fresh 2400×1000 PNG.

  Both processes exited by themselves. In both, the (now daemon) reader thread was still alive at exit, so before the fix even a successful export could hold exit open for as long as a Chrome descendant kept the pipe.
- **Baseline:** frozen `main` 7b429c8 gave `8 failed, 7486 passed, 1497 skipped, 11 xfailed, 19 errors in 463.72s` (the 8 are fixed on `main` 31a3e31), then hung (§3).
- **Ruff:** `uvx ruff@0.17.1 check --select F,E9 --ignore F401,F841` passes on the three touched Python files. With the project config, `report_visualizer.py` reports the same 75 pre-existing findings before and after, and the new test adds none.

## 6) Follow-ups (not done here)

- **Kaleido launch failures themselves.** The roughly 30 s failures with system Google Chrome 155 look environmental: Kaleido uses the system Chrome, and GoogleUpdater processes started during the runs. They now cost time but no longer hang the process. Skipping `test_wave9_visualizer.py::test_kaleido_png_pair_standalone_builder` on that specific launch error, or pinning a Kaleido-managed Chrome (`choreo_get_chrome`), is still open (see the practical-jang note §5).
- **Orphaned Chrome processes after Kaleido launches.** choreographer does not kill the browser or clean its temp dir when `open()` fails, and system-Chrome `chrome_crashpad_handler`s with a pipe as stderr outlive test runs. One from 14:58:50 was still alive at 16:22, and they do exit eventually. They no longer block anything. Out of scope; upstream.
- **Suite writes into the checkout.** The frozen-copy runs leave `backend/log/`, `backend/logs/` and `backend/uploads/` behind. This is listed in the practical-jang note §5, and the uploads part is being isolated by a conftest fixture on branch `claude/eloquent-shannon-5a149e`.
