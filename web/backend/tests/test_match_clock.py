import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from match_clock import (
    end_match,
    mark_turn_done,
    pause_match,
    resume_match,
    start_match,
    sync_active_color,
)


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


def test_pause_match_freezes_clock():
    clock = start_match()
    paused = pause_match(clock)
    assert paused["status"] == "paused"
    assert paused["frozen_at"] is not None
    assert paused["match_started_at"] == clock["match_started_at"]
    assert paused["move_started_at"] == clock["move_started_at"]


def test_resume_match_shifts_timestamps_forward_by_pause_duration():
    clock = start_match()
    paused = pause_match(clock)
    time.sleep(0.05)
    resumed = resume_match(paused)

    assert resumed["status"] == "running"
    assert resumed["frozen_at"] is None

    original_match_start = datetime.fromisoformat(clock["match_started_at"])
    new_match_start = datetime.fromisoformat(resumed["match_started_at"])
    shift = (new_match_start - original_match_start).total_seconds()
    assert shift > 0  # shifted forward by (roughly) the pause duration

    original_move_start = datetime.fromisoformat(clock["move_started_at"])
    new_move_start = datetime.fromisoformat(resumed["move_started_at"])
    move_shift = (new_move_start - original_move_start).total_seconds()
    assert move_shift > 0


def test_resume_preserves_active_color():
    clock = start_match()
    clock = mark_turn_done(clock)  # black to move
    paused = pause_match(clock)
    resumed = resume_match(paused)
    assert resumed["active_color"] == "black"


def test_end_match_marks_finished_and_freezes():
    clock = start_match()
    ended = end_match(clock)
    assert ended["status"] == "finished"
    assert ended["frozen_at"] is not None


def test_end_match_from_paused():
    clock = start_match()
    paused = pause_match(clock)
    ended = end_match(paused)
    assert ended["status"] == "finished"


def test_sync_active_color_flips_and_resets_move_clock():
    clock = start_match()  # active_color == "white"
    updated = sync_active_color(clock, "black")
    assert updated["active_color"] == "black"
    assert updated["move_started_at"] != clock["move_started_at"]
    assert updated["match_started_at"] == clock["match_started_at"]


def test_sync_active_color_noop_when_already_matching():
    clock = start_match()
    updated = sync_active_color(clock, "white")
    assert updated == clock


def test_sync_active_color_noop_when_idle():
    clock = {
        "status": "idle",
        "match_started_at": None,
        "active_color": None,
        "move_started_at": None,
        "frozen_at": None,
    }
    updated = sync_active_color(clock, "white")
    assert updated == clock


def test_sync_active_color_noop_when_paused():
    clock = pause_match(start_match())
    updated = sync_active_color(clock, "black")
    assert updated == clock


def test_sync_active_color_noop_when_finished():
    clock = end_match(start_match())
    updated = sync_active_color(clock, "black")
    assert updated == clock
