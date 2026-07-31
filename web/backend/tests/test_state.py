import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import apply_move, initial_board, rebind_role

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


def test_initial_board_has_32_pieces():
    board = initial_board("white", BINDINGS)
    assert len(board) == 32


def test_initial_board_our_side_has_robot_ids():
    board = initial_board("white", BINDINGS)
    our_squares = [sq for sq, p in board.items() if p["color"] == "white"]
    assert len(our_squares) == 16
    for sq in our_squares:
        assert "robot_id" in board[sq]


def test_initial_board_their_side_has_no_robot_ids():
    board = initial_board("white", BINDINGS)
    their_squares = [sq for sq, p in board.items() if p["color"] == "black"]
    assert len(their_squares) == 16
    for sq in their_squares:
        assert "robot_id" not in board[sq]


def test_initial_board_king_and_queen_placement():
    board = initial_board("white", BINDINGS)
    assert board["e1"] == {
        "color": "white",
        "piece": "king",
        "robot_id": "drone-01",
        "role": "king",
    }
    assert board["d1"] == {
        "color": "white",
        "piece": "queen",
        "robot_id": "drone-02",
        "role": "queen",
    }
    assert board["e8"] == {"color": "black", "piece": "king"}


def test_initial_board_our_side_has_roles():
    board = initial_board("white", BINDINGS)
    assert board["a1"]["role"] == "rook_1"
    assert board["h1"]["role"] == "rook_2"
    assert board["e2"]["role"] == "pawn_5"


def test_rebind_role_updates_robot_id_on_board():
    board = initial_board("white", BINDINGS)
    new_board = rebind_role(board, "king", "drone-99")
    assert new_board["e1"]["robot_id"] == "drone-99"
    assert new_board["e1"]["role"] == "king"
    assert board["e1"]["robot_id"] == "drone-01"  # original untouched


def test_rebind_role_is_noop_when_piece_not_on_board():
    board = initial_board("white", BINDINGS)
    del board["e1"]  # king captured/removed
    new_board = rebind_role(board, "king", "drone-99")
    assert new_board == board


def test_initial_board_flips_for_black():
    board = initial_board("black", BINDINGS)
    assert board["e8"]["robot_id"] == "drone-01"
    assert "robot_id" not in board["e1"]


def test_view_mode_rejects_our_own_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "view", "e2", "e4", our_color="white")
    assert result["ok"] is False
    assert new_board == board


def test_view_mode_allows_opponent_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "view", "e7", "e5", our_color="white")
    assert result["ok"] is True
    assert "e7" not in new_board
    assert new_board["e5"]["color"] == "black"


def test_correct_mode_moves_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "correct", "e2", "e4", our_color="white")
    assert result["ok"] is True
    assert result["captured"] is False
    assert "e2" not in new_board
    assert new_board["e4"]["piece"] == "pawn"


def test_correct_mode_captures_opposite_color():
    board = initial_board("white", BINDINGS)
    board["e5"] = {"color": "black", "piece": "pawn"}
    new_board, result = apply_move(board, "correct", "e2", "e5", our_color="white")
    assert result["ok"] is True
    assert result["captured"] is True
    assert new_board["e5"]["color"] == "white"


def test_correct_mode_rejects_same_color_target():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "correct", "a1", "b1", our_color="white")
    assert result["ok"] is False
    assert new_board == board


def test_correct_mode_rejects_empty_from():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "correct", "e4", "e5", our_color="white")
    assert result["ok"] is False


def test_manual_mode_moves_and_reports_robot_id():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "manual", "e2", "e4", our_color="white")
    assert result["ok"] is True
    assert result["moved_robot_id"] == "peshka-05"
    assert new_board["e4"]["robot_id"] == "peshka-05"


def test_manual_mode_reports_no_robot_id_for_opponent_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "manual", "e7", "e5", our_color="white")
    assert result["ok"] is True
    assert result["moved_robot_id"] is None
