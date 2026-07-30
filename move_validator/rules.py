"""Move legality, check/checkmate/stalemate.

Simplified chess rules per the competition regulation: no castling, no en
passant, no promotion, no repetition/50-move rule - none of those are
implemented as move types, so attempting them is simply rejected by the
geometry checks below (see the design doc for details).
"""

from __future__ import annotations

from .board import (
    ALL_SQUARES,
    file_rank_to_square,
    is_valid_square,
    opposite_color,
    square_to_file_rank,
)

PIECE_RU_GENITIVE = {
    "king": "короля",
    "queen": "ферзя",
    "rook": "ладьи",
    "bishop": "слона",
    "knight": "коня",
    "pawn": "пешки",
}

COLOR_RU_GENITIVE_PLURAL = {"white": "белых", "black": "чёрных"}


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _illegal(reason: str) -> dict:
    return {"legal": False, "reason": reason, "is_capture": False, "captured": None}


def _path_clear(board: dict, from_sq: str, to_sq: str) -> bool:
    ff, fr = square_to_file_rank(from_sq)
    tf, tr = square_to_file_rank(to_sq)
    step_f, step_r = _sign(tf - ff), _sign(tr - fr)
    f, r = ff + step_f, fr + step_r
    while (f, r) != (tf, tr):
        if file_rank_to_square(f, r) in board:
            return False
        f += step_f
        r += step_r
    return True


def _validate_geometry(board: dict, color: str, piece: str, from_sq: str, to_sq: str):
    """Pseudo-legal move geometry: bounds/occupancy of `to` already checked
    by the caller. Returns (ok, reason)."""

    ff, fr = square_to_file_rank(from_sq)
    tf, tr = square_to_file_rank(to_sq)
    df, dr = tf - ff, tr - fr
    target = board.get(to_sq)

    if piece == "king":
        if max(abs(df), abs(dr)) != 1:
            return False, "Король может ходить только на одну клетку"
        return True, None

    if piece == "knight":
        if (abs(df), abs(dr)) not in {(1, 2), (2, 1)}:
            return False, "Конь так не ходит"
        return True, None

    if piece == "rook":
        if not (df == 0 or dr == 0):
            return False, "Ладья не может ходить по диагонали"
        if not _path_clear(board, from_sq, to_sq):
            return False, "Путь до клетки перекрыт другой фигурой"
        return True, None

    if piece == "bishop":
        if abs(df) != abs(dr):
            return False, "Слон ходит только по диагонали"
        if not _path_clear(board, from_sq, to_sq):
            return False, "Путь до клетки перекрыт другой фигурой"
        return True, None

    if piece == "queen":
        if not (df == 0 or dr == 0 or abs(df) == abs(dr)):
            return False, "Ферзь так не ходит"
        if not _path_clear(board, from_sq, to_sq):
            return False, "Путь до клетки перекрыт другой фигурой"
        return True, None

    if piece == "pawn":
        direction = 1 if color == "white" else -1
        start_rank = 2 if color == "white" else 7
        if df == 0:
            if dr == direction:
                if target is not None:
                    return False, "Пешка не может ходить вперёд на занятую клетку"
                return True, None
            if dr == 2 * direction and fr == start_rank:
                mid_sq = file_rank_to_square(ff, fr + direction)
                if mid_sq in board or target is not None:
                    return False, "Путь до клетки перекрыт другой фигурой"
                return True, None
            return False, "Пешка так не ходит"
        if abs(df) == 1 and dr == direction:
            if target is None:
                return False, "Пешка может ходить по диагонали только при взятии"
            return True, None
        return False, "Пешка так не ходит"

    return False, f"Неизвестный тип фигуры: {piece}"


