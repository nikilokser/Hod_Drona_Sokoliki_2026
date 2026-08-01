import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scoring
from state import initial_board

BINDINGS = {
    "king": "drone-01",
    "queen": "drone-02",
    "bishop_1": "drone-03",
    "bishop_2": "drone-04",
    "knight_1": "drone-05",
    "knight_2": "drone-06",
    "rook_1": "rover-01",
    "rook_2": "rover-02",
    **{f"pawn_{i}": f"peshka-0{i}" for i in range(1, 9)},
}


def make_app_state(**overrides):
    state = {
        "board": initial_board("white", BINDINGS),
        "our_color": "white",
        "captured_pieces": [],
        "match_clock": {"status": "idle", "move_started_at": None},
        "move_limit_sec": 300,
    }
    state.update(overrides)
    return state


# --- capture_points ----------------------------------------------------------


def test_capture_points_credits_the_opposite_color():
    captured = [{"color": "black", "piece": "pawn"}, {"color": "white", "piece": "queen"}]
    assert scoring.capture_points(captured) == {"white": 10, "black": 90}


def test_capture_points_empty_list():
    assert scoring.capture_points([]) == {"white": 0, "black": 0}


def test_capture_points_unknown_piece_scores_zero():
    assert scoring.capture_points([{"color": "black", "piece": "king"}]) == {"white": 0, "black": 0}


# --- total_score ---------------------------------------------------------------


def test_total_score_combines_captures_checks_and_timing():
    app_state = make_app_state(
        our_color="white",
        captured_pieces=[{"color": "black", "piece": "rook"}],  # we captured -> +50
        check_bonus={"white": 50, "black": 0},
        move_time_stats={
            "white": {"count": 2, "total_sec": 10, "score": 2},
            "black": {"count": 1, "total_sec": 400, "score": -10},
        },
    )
    assert scoring.total_score(app_state) == {"ours": 102, "theirs": -10}


def test_total_score_defaults_to_zero_with_no_history():
    assert scoring.total_score(make_app_state()) == {"ours": 0, "theirs": 0}


def test_total_score_from_black_perspective():
    app_state = make_app_state(
        our_color="black",
        captured_pieces=[{"color": "black", "piece": "queen"}],  # white captured -> theirs
        check_bonus={"white": 0, "black": 50},
    )
    score = scoring.total_score(app_state)
    assert score["ours"] == 50
    assert score["theirs"] == 90


# --- record_real_move: fullmove_number ----------------------------------------


def test_record_real_move_increments_fullmove_only_after_black():
    app_state = make_app_state(fullmove_number=1)
    board = initial_board("white", BINDINGS)
    scoring.record_real_move(app_state, "white", board)
    assert app_state["fullmove_number"] == 1
    scoring.record_real_move(app_state, "black", board)
    assert app_state["fullmove_number"] == 2


# --- record_real_move: check bonus ----------------------------------------------


def _board_with_check():
    # White queen on d8 gives check to the black king on e8 (adjacent, same
    # rank) - a minimal board, not a real game position.
    return {
        "e8": {"color": "black", "piece": "king"},
        "d8": {"color": "white", "piece": "queen"},
        "e1": {"color": "white", "piece": "king"},
    }


def test_record_real_move_awards_check_bonus_to_mover():
    app_state = make_app_state()
    scoring.record_real_move(app_state, "white", _board_with_check())
    assert app_state["check_bonus"]["white"] == scoring.CHECK_BONUS
    assert app_state["check_bonus"]["black"] == 0


def test_record_real_move_no_check_bonus_when_not_in_check():
    app_state = make_app_state()
    board = initial_board("white", BINDINGS)
    scoring.record_real_move(app_state, "white", board)
    assert app_state.get("check_bonus", {}).get("white", 0) == 0


def test_record_real_move_check_bonus_accumulates():
    app_state = make_app_state()
    scoring.record_real_move(app_state, "white", _board_with_check())
    scoring.record_real_move(app_state, "white", _board_with_check())
    assert app_state["check_bonus"]["white"] == scoring.CHECK_BONUS * 2


# --- record_real_move: move timing ----------------------------------------------


def _running_clock(seconds_ago: float) -> dict:
    started = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"status": "running", "move_started_at": started.isoformat()}


def test_record_real_move_on_time_scores_bonus():
    app_state = make_app_state(match_clock=_running_clock(5), move_limit_sec=300)
    board = initial_board("white", BINDINGS)
    scoring.record_real_move(app_state, "white", board)
    stats = app_state["move_time_stats"]["white"]
    assert stats["count"] == 1
    assert stats["score"] == scoring.ON_TIME_BONUS


def test_record_real_move_timeout_scores_penalty():
    app_state = make_app_state(match_clock=_running_clock(400), move_limit_sec=300)
    board = initial_board("white", BINDINGS)
    scoring.record_real_move(app_state, "white", board)
    stats = app_state["move_time_stats"]["white"]
    assert stats["score"] == -scoring.TIMEOUT_PENALTY


def test_record_real_move_no_timing_when_clock_not_running():
    app_state = make_app_state(match_clock={"status": "idle", "move_started_at": None})
    board = initial_board("white", BINDINGS)
    scoring.record_real_move(app_state, "white", board)
    assert app_state.get("move_time_stats", {}).get("white", {}).get("count", 0) == 0


# --- average_move_sec ----------------------------------------------------------


def test_average_move_sec_none_when_no_moves():
    assert scoring.average_move_sec(make_app_state(), "white") is None


def test_average_move_sec_computes_mean():
    app_state = make_app_state(
        move_time_stats={
            "white": {"count": 2, "total_sec": 30.0, "score": 2},
            "black": {"count": 0, "total_sec": 0.0, "score": 0},
        }
    )
    assert scoring.average_move_sec(app_state, "white") == 15.0
