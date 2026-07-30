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
