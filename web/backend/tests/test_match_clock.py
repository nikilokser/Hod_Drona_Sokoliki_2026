import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from match_clock import mark_turn_done, start_match


def test_start_match_sets_running_state():
    clock = start_match()
    assert clock["status"] == "running"
    assert clock["active_color"] == "white"
    assert clock["match_started_at"] is not None
    assert clock["move_started_at"] is not None
    assert clock["match_started_at"] == clock["move_started_at"]


def test_start_match_resets_to_white_even_after_black_was_active():
    clock = start_match()
    clock = mark_turn_done(clock)  # now black to move
    assert clock["active_color"] == "black"

    restarted = start_match()
    assert restarted["status"] == "running"
    assert restarted["active_color"] == "white"


def test_mark_turn_done_flips_color_from_white():
    clock = start_match()
    updated = mark_turn_done(clock)
    assert updated["active_color"] == "black"
    assert updated["move_started_at"] != clock["move_started_at"]
    assert updated["match_started_at"] == clock["match_started_at"]


def test_mark_turn_done_flips_color_from_black():
    clock = start_match()
    once = mark_turn_done(clock)
    twice = mark_turn_done(once)
    assert twice["active_color"] == "white"
