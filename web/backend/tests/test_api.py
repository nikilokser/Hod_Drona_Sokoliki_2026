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
    app_module.app_state["match_clock"] = {
        "status": "idle",
        "match_started_at": None,
        "active_color": None,
        "move_started_at": None,
        "frozen_at": None,
    }
    app_module.app_state["side_to_move"] = "white"
    app_module.app_state["stockfish_enabled"] = False
    app_module.app_state["captured_pieces"] = []
    yield


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_move_rejected_in_view_mode_for_our_own_piece(client):
    response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 400
    assert "e2" in app_module.app_state["board"]


def test_move_allowed_in_view_mode_for_opponent_piece(client):
    # No automated board tracking - view mode must still let the operator
    # record what the opponent actually did on the real field.
    response = client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert response.status_code == 200
    assert "e7" not in app_module.app_state["board"]
    assert app_module.app_state["board"]["e5"]["color"] == "black"


def test_move_applied_in_correct_mode_without_gateway_call(client):
    client.post("/api/mode", json={"mode": "correct"})
    with patch("move_orchestrator.send_fly_command") as mock_send:
        response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 200
    assert "e4" in app_module.app_state["board"]
    mock_send.assert_not_called()


def test_manual_mode_calls_gateway_for_bound_piece(client):
    # Bind explicitly instead of relying on whatever robot_id happens to be
    # in the real config/bindings.json right now - that file reflects live
    # bindings made through the running UI and drifts independently of this
    # test. A non-pawn piece specifically: pawns are dispatched through
    # peshka_client (direct HTTP to the robot's own IP), not the Gateway -
    # see test_move_orchestrator.py for that path.
    client.post("/api/bindings", json={"role": "knight_1", "robot_id": "drone-99"})
    client.post("/api/mode", json={"mode": "manual"})
    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        response = client.post("/api/move", json={"from": "b1", "to": "c3"})
    assert response.status_code == 200
    mock_send.assert_called_once_with("drone-99", "c3")
    body = response.json()
    assert body["result"]["gateway_result"] == {"ok": True, "response": {}}


# --- last_move tracking and match-clock auto-sync ---------------------------


def test_last_move_recorded_in_view_mode(client):
    client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert app_module.app_state["last_move"] == {
        "from": "e7", "to": "e5", "color": "black", "piece": "pawn",
    }


def test_last_move_recorded_in_correct_mode(client):
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert app_module.app_state["last_move"] == {
        "from": "e2", "to": "e4", "color": "white", "piece": "pawn",
    }


def test_last_move_recorded_in_manual_mode(client):
    client.post("/api/mode", json={"mode": "manual"})
    with patch("move_orchestrator.send_fly_command", return_value={"ok": True}):
        client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert app_module.app_state["last_move"] == {
        "from": "e2", "to": "e4", "color": "white", "piece": "pawn",
    }


def test_reset_clears_last_move(client):
    client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert app_module.app_state["last_move"] is not None
    client.post("/api/reset")
    assert app_module.app_state["last_move"] is None


# --- captured-pieces tracking and piece deletion -----------------------------


def test_capturing_move_records_captured_piece(client):
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e7"})  # white pawn takes black pawn
    assert app_module.app_state["captured_pieces"] == [{"color": "black", "piece": "pawn"}]


def test_non_capturing_move_does_not_record_anything(client):
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert app_module.app_state["captured_pieces"] == []


def test_reset_clears_captured_pieces(client):
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e7"})
    assert app_module.app_state["captured_pieces"] != []
    client.post("/api/reset")
    assert app_module.app_state["captured_pieces"] == []


def test_delete_piece_removes_it_and_records_capture(client):
    client.post("/api/mode", json={"mode": "correct"})
    response = client.post("/api/delete-piece", json={"square": "e7"})
    assert response.status_code == 200
    assert "e7" not in app_module.app_state["board"]
    assert app_module.app_state["captured_pieces"] == [{"color": "black", "piece": "pawn"}]


def test_delete_piece_rejected_in_view_mode_for_own_piece(client):
    response = client.post("/api/delete-piece", json={"square": "e2"})
    assert response.status_code == 400
    assert "e2" in app_module.app_state["board"]
    assert app_module.app_state["captured_pieces"] == []


def test_delete_piece_allowed_in_view_mode_for_opponent_piece(client):
    response = client.post("/api/delete-piece", json={"square": "e7"})
    assert response.status_code == 200
    assert "e7" not in app_module.app_state["board"]


def test_delete_piece_rejects_empty_square(client):
    response = client.post("/api/delete-piece", json={"square": "e4"})
    assert response.status_code == 400


def test_view_mode_move_auto_advances_running_clock(client):
    client.post("/api/match/start")  # white active, running
    # Simulate: it's actually black's (the opponent's) turn right now.
    client.post("/api/side-to-move", json={"color": "black"})
    client.post("/api/match/turn-done")  # judge flips the clock to match: black active

    client.post("/api/move", json={"from": "e7", "to": "e5"})  # opponent's real move, recorded
    assert app_module.app_state["side_to_move"] == "white"
    assert app_module.app_state["match_clock"]["active_color"] == "white"


