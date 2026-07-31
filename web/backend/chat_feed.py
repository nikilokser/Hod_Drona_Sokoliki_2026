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
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

import httpx
import websockets

from gateway_client import GATEWAY_BASE_URL

LOGGER = logging.getLogger(__name__)

DEFAULT_CHAT_HISTORY_PATH = Path(__file__).parent / "config" / "chat_history.jsonl"
MAX_CHAT_EVENTS_IN_MEMORY = 1000
RECONNECT_DELAY_SEC = 3
# The Gateway's duplicate-publish bug fires the second copy ~1ms after the
# first - a few seconds is generous slack for clock/serialization jitter
# while staying far below the minutes/hours between legitimately-repeated
# identical events (e.g. the same "Команда получена pseudo-agent." status
# text recurring for a robot on every future dispatch).
DUPLICATE_PUBLISH_WINDOW_SEC = 5


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


def _parse_timestamp(event: dict) -> datetime | None:
    ts = event.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_duplicate_publish(events: list[dict], event: dict) -> bool:
    """The Gateway has a known bug where it sometimes publishes the exact
    same event twice under two different event_ids (same dispatch_id,
    same text, ~1ms apart) - not something in our control to fix upstream.

    For events carrying a dispatch_id (command/answer/error), match on
    dispatch_id + event_type + direction + text as an event we already
    have - requiring an exact text match is what keeps this from
    swallowing legitimate distinct status updates that share a
    dispatch_id with their originating command.

    Events without a dispatch_id (status/availability/system) get no
    dispatch_id to key on, but are just as susceptible to the same
    Gateway bug (e.g. a free-text chat message or an "offline" ping
    republished under a fresh event_id ~1ms later) - for those, match on
    event_type + direction + text + robot_id *within a tight time
    window* instead. The time window matters: identical status text like
    "Команда получена pseudo-agent." legitimately recurs for the same
    robot many times over a match (once per dispatch, minutes/hours
    apart) - only a near-instant repeat is the publish bug, not a
    same-text-eventually-again."""

    dispatch_id = event.get("dispatch_id")
    if dispatch_id:
        return any(
            e.get("dispatch_id") == dispatch_id
            and e.get("event_type") == event.get("event_type")
            and e.get("direction") == event.get("direction")
            and e.get("text") == event.get("text")
            for e in events
        )

    event_ts = _parse_timestamp(event)
    if event_ts is None:
        return False

    for e in events:
        if e.get("dispatch_id"):
            continue
        if (
            e.get("event_type") != event.get("event_type")
            or e.get("direction") != event.get("direction")
            or e.get("text") != event.get("text")
            or e.get("robot_id") != event.get("robot_id")
        ):
            continue
        e_ts = _parse_timestamp(e)
        if e_ts is not None and abs((event_ts - e_ts).total_seconds()) <= DUPLICATE_PUBLISH_WINDOW_SEC:
            return True

    return False


def dedupe_events(events: list[dict]) -> list[dict]:
    """One-time cleanup for events already loaded from history/disk -
    applies the same rules as merge_event so Gateway duplicate-publishes
    recorded before this fix existed don't linger in the UI. Does not
    touch the on-disk log (kept as the untouched historical record)."""

    deduped: list[dict] = []
    seen_ids: set[str] = set()
    for event in events:
        event_id = event.get("event_id")
        if event_id is not None and event_id in seen_ids:
            continue
        if _is_duplicate_publish(deduped, event):
            continue
        if event_id is not None:
            seen_ids.add(event_id)
        deduped.append(event)
    return deduped


def merge_event(
    app_state: dict, event: dict, path: Path = DEFAULT_CHAT_HISTORY_PATH
) -> bool:
    """Add event to app_state["chat_events"] and to disk unless its
    event_id is already known, or it's a duplicate Gateway publish of an
    event we already have (see _is_duplicate_publish). Returns True if
    the event was newly added."""

    events = app_state.setdefault("chat_events", [])
    event_id = event.get("event_id")
    if event_id is not None and any(e.get("event_id") == event_id for e in events):
        return False
    if _is_duplicate_publish(events, event):
        return False

    events.append(event)
    if len(events) > MAX_CHAT_EVENTS_IN_MEMORY:
        del events[: len(events) - MAX_CHAT_EVENTS_IN_MEMORY]

    append_chat_event(event, path)
    return True


def check_pending_robot_move(app_state: dict, event: dict) -> bool:
    """Reacts to events concerning a robot we're still waiting to hear back
    from about a physically dispatched move (tracked in
    app_state["pending_robot_moves"] by move_orchestrator.execute_move):

    - an "availability" event reporting it went offline - the move's real
      outcome is now unknown (it may have started flying and lost comms
      mid-flight), so surface a clear alert instead of silently waiting
      forever for an answer that may never arrive;
    - an "answer" event - the robot did report back (whatever the outcome),
      already visible as its own chat event, so just stop tracking it.

    Returns True if app_state changed (caller should broadcast)."""

    pending = app_state.get("pending_robot_moves")
    if not pending:
        return False

    robot_id = event.get("robot_id")
    if robot_id not in pending:
        return False

    if event.get("event_type") == "availability" and event.get("online") is False:
        move = pending.pop(robot_id)
        alert = {
            "id": str(uuid.uuid4()),
            "robot_id": robot_id,
            "from": move["from"],
            "to": move["to"],
            "at": event.get("timestamp"),
            "text": (
                f"{robot_id} ушёл в оффлайн во время выполнения хода "
                f"{move['from']} → {move['to']} — результат неизвестен"
            ),
        }
        app_state.setdefault("robot_alerts", []).append(alert)
        return True

    if event.get("event_type") == "answer":
        pending.pop(robot_id, None)
        return True

    return False


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
                if check_pending_robot_move(app_state, event):
                    changed = True
            if changed:
                await broadcast(app_state)

            async with websockets.connect(ws_url) as ws:
                async for raw in ws:
                    event = json.loads(raw)
                    changed = merge_event(app_state, event)
                    if check_pending_robot_move(app_state, event):
                        changed = True
                    if changed:
                        await broadcast(app_state)
        except (OSError, websockets.exceptions.WebSocketException, json.JSONDecodeError):
            LOGGER.info("Gateway chat feed unavailable, will retry")
        except asyncio.CancelledError:
            raise

        await asyncio.sleep(RECONNECT_DELAY_SEC)
