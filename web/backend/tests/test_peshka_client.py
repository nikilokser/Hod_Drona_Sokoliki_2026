import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import peshka_client


# --- classify_pawn_move: white --------------------------------------------------------


def test_classify_white_single_push():
    assert peshka_client.classify_pawn_move("e2", "e3", "white") == ("forward", 1)


def test_classify_white_double_push():
    assert peshka_client.classify_pawn_move("e2", "e4", "white") == ("forward", 2)


def test_classify_white_diagonal_capture_right():
    # increasing file (e->f) is the robot's right while facing white's
    # forward direction.
    assert peshka_client.classify_pawn_move("e4", "f5", "white") == ("diagonal", "R")


def test_classify_white_diagonal_capture_left():
    assert peshka_client.classify_pawn_move("e4", "d5", "white") == ("diagonal", "L")


# --- classify_pawn_move: black (mirrored L/R, forward = decreasing rank) --------------


def test_classify_black_single_push():
    assert peshka_client.classify_pawn_move("e7", "e6", "black") == ("forward", 1)


def test_classify_black_double_push():
    assert peshka_client.classify_pawn_move("e7", "e5", "black") == ("forward", 2)


def test_classify_black_diagonal_capture_right():
    # Black physically faces the opposite way down the board, so increasing
    # file is its LEFT, not its right - mirrored from white.
    assert peshka_client.classify_pawn_move("e5", "f4", "black") == ("diagonal", "L")


def test_classify_black_diagonal_capture_left():
    assert peshka_client.classify_pawn_move("e5", "d4", "black") == ("diagonal", "R")


# --- classify_pawn_move: shapes no real pawn move can take ----------------------------


def test_classify_rejects_sideways_move():
    assert peshka_client.classify_pawn_move("e4", "f4", "white") is None


def test_classify_rejects_backward_move():
    # e4->e5 is forward for white but backward for black (black's forward
    # direction is decreasing rank).
    assert peshka_client.classify_pawn_move("e4", "e5", "black") is None


def test_classify_rejects_triple_forward():
    assert peshka_client.classify_pawn_move("e2", "e5", "white") is None


def test_classify_rejects_diagonal_two_cells():
    assert peshka_client.classify_pawn_move("e2", "g4", "white") is None


def test_classify_rejects_knight_shaped_move():
    assert peshka_client.classify_pawn_move("b1", "c3", "white") is None


# --- pawn_move_text --------------------------------------------------------


def test_pawn_move_text_forward_one():
    assert peshka_client.pawn_move_text(("forward", 1)) == "вперёд на одну клетку"


def test_pawn_move_text_forward_two():
    assert peshka_client.pawn_move_text(("forward", 2)) == "вперёд на две клетки"


def test_pawn_move_text_diagonal_left():
    assert peshka_client.pawn_move_text(("diagonal", "L")) == "по диагонали влево"


def test_pawn_move_text_diagonal_right():
    assert peshka_client.pawn_move_text(("diagonal", "R")) == "по диагонали вправо"
