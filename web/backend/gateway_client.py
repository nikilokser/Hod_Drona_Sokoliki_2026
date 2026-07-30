"""Thin client for the organizers' Gateway (sverk_ai_communication_server).

Only used in "manual" field mode, to send a fly-to-square command to a
robot bound to the piece being dragged. Network/timeout errors are caught
and returned as a normal {"ok": False, ...} result - a Gateway outage must
never crash a board move that already happened in the UI.
"""

from __future__ import annotations

import os

import httpx

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:8080")


def send_fly_command(robot_id: str, to_sq: str) -> dict:
    payload = {
        "robot_id": robot_id,
        "text": f"лети в клетку {to_sq}",
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
