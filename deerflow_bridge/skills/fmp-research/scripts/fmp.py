#!/usr/bin/env python3
"""Small Codex entrypoint for the same official MCP client used by research."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


def _client_type():
    here = Path(__file__).resolve()
    # Installed bundles contain a byte-identical copy of the canonical client.
    # The source bundle uses that client directly rather than maintaining a fork.
    candidates = (here.with_name("fmp_mcp.py"), here.parents[3] / "fmp_mcp.py")
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise RuntimeError("client_not_installed")
    spec = importlib.util.spec_from_file_location("_fmp_skill_client", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("client_not_installed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.FmpMcpClient


def _environment(path: str | None) -> dict[str, str]:
    allowed = {"FMP_API_KEY", "FMP_ENABLED", "FMP_TIMEOUT_SECONDS", "FMP_MAX_CALLS",
               "FMP_MAX_RESPONSE_BYTES", "FMP_MAX_TOOL_PAGES", "FMP_MAX_TOOLS"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    if path:
        source = Path(path).expanduser()
        if not source.is_file() or source.stat().st_size > 262144:
            raise ValueError("invalid_environment_file")
        for line in source.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"\s*(?:export\s+)?(FMP_[A-Z_]+)\s*=\s*(.*?)\s*", line)
            if not match or match[1] not in allowed or match[1] in env:
                continue
            value = match[2]
            if value[:1] in {"'", '"'}:
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError("invalid_environment_value")
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].strip()
            if "\x00" in value or "${" in value or "$(" in value:
                raise ValueError("unsupported_environment_expansion")
            env[match[1]] = value
    return env


def _arguments(path: str) -> dict:
    source = Path(path).expanduser()
    if not source.is_file() or source.stat().st_size > 65536:
        raise ValueError("invalid_arguments_file")
    def reject_constant(_):
        raise ValueError("non_finite_number")
    data = json.loads(source.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("arguments_must_be_object")
    return data


def _write_new(path: str, text: str) -> None:
    # O_EXCL also rejects existing symlinks. Capture files are private and never
    # silently replace an earlier generation's evidence.
    target = Path(path).expanduser()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Explicit local dotenv file; only FMP settings are read")
    sub = parser.add_subparsers(dest="operation", required=True)
    discover = sub.add_parser("discover", help="Discover official tool names and schemas")
    discover.add_argument("--query", default="")
    discover.add_argument("--output")
    call = sub.add_parser("call", help="Call one discovered official tool")
    call.add_argument("--tool", required=True)
    call.add_argument("--arguments-file", required=True)
    call.add_argument("--output")
    args = parser.parse_args(argv)
    client = None
    try:
        env = _environment(args.env_file)
        if args.output and Path(args.output).expanduser().exists():
            raise FileExistsError("capture_exists")
        arguments = _arguments(args.arguments_file) if args.operation == "call" else None
        client = _client_type()(env=env)
        result = (client.discover(args.query) if args.operation == "discover"
                  else client.call(args.tool, arguments))
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        secret = env.get("FMP_API_KEY", "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
        if args.output:
            _write_new(args.output, text)
            print(json.dumps({"output": str(Path(args.output).expanduser()),
                              "status": json.loads(text).get("status", {})}, ensure_ascii=False))
        else:
            print(text, end="")
        return 0 if result.get("status", {}).get("state") in {"ok", "verified_empty"} else 2
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        # Fixed reason classes are useful without exposing credential-bearing
        # paths, authenticated URLs or provider exception messages.
        reason = ("output_exists" if isinstance(exc, FileExistsError) else
                  "missing_dependency" if isinstance(exc, ImportError) else
                  "invalid_local_input" if isinstance(exc, ValueError) else
                  "input_output_error" if isinstance(exc, OSError) else
                  "client_not_installed")
        print(json.dumps({"provider": "fmp", "status": {
            "state": "unavailable", "reason": reason}}))
        return 2
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass  # The client owns bounded cleanup; never print provider errors here.


if __name__ == "__main__":
    raise SystemExit(main())
