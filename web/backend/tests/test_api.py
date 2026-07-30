import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import app as app_module
from state import initial_board


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    # Never let a test write to the real config/bindings.json.
    monkeypatch.setattr(app_module, "save_bindings", lambda bindings: None)

    fresh_bindings = dict(app_module._initial_bindings)
    app_module.app_state["bindings"] = fresh_bindings
    app_module.app_state["board"] = initial_board("white", fresh_bindings)
    app_module.app_state["mode"] = "view"
    app_module.app_state["our_color"] = "white"
    yield


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_move_rejected_in_view_mode(client):
    response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 400
    assert "e2" in app_module.app_state["board"]


def test_move_applied_in_correct_mode_without_gateway_call(client):
    client.post("/api/mode", json={"mode": "correct"})
    with patch("app.send_fly_command") as mock_send:
        response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 200
    assert "e4" in app_module.app_state["board"]
    mock_send.assert_not_called()


def test_manual_mode_calls_gateway_for_bound_piece(client):
    client.post("/api/mode", json={"mode": "manual"})
    with patch(
        "app.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 200
    mock_send.assert_called_once_with("peshka-05", "e4")
    body = response.json()
    assert body["result"]["gateway_result"] == {"ok": True, "response": {}}


def test_manual_mode_skips_gateway_for_opponent_piece(client):
    client.post("/api/mode", json={"mode": "manual"})
    with patch("app.send_fly_command") as mock_send:
        response = client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert response.status_code == 200
    mock_send.assert_not_called()


def test_manual_mode_keeps_move_on_gateway_error(client):
    client.post("/api/mode", json={"mode": "manual"})
    with patch(
        "app.send_fly_command", return_value={"ok": False, "error": "timeout"}
    ):
        response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 200
    assert "e4" in app_module.app_state["board"]


def test_our_color_switch_resets_board(client):
    response = client.post("/api/our-color", json={"color": "black"})
    assert response.status_code == 200
    expected_king_robot = app_module.app_state["bindings"]["king"]
    assert app_module.app_state["board"]["e8"]["robot_id"] == expected_king_robot


def test_list_robots_proxies_gateway(client):
    fake_robots = {"ok": True, "robots": [{"robot_id": "drone-01", "online": True}]}
    with patch("app.get_robots", return_value=fake_robots):
        response = client.get("/api/robots")
    assert response.status_code == 200
    assert response.json() == fake_robots


def test_list_robots_surfaces_gateway_error(client):
    with patch(
        "app.get_robots", return_value={"ok": False, "error": "connection refused"}
    ):
        response = client.get("/api/robots")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_set_binding_updates_bindings_and_board(client):
    response = client.post(
        "/api/bindings", json={"role": "king", "robot_id": "drone-99"}
    )
    assert response.status_code == 200
    assert app_module.app_state["bindings"]["king"] == "drone-99"
    assert app_module.app_state["board"]["e1"]["robot_id"] == "drone-99"


def test_set_binding_rejects_unknown_role(client):
    response = client.post(
        "/api/bindings", json={"role": "dragon", "robot_id": "drone-99"}
    )
    assert response.status_code == 422
    assert "dragon" not in app_module.app_state["bindings"]


def test_reset_restores_starting_position(client):
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert "e2" not in app_module.app_state["board"]

    response = client.post("/api/reset")
    assert response.status_code == 200
    assert app_module.app_state["board"]["e2"]["piece"] == "pawn"
    assert "e4" not in app_module.app_state["board"]


def test_reset_keeps_current_our_color(client):
    client.post("/api/our-color", json={"color": "black"})
    response = client.post("/api/reset")
    assert response.status_code == 200
    assert app_module.app_state["board"]["e8"]["piece"] == "king"
    assert app_module.app_state["our_color"] == "black"


def test_chat_send_proxies_to_gateway(client):
    with patch(
        "app.send_chat_message", return_value={"ok": True, "response": {}}
    ) as mock_send:
        response = client.post("/api/chat/send", json={"text": "@rover_01 статус"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "response": {}}
    mock_send.assert_called_once_with("@rover_01 статус")


def test_chat_send_surfaces_gateway_error(client):
    with patch(
        "app.send_chat_message", return_value={"ok": False, "error": "timeout"}
    ):
        response = client.post("/api/chat/send", json={"text": "@rover_01 статус"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
