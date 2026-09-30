"""INFRA-3: the pure max_tokens escalation schedule (app/utils/llm_recovery.py).

No I/O, no Config: every case is one call of next_max_tokens.
"""

import ast

import pytest

from app.utils import llm_recovery
from app.utils.llm_recovery import next_max_tokens


def test_doubles_with_a_floor():
    assert next_max_tokens(512, ceiling=32768) == 1024
    assert next_max_tokens(4096, ceiling=32768) == 8192
    # The 64-token report preflight probe jumps to the floor, not to 128.
    assert next_max_tokens(64, ceiling=32768) == 1024
    assert next_max_tokens(8192, ceiling=32768, floor=2048) == 16384


def test_unknown_current_starts_at_four_floors():
    assert next_max_tokens(None, ceiling=32768) == 4096
    assert next_max_tokens(None, ceiling=32768, floor=512) == 2048


def test_clamps_to_the_ceiling():
    assert next_max_tokens(20000, ceiling=32768) == 32768
    assert next_max_tokens(None, ceiling=3000) == 3000


def test_clamps_to_the_context_window_minus_prompt_and_reserve():
    assert next_max_tokens(4096, ceiling=32768, context_window=10000, prompt_tokens=3000) == 5976
    assert next_max_tokens(4096, ceiling=32768, context_window=10000, prompt_tokens=3000,
                           reserve=0) == 7000
    # A clamp needs both numbers: an unknown prompt size leaves only the ceiling.
    assert next_max_tokens(4096, ceiling=32768, context_window=10000) == 8192
    assert next_max_tokens(4096, ceiling=32768, prompt_tokens=3000) == 8192


@pytest.mark.parametrize("current, kwargs", [
    (32768, {"ceiling": 32768}),                                             # at the ceiling
    (40000, {"ceiling": 32768}),                                             # above it
    (5976, {"ceiling": 32768, "context_window": 10000, "prompt_tokens": 3000}),  # window full
    (4096, {"ceiling": 32768, "context_window": 8000, "prompt_tokens": 7500}),   # below current
    (None, {"ceiling": 32768, "context_window": 8000, "prompt_tokens": 7500}),   # no room at all
    (None, {"ceiling": 0}),
])
def test_returns_none_without_headroom(current, kwargs):
    assert next_max_tokens(current, **kwargs) is None


def test_result_is_always_strictly_greater_than_current():
    current = 64
    seen = [current]
    while True:
        nxt = next_max_tokens(current, ceiling=32768)
        if nxt is None:
            break
        assert nxt > current
        seen.append(nxt)
        current = nxt
    assert seen == [64, 1024, 2048, 4096, 8192, 16384, 32768]


def test_module_is_pure_stdlib():
    """No Config / I/O import: the schedule stays offline-testable in isolation."""
    with open(llm_recovery.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative (app) imports"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"typing"}, imported
