"""Fake stdio MCP server for the data-hub tests (``tests/test_data_mcp.py``).

Stands in for the six vendored data servers so the hub tests stay hermetic: no
network, no node, no built servers.  Run with the backend venv's interpreter::

    python tests/fixtures/fake_mcp_server.py [--startup-delay S] [--exit-at-start CODE]

Every startup writes one banner line to stderr (the hub redirects it into its
per-server errlog file).  ``--startup-delay`` sleeps before serving (start
timeout tests); ``--exit-at-start`` exits before serving (startup-crash tests).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("fake-data")


@server.tool()
def echo(text: str) -> str:
    """Return ``text`` unchanged."""
    return text


@server.tool()
async def sleep(seconds: float) -> str:
    """Sleep without blocking the server, then report the duration."""
    await asyncio.sleep(seconds)
    return f"slept {seconds}"


@server.tool()
def fail(message: str) -> str:
    """Raise, so the server answers with ``isError=True`` carrying ``message``."""
    raise ValueError(message)


@server.tool()
def crash(code: int = 3) -> str:
    """Terminate the server process immediately (no shutdown, no reply)."""
    sys.stderr.write(f"fake-mcp crashing with exit code {code}\n")
    sys.stderr.flush()
    os._exit(code)


@server.tool()
def env_probe(name: str) -> str:
    """Report whether env var ``name`` is set and its length (never its value)."""
    value = os.environ.get(name)
    return json.dumps({"set": value is not None, "length": len(value or "")})


@server.tool()
def env_echo(name: str) -> str:
    """Echo the raw value of env var ``name`` (exercises the hub's secret redaction)."""
    return f"value={os.environ.get(name, '')}"


@server.tool()
def cwd_probe() -> str:
    """Return the server process's working directory."""
    return os.getcwd()


@server.tool()
def pid() -> int:
    """Return the server process id."""
    return os.getpid()


@server.tool()
def table(rows: int = 2) -> dict[str, Any]:
    """Return a small dict, which FastMCP also exposes as structured content."""
    return {"rows": [{"i": i, "value": i * 1.5} for i in range(rows)]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup-delay", type=float, default=0.0)
    parser.add_argument("--exit-at-start", type=int, default=None)
    options = parser.parse_args()
    sys.stderr.write(f"fake-mcp starting pid={os.getpid()}\n")
    sys.stderr.flush()
    if options.exit_at_start is not None:
        sys.stderr.write("fake-mcp fatal: configured to exit at start\n")
        sys.stderr.flush()
        sys.exit(options.exit_at_start)
    if options.startup_delay > 0:
        time.sleep(options.startup_delay)
    server.run("stdio")


if __name__ == "__main__":
    main()
