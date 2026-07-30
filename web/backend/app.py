import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bindings import load_bindings, save_bindings
from chat_feed import load_chat_events, run_chat_feed
from gateway_client import get_robots, send_chat_message, send_fly_command
from match_clock import end_match, mark_turn_done, pause_match, resume_match, start_match
from state import ALL_ROLES, apply_move, initial_board, rebind_role
from stockfish_client import run_continuous_analysis, start_engine, stop_engine
from ws_manager import ConnectionManager

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    chat_task = asyncio.create_task(run_chat_feed(app_state, manager.broadcast))
    await start_engine()
    analysis_task = asyncio.create_task(run_continuous_analysis(app_state, manager.broadcast))
    try:
        yield
    finally:
        chat_task.cancel()
        analysis_task.cancel()
        await stop_engine()


app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()

_initial_bindings = load_bindings()
app_state: dict = {
    "board": initial_board("white", _initial_bindings),
    "mode": "view",
    "our_color": "white",
    "bindings": _initial_bindings,
    "chat_events": load_chat_events(),
    "match_clock": {
        "status": "idle",
        "match_started_at": None,
        "active_color": None,
        "move_started_at": None,
        "frozen_at": None,
    },
    "side_to_move": "white",
    "stockfish_enabled": False,
    "stockfish_analysis": None,
}


class ModeRequest(BaseModel):
    mode: Literal["view", "correct", "manual"]


class ColorRequest(BaseModel):
    color: Literal["white", "black"]


class MoveRequest(BaseModel):
    # "from" is a Python keyword, so the request body is read as a raw dict
    # instead of aliasing a "from_" field - simpler than fighting pydantic
    # aliasing over a reserved word.
    from_square: str
    to_square: str

    @staticmethod
    def from_body(body: dict) -> "MoveRequest":
        try:
            return MoveRequest(from_square=body["from"], to_square=body["to"])
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"отсутствует поле {exc}"
            ) from exc


@app.get("/api/state")
async def get_state() -> dict:
    return app_state


@app.post("/api/mode")
async def set_mode(payload: ModeRequest) -> dict:
    app_state["mode"] = payload.mode
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/our-color")
async def set_our_color(payload: ColorRequest) -> dict:
    app_state["our_color"] = payload.color
    app_state["board"] = initial_board(payload.color, app_state["bindings"])
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/reset")
async def reset_board() -> dict:
    app_state["board"] = initial_board(app_state["our_color"], app_state["bindings"])
    await manager.broadcast(app_state)
    return app_state


class BindingRequest(BaseModel):
    role: str
    robot_id: str


@app.get("/api/robots")
async def list_robots() -> dict:
    return get_robots()


@app.post("/api/bindings")
async def set_binding(payload: BindingRequest) -> dict:
    if payload.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail=f"неизвестная роль: {payload.role}")

    app_state["bindings"][payload.role] = payload.robot_id
    save_bindings(app_state["bindings"])
    app_state["board"] = rebind_role(app_state["board"], payload.role, payload.robot_id)

    await manager.broadcast(app_state)
    return app_state


@app.post("/api/move")
async def move(body: dict) -> dict:
    payload = MoveRequest.from_body(body)

    if app_state["mode"] == "manual":
        moving_piece = app_state["board"].get(payload.from_square)
        if moving_piece and moving_piece["color"] != app_state["side_to_move"]:
            # Manual mode dispatches real robot commands - block moving the
            # wrong side outright instead of silently sending one. "correct"
            # mode (unrestricted) is the escape hatch for fixing the board.
            raise HTTPException(status_code=400, detail="Сейчас не ваш ход")

    new_board, result = apply_move(
        app_state["board"], app_state["mode"], payload.from_square, payload.to_square
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    app_state["board"] = new_board
    app_state["side_to_move"] = "black" if new_board[payload.to_square]["color"] == "white" else "white"

    if app_state["mode"] == "manual" and result["moved_robot_id"]:
        result["gateway_result"] = send_fly_command(
            result["moved_robot_id"], payload.to_square
        )

    await manager.broadcast(app_state)
    return {"state": app_state, "result": result}


class ChatSendRequest(BaseModel):
    text: str


@app.post("/api/chat/send")
async def send_chat(payload: ChatSendRequest) -> dict:
    return send_chat_message(payload.text)


@app.post("/api/match/start")
async def start_match_clock() -> dict:
    app_state["match_clock"] = start_match()
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/match/turn-done")
async def turn_done() -> dict:
    if app_state["match_clock"]["status"] != "running":
        raise HTTPException(status_code=400, detail="матч ещё не начат")

    app_state["match_clock"] = mark_turn_done(app_state["match_clock"])
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/match/pause")
async def pause_match_clock() -> dict:
    if app_state["match_clock"]["status"] != "running":
        raise HTTPException(status_code=400, detail="матч сейчас не идёт")

    app_state["match_clock"] = pause_match(app_state["match_clock"])
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/match/resume")
async def resume_match_clock() -> dict:
    if app_state["match_clock"]["status"] != "paused":
        raise HTTPException(status_code=400, detail="матч не на паузе")

    app_state["match_clock"] = resume_match(app_state["match_clock"])
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/match/end")
async def end_match_clock() -> dict:
    if app_state["match_clock"]["status"] not in ("running", "paused"):
        raise HTTPException(status_code=400, detail="матч не идёт")

    app_state["match_clock"] = end_match(app_state["match_clock"])
    await manager.broadcast(app_state)
    return app_state


@app.post("/api/side-to-move")
async def set_side_to_move(payload: ColorRequest) -> dict:
    app_state["side_to_move"] = payload.color
    await manager.broadcast(app_state)
    return app_state


class StockfishEnableRequest(BaseModel):
    enabled: bool


@app.post("/api/stockfish/enable")
async def set_stockfish_enabled(payload: StockfishEnableRequest) -> dict:
    app_state["stockfish_enabled"] = payload.enabled
    await manager.broadcast(app_state)
    return app_state


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket, app_state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
