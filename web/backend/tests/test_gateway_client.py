import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import gateway_client


def test_send_fly_command_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"success": True}

    with patch("gateway_client.httpx.post", return_value=mock_response) as mock_post:
        result = gateway_client.send_fly_command("drone-01", "e4")

    assert result == {"ok": True, "response": {"success": True}}
    called_url, called_kwargs = mock_post.call_args
    assert called_url[0] == f"{gateway_client.GATEWAY_BASE_URL}/api/v1/messages"
    assert called_kwargs["json"] == {
        "robot_id": "drone-01",
        "text": "лети в клетку e4",
        "wait_for_answer": False,
    }


def test_send_fly_command_network_error_does_not_raise():
    with patch(
        "gateway_client.httpx.post", side_effect=httpx.ConnectError("boom")
    ):
        result = gateway_client.send_fly_command("drone-01", "e4")

    assert result["ok"] is False
    assert "boom" in result["error"]


def test_send_fly_command_http_status_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=MagicMock()
    )

    with patch("gateway_client.httpx.post", return_value=mock_response):
        result = gateway_client.send_fly_command("drone-01", "e4")

    assert result["ok"] is False


def test_get_robots_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [{"robot_id": "drone-01", "online": True}]

    with patch("gateway_client.httpx.get", return_value=mock_response) as mock_get:
        result = gateway_client.get_robots()

    assert result == {"ok": True, "robots": [{"robot_id": "drone-01", "online": True}]}
    called_url = mock_get.call_args[0][0]
    assert called_url == f"{gateway_client.GATEWAY_BASE_URL}/api/v1/robots"


def test_get_robots_network_error_does_not_raise():
    with patch("gateway_client.httpx.get", side_effect=httpx.ConnectError("down")):
        result = gateway_client.get_robots()

    assert result["ok"] is False
    assert "down" in result["error"]


def test_send_chat_message_success():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"success": True}

    with patch("gateway_client.httpx.post", return_value=mock_response) as mock_post:
        result = gateway_client.send_chat_message("@rover_01 статус")

    assert result == {"ok": True, "response": {"success": True}}
    called_url, called_kwargs = mock_post.call_args
    assert called_url[0] == f"{gateway_client.GATEWAY_BASE_URL}/api/v1/chat/send"
    assert called_kwargs["json"] == {"text": "@rover_01 статус"}


def test_send_chat_message_network_error_does_not_raise():
    with patch("gateway_client.httpx.post", side_effect=httpx.ConnectError("down")):
        result = gateway_client.send_chat_message("@rover_01 статус")

    assert result["ok"] is False
    assert "down" in result["error"]
