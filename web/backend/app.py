import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Must run before the local imports below - gateway_client/move_orchestrator/
# stockfish_client read API keys and URLs from the environment at import
# time (module-level constants), so .env has to be loaded first or those
# values would be captured empty.
load_dotenv()

from bindings import load_bindings, save_bindings  # noqa: E402
from chat_feed import dedupe_events, load_chat_events, run_chat_feed  # noqa: E402
from excluded_roles import load_excluded_roles, save_excluded_roles  # noqa: E402
from gateway_client import get_robots, send_chat_message  # noqa: E402
from match_clock import (  # noqa: E402
    end_match,
    mark_turn_done,
    pause_match,
    resume_match,
    start_match,
    sync_active_color,
)
from move_orchestrator import execute_move, propose_and_execute_move  # noqa: E402
from state import ALL_ROLES, apply_move, delete_piece, initial_board, rebind_role  # noqa: E402
from stockfish_client import run_continuous_analysis, start_engine, stop_engine  # noqa: E402
from ws_manager import ConnectionManager  # noqa: E402

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
    "chat_events": dedupe_events(load_chat_events()),
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
    "orchestrator_log": [],
    "pending_robot_moves": {},
    "robot_alerts": [],
    "last_move": None,
    "captured_pieces": [],
    "move_limit_sec": 5 * 60,
    "match_limit_sec": 2 * 60 * 60,
    "excluded_roles": load_excluded_roles(),
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
    app_state["last_move"] = None
    app_state["captured_pieces"] = []
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


class ExcludeRoleRequest(BaseModel):
    role: str
    excluded: bool


@app.post("/api/bindings/exclude")
async def set_role_excluded(payload: ExcludeRoleRequest) -> dict:
    """Marks/unmarks a piece role as excluded from moves - e.g. its robot is
    known broken (stuck kill switch, offline for the match). Excluded roles
    are skipped by the AI orchestrator's proposals and refused by manual
    dispatch (see move_orchestrator.py), but stay on the board and can still
    be repositioned via "correct" mode - this is about not commanding the
    robot, not about hiding the piece."""

    if payload.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail=f"неизвестная роль: {payload.role}")

    excluded = set(app_state.get("excluded_roles", []))
    if payload.excluded:
        excluded.add(payload.role)
    else:
        excluded.discard(payload.role)
    app_state["excluded_roles"] = sorted(excluded)
    save_excluded_roles(app_state["excluded_roles"])

    await manager.broadcast(app_state)
    return app_state


@app.post("/api/move")
async def move(body: dict) -> dict:
    payload = MoveRequest.from_body(body)

    if app_state["mode"] == "manual":
        # execute_move also dispatches the real robot command for a bound
        # piece - shared with the AI orchestrator so both paths execute a
        # move identically (see move_orchestrator.py).
        result = execute_move(app_state, payload.from_square, payload.to_square)
    else:
        new_board, result = apply_move(
            app_state["board"],
            app_state["mode"],
            payload.from_square,
            payload.to_square,
            our_color=app_state["our_color"],
        )
        if result["ok"]:
            app_state["board"] = new_board
            app_state["side_to_move"] = (
                "black" if new_board[payload.to_square]["color"] == "white" else "white"
            )
            app_state["last_move"] = {
                "from": payload.from_square,
                "to": payload.to_square,
                "color": new_board[payload.to_square]["color"],
                "piece": new_board[payload.to_square]["piece"],
            }
            if result.get("captured_piece"):
                app_state.setdefault("captured_pieces", []).append(result["captured_piece"])
            if app_state["mode"] == "view":
                # "correct" is a pure board-state fix (drag either side
                # freely, no legality/turn check) - not a real move, so it
                # must not silently advance the judge-controlled clock.
                # "view" (recording the opponent's actual move) and
                # "manual" (handled inside execute_move above) both do.
                app_state["match_clock"] = sync_active_color(
                    app_state["match_clock"], app_state["side_to_move"]
                )

    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    await manager.broadcast(app_state)
    return {"state": app_state, "result": result}


class DeletePieceRequest(BaseModel):
    square: str


@app.post("/api/delete-piece")
async def delete_piece_endpoint(payload: DeletePieceRequest) -> dict:
    new_board, result = delete_piece(
        app_state["board"], app_state["mode"], payload.square, our_color=app_state["our_color"]
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    app_state["board"] = new_board
    app_state.setdefault("captured_pieces", []).append(result["removed_piece"])

    await manager.broadcast(app_state)
    return {"state": app_state, "result": result}


@app.post("/api/orchestrator/propose-move")
async def propose_move() -> dict:
    return await propose_and_execute_move(app_state, manager.broadcast)


@app.post("/api/robot-alerts/{alert_id}/dismiss")
async def dismiss_robot_alert(alert_id: str) -> dict:
    app_state["robot_alerts"] = [
        alert for alert in app_state.get("robot_alerts", []) if alert["id"] != alert_id
    ]
    await manager.broadcast(app_state)
    return app_state


class ChatSendRequest(BaseModel):
    text: str


@app.post("/api/chat/send")
async def send_chat(payload: ChatSendRequest) -> dict:
    return send_chat_message(payload.text)


@app.post("/api/chat/clear")
async def clear_chat() -> dict:
    # Clears only the in-memory/displayed feed, not the on-disk
    # chat_history.jsonl log (that's the permanent match record, by design -
    # see chat_feed.py). A backend restart or Gateway resync will reload the
    # full history from disk/Gateway again, so this is a "declutter my
    # current view" action, not a permanent delete.
    app_state["chat_events"] = []
    await manager.broadcast(app_state)
    return app_state


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


class MatchLimitsRequest(BaseModel):
    move_limit_sec: int
    match_limit_sec: int


@app.post("/api/match/limits")
async def set_match_limits(payload: MatchLimitsRequest) -> dict:
    if payload.move_limit_sec <= 0 or payload.match_limit_sec <= 0:
        raise HTTPException(status_code=422, detail="лимиты должны быть положительными")

    app_state["move_limit_sec"] = payload.move_limit_sec
    app_state["match_limit_sec"] = payload.match_limit_sec
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


class NoCacheStaticFiles(StaticFiles):
    """Frontend files are actively edited during development and re-served
    from the same URLs on every change - without this, browsers can serve a
    stale cached board.js/styles.css/index.html after a plain reload (no
    explicit Cache-Control header means some browsers apply heuristic
    caching), which looks indistinguishable from a real layout/JS bug."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
