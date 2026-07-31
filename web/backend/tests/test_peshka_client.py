import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import peshka_client


# --- compute_move --------------------------------------------------------


def test_compute_move_straight_push_needs_no_turn():
    move = peshka_client.compute_move("e2", "e4", current_heading_deg=0.0)
    assert move["turn_deg"] is None
    assert move["distance_mm"] == 800
    assert move["resulting_heading_deg"] == 0.0


def test_compute_move_black_straight_push_needs_no_turn():
    # Black's pawns start facing 180 deg (toward decreasing rank).
    move = peshka_client.compute_move("e7", "e5", current_heading_deg=180.0)
    assert move["turn_deg"] is None
    assert move["distance_mm"] == 800


def test_compute_move_diagonal_capture_turns_left():
    # e4 -> d5: one cell toward decreasing file, one toward increasing rank -
    # from a pawn facing "north" (0 deg), that's 45 deg to the left.
    move = peshka_client.compute_move("e4", "d5", current_heading_deg=0.0)
    assert move["turn_deg"] == -45
    assert move["distance_mm"] == round((2 * 400**2) ** 0.5)
    assert move["resulting_heading_deg"] == 315.0


def test_compute_move_diagonal_capture_turns_right():
    move = peshka_client.compute_move("e4", "f5", current_heading_deg=0.0)
    assert move["turn_deg"] == 45
    assert move["resulting_heading_deg"] == 45.0


def test_compute_move_small_correction_is_skipped():
    move = peshka_client.compute_move("e2", "e4", current_heading_deg=5.0)
    # target heading is 0 deg, 5 deg away from current - inside the robot's
    # forbidden [-10, 10] turn deadzone.
    assert move["turn_deg"] is None
    assert move["resulting_heading_deg"] == 5.0  # unchanged, we never turned


def test_compute_move_knight_shaped_distance_and_angle():
    move = peshka_client.compute_move("b1", "c3", current_heading_deg=0.0)
    assert move["distance_mm"] == round((400**2 + 800**2) ** 0.5)
    # atan2(400, 800) ~ 26.57 deg to the right.
    assert move["turn_deg"] == 27


def test_normalize_angle_wraps_correctly():
    assert peshka_client._normalize_angle(190) == -170
    assert peshka_client._normalize_angle(-190) == 170
    assert peshka_client._normalize_angle(180) == 180
    assert peshka_client._normalize_angle(-180) == 180


def test_initial_heading_by_color():
    assert peshka_client.initial_heading_deg("white") == 0.0
    assert peshka_client.initial_heading_deg("black") == 180.0


# --- load_peshka_ips --------------------------------------------------------


def test_load_peshka_ips(tmp_path):
    path = tmp_path / "peshka_ips.json"
    path.write_text('{"peshka-01": "10.0.0.1"}', encoding="utf-8")
    assert peshka_client.load_peshka_ips(path) == {"peshka-01": "10.0.0.1"}


# --- get_status / send_command (HTTP transport) --------------------------------------------------------


def test_get_status_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "Ready", "rightEncoder": 0, "leftEncoder": 0}

    with patch("peshka_client.httpx.get", return_value=mock_response) as mock_get:
        result = peshka_client.get_status("10.0.0.1")

    assert result == {"ok": True, "status": "Ready", "rightEncoder": 0, "leftEncoder": 0}
    assert mock_get.call_args[0][0] == "http://10.0.0.1/status"


def test_get_status_network_error_does_not_raise():
    with patch("peshka_client.httpx.get", side_effect=httpx.ConnectError("down")):
        result = peshka_client.get_status("10.0.0.1")
    assert result["ok"] is False
    assert "down" in result["error"]


def test_send_command_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "Moving forward 200mm"}

    with patch("peshka_client.httpx.post", return_value=mock_response) as mock_post:
        result = peshka_client.send_command("10.0.0.1", "forward", distance=200)

    assert result == {"ok": True, "status": "Moving forward 200mm"}
    called_url, called_kwargs = mock_post.call_args
    assert called_url[0] == "http://10.0.0.1/command"
    assert called_kwargs["json"] == {"command": "forward", "distance": 200, "angle": 0}


def test_send_command_http_error_does_not_raise():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad request", request=MagicMock(), response=MagicMock()
    )
    with patch("peshka_client.httpx.post", return_value=mock_response):
        result = peshka_client.send_command("10.0.0.1", "forward", distance=5)
    assert result["ok"] is False


# --- move_pawn_to_cell --------------------------------------------------------


def test_move_pawn_to_cell_straight_push_skips_turn(monkeypatch):
    monkeypatch.setattr(peshka_client, "STATUS_POLL_INTERVAL_SEC", 0)
    send_calls = []

    def fake_send_command(ip, command, distance=0, angle=0):
        send_calls.append((command, distance, angle))
        return {"ok": True}

    monkeypatch.setattr(peshka_client, "send_command", fake_send_command)
    monkeypatch.setattr(peshka_client, "get_status", lambda ip: {"ok": True, "status": "Ready"})

    result = peshka_client.move_pawn_to_cell("10.0.0.1", "e2", "e4", current_heading_deg=0.0)

    assert result == {"ok": True, "resulting_heading_deg": 0.0}
    # no turn command sent - straight push
    assert send_calls == [("forward", 800, 0)]


def test_move_pawn_to_cell_diagonal_sends_turn_then_forward(monkeypatch):
    monkeypatch.setattr(peshka_client, "STATUS_POLL_INTERVAL_SEC", 0)
    send_calls = []

    def fake_send_command(ip, command, distance=0, angle=0):
        send_calls.append((command, distance, angle))
        return {"ok": True}

    monkeypatch.setattr(peshka_client, "send_command", fake_send_command)
    monkeypatch.setattr(peshka_client, "get_status", lambda ip: {"ok": True, "status": "Ready"})

    result = peshka_client.move_pawn_to_cell("10.0.0.1", "e4", "d5", current_heading_deg=0.0)

    assert result["ok"] is True
    assert result["resulting_heading_deg"] == 315.0
    assert send_calls[0][0] == "turn"
    assert send_calls[1][0] == "forward"


def test_move_pawn_to_cell_turn_command_failure_aborts():
    with patch("peshka_client.send_command", return_value={"ok": False, "error": "conn refused"}):
        result = peshka_client.move_pawn_to_cell("10.0.0.1", "e4", "d5", current_heading_deg=0.0)
    assert result["ok"] is False
    assert "conn refused" in result["error"]


def test_move_pawn_to_cell_wait_timeout_reported(monkeypatch):
    monkeypatch.setattr(peshka_client, "STATUS_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(peshka_client, "MOVE_WAIT_TIMEOUT_SEC", 0)
    monkeypatch.setattr(peshka_client, "send_command", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        peshka_client, "get_status", lambda ip: {"ok": True, "status": "Moving forward"}
    )

    result = peshka_client.move_pawn_to_cell("10.0.0.1", "e2", "e4", current_heading_deg=0.0)

    assert result["ok"] is False
    assert "не завершилось" in result["error"]
