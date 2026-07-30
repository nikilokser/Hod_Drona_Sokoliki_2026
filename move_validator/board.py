"""Board data and algebraic-notation helpers.

See docs/superpowers/specs/2026-07-30-move-validator-design.md for the
full design. board_state format:
    board_state = {
        "board": {"e2": ("white", "pawn"), ...},  # only occupied squares
        "side_to_move": "white" | "black",
    }
"""

from __future__ import annotations

FILES = "abcdefgh"
PIECE_TYPES = ("king", "queen", "rook", "bishop", "knight", "pawn")

ALL_SQUARES = [f"{file}{rank}" for rank in range(1, 9) for file in FILES]

_BACK_RANK_PIECES = ["rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook"]


def is_valid_square(square: str) -> bool:
    return (
        isinstance(square, str)
        and len(square) == 2
        and square[0] in FILES
        and square[1] in "12345678"
    )


def square_to_file_rank(square: str) -> tuple[int, int]:
    return FILES.index(square[0]), int(square[1])


def file_rank_to_square(file_index: int, rank: int) -> str:
    return f"{FILES[file_index]}{rank}"


def opposite_color(color: str) -> str:
    return "black" if color == "white" else "white"


def initial_board() -> dict:
    """Standard starting position, full 16 vs 16 set, white to move."""

    board: dict[str, tuple[str, str]] = {}
    for file_index, piece in enumerate(_BACK_RANK_PIECES):
        board[file_rank_to_square(file_index, 1)] = ("white", piece)
        board[file_rank_to_square(file_index, 8)] = ("black", piece)
    for file_index in range(8):
        board[file_rank_to_square(file_index, 2)] = ("white", "pawn")
        board[file_rank_to_square(file_index, 7)] = ("black", "pawn")

    return {"board": board, "side_to_move": "white"}
