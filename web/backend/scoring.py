"""Running match-score estimate, fed to the AI orchestrator's prompt so it
can reason about material trades / check bonuses / time pressure - not an
official scoreboard. Judge-only-visible penalties (a physically illegal
move, a manual judge correction) aren't tracked here, only what the
backend can see directly: captures already recorded in
app_state["captured_pieces"], checks delivered (via move_validator's
is_in_check), and move timing against the same clock both sides' timers
already use.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# move_validator lives at the repo root, not under web/backend - see the
# identical sys.path setup in move_orchestrator.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from move_validator import is_in_check  # noqa: E402 (see sys.path setup above)

POINTS_BY_PIECE = {"pawn": 10, "knight": 30, "bishop": 30, "rook": 50, "queen": 90}
CHECK_BONUS = 50
ON_TIME_BONUS = 1
TIMEOUT_PENALTY = 10


def _opposite(color: str) -> str:
    return "black" if color == "white" else "white"


def _empty_move_time_stats() -> dict:
    return {
        "white": {"count": 0, "total_sec": 0.0, "score": 0},
        "black": {"count": 0, "total_sec": 0.0, "score": 0},
    }


def capture_points(captured_pieces: list[dict]) -> dict:
    """{"white": N, "black": N} - points earned by each color from pieces
    of the OTHER color it captured. captured_pieces stores the captured
    piece's own color/type, so the capturer is the opposite color."""

    points = {"white": 0, "black": 0}
    for piece in captured_pieces:
        capturer = _opposite(piece["color"])
        points[capturer] += POINTS_BY_PIECE.get(piece["piece"], 0)
    return points


def total_score(app_state: dict) -> dict:
    """{"ours": N, "theirs": N} - capture + check + move-timing points
    from our_color's perspective, for display and for the AI prompt."""

    our_color = app_state["our_color"]
    their_color = _opposite(our_color)
    captures = capture_points(app_state.get("captured_pieces", []))
    checks = app_state.get("check_bonus", {"white": 0, "black": 0})
    timing = app_state.get("move_time_stats", _empty_move_time_stats())
    ours = captures[our_color] + checks[our_color] + timing[our_color]["score"]
    theirs = captures[their_color] + checks[their_color] + timing[their_color]["score"]
    return {"ours": ours, "theirs": theirs}


def record_real_move(app_state: dict, moved_color: str, new_board: dict) -> None:
    """Updates fullmove_number, check_bonus, and move_time_stats for a move
    that just happened for real - AI-orchestrated/manual execution, or an
    opponent's move recorded in "view" mode. Does NOT apply to "correct"
    mode, which is a pure board-state fix, not a real move (callers must
    only invoke this from the same real-move paths that already call
    match_clock.sync_active_color/mark_turn_done).

    Must be called BEFORE the match clock's active_color/move_started_at is
    advanced, since it reads the just-completed move's elapsed time from
    the clock as it stood during that move."""

    if moved_color == "black":
        app_state["fullmove_number"] = app_state.get("fullmove_number", 1) + 1

    opponent_color = _opposite(moved_color)
    validator_state = {
        "board": {sq: (occ["color"], occ["piece"]) for sq, occ in new_board.items()},
        "side_to_move": opponent_color,
    }
    if is_in_check(validator_state, opponent_color):
        bonus = app_state.setdefault("check_bonus", {"white": 0, "black": 0})
        bonus[moved_color] = bonus.get(moved_color, 0) + CHECK_BONUS

    clock = app_state.get("match_clock", {})
    if clock.get("status") == "running" and clock.get("move_started_at"):
        elapsed = (
            datetime.now(timezone.utc) - datetime.fromisoformat(clock["move_started_at"])
        ).total_seconds()
        stats = app_state.setdefault("move_time_stats", _empty_move_time_stats())
        side = stats[moved_color]
        side["count"] += 1
        side["total_sec"] += elapsed
        move_limit = app_state.get("move_limit_sec", 300)
        side["score"] += ON_TIME_BONUS if elapsed <= move_limit else -TIMEOUT_PENALTY


def average_move_sec(app_state: dict, color: str) -> float | None:
    stats = app_state.get("move_time_stats", _empty_move_time_stats())[color]
    if stats["count"] == 0:
        return None
    return stats["total_sec"] / stats["count"]
