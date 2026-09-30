"""SIM-5 (C42 d): what camel actually delivers from an agent's memory to the model.

DRF injects per-round notes into each OASIS agent's camel memory.  camel's
ScoreBasedContextCreator keeps only records[0] as the system message and drops
every later SYSTEM-role record, so:

* the world clock / ResponseLog notes must be written with the USER role (they
  are, see test_calendar_round_loop.test_world_clock_delivered_as_user_role);
* the affect line written by _inject_agent_dynamics as a SYSTEM 'StateUpdater'
  record never reaches the model, which {plat}_dynamics_summary.json records as
  prompt_delivery='system_record_dropped_by_context_creator'.

This test uses the real ChatHistoryMemory + ScoreBasedContextCreator so that a
camel upgrade changing either behaviour fails here first.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("camel")

from camel.memories import ChatHistoryMemory, MemoryRecord  # noqa: E402
from camel.memories.context_creators.score_based import ScoreBasedContextCreator  # noqa: E402
from camel.messages import BaseMessage  # noqa: E402
from camel.types import OpenAIBackendRole  # noqa: E402
from camel.utils import BaseTokenCounter  # noqa: E402

SYSTEM_TEXT = "You are IBM, a quantum-computing vendor. Speak as IBM would in public."
STATE_LINE = "（当前状态：情绪亢奋/激动；立场已明显强化）"
WORLD_CLOCK = "# WORLD CLOCK — 2027-H1 (2027-01-01 → 2027-06-30) | round 2/29"


class _LengthTokenCounter(BaseTokenCounter):
    """Deterministic offline counter: one token per character."""

    def count_tokens_from_messages(self, messages):
        return sum(len(str(m.get("content") or "")) for m in messages)

    def encode(self, text):
        return [ord(ch) for ch in text]

    def decode(self, token_ids):
        return "".join(chr(t) for t in token_ids)


def _context():
    memory = ChatHistoryMemory(ScoreBasedContextCreator(_LengthTokenCounter(), token_limit=10**6))
    memory.write_records([
        MemoryRecord(message=BaseMessage.make_assistant_message(role_name="IBM", content=SYSTEM_TEXT),
                     role_at_backend=OpenAIBackendRole.SYSTEM),
        MemoryRecord(message=BaseMessage.make_user_message(role_name="StateUpdater", content=STATE_LINE),
                     role_at_backend=OpenAIBackendRole.SYSTEM),
        MemoryRecord(message=BaseMessage.make_user_message(role_name="WorldClock", content=WORLD_CLOCK),
                     role_at_backend=OpenAIBackendRole.USER),
    ])
    messages, _tokens = memory.get_context()
    return messages


def test_sealed_system_head_survives():
    messages = _context()
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_TEXT


def test_system_note_after_the_head_is_dropped():
    messages = _context()
    assert not any(STATE_LINE in str(m.get("content") or "") for m in messages)
    assert sum(1 for m in messages if m["role"] == "system") == 1


def test_user_world_clock_note_is_delivered():
    messages = _context()
    assert any(m["role"] == "user" and "# WORLD CLOCK" in str(m.get("content") or "")
               for m in messages)


def test_dynamics_summary_records_the_drop():
    import run_parallel_simulation as rps

    assert rps._DYNAMICS_PROMPT_DELIVERY == "system_record_dropped_by_context_creator"
