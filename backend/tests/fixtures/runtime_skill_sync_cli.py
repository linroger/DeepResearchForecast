"""Registered test entrypoint for the real runtime skill sync CLI."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "deerflow_bridge" / "runtime_skill_sync.py"),
        run_name="__main__",
    )
