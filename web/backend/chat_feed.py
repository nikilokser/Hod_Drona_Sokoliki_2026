"""Keeps app_state["chat_events"] in sync with the organizers' Gateway
(sverk_ai_communication_server) chat history/WS feed.

This displays the raw command/answer/status/availability events Gateway
already collects - it does not interpret or group them, and it is not an
orchestrator for negotiation between our own LLM agents (see the design
doc). Regulation requires showing agent negotiations on screen during a
match, so this feed must keep working (survive our own backend restarts)
even if the Gateway itself is flaky.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

import httpx
import websockets

from gateway_client import GATEWAY_BASE_URL

LOGGER = logging.getLogger(__name__)

DEFAULT_CHAT_HISTORY_PATH = Path(__file__).parent / "config" / "chat_history.jsonl"
MAX_CHAT_EVENTS_IN_MEMORY = 1000
RECONNECT_DELAY_SEC = 3


def load_chat_events(path: Path = DEFAULT_CHAT_HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []

    events: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                LOGGER.warning("Skipping malformed chat history line")
    return events


def append_chat_event(event: dict, path: Path = DEFAULT_CHAT_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False))
        f.write("\n")


def merge_event(
    app_state: dict, event: dict, path: Path = DEFAULT_CHAT_HISTORY_PATH
) -> bool:
    """Add event to app_state["chat_events"] and to disk unless its
    event_id is already known. Returns True if the event was new."""

    events = app_state.setdefault("chat_events", [])
    event_id = event.get("event_id")
    if event_id is not None and any(e.get("event_id") == event_id for e in events):
        return False

    events.append(event)
    if len(events) > MAX_CHAT_EVENTS_IN_MEMORY:
        del events[: len(events) - MAX_CHAT_EVENTS_IN_MEMORY]

    append_chat_event(event, path)
    return True


def fetch_history(limit: int = 1000) -> list[dict]:
    try:
        response = httpx.get(
            f"{GATEWAY_BASE_URL}/api/v1/chat/history",
            params={"limit": limit},
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return []


def _gateway_ws_url() -> str:
    return (
        GATEWAY_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        + "/api/v1/chat/ws"
    )


async def run_chat_feed(
    app_state: dict, broadcast: Callable[[dict], Awaitable[None]]
) -> None:
    """Background task: forever keeps app_state["chat_events"] in sync with
    the Gateway, reconnecting on any failure. Never raises."""

    ws_url = _gateway_ws_url()

    while True:
        try:
            changed = False
            for event in fetch_history():
                if merge_event(app_state, event):
                    changed = True
            if changed:
                await broadcast(app_state)

            async with websockets.connect(ws_url) as ws:
                async for raw in ws:
                    event = json.loads(raw)
                    if merge_event(app_state, event):
                        await broadcast(app_state)
        except (OSError, websockets.exceptions.WebSocketException, json.JSONDecodeError):
            LOGGER.info("Gateway chat feed unavailable, will retry")
        except asyncio.CancelledError:
            raise

        await asyncio.sleep(RECONNECT_DELAY_SEC)
