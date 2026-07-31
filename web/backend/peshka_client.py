"""HTTP client and chess-cell geometry for peshka (pawn) robots.

Pawns are NOT reachable through the organizers' Gateway (sverk_ai_communication_server) -
unlike drones/rovers, they have no MQTT bridge, only a direct HTTP API on
their own IP (see peshka-documentation.pdf). Two commands: forward(distance_mm)
(10-10000mm, forward only) and turn(angle_deg) (tank turn in place, only
|angle| in [10, 180]). The robot has no absolute-heading concept of its own -
only wheel encoder counters - so which way a pawn is currently facing on the
board has to be tracked by us (app_state["peshka_headings"]) and updated
after every move, the same way board position itself is our own source of
truth rather than the robot's.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import httpx

DEFAULT_PESHKA_IPS_PATH = Path(__file__).parent / "config" / "peshka_ips.json"

FILES = "abcdefgh"
# Matches CHESS_CELL_SIZE_M=0.40 used on the drone side (see CLAUDE.md) - one
# shared board scale across the whole fleet.
CELL_SIZE_MM = 400

STATUS_POLL_INTERVAL_SEC = 0.8
MOVE_WAIT_TIMEOUT_SEC = 30.0
HTTP_TIMEOUT_SEC = 10.0


def load_peshka_ips(path: Path = DEFAULT_PESHKA_IPS_PATH) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _square_to_xy(square: str) -> tuple[int, int]:
    return FILES.index(square[0]), int(square[1]) - 1


def initial_heading_deg(our_color: str) -> float:
    """Our pawns start facing the opponent: white pushes toward increasing
    rank (0 deg, "north" in board-plane terms), black toward decreasing rank
    (180 deg) - matches how they're physically set up on the board."""

    return 0.0 if our_color == "white" else 180.0


def _normalize_angle(deg: float) -> float:
    """Wraps to (-180, 180] - the range turn() accepts."""

    wrapped = (deg + 180) % 360 - 180
    return 180.0 if wrapped == -180.0 else wrapped


def compute_move(from_sq: str, to_sq: str, current_heading_deg: float) -> dict:
    """Translates a chess move into what a pawn actually needs to do:
    how far to turn (deg, None if no turn needed) and how far to drive
    forward (mm), plus the heading it ends up facing afterward.

    Board-plane bearing convention: 0 deg = facing toward increasing rank
    ("north"), 90 deg = toward increasing file ("east") - matches turn()'s
    positive-is-clockwise convention directly via atan2(dx, dy).

    The robot rejects |angle| < 10 deg (see peshka-documentation.pdf), so a
    small required correction is simply skipped rather than sent - the
    resulting heading is then whatever we didn't turn away from, not the
    unreachable ideal target, so heading tracking doesn't drift out of sync
    with what the robot actually did."""

    from_x, from_y = _square_to_xy(from_sq)
    to_x, to_y = _square_to_xy(to_sq)
    dx = (to_x - from_x) * CELL_SIZE_MM
    dy = (to_y - from_y) * CELL_SIZE_MM

    distance_mm = round(math.hypot(dx, dy))
    target_heading = math.degrees(math.atan2(dx, dy)) % 360
    turn_deg = _normalize_angle(target_heading - current_heading_deg)

    if abs(turn_deg) < 10:
        return {"turn_deg": None, "distance_mm": distance_mm, "resulting_heading_deg": current_heading_deg}

    return {
        "turn_deg": round(turn_deg),
        "distance_mm": distance_mm,
        "resulting_heading_deg": target_heading,
    }


def _base_url(ip: str) -> str:
    return f"http://{ip}"


def get_status(ip: str) -> dict:
    try:
        response = httpx.get(f"{_base_url(ip)}/status", timeout=HTTP_TIMEOUT_SEC)
        response.raise_for_status()
        return {"ok": True, **response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}


def send_command(ip: str, command: str, distance: int = 0, angle: int = 0) -> dict:
    payload = {"command": command, "distance": distance, "angle": angle}
    try:
        response = httpx.post(
            f"{_base_url(ip)}/command", json=payload, timeout=HTTP_TIMEOUT_SEC
        )
        response.raise_for_status()
        return {"ok": True, **response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}


def _wait_until_ready(ip: str, timeout_sec: float | None = None) -> dict:
    # Reads the module attribute at call time rather than capturing it as a
    # default parameter value, which Python would bind once at function
    # definition - that would make MOVE_WAIT_TIMEOUT_SEC effectively
    # unpatchable/unconfigurable after import (bit tests and callers alike).
    if timeout_sec is None:
        timeout_sec = MOVE_WAIT_TIMEOUT_SEC
    deadline = time.monotonic() + timeout_sec
    last_status: dict = {"ok": False, "error": "no status received"}
    while time.monotonic() < deadline:
        last_status = get_status(ip)
        if last_status.get("ok") and last_status.get("status") == "Ready":
            return last_status
        time.sleep(STATUS_POLL_INTERVAL_SEC)
    return {"ok": False, "error": f"робот не вернулся в Ready за {timeout_sec:.0f} с", "last_status": last_status}


def move_pawn_to_cell(ip: str, from_sq: str, to_sq: str, current_heading_deg: float) -> dict:
    """Drives a pawn from from_sq to to_sq: an optional in-place turn
    followed by a straight drive forward, waiting for the robot to report
    Ready after each step. Returns {"ok": True, "resulting_heading_deg": ...}
    on success, or {"ok": False, "error": ...} - same shape convention as
    gateway_client, never raises."""

    move = compute_move(from_sq, to_sq, current_heading_deg)

    if move["turn_deg"] is not None:
        turn_result = send_command(ip, "turn", angle=move["turn_deg"])
        if not turn_result.get("ok"):
            return {"ok": False, "error": turn_result.get("error", "turn command failed")}
        wait_result = _wait_until_ready(ip)
        if not wait_result.get("ok"):
            return {"ok": False, "error": f"поворот не завершился: {wait_result.get('error')}"}

    forward_result = send_command(ip, "forward", distance=move["distance_mm"])
    if not forward_result.get("ok"):
        return {"ok": False, "error": forward_result.get("error", "forward command failed")}
    wait_result = _wait_until_ready(ip)
    if not wait_result.get("ok"):
        return {"ok": False, "error": f"движение вперёд не завершилось: {wait_result.get('error')}"}

    return {"ok": True, "resulting_heading_deg": move["resulting_heading_deg"]}