def test_correct_mode_move_does_not_advance_running_clock(client):
    client.post("/api/match/start")
    client.post("/api/mode", json={"mode": "correct"})
    client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert app_module.app_state["match_clock"]["active_color"] == "white"


def test_manual_mode_move_auto_advances_running_clock(client):
    client.post("/api/match/start")
    client.post("/api/mode", json={"mode": "manual"})
    with patch("move_orchestrator.send_fly_command", return_value={"ok": True}):
        client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert app_module.app_state["match_clock"]["active_color"] == "black"


def test_view_mode_move_does_not_advance_idle_clock(client):
    client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert app_module.app_state["match_clock"]["status"] == "idle"
    assert app_module.app_state["match_clock"]["active_color"] is None


def test_manual_mode_skips_gateway_for_opponent_piece(client):
    client.post("/api/mode", json={"mode": "manual"})
    client.post("/api/side-to-move", json={"color": "black"})  # legitimately black's turn
    with patch("move_orchestrator.send_fly_command") as mock_send:
        response = client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert response.status_code == 200
    mock_send.assert_not_called()


def test_manual_mode_allows_moving_any_piece_regardless_of_turn(client):
    # "Manual" is a debug mode: any piece can be dragged no matter whose
    # turn it officially is (per user request) - move our own white piece
    # while side_to_move says black, and it still goes through and still
    # dispatches to the robot. Non-pawn piece: pawns are dispatched through
    # peshka_client, not the Gateway.
    client.post("/api/bindings", json={"role": "knight_1", "robot_id": "drone-99"})
    client.post("/api/mode", json={"mode": "manual"})
    client.post("/api/side-to-move", json={"color": "black"})
    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        response = client.post("/api/move", json={"from": "b1", "to": "c3"})
    assert response.status_code == 200
    assert "c3" in app_module.app_state["board"]
    mock_send.assert_called_once_with("drone-99", "c3")


def test_correct_mode_allows_wrong_turn_move(client):
    client.post("/api/mode", json={"mode": "correct"})
    # correct mode stays unrestricted regardless of side_to_move
    response = client.post("/api/move", json={"from": "e7", "to": "e5"})
    assert response.status_code == 200
    assert "e5" in app_module.app_state["board"]


def test_manual_mode_keeps_move_on_gateway_error(client):
    client.post("/api/mode", json={"mode": "manual"})
    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": False, "error": "timeout"}
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


def test_match_start_sets_running_state(client):
    response = client.post("/api/match/start")
    assert response.status_code == 200
    clock = app_module.app_state["match_clock"]
    assert clock["status"] == "running"
    assert clock["active_color"] == "white"


def test_turn_done_rejected_before_match_start(client):
    response = client.post("/api/match/turn-done")
    assert response.status_code == 400
    assert app_module.app_state["match_clock"]["status"] == "idle"


def test_turn_done_flips_active_color(client):
    client.post("/api/match/start")
    response = client.post("/api/match/turn-done")
    assert response.status_code == 200
    assert app_module.app_state["match_clock"]["active_color"] == "black"


def test_pause_rejected_before_match_start(client):
    response = client.post("/api/match/pause")
    assert response.status_code == 400


def test_pause_then_turn_done_rejected(client):
    client.post("/api/match/start")
    client.post("/api/match/pause")
    assert app_module.app_state["match_clock"]["status"] == "paused"

    response = client.post("/api/match/turn-done")
    assert response.status_code == 400


def test_resume_rejected_when_not_paused(client):
    client.post("/api/match/start")
    response = client.post("/api/match/resume")
    assert response.status_code == 400


def test_pause_then_resume_returns_to_running(client):
    client.post("/api/match/start")
    client.post("/api/match/pause")
    response = client.post("/api/match/resume")
    assert response.status_code == 200
    assert app_module.app_state["match_clock"]["status"] == "running"


def test_end_match_rejected_when_idle(client):
    response = client.post("/api/match/end")
    assert response.status_code == 400


def test_end_match_from_running(client):
    client.post("/api/match/start")
    response = client.post("/api/match/end")
    assert response.status_code == 200
    assert app_module.app_state["match_clock"]["status"] == "finished"


def test_turn_done_rejected_after_match_end(client):
    client.post("/api/match/start")
    client.post("/api/match/end")
    response = client.post("/api/match/turn-done")
    assert response.status_code == 400


def test_move_auto_updates_side_to_move(client):
    client.post("/api/mode", json={"mode": "correct"})
    response = client.post("/api/move", json={"from": "e2", "to": "e4"})
    assert response.status_code == 200
    assert app_module.app_state["side_to_move"] == "black"


def test_side_to_move_manual_override(client):
    response = client.post("/api/side-to-move", json={"color": "black"})
    assert response.status_code == 200
    assert app_module.app_state["side_to_move"] == "black"


def test_stockfish_enable_toggles_flag(client):
    response = client.post("/api/stockfish/enable", json={"enabled": True})
    assert response.status_code == 200
    assert app_module.app_state["stockfish_enabled"] is True

    response = client.post("/api/stockfish/enable", json={"enabled": False})
    assert response.status_code == 200
    assert app_module.app_state["stockfish_enabled"] is False
