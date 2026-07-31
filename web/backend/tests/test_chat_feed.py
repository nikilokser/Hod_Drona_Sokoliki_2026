import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import chat_feed


def test_merge_event_adds_new_event(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    event = {"event_id": "1", "text": "hello"}

    added = chat_feed.merge_event(app_state, event, path)

    assert added is True
    assert app_state["chat_events"] == [event]
    assert chat_feed.load_chat_events(path) == [event]


def test_merge_event_deduplicates_by_event_id(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    event = {"event_id": "1", "text": "hello"}

    chat_feed.merge_event(app_state, event, path)
    added_again = chat_feed.merge_event(app_state, dict(event), path)

    assert added_again is False
    assert len(app_state["chat_events"]) == 1
    assert len(chat_feed.load_chat_events(path)) == 1


def test_merge_event_drops_gateway_duplicate_publish(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    first = {
        "event_id": "aaa",
        "dispatch_id": "d1",
        "event_type": "command",
        "direction": "outgoing",
        "text": "@rover_01 статус",
    }
    # Same dispatch_id/type/direction/text, different event_id - exactly
    # the Gateway's known duplicate-publish bug.
    second = {**first, "event_id": "bbb"}

    added_first = chat_feed.merge_event(app_state, first, path)
    added_second = chat_feed.merge_event(app_state, second, path)

    assert added_first is True
    assert added_second is False
    assert len(app_state["chat_events"]) == 1
    assert len(chat_feed.load_chat_events(path)) == 1


def test_merge_event_keeps_distinct_status_updates_with_same_dispatch_id(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    first = {
        "event_id": "aaa",
        "dispatch_id": "d1",
        "event_type": "status",
        "direction": "incoming",
        "text": "Раунд 1: отправляю запрос к LLM",
    }
    second = {
        "event_id": "bbb",
        "dispatch_id": "d1",
        "event_type": "status",
        "direction": "incoming",
        "text": "Готово, ровер доехал до клетки C1",
    }

    added_first = chat_feed.merge_event(app_state, first, path)
    added_second = chat_feed.merge_event(app_state, second, path)

    assert added_first is True
    assert added_second is True
    assert len(app_state["chat_events"]) == 2


def test_merge_event_keeps_events_without_dispatch_id(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    event = {"event_id": "1", "event_type": "system", "direction": "system", "text": "connected"}

    chat_feed.merge_event(app_state, event, path)
    added_again = chat_feed.merge_event(
        app_state, {**event, "event_id": "2"}, path
    )

    assert added_again is True
    assert len(app_state["chat_events"]) == 2


def test_merge_event_drops_near_instant_duplicate_without_dispatch_id(tmp_path):
    # Reproduces the Gateway's duplicate-publish bug for events that don't
    # carry a dispatch_id (availability/status/plain chat) - the same
    # content republished ~1ms later under a fresh event_id.
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    first = {
        "event_id": "aaa",
        "event_type": "availability",
        "direction": "system",
        "robot_id": "sverk-8",
        "text": "offline",
        "timestamp": "2026-07-31T12:00:00.000000Z",
    }
    second = {**first, "event_id": "bbb", "timestamp": "2026-07-31T12:00:00.032000Z"}

    added_first = chat_feed.merge_event(app_state, first, path)
    added_second = chat_feed.merge_event(app_state, second, path)

    assert added_first is True
    assert added_second is False
    assert len(app_state["chat_events"]) == 1


def test_merge_event_keeps_same_text_far_apart_without_dispatch_id(tmp_path):
    # A robot legitimately recurring status ("Команда получена") repeats the
    # exact same text on every future dispatch, hours apart - must not be
    # mistaken for the near-instant Gateway duplicate-publish bug.
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    first = {
        "event_id": "aaa",
        "event_type": "status",
        "direction": "incoming",
        "robot_id": "sverk-108",
        "text": "Команда получена pseudo-agent.",
        "timestamp": "2026-07-30T15:46:04.812285Z",
    }
    second = {
        **first,
        "event_id": "bbb",
        "timestamp": "2026-07-30T16:00:58.047947Z",
    }

    added_first = chat_feed.merge_event(app_state, first, path)
    added_second = chat_feed.merge_event(app_state, second, path)

    assert added_first is True
    assert added_second is True
    assert len(app_state["chat_events"]) == 2


def test_merge_event_keeps_near_instant_same_text_different_robot(tmp_path):
    # Two different robots going offline at nearly the same moment are
    # distinct events, not a duplicate publish of one - robot_id must be
    # part of the match, not just event_type/direction/text.
    path = tmp_path / "chat_history.jsonl"
    app_state = {}
    first = {
        "event_id": "aaa",
        "event_type": "availability",
        "direction": "system",
        "robot_id": "sverk-8",
        "text": "offline",
        "timestamp": "2026-07-31T12:00:00.000000Z",
    }
    second = {**first, "event_id": "bbb", "robot_id": "sverk-108"}

    added_first = chat_feed.merge_event(app_state, first, path)
    added_second = chat_feed.merge_event(app_state, second, path)

    assert added_first is True
    assert added_second is True
    assert len(app_state["chat_events"]) == 2


def test_dedupe_events_removes_gateway_duplicate_publish():
    first = {
        "event_id": "aaa",
        "dispatch_id": "d1",
        "event_type": "command",
        "direction": "outgoing",
        "text": "@rover_01 статус",
    }
    second = {**first, "event_id": "bbb"}

    result = chat_feed.dedupe_events([first, second])

    assert result == [first]


def test_dedupe_events_removes_near_instant_duplicate_without_dispatch_id():
    first = {
        "event_id": "aaa",
        "event_type": "availability",
        "direction": "system",
        "robot_id": "sverk-8",
        "text": "offline",
        "timestamp": "2026-07-31T12:00:00.000000Z",
    }
    second = {**first, "event_id": "bbb", "timestamp": "2026-07-31T12:00:00.032000Z"}

    result = chat_feed.dedupe_events([first, second])

    assert result == [first]


def test_dedupe_events_keeps_same_text_far_apart_without_dispatch_id():
    first = {
        "event_id": "aaa",
        "event_type": "status",
        "direction": "incoming",
        "robot_id": "sverk-108",
        "text": "Команда получена pseudo-agent.",
        "timestamp": "2026-07-30T15:46:04.812285Z",
    }
    second = {**first, "event_id": "bbb", "timestamp": "2026-07-30T16:00:58.047947Z"}

    result = chat_feed.dedupe_events([first, second])

    assert len(result) == 2


def test_dedupe_events_keeps_distinct_events():
    events = [
        {"event_id": "1", "dispatch_id": "d1", "event_type": "command", "direction": "outgoing", "text": "a"},
        {"event_id": "2", "dispatch_id": "d1", "event_type": "answer", "direction": "incoming", "text": "b"},
        {"event_id": "3", "dispatch_id": "d2", "event_type": "command", "direction": "outgoing", "text": "a"},
    ]

    result = chat_feed.dedupe_events(events)

    assert len(result) == 3


def test_merge_event_truncates_in_memory_list(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_feed, "MAX_CHAT_EVENTS_IN_MEMORY", 3)
    path = tmp_path / "chat_history.jsonl"
    app_state = {}

    for i in range(5):
        chat_feed.merge_event(app_state, {"event_id": str(i)}, path)

    assert len(app_state["chat_events"]) == 3
    assert [e["event_id"] for e in app_state["chat_events"]] == ["2", "3", "4"]
    # the file itself is never truncated - it's the full match log
    assert len(chat_feed.load_chat_events(path)) == 5


def test_load_chat_events_missing_file_returns_empty(tmp_path):
    path = tmp_path / "does_not_exist.jsonl"
    assert chat_feed.load_chat_events(path) == []


def test_load_chat_events_skips_malformed_lines(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    path.write_text('{"event_id": "1"}\nnot json\n{"event_id": "2"}\n', encoding="utf-8")

    events = chat_feed.load_chat_events(path)

    assert events == [{"event_id": "1"}, {"event_id": "2"}]


def test_fetch_history_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [{"event_id": "1"}]

    with patch("chat_feed.httpx.get", return_value=mock_response) as mock_get:
        result = chat_feed.fetch_history(limit=10)

    assert result == [{"event_id": "1"}]
    called_url = mock_get.call_args[0][0]
    assert called_url == f"{chat_feed.GATEWAY_BASE_URL}/api/v1/chat/history"
    assert mock_get.call_args[1]["params"] == {"limit": 10}


def test_fetch_history_network_error_returns_empty_list():
    with patch("chat_feed.httpx.get", side_effect=httpx.ConnectError("down")):
        result = chat_feed.fetch_history()

    assert result == []


def test_gateway_ws_url_converts_scheme():
    assert chat_feed._gateway_ws_url().startswith("ws://")
    assert chat_feed._gateway_ws_url().endswith("/api/v1/chat/ws")


def test_check_pending_robot_move_ignores_unrelated_robot():
    app_state = {"pending_robot_moves": {"drone-01": {"from": "e2", "to": "e4"}}}
    event = {"robot_id": "drone-02", "event_type": "availability", "online": False}

    changed = chat_feed.check_pending_robot_move(app_state, event)

    assert changed is False
    assert "drone-01" in app_state["pending_robot_moves"]


def test_check_pending_robot_move_ignores_when_nothing_pending():
    app_state = {}
    event = {"robot_id": "drone-01", "event_type": "availability", "online": False}

    assert chat_feed.check_pending_robot_move(app_state, event) is False


def test_check_pending_robot_move_alerts_on_offline_and_stops_tracking():
    app_state = {"pending_robot_moves": {"drone-01": {"from": "e2", "to": "e4"}}}
    event = {
        "robot_id": "drone-01",
        "event_type": "availability",
        "online": False,
        "timestamp": "2026-08-01T12:00:00Z",
    }

    changed = chat_feed.check_pending_robot_move(app_state, event)

    assert changed is True
    assert "drone-01" not in app_state["pending_robot_moves"]
    assert len(app_state["robot_alerts"]) == 1
    alert = app_state["robot_alerts"][0]
    assert alert["robot_id"] == "drone-01"
    assert alert["from"] == "e2"
    assert alert["to"] == "e4"
    assert "e2" in alert["text"] and "e4" in alert["text"]


def test_check_pending_robot_move_ignores_online_true():
    app_state = {"pending_robot_moves": {"drone-01": {"from": "e2", "to": "e4"}}}
    event = {"robot_id": "drone-01", "event_type": "availability", "online": True}

    changed = chat_feed.check_pending_robot_move(app_state, event)

    assert changed is False
    assert "drone-01" in app_state["pending_robot_moves"]
    assert app_state.get("robot_alerts", []) == []


def test_check_pending_robot_move_clears_on_answer_without_alert():
    app_state = {"pending_robot_moves": {"drone-01": {"from": "e2", "to": "e4"}}}
    event = {"robot_id": "drone-01", "event_type": "answer", "text": "Готово."}

    changed = chat_feed.check_pending_robot_move(app_state, event)

    assert changed is True
    assert "drone-01" not in app_state["pending_robot_moves"]
    assert app_state.get("robot_alerts", []) == []


def test_check_pending_robot_move_duplicate_offline_event_alerts_once():
    app_state = {"pending_robot_moves": {"drone-01": {"from": "e2", "to": "e4"}}}
    event = {"robot_id": "drone-01", "event_type": "availability", "online": False}

    chat_feed.check_pending_robot_move(app_state, event)
    changed_again = chat_feed.check_pending_robot_move(app_state, dict(event))

    assert changed_again is False
    assert len(app_state["robot_alerts"]) == 1
