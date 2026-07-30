import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import chess
import chess.engine

import stockfish_client
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


def test_board_to_fen_starting_position():
    board = initial_board("white", BINDINGS)
    fen = stockfish_client.board_to_fen(board, "white")
    assert fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1"
    # must parse as a valid chess.Board
    parsed = chess.Board(fen)
    assert len(list(parsed.legal_moves)) == 20


def test_board_to_fen_black_to_move():
    board = initial_board("white", BINDINGS)
    fen = stockfish_client.board_to_fen(board, "black")
    assert fen.split(" ")[1] == "b"


def test_board_to_fen_sparse_position():
    board = {
        "e1": {"color": "white", "piece": "king"},
        "e8": {"color": "black", "piece": "king"},
        "a1": {"color": "white", "piece": "rook"},
    }
    fen = stockfish_client.board_to_fen(board, "white")
    assert fen == "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"


@pytest.mark.asyncio
async def test_get_best_move_without_engine_returns_error(monkeypatch):
    monkeypatch.setattr(stockfish_client, "_engine", None)
    board = initial_board("white", BINDINGS)

    result = await stockfish_client.get_best_move(board, "white")

    assert result["ok"] is False
    assert "не установлен" in result["error"]


@pytest.mark.asyncio
async def test_get_best_move_success(monkeypatch):
    fake_move = chess.Move.from_uci("e2e4")
    fake_score = MagicMock()
    fake_score.white.return_value.score.return_value = 30
    fake_result = MagicMock(move=fake_move, info={"score": fake_score})

    fake_engine = MagicMock()
    fake_engine.play = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(stockfish_client, "_engine", fake_engine)

    board = initial_board("white", BINDINGS)
    result = await stockfish_client.get_best_move(board, "white")

    assert result == {"ok": True, "from": "e2", "to": "e4", "score": 30}


@pytest.mark.asyncio
async def test_get_best_move_engine_error_does_not_raise(monkeypatch):
    fake_engine = MagicMock()
    fake_engine.play = AsyncMock(side_effect=chess.engine.EngineError("boom"))
    monkeypatch.setattr(stockfish_client, "_engine", fake_engine)

    board = initial_board("white", BINDINGS)
    result = await stockfish_client.get_best_move(board, "white")

    assert result["ok"] is False


@pytest.mark.asyncio
async def test_get_best_move_rejects_board_without_both_kings(monkeypatch):
    fake_engine = MagicMock()
    fake_engine.play = AsyncMock()
    monkeypatch.setattr(stockfish_client, "_engine", fake_engine)

    board = initial_board("white", BINDINGS)
    del board["e1"]  # white king captured via manual drag-and-drop

    result = await stockfish_client.get_best_move(board, "white")

    assert result["ok"] is False
    assert "королю" in result["error"]
    fake_engine.play.assert_not_called()


def test_apply_analysis_result_changes_and_signals_broadcast():
    app_state = {}
    changed = stockfish_client.apply_analysis_result(app_state, {"from": "e2", "to": "e4"})
    assert changed is True
    assert app_state["stockfish_analysis"] == {"from": "e2", "to": "e4"}


def test_apply_analysis_result_no_change_when_identical():
    app_state = {"stockfish_analysis": {"from": "e2", "to": "e4"}}
    changed = stockfish_client.apply_analysis_result(app_state, {"from": "e2", "to": "e4"})
    assert changed is False


def test_apply_analysis_result_handles_none():
    app_state = {"stockfish_analysis": {"from": "e2", "to": "e4"}}
    changed = stockfish_client.apply_analysis_result(app_state, None)
    assert changed is True
    assert app_state["stockfish_analysis"] is None
