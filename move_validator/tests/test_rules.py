from move_validator import (
    apply_move,
    initial_board,
    is_checkmate,
    is_in_check,
    is_stalemate,
    validate_move,
)


def bs(board, side="white"):
    return {"board": board, "side_to_move": side}


def test_initial_board_has_32_pieces_and_white_to_move():
    state = initial_board()
    assert len(state["board"]) == 32
    assert state["side_to_move"] == "white"


def test_rook_moves_straight():
    state = bs({"a1": ("white", "rook")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert result["legal"] is True


def test_rook_cannot_move_diagonally():
    state = bs({"a1": ("white", "rook")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "b2"})
    assert result["legal"] is False
    assert "диагонали" in result["reason"]


def test_rook_blocked_path():
    state = bs({"a1": ("white", "rook"), "a3": ("white", "pawn")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert result["legal"] is False
    assert "перекрыт" in result["reason"]


def test_bishop_moves_diagonally():
    state = bs({"c1": ("white", "bishop")})
    result = validate_move(state, {"piece": "bishop", "from": "c1", "to": "f4"})
    assert result["legal"] is True


def test_bishop_cannot_move_straight():
    state = bs({"c1": ("white", "bishop")})
    result = validate_move(state, {"piece": "bishop", "from": "c1", "to": "c4"})
    assert result["legal"] is False


def test_bishop_blocked_path():
    state = bs({"c1": ("white", "bishop"), "d2": ("white", "pawn")})
    result = validate_move(state, {"piece": "bishop", "from": "c1", "to": "e3"})
    assert result["legal"] is False
    assert "перекрыт" in result["reason"]


def test_knight_moves_in_l_shape():
    state = bs({"b1": ("white", "knight")})
    result = validate_move(state, {"piece": "knight", "from": "b1", "to": "c3"})
    assert result["legal"] is True


def test_knight_illegal_move():
    state = bs({"b1": ("white", "knight")})
    result = validate_move(state, {"piece": "knight", "from": "b1", "to": "b3"})
    assert result["legal"] is False
    assert "не ходит" in result["reason"]


def test_knight_jumps_over_pieces():
    state = bs({"b1": ("white", "knight"), "c2": ("white", "pawn"), "d2": ("white", "pawn")})
    result = validate_move(state, {"piece": "knight", "from": "b1", "to": "c3"})
    assert result["legal"] is True


def test_queen_moves_straight_and_diagonally():
    state = bs({"d1": ("white", "queen")})
    assert validate_move(state, {"piece": "queen", "from": "d1", "to": "d5"})["legal"]
    assert validate_move(state, {"piece": "queen", "from": "d1", "to": "a4"})["legal"]


def test_queen_illegal_geometry():
    state = bs({"d1": ("white", "queen")})
    result = validate_move(state, {"piece": "queen", "from": "d1", "to": "e3"})
    assert result["legal"] is False


def test_king_moves_one_square():
    state = bs({"e1": ("white", "king")})
    result = validate_move(state, {"piece": "king", "from": "e1", "to": "e2"})
    assert result["legal"] is True


def test_king_cannot_move_two_squares():
    state = bs({"e1": ("white", "king")})
    result = validate_move(state, {"piece": "king", "from": "e1", "to": "e3"})
    assert result["legal"] is False


def test_pawn_single_step():
    state = bs({"e2": ("white", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e2", "to": "e3"})
    assert result["legal"] is True


def test_pawn_double_step_from_start():
    state = bs({"e2": ("white", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e2", "to": "e4"})
    assert result["legal"] is True


def test_pawn_double_step_not_from_start_rank():
    state = bs({"e3": ("white", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e3", "to": "e5"})
    assert result["legal"] is False


def test_pawn_double_step_blocked():
    state = bs({"e2": ("white", "pawn"), "e3": ("black", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e2", "to": "e4"})
    assert result["legal"] is False
    assert "перекрыт" in result["reason"]


def test_pawn_forward_blocked_by_any_piece():
    state = bs({"e2": ("white", "pawn"), "e3": ("black", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e2", "to": "e3"})
    assert result["legal"] is False


def test_pawn_diagonal_capture():
    state = bs({"e4": ("white", "pawn"), "d5": ("black", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e4", "to": "d5"})
    assert result["legal"] is True
    assert result["is_capture"] is True
    assert result["captured"] == "pawn"


def test_pawn_diagonal_without_capture_is_illegal():
    """Also demonstrates en passant is rejected: it is exactly this shape
    (diagonal move onto an empty square), which the validator has no
    special case for."""
    state = bs({"e5": ("white", "pawn"), "d5": ("black", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "e5", "to": "d6"})
    assert result["legal"] is False
    assert "взятии" in result["reason"]


def test_capture_opponent_piece():
    state = bs({"a1": ("white", "rook"), "a5": ("black", "pawn")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert result["legal"] is True
    assert result["is_capture"] is True
    assert result["captured"] == "pawn"


def test_cannot_capture_own_piece():
    state = bs({"a1": ("white", "rook"), "a5": ("white", "pawn")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert result["legal"] is False
    assert "своя фигура" in result["reason"]


def test_wrong_color_to_move():
    state = bs({"e2": ("black", "pawn")}, side="white")
    result = validate_move(state, {"piece": "pawn", "from": "e2", "to": "e3"})
    assert result["legal"] is False


def test_claimed_piece_does_not_match_board():
    state = bs({"g1": ("white", "bishop")})
    result = validate_move(state, {"piece": "knight", "from": "g1", "to": "f3"})
    assert result["legal"] is False
    assert "нет коня" in result["reason"]


def test_move_to_same_square_is_illegal():
    state = bs({"a1": ("white", "rook")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a1"})
    assert result["legal"] is False


def test_invalid_square_is_illegal():
    state = bs({"a1": ("white", "rook")})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "i9"})
    assert result["legal"] is False


def test_move_from_empty_square_is_illegal():
    state = bs({})
    result = validate_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert result["legal"] is False
    assert "нет фигуры" in result["reason"]


def test_move_exposing_own_king_to_check_is_illegal():
    # White king e1, white rook e2 pinned by black rook on e8 along the e-file.
    state = bs(
        {
            "e1": ("white", "king"),
            "e2": ("white", "rook"),
            "e8": ("black", "rook"),
        }
    )
    result = validate_move(state, {"piece": "rook", "from": "e2", "to": "d2"})
    assert result["legal"] is False
    assert "под шахом" in result["reason"]


def test_pinned_piece_can_still_move_along_the_pin_line():
    state = bs(
        {
            "e1": ("white", "king"),
            "e2": ("white", "rook"),
            "e8": ("black", "rook"),
        }
    )
    result = validate_move(state, {"piece": "rook", "from": "e2", "to": "e5"})
    assert result["legal"] is True


def test_is_in_check_true_and_false():
    checked = bs({"e1": ("white", "king"), "e8": ("black", "rook")})
    assert is_in_check(checked, "white") is True

    safe = bs({"e1": ("white", "king"), "a8": ("black", "rook")})
    assert is_in_check(safe, "white") is False


def test_checkmate_back_rank():
    state = bs(
        {
            "g1": ("white", "king"),
            "f2": ("white", "pawn"),
            "g2": ("white", "pawn"),
            "h2": ("white", "pawn"),
            "a1": ("black", "rook"),
        },
        side="white",
    )
    assert is_in_check(state, "white") is True
    assert is_checkmate(state) is True
    assert is_stalemate(state) is False


def test_stalemate_classic_corner():
    state = bs(
        {
            "a1": ("white", "king"),
            "b3": ("black", "queen"),
            "c2": ("black", "king"),
        },
        side="white",
    )
    assert is_in_check(state, "white") is False
    assert is_stalemate(state) is True
    assert is_checkmate(state) is False


def test_castling_shape_is_rejected():
    state = bs({"e1": ("white", "king"), "h1": ("white", "rook")})
    result = validate_move(state, {"piece": "king", "from": "e1", "to": "g1"})
    assert result["legal"] is False


def test_promotion_is_not_applied():
    state = bs({"a7": ("white", "pawn")})
    result = validate_move(state, {"piece": "pawn", "from": "a7", "to": "a8"})
    assert result["legal"] is True
    new_state = apply_move(state, {"piece": "pawn", "from": "a7", "to": "a8"})
    assert new_state["board"]["a8"] == ("white", "pawn")


def test_apply_move_flips_side_to_move():
    state = bs({"a1": ("white", "rook")}, side="white")
    new_state = apply_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert new_state["side_to_move"] == "black"
    assert "a1" not in new_state["board"]
    assert new_state["board"]["a5"] == ("white", "rook")


def test_apply_move_does_not_mutate_input_board():
    state = bs({"a1": ("white", "rook")}, side="white")
    original_board = state["board"]
    apply_move(state, {"piece": "rook", "from": "a1", "to": "a5"})
    assert original_board == {"a1": ("white", "rook")}
