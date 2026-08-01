"""Thin client for the organizers' Gateway (sverk_ai_communication_server).

Only used in "manual" field mode, to send a move-to-square command to a
robot bound to the piece being dragged (fly for drones, drive for rovers -
see send_fly_command). Network/timeout errors are caught and returned as a
normal {"ok": False, ...} result - a Gateway outage must never crash a
board move that already happened in the UI.
"""

from __future__ import annotations

import os

import httpx

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:8080")


def send_fly_command(robot_id: str, to_sq: str) -> dict:
    # Rooks are ground rovers (robot_id "rover-*" per the organizers'
    # fleet.yaml), not drones - everything else that goes through this
    # function (king/queen/bishop/knight) flies.
    verb = "едь" if robot_id.startswith("rover-") else "лети"
    payload = {
        "robot_id": robot_id,
        "text": f"{verb} в клетку {to_sq}",
        "wait_for_answer": False,
    }
    try:
        response = httpx.post(
            f"{GATEWAY_BASE_URL}/api/v1/messages", json=payload, timeout=5.0
        )
        response.raise_for_status()
        return {"ok": True, "response": response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}


def send_chat_message(text: str) -> dict:
    """Send a human chat message through the Gateway (same channel as its
    own /chat web UI - target a robot with @mention in the text, e.g.
    "@rover_01 статус"). The message and the robot's reply both come back
    to us through the chat_feed WS listener like any other event, so we
    don't need to append it to app_state ourselves here."""

    try:
        response = httpx.post(
            f"{GATEWAY_BASE_URL}/api/v1/chat/send", json={"text": text}, timeout=5.0
        )
        response.raise_for_status()
        return {"ok": True, "response": response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}


def ask_robots(robot_ids: list[str], text: str, timeout_sec: float = 30.0) -> dict:
    """Send the same text to several robots and wait for their answers
    (used for move-negotiation voting). Unlike send_fly_command, this blocks
    for up to timeout_sec per robot - Gateway answers each target
    independently, so one non-responding/offline robot doesn't hold up the
    others (see sverk_ai_communication_server's dispatch code)."""

    payload = {
        "robot_ids": robot_ids,
        "text": text,
        "wait_for_answer": True,
        "answer_timeout_sec": timeout_sec,
    }
    try:
        response = httpx.post(
            f"{GATEWAY_BASE_URL}/api/v1/messages",
            json=payload,
            timeout=timeout_sec + 5.0,
        )
        response.raise_for_status()
        return {"ok": True, "response": response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}


def get_robots() -> dict:
    """Fetch the robot registry from the Gateway. Also doubles as the
    Gateway connectivity check for the UI - {"ok": False} means the
    Gateway is unreachable, not that no robots exist."""

    try:
        response = httpx.get(f"{GATEWAY_BASE_URL}/api/v1/robots", timeout=5.0)
        response.raise_for_status()
        return {"ok": True, "robots": response.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}
