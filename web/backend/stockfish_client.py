"""Position analysis via a locally installed Stockfish binary.

This is an analysis/practice tool only - the regulation forbids chess
engines from choosing moves during a real match (see CLAUDE.md). The
double-confirmation gate lives in app.py/the frontend; this module just
does the FEN conversion and talks to the engine.

Stockfish itself is NOT bundled in this repo - install separately
(e.g. `brew install stockfish`) and point STOCKFISH_PATH at it if it's
not on PATH.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable

import chess
import chess.engine

LOGGER = logging.getLogger(__name__)

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "stockfish")
DEFAULT_MOVETIME_MS = 1000

FILES = "abcdefgh"
PIECE_TO_FEN = {
    "king": "k",
    "queen": "q",
    "rook": "r",
    "bishop": "b",
    "knight": "n",
    "pawn": "p",
}

_engine: chess.engine.UciProtocol | None = None


def _has_one_king_per_side(board: dict) -> bool:
    white_kings = sum(1 for p in board.values() if p["color"] == "white" and p["piece"] == "king")
    black_kings = sum(1 for p in board.values() if p["color"] == "black" and p["piece"] == "king")
    return white_kings == 1 and black_kings == 1


def board_to_fen(board: dict, side_to_move: str, fullmove_number: int = 1) -> str:
    """Convert our board dict ({"e2": {"color": "white", "piece": "pawn"}})
    into a FEN string. Castling/en-passant are always "-" (not part of our
    simplified rules) and the halfmove clock is always "0" (we don't track
    it, and it doesn't affect Stockfish's evaluation) - but fullmove_number
    should be the real move count (see app_state["fullmove_number"] in
    scoring.py), not left at the "1" default: the AI orchestrator's prompt
    includes this FEN, and a wrong/stuck move number there was observed
    live 2026-08-02 misleading the model about how far into the game it
    was."""

    rows = []
    for rank in range(8, 0, -1):
        row = ""
        empty_run = 0
        for file_letter in FILES:
            square = f"{file_letter}{rank}"
            occupant = board.get(square)
            if occupant is None:
                empty_run += 1
                continue
            if empty_run:
                row += str(empty_run)
                empty_run = 0
            letter = PIECE_TO_FEN[occupant["piece"]]
            row += letter.upper() if occupant["color"] == "white" else letter
        if empty_run:
            row += str(empty_run)
        rows.append(row)

    placement = "/".join(rows)
    side_letter = "w" if side_to_move == "white" else "b"
    return f"{placement} {side_letter} - - 0 {fullmove_number}"


async def start_engine() -> None:
    global _engine
    try:
        _transport, engine = await chess.engine.popen_uci(STOCKFISH_PATH)
        _engine = engine
    except Exception:
        LOGGER.warning("Stockfish binary not available at %r", STOCKFISH_PATH)
        _engine = None


async def stop_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.quit()
        _engine = None


async def get_best_move(
    board: dict,
    side_to_move: str,
    movetime_ms: int = DEFAULT_MOVETIME_MS,
    fullmove_number: int = 1,
) -> dict:
    if _engine is None:
        return {"ok": False, "error": "Stockfish не установлен или не запущен"}

    if not _has_one_king_per_side(board):
        # Manual drag-and-drop can capture any piece, including a king -
        # feeding that position to the engine produces nonsense/errors.
        return {"ok": False, "error": "На доске должно быть по одному королю каждого цвета"}

    fen = board_to_fen(board, side_to_move, fullmove_number)
    try:
        chess_board = chess.Board(fen)
    except ValueError as exc:
        return {"ok": False, "error": f"Некорректная позиция: {exc}"}

    try:
        result = await _engine.play(
            chess_board,
            chess.engine.Limit(time=movetime_ms / 1000),
            info=chess.engine.INFO_SCORE,
        )
    except chess.engine.EngineError as exc:
        return {"ok": False, "error": str(exc)}

    if result.move is None:
        return {"ok": False, "error": "Нет доступных ходов (мат или пат)"}

    score = None
    if result.info and "score" in result.info:
        score = result.info["score"].white().score(mate_score=100000)

    return {
        "ok": True,
        "from": chess.square_name(result.move.from_square),
        "to": chess.square_name(result.move.to_square),
        "score": score,
    }


CONTINUOUS_MOVETIME_MS = 500
DISABLED_POLL_INTERVAL_SEC = 0.5


def apply_analysis_result(app_state: dict, result: dict | None) -> bool:
    """Updates app_state["stockfish_analysis"] if it actually changed.
    Returns True when it changed (caller should broadcast)."""

    if result == app_state.get("stockfish_analysis"):
        return False
    app_state["stockfish_analysis"] = result
    return True


async def run_continuous_analysis(
    app_state: dict, broadcast: Callable[[dict], Awaitable[None]]
) -> None:
    """Background task: while stockfish_enabled is on, keeps re-analysing
    the current position for whoever is on move and pushing updates.
    A real analysis call already takes ~CONTINUOUS_MOVETIME_MS, which paces
    the loop naturally - but get_best_move can also return an error
    synchronously with no await at all (engine not running, or an invalid
    board with != 1 king per side from manual drag-and-drop testing). Without
    an unconditional sleep, that turns this into a tight loop that pegs a CPU
    core and starves the asyncio event loop for the whole process - observed
    live 2026-08-02 as the actual cause of "the model doesn't respond" and
    "chat doesn't always arrive" (both are just other coroutines never
    getting scheduled)."""

    while True:
        if app_state.get("stockfish_enabled"):
            result = await get_best_move(
                app_state["board"],
                app_state["side_to_move"],
                movetime_ms=CONTINUOUS_MOVETIME_MS,
                fullmove_number=app_state.get("fullmove_number", 1),
            )
        else:
            result = None

        if apply_analysis_result(app_state, result):
            await broadcast(app_state)

        if result is None or not result.get("ok"):
            await asyncio.sleep(DISABLED_POLL_INTERVAL_SEC)
