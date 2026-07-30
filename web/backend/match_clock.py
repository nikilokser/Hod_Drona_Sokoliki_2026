"""Pure logic for the move/match clock: no HTTP, no globals.

The countdown itself is never computed here or anywhere on the backend -
only start timestamps are stored. Each browser computes "now - started_at"
locally (see board.js). This module only produces/updates the timestamps.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_match() -> dict:
    """(Re)starts the match clock: white to move, both clocks zeroed to
    now. Safe to call whether the match was idle or already running - a
    fresh start always resets everything (the frontend is responsible for
    confirming with the user before calling this while already running)."""

    now = _now_iso()
    return {
        "status": "running",
        "match_started_at": now,
        "active_color": "white",
        "move_started_at": now,
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
