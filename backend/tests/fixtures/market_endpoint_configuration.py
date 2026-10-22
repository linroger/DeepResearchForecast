"""Read import-time endpoint configuration in an isolated, guard-admitted child."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deerflow_bridge"))
import deerflow_research as bridge

print(bridge._POLYMARKET_BASE_URL, bridge._CLOB_BASE_URL)
