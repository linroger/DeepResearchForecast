"""Inter-round world-delta digest for the calendar-temporal simulation (spec §4).

Pure, deterministic, no LLM, no I/O. Each round the loop hands the digest built here
to the NEXT round's world-clock header ("## WHAT CHANGED LAST PERIOD"). It surfaces
only qualitative facts: the fired scheduled events, the most influential organic
posts, and — optionally — a direction-only momentum line for the leading scenario.

Herding guard (judge-vetoed): **no numeric shares or percentages ever appear** in
agent-facing text. The full quantitative shares live in ``world_digest.jsonl`` and
the trajectory artifacts, never here. The momentum line is strictly qualitative
("strengthened|weakened|held") regardless of what extra keys ``leader_move`` carries.

SIM-6 (SIM_PERIOD_CONTEXT_V2): ``sectioned=True`` gives events and peer posts their
own whole-line caps and omission markers instead of the legacy silent ``char_cap``
prefix cut, so oversized event text can never starve the posts or vice versa. Events
carried out of a round that produced no digest (tagged ``carried_from_round``) get a
section of their own, so an earlier period's event is never presented as last period's.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

_DIRECTION_WORD = {"up": "strengthened", "down": "weakened", "flat": "held"}
_POST_CLIP = 140
# Sectioned layout (SIM-6). The scenario prefix mirrors sim_period_context's label; it is
# kept inline so this module stays dependency-free.
_SCENARIO_PREFIX = "SCENARIO ASSUMPTION (what-if, not observed): "
_EVENTS_HEADING = "### Scheduled events last period"
_CARRIED_EVENTS_HEADING = "### Scheduled events from earlier periods (no digest was produced)"
_POSTS_HEADING = "### Most-influential actor posts last period (peer claims, unverified)"
# Event key set by the in-band evolver on an event carried out of a round that was never
# stepped (dead on every platform, or its step failed): the 1-based round it fired in.
CARRIED_FROM_ROUND_KEY = "carried_from_round"
# A first line that does not fit its section on its own is cut on a word boundary and
# ends with this marker, instead of the section showing only "(+N ... omitted)".
_TRUNCATED_MARKER = "…(truncated)"
_MIN_CLIPPED_CHARS = 40  # below this a cut line says too little: drop it whole instead


def _more_marker(n: int) -> str:
    return f"(+{n} more omitted)"


def _clip_line(line: str, room: int) -> str:
    """``line`` cut to at most ``room`` characters, ending with ``…(truncated)``;
    cut at the last space when one lies in the second half (and past the minimum).
    '' when fewer than ``_MIN_CLIPPED_CHARS`` characters of it would remain."""
    keep = room - len(_TRUNCATED_MARKER)
    if keep < _MIN_CLIPPED_CHARS:
        return ""
    head = line[:keep]
    space = head.rfind(" ")
    if space >= max(keep // 2, _MIN_CLIPPED_CHARS):
        head = head[:space]
    head = head.rstrip()
    return head + _TRUNCATED_MARKER if len(head) >= _MIN_CLIPPED_CHARS else ""


def fit_whole_lines(lines: Sequence[str], budget: int,
                    marker: Callable[[int], str]) -> Tuple[List[str], int]:
    """Longest prefix of whole ``lines`` that fits ``budget`` characters when joined by
    newlines, reserving room for ``marker(n_omitted)`` whenever a line is dropped.

    Returns ``(kept, n_omitted)``. Kept lines are whole; the first line that does not
    fit ends the prefix. Exception: when no whole line fits, the first line is kept cut
    to the room left beside the marker (see ``_clip_line``, explicit ``…(truncated)``
    ending) rather than dropped. When that room is too small, nothing is kept (the
    caller still shows the marker, so the omission is never silent)."""
    lines = list(lines)
    if len("\n".join(lines)) <= budget:
        return lines, 0
    kept = 0
    used = -1  # length of "\n".join(lines[:kept]); -1 so the first line adds no newline
    for idx, line in enumerate(lines[:-1]):
        used_next = used + 1 + len(line)
        if used_next + 1 + len(marker(len(lines) - idx - 1)) > budget:
            break
        used, kept = used_next, idx + 1
    if kept == 0 and lines:
        rest = len(lines) - 1
        clipped = _clip_line(lines[0], budget - (1 + len(marker(rest)) if rest else 0))
        if clipped:
            return [clipped], rest
    return lines[:kept], len(lines) - kept


def build_world_delta(round_actions: list, fired_events: list,
                      leader_move: Optional[dict] = None,
                      top_k: int = 5, char_cap: int = 900, *,
                      sectioned: bool = False, event_char_cap: int = 600,
                      post_char_cap: int = 600) -> str:
    """Build the qualitative delta digest for one completed period.

    Sections in order: fired events as ``[{date}] {content}`` lines; the top-k
    organic posts ranked by author ``influence_weight`` as
    ``{actor_name}: {content[:140]}``; if ``leader_move`` is given
    (``{"leader": str, "direction": "up"|"down"|"flat"}``), a qualitative momentum
    line — never any numeric share. Output is truncated to ``char_cap`` characters.
    Any error or fully empty input returns ``""`` (the header then renders its own
    placeholder) — this function must never break a running round.

    ``sectioned=True`` (SIM-6) ignores ``char_cap``. Non-empty sections in order:
    events carried out of earlier periods (``carried_from_round`` set) under
    ``### Scheduled events from earlier periods (no digest was produced)`` and this
    period's events under ``### Scheduled events last period``, each capped at
    ``event_char_cap`` (scenario injections prefixed ``SCENARIO ASSUMPTION (what-if,
    not observed): ``); the posts under ``### Most-influential actor posts last period
    (peer claims, unverified)`` capped at ``post_char_cap``. Each cap keeps whole lines
    and ends with ``(+N more omitted)`` (a first line too long on its own is cut with an
    explicit ``…(truncated)`` ending, see ``fit_whole_lines``); then the momentum line,
    never cut. A post clipped at 140 characters ends with an ellipsis.
    """
    try:
        event_lines: list = []
        carried_lines: list = []

        # --- fired scheduled events this period ---------------------------------
        for ev in fired_events or []:
            if not isinstance(ev, dict):
                continue
            content = str(ev.get("content", "") or "").strip()
            if not content:
                continue
            date = str(ev.get("date", "") or "").strip()
            if date and not content.startswith(f"[{date}]"):
                line = f"[{date}] {content}"
            else:  # content already carries the "[{date}] " prefix (config-gen §4)
                line = content
            if (sectioned and ev.get("is_scenario_injection")
                    and not line.startswith(_SCENARIO_PREFIX)):
                line = _SCENARIO_PREFIX + line
            if sectioned and ev.get(CARRIED_FROM_ROUND_KEY) is not None:
                carried_lines.append(line)
            else:
                event_lines.append(line)

        # --- top-k organic posts by author influence_weight ----------------------
        posts = []
        for idx, act in enumerate(round_actions or []):
            if not isinstance(act, dict):
                continue
            content = str(act.get("content", "") or "").strip()
            if not content:
                continue
            try:
                weight = float(act.get("influence_weight", 0.0) or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            name = str(act.get("actor_name") or act.get("agent_name")
                       or act.get("name") or "unknown").strip() or "unknown"
            posts.append((-weight, idx, name, content))
        posts.sort()  # weight desc, then input order — deterministic tie-break
        post_lines = []
        for _, _, name, content in posts[: max(0, int(top_k))]:
            clipped = content[:_POST_CLIP]
            if sectioned and len(content) > _POST_CLIP:
                clipped += "…"
            post_lines.append(f"{name}: {clipped}")

        # --- qualitative momentum (direction only; no shares/percentages ever) ---
        momentum = ""
        if isinstance(leader_move, dict):
            leader = str(leader_move.get("leader", "") or "").strip()
            word = _DIRECTION_WORD.get(str(leader_move.get("direction", "") or ""))
            if leader and word:
                momentum = f"Momentum: {leader} {word} this period."

        if sectioned:
            lines: list = []
            for heading, section, cap in (
                    (_CARRIED_EVENTS_HEADING, carried_lines, event_char_cap),
                    (_EVENTS_HEADING, event_lines, event_char_cap),
                    (_POSTS_HEADING, post_lines, post_char_cap)):
                if not section:
                    continue
                kept, omitted = fit_whole_lines(section, int(cap), _more_marker)
                lines += [heading, *kept] + ([_more_marker(omitted)] if omitted else [])
            if momentum:
                lines.append(momentum)
            return "\n".join(lines)

        lines = event_lines + post_lines + ([momentum] if momentum else [])
        if not lines:
            return ""
        return "\n".join(lines)[: max(0, int(char_cap))]
    except Exception:
        return ""
