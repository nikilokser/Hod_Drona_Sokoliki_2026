"""Pure board/state logic: no HTTP, no globals, no I/O.

Board format matches the move_validator design doc so a validator can be
plugged in later without changing this data shape:
    board[square] = {"color": "white"|"black", "piece": "king"|"queen"|"rook"|
                      "bishop"|"knight"|"pawn", "robot_id": "drone-01",
                      "role": "king"}
"robot_id" and "role" are present only on squares occupied by our own,
bound pieces. "role" is a stable identifier for that piece instance
("king", "bishop_1", "pawn_5", ...) that travels with the piece for the
whole match - it is what lets bindings be edited at runtime (see
rebind_role) even after pieces have moved off their starting squares.

bindings maps a piece role ("king", "queen", "bishop_1", "bishop_2",
"knight_1", "knight_2", "rook_1", "rook_2", "pawn_1".."pawn_8") to a
robot_id. "_1" is the a-file/queenside instance, "_2" is the h-file/
kingside instance; pawn_1.."pawn_8" run a-file to h-file.
"""

from __future__ import annotations

FILES = "abcdefgh"

# (file_index, role) for the back rank, a-file to h-file.
BACK_RANK = [
    (0, "rook_1"),
    (1, "knight_1"),
    (2, "bishop_1"),
    (3, "queen"),
    (4, "king"),
    (5, "bishop_2"),
    (6, "knight_2"),
    (7, "rook_2"),
]

ROLE_TO_PIECE = {
    "king": "king",
    "queen": "queen",
    "rook_1": "rook",
    "rook_2": "rook",
    "bishop_1": "bishop",
    "bishop_2": "bishop",
    "knight_1": "knight",
    "knight_2": "knight",
}

ALL_ROLES = [role for _file_index, role in BACK_RANK] + [
    f"pawn_{i}" for i in range(1, 9)
]


def _square(file_index: int, rank: int) -> str:
    return f"{FILES[file_index]}{rank}"


def _opposite(color: str) -> str:
    return "black" if color == "white" else "white"


def initial_board(our_color: str, bindings: dict[str, str]) -> dict:
    """Standard starting position for both sides (16 + 16 pieces).

    Squares belonging to our_color get "robot_id" from bindings; the other
    side's squares never get a robot_id.
    """

    board: dict[str, dict] = {}
    their_color = _opposite(our_color)
    our_back_rank = 1 if our_color == "white" else 8
    our_pawn_rank = 2 if our_color == "white" else 7
    their_back_rank = 8 if our_color == "white" else 1
    their_pawn_rank = 7 if our_color == "white" else 2

    for file_index, role in BACK_RANK:
        piece = ROLE_TO_PIECE[role]
        board[_square(file_index, our_back_rank)] = {
            "color": our_color,
            "piece": piece,
            "robot_id": bindings[role],
            "role": role,
        }
        board[_square(file_index, their_back_rank)] = {
            "color": their_color,
            "piece": piece,
        }

    for file_index in range(8):
        pawn_role = f"pawn_{file_index + 1}"
        board[_square(file_index, our_pawn_rank)] = {
            "color": our_color,
            "piece": "pawn",
            "robot_id": bindings[pawn_role],
            "role": pawn_role,
        }
        board[_square(file_index, their_pawn_rank)] = {
            "color": their_color,
            "piece": "pawn",
        }

    return board


# Reduced semifinal starting position (per the organizers' 2026-08-01 photo
# of the physical setup): one rook per side instead of two - white keeps
# the a-file rook (rook_1), black keeps the h-file rook (rook_2) - and only
# four pawns per side, c/d/e/f files (pawn_3..pawn_6 in our a-to-h
# numbering). Everything else matches the standard back rank. The final
# uses the full board (initial_board).
SEMIFINAL_ROOK_ROLE = {"white": "rook_1", "black": "rook_2"}
SEMIFINAL_PAWN_FILES = {3, 4, 5, 6}


def semifinal_initial_board(our_color: str, bindings: dict[str, str]) -> dict:
    board: dict[str, dict] = {}
    their_color = _opposite(our_color)
    our_back_rank = 1 if our_color == "white" else 8
    our_pawn_rank = 2 if our_color == "white" else 7
    their_back_rank = 8 if our_color == "white" else 1
    their_pawn_rank = 7 if our_color == "white" else 2

    def _rook_present(role: str, color: str) -> bool:
        return role not in ("rook_1", "rook_2") or role == SEMIFINAL_ROOK_ROLE[color]

    for file_index, role in BACK_RANK:
        piece = ROLE_TO_PIECE[role]
        if _rook_present(role, our_color):
            board[_square(file_index, our_back_rank)] = {
                "color": our_color,
                "piece": piece,
                "robot_id": bindings[role],
                "role": role,
            }
        if _rook_present(role, their_color):
            board[_square(file_index, their_back_rank)] = {
                "color": their_color,
                "piece": piece,
            }

    for file_index in range(8):
        if (file_index + 1) not in SEMIFINAL_PAWN_FILES:
            continue
        pawn_role = f"pawn_{file_index + 1}"
        board[_square(file_index, our_pawn_rank)] = {
            "color": our_color,
            "piece": "pawn",
            "robot_id": bindings[pawn_role],
            "role": pawn_role,
        }
        board[_square(file_index, their_pawn_rank)] = {
            "color": their_color,
            "piece": "pawn",
        }

    return board


