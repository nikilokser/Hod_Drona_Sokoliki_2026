from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bindings import load_bindings, save_bindings
from gateway_client import get_robots, send_fly_command
from state import ALL_ROLES, apply_move, initial_board, rebind_role
from ws_manager import ConnectionManager

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI()
manager = ConnectionManager()

_initial_bindings = load_bindings()
app_state: dict = {
    "board": initial_board("white", _initial_bindings),
    "mode": "view",
    "our_color": "white",
    "bindings": _initial_bindings,
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
    new_board, result = apply_move(
        app_state["board"], app_state["mode"], payload.from_square, payload.to_square
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    app_state["board"] = new_board

    if app_state["mode"] == "manual" and result["moved_robot_id"]:
        result["gateway_result"] = send_fly_command(
            result["moved_robot_id"], payload.to_square
        )

    await manager.broadcast(app_state)
    return {"state": app_state, "result": result}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket, app_state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
