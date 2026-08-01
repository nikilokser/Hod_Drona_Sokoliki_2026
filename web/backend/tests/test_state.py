import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import (
    apply_move,
    delete_piece,
    initial_board,
    rebind_role,
    semifinal_initial_board,
    semifinal_v2_initial_board,
)

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


def test_apply_move_reports_captured_piece_details():
    board = initial_board("white", BINDINGS)
    board["e5"] = {"color": "black", "piece": "pawn"}
    new_board, result = apply_move(board, "correct", "e2", "e5", our_color="white")
    assert result["ok"] is True
    assert result["captured_piece"] == {"color": "black", "piece": "pawn"}


def test_apply_move_reports_no_captured_piece_when_target_empty():
    board = initial_board("white", BINDINGS)
    new_board, result = apply_move(board, "correct", "e2", "e4", our_color="white")
    assert result["ok"] is True
    assert result["captured_piece"] is None


# --- delete_piece -----------------------------------------------------------


def test_delete_piece_removes_from_board_in_correct_mode():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "correct", "e7", our_color="white")
    assert result["ok"] is True
    assert result["removed_piece"] == {"color": "black", "piece": "pawn"}
    assert "e7" not in new_board


def test_delete_piece_removes_our_own_piece_in_correct_mode():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "correct", "e2", our_color="white")
    assert result["ok"] is True
    assert result["removed_piece"] == {"color": "white", "piece": "pawn"}
    assert "e2" not in new_board


def test_delete_piece_removes_any_piece_in_manual_mode():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "manual", "e2", our_color="white")
    assert result["ok"] is True
    assert "e2" not in new_board


def test_delete_piece_view_mode_rejects_our_own_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "view", "e2", our_color="white")
    assert result["ok"] is False
    assert new_board == board
    assert "e2" in new_board


def test_delete_piece_view_mode_allows_opponent_piece():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "view", "e7", our_color="white")
    assert result["ok"] is True
    assert "e7" not in new_board


def test_delete_piece_rejects_empty_square():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "correct", "e4", our_color="white")
    assert result["ok"] is False
    assert new_board == board


def test_delete_piece_rejects_unknown_mode():
    board = initial_board("white", BINDINGS)
    new_board, result = delete_piece(board, "bogus", "e2", our_color="white")
    assert result["ok"] is False


# --- semifinal_initial_board -----------------------------------------------


def test_semifinal_board_has_22_pieces():
    # 2 * (1 king, 1 queen, 2 bishops, 2 knights, 1 rook, 4 pawns) = 22
    board = semifinal_initial_board("white", BINDINGS)
    assert len(board) == 22


def test_semifinal_board_white_keeps_a_file_rook_only():
    board = semifinal_initial_board("white", BINDINGS)
    assert board["a1"] == {"color": "white", "piece": "rook", "robot_id": "rover-01", "role": "rook_1"}
    assert "h1" not in board


def test_semifinal_board_black_keeps_h_file_rook_only():
    board = semifinal_initial_board("white", BINDINGS)
    assert board["h8"] == {"color": "black", "piece": "rook"}
    assert "a8" not in board


def test_semifinal_board_pawns_only_on_c_to_f_files():
    board = semifinal_initial_board("white", BINDINGS)
    our_pawns = {sq for sq, p in board.items() if p["color"] == "white" and p["piece"] == "pawn"}
    their_pawns = {sq for sq, p in board.items() if p["color"] == "black" and p["piece"] == "pawn"}
    assert our_pawns == {"c2", "d2", "e2", "f2"}
    assert their_pawns == {"c7", "d7", "e7", "f7"}


def test_semifinal_board_our_side_has_robot_ids():
    board = semifinal_initial_board("white", BINDINGS)
    our_squares = [sq for sq, p in board.items() if p["color"] == "white"]
    assert len(our_squares) == 11
    for sq in our_squares:
        assert "robot_id" in board[sq]


def test_semifinal_board_rook_assignment_flips_with_our_color():
    # Rook presence is fixed by absolute color (white=a-file, black=h-file),
    # not by which side is "ours" - our_color only affects which back rank
    # (1 or 8) each color's pieces land on and who gets robot_id/role.
    board = semifinal_initial_board("black", BINDINGS)
    assert board["a1"]["piece"] == "rook" and board["a1"]["color"] == "white"
    assert "robot_id" not in board["a1"]
    assert board["h8"] == {"color": "black", "piece": "rook", "robot_id": "rover-02", "role": "rook_2"}


# --- semifinal_v2_initial_board ---------------------------------------------


def test_semifinal_v2_board_has_22_pieces():
    board = semifinal_v2_initial_board("white", BINDINGS)
    assert len(board) == 22


def test_semifinal_v2_board_white_king_queen_standard():
    board = semifinal_v2_initial_board("white", BINDINGS)
    assert board["d1"] == {"color": "white", "piece": "queen", "robot_id": "drone-02", "role": "queen"}
    assert board["e1"] == {"color": "white", "piece": "king", "robot_id": "drone-01", "role": "king"}


def test_semifinal_v2_board_black_king_queen_swapped():
    board = semifinal_v2_initial_board("white", BINDINGS)
    assert board["d8"] == {"color": "black", "piece": "king"}
    assert board["e8"] == {"color": "black", "piece": "queen"}


def test_semifinal_v2_board_our_king_role_follows_the_piece_not_the_square():
    # If we're black, our own king is still role "king" (bound via
    # bindings["king"]) even though it now sits on d8, not e8.
    board = semifinal_v2_initial_board("black", BINDINGS)
    assert board["d8"] == {"color": "black", "piece": "king", "robot_id": "drone-01", "role": "king"}
    assert board["e8"] == {"color": "black", "piece": "queen", "robot_id": "drone-02", "role": "queen"}


def test_semifinal_v2_board_rook_files():
    board = semifinal_v2_initial_board("white", BINDINGS)
    assert board["a1"]["piece"] == "rook" and board["a1"]["color"] == "white"
    assert "h1" not in board
    assert board["h8"] == {"color": "black", "piece": "rook"}
    assert "a8" not in board


def test_semifinal_v2_board_pawn_files_differ_by_color():
    board = semifinal_v2_initial_board("white", BINDINGS)
    white_pawns = {sq for sq, p in board.items() if p["color"] == "white" and p["piece"] == "pawn"}
    black_pawns = {sq for sq, p in board.items() if p["color"] == "black" and p["piece"] == "pawn"}
    assert white_pawns == {"a2", "d2", "e2", "f2"}
    assert black_pawns == {"c7", "d7", "e7", "h7"}