# Second reduced semifinal starting position (per the organizers'
# 2026-08-02 second photo) - same one-rook-per-side idea as
# semifinal_initial_board, but different pawn files (white a/d/e/f, black
# c/d/e/h - each keeps a pawn on its surviving rook's file, unlike
# variant 1's plain c-f block), AND black's king/queen are swapped from
# the usual squares (black king on the d-file, queen on the e-file) -
# confirmed intentional by the user 2026-08-02, not a misread of the
# photo. White's king/queen stay standard. "role" still tracks the piece
# itself (king's role is always "king", wherever it starts), only the
# SQUARE assignment differs here.
SEMIFINAL_V2_ROOK_ROLE = {"white": "rook_1", "black": "rook_2"}
SEMIFINAL_V2_PAWN_FILES = {"white": {1, 4, 5, 6}, "black": {3, 4, 5, 8}}


def _semifinal_v2_back_rank(color: str):
    for file_index, role in BACK_RANK:
        if color == "black":
            if role == "king":
                role = "queen"
            elif role == "queen":
                role = "king"
        if role in ("rook_1", "rook_2") and role != SEMIFINAL_V2_ROOK_ROLE[color]:
            continue
        yield file_index, role


def semifinal_v2_initial_board(our_color: str, bindings: dict[str, str]) -> dict:
    board: dict[str, dict] = {}
    their_color = _opposite(our_color)
    our_back_rank = 1 if our_color == "white" else 8
    our_pawn_rank = 2 if our_color == "white" else 7
    their_back_rank = 8 if our_color == "white" else 1
    their_pawn_rank = 7 if our_color == "white" else 2

    for file_index, role in _semifinal_v2_back_rank(our_color):
        board[_square(file_index, our_back_rank)] = {
            "color": our_color,
            "piece": ROLE_TO_PIECE[role],
            "robot_id": bindings[role],
            "role": role,
        }
    for file_index, role in _semifinal_v2_back_rank(their_color):
        board[_square(file_index, their_back_rank)] = {
            "color": their_color,
            "piece": ROLE_TO_PIECE[role],
        }

    for file_index in range(8):
        file_num = file_index + 1
        if file_num in SEMIFINAL_V2_PAWN_FILES[our_color]:
            pawn_role = f"pawn_{file_num}"
            board[_square(file_index, our_pawn_rank)] = {
                "color": our_color,
                "piece": "pawn",
                "robot_id": bindings[pawn_role],
                "role": pawn_role,
            }
        if file_num in SEMIFINAL_V2_PAWN_FILES[their_color]:
            board[_square(file_index, their_pawn_rank)] = {
                "color": their_color,
                "piece": "pawn",
            }

    return board


def rebind_role(board: dict, role: str, robot_id: str) -> dict:
    """Update the robot_id of whichever square currently holds the piece
    with this role. If that piece was captured and is no longer on the
    board, this is a no-op on the board (the caller is still responsible
    for updating the bindings mapping itself)."""

    new_board = dict(board)
    for square, occupant in board.items():
        if occupant.get("role") == role:
            new_board[square] = {**occupant, "robot_id": robot_id}
            break
    return new_board


def apply_move(
    board: dict, mode: str, from_sq: str, to_sq: str, our_color: str
) -> tuple[dict, dict]:
    """Apply a manual move, following the rules of the given field mode.

    Returns (new_board, result). result is
    {"ok": True, "captured": bool, "moved_robot_id": str | None} on success,
    or {"ok": False, "error": str} on failure (board is returned unchanged).

    No chess-legality checking here on purpose (see the web-board-design and
    move_validator design docs) - only the data-integrity invariant that two
    same-color pieces can never occupy the same square.

    "view" only allows moving the opponent's pieces (our_color is required
    to know which those are) - there is no automated tracking of the real
    board, so this is the only way to record the opponent's actual move
    while keeping our own displayed pieces protected from accidental drags
    during a live match.
    """

    if mode not in ("view", "correct", "manual"):
        return board, {"ok": False, "error": f"неизвестный режим: {mode}"}

    moving = board.get(from_sq)
    if moving is None:
        return board, {"ok": False, "error": f"на клетке {from_sq} нет фигуры"}

    if mode == "view" and moving["color"] == our_color:
        return board, {
            "ok": False,
            "error": "режим наблюдения — можно двигать только фигуры соперника",
        }

    if from_sq == to_sq:
        return board, {"ok": False, "error": "исходная и целевая клетка совпадают"}

    target = board.get(to_sq)
    if target is not None and target["color"] == moving["color"]:
        return board, {
            "ok": False,
            "error": f"на клетке {to_sq} уже стоит фигура того же цвета",
        }

    new_board = dict(board)
    del new_board[from_sq]
    new_board[to_sq] = moving

    return new_board, {
        "ok": True,
        "captured": target is not None,
        "captured_piece": {"color": target["color"], "piece": target["piece"]} if target else None,
        "moved_robot_id": moving.get("robot_id"),
    }


def delete_piece(board: dict, mode: str, square: str, our_color: str) -> tuple[dict, dict]:
    """Removes a piece from the board entirely - for recording a capture
    where the judge physically takes the piece off the field (no
    corresponding destination square the way apply_move has), or a
    board-state correction that needs a piece gone rather than relocated.

    Same mode permission rule as apply_move: "view" only allows removing
    the opponent's pieces (there is no automated tracking of the real
    board, so this doubles as the way to record an opponent's capture);
    "correct"/"manual" are unrestricted, matching apply_move's own rule.
    """

    if mode not in ("view", "correct", "manual"):
        return board, {"ok": False, "error": f"неизвестный режим: {mode}"}

    occupant = board.get(square)
    if occupant is None:
        return board, {"ok": False, "error": f"на клетке {square} нет фигуры"}

    if mode == "view" and occupant["color"] == our_color:
        return board, {
            "ok": False,
            "error": "режим наблюдения — можно удалять только фигуры соперника",
        }

    new_board = dict(board)
    del new_board[square]

    return new_board, {
        "ok": True,
        "removed_piece": {"color": occupant["color"], "piece": occupant["piece"]},
    }
