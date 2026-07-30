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

import logging
import os

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


def board_to_fen(board: dict, side_to_move: str) -> str:
    """Convert our board dict ({"e2": {"color": "white", "piece": "pawn"}})
    into a FEN string. Castling/en-passant are always "-" (not part of our
    simplified rules), move counters are fixed placeholders - none of that
    affects Stockfish's evaluation of the given position."""

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
    return f"{placement} {side_letter} - - 0 1"


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
    board: dict, side_to_move: str, movetime_ms: int = DEFAULT_MOVETIME_MS
) -> dict:
    if _engine is None:
        return {"ok": False, "error": "Stockfish не установлен или не запущен"}

    fen = board_to_fen(board, side_to_move)
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