def _attacks(board: dict, attacker_sq: str, target_sq: str) -> bool:
    """Does the piece on attacker_sq threaten target_sq? Used for check
    detection - unlike _validate_geometry, a pawn's attack pattern is
    diagonal regardless of whether target_sq is actually occupied."""

    color, piece = board[attacker_sq]
    ff, fr = square_to_file_rank(attacker_sq)
    tf, tr = square_to_file_rank(target_sq)
    df, dr = tf - ff, tr - fr

    if piece == "king":
        return max(abs(df), abs(dr)) == 1
    if piece == "knight":
        return (abs(df), abs(dr)) in {(1, 2), (2, 1)}
    if piece == "rook":
        return (df == 0 or dr == 0) and (df != 0 or dr != 0) and _path_clear(board, attacker_sq, target_sq)
    if piece == "bishop":
        return abs(df) == abs(dr) and df != 0 and _path_clear(board, attacker_sq, target_sq)
    if piece == "queen":
        straight_or_diagonal = df == 0 or dr == 0 or abs(df) == abs(dr)
        return straight_or_diagonal and (df != 0 or dr != 0) and _path_clear(board, attacker_sq, target_sq)
    if piece == "pawn":
        direction = 1 if color == "white" else -1
        return abs(df) == 1 and dr == direction
    return False


def is_in_check(board_state: dict, color: str) -> bool:
    board = board_state["board"]
    king_sq = next(
        (sq for sq, (c, p) in board.items() if c == color and p == "king"), None
    )
    if king_sq is None:
        return False
    attacker_color = opposite_color(color)
    return any(
        _attacks(board, sq, king_sq)
        for sq, (c, _p) in board.items()
        if c == attacker_color
    )


def apply_move(board_state: dict, move: dict) -> dict:
    """Apply an already-validated move. Behavior for an illegal move is
    undefined - callers must call validate_move first."""

    board = dict(board_state["board"])
    from_sq, to_sq = move["from"], move["to"]
    moving_piece = board.pop(from_sq)
    board[to_sq] = moving_piece

    return {
        "board": board,
        "side_to_move": opposite_color(board_state["side_to_move"]),
    }


def validate_move(board_state: dict, move: dict) -> dict:
    board = board_state["board"]
    side = board_state["side_to_move"]
    from_sq, to_sq, claimed_piece = move["from"], move["to"], move["piece"]

    for sq in (from_sq, to_sq):
        if not is_valid_square(sq):
            return _illegal(f"Некорректная клетка: {sq}")

    if from_sq == to_sq:
        return _illegal("Исходная и целевая клетка совпадают")

    occupant = board.get(from_sq)
    if occupant is None:
        return _illegal(f"На клетке {from_sq} нет фигуры")

    actual_color, actual_piece = occupant
    if actual_color != side:
        return _illegal(
            f"Сейчас ход {COLOR_RU_GENITIVE_PLURAL[side]}, "
            f"а на клетке {from_sq} стоит фигура другого цвета"
        )
    if actual_piece != claimed_piece:
        return _illegal(
            f"На клетке {from_sq} нет {PIECE_RU_GENITIVE[claimed_piece]} — там другая фигура"
        )

    target = board.get(to_sq)
    if target is not None and target[0] == side:
        return _illegal(f"На клетке {to_sq} уже стоит своя фигура")

    ok, reason = _validate_geometry(board, side, actual_piece, from_sq, to_sq)
    if not ok:
        return _illegal(reason)

    new_state = apply_move(board_state, move)
    if is_in_check(new_state, side):
        return _illegal("Этот ход оставляет вашего короля под шахом")

    return {
        "legal": True,
        "reason": None,
        "is_capture": target is not None,
        "captured": target[1] if target is not None else None,
    }


def _all_legal_moves(board_state: dict, color: str):
    for from_sq, (c, piece) in list(board_state["board"].items()):
        if c != color:
            continue
        for to_sq in ALL_SQUARES:
            if to_sq == from_sq:
                continue
            move = {"piece": piece, "from": from_sq, "to": to_sq}
            if validate_move(board_state, move)["legal"]:
                yield move


def is_checkmate(board_state: dict) -> bool:
    color = board_state["side_to_move"]
    if not is_in_check(board_state, color):
        return False
    return next(_all_legal_moves(board_state, color), None) is None


def is_stalemate(board_state: dict) -> bool:
    color = board_state["side_to_move"]
    if is_in_check(board_state, color):
        return False
    return next(_all_legal_moves(board_state, color), None) is None
