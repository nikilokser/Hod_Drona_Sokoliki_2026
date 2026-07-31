"""Pure logic for the move/match clock: no HTTP, no globals.

The countdown itself is never computed here or anywhere on the backend -
only start timestamps are stored. Each browser computes "now - started_at"
locally (see board.js). This module only produces/updates the timestamps.

status is one of "idle" | "running" | "paused" | "finished". While
"paused" or "finished", "frozen_at" holds the moment the clock stopped -
the frontend uses it instead of the live clock so the countdown visibly
freezes. Resuming shifts match_started_at/move_started_at forward by the
paused duration, so the existing "now - started_at" math on the frontend
keeps working unchanged once running again.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def start_match() -> dict:
    """(Re)starts the match clock: white to move, both clocks zeroed to
    now. Safe to call whether the match was idle, running, paused or
    finished - a fresh start always resets everything (the frontend is
    responsible for confirming with the user before calling this while
    already running/paused)."""

    now = _now_iso()
    return {
        "status": "running",
        "match_started_at": now,
        "active_color": "white",
        "move_started_at": now,
        "frozen_at": None,
    }


def mark_turn_done(match_clock: dict) -> dict:
    """Flips active_color and resets the move clock. Caller must ensure
    status == "running" first (see app.py)."""

    opposite = "black" if match_clock["active_color"] == "white" else "white"
    return {
        **match_clock,
        "active_color": opposite,
        "move_started_at": _now_iso(),
    }


def pause_match(match_clock: dict) -> dict:
    """Caller must ensure status == "running" first (see app.py)."""

    return {**match_clock, "status": "paused", "frozen_at": _now_iso()}


def resume_match(match_clock: dict) -> dict:
    """Caller must ensure status == "paused" first (see app.py). Shifts
    both start timestamps forward by however long the pause lasted, so
    the countdown continues from where it was frozen instead of jumping."""

    now = datetime.now(timezone.utc)
    paused_duration = now - _parse(match_clock["frozen_at"])

    return {
        **match_clock,
        "status": "running",
        "match_started_at": (_parse(match_clock["match_started_at"]) + paused_duration).isoformat(),
        "move_started_at": (_parse(match_clock["move_started_at"]) + paused_duration).isoformat(),
        "frozen_at": None,
    }


def sync_active_color(match_clock: dict, new_active_color: str) -> dict:
    """Keeps the match clock's active_color in lockstep with the board's
    side_to_move whenever a real move happens (manual-mode/orchestrator
    moves, and opponent moves recorded via view-mode drag) - instead of
    requiring a separate manual "Ход сделан" click after every single move.
    "correct" mode is a pure board-state fix, not a real move, and does not
    call this. No-op if the clock isn't currently running or already
    matches - a move made before "Старт матча", or while paused/finished,
    must not implicitly start or perturb the clock."""

    if match_clock["status"] != "running" or match_clock["active_color"] == new_active_color:
        return match_clock
    return {**match_clock, "active_color": new_active_color, "move_started_at": _now_iso()}


def end_match(match_clock: dict) -> dict:
    """Ends the match early. Caller must ensure status is "running" or
    "paused" first (see app.py) - there is nothing to end from "idle",
    and "finished" is already terminal."""

    return {**match_clock, "status": "finished", "frozen_at": _now_iso()}
