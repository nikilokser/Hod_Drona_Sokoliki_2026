import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import move_orchestrator
from state import initial_board

BINDINGS = {
    "king": "drone-01",
    "queen": "drone-02",
    "bishop_1": "drone-03",
    "bishop_2": "drone-04",
    "knight_1": "drone-05",
    "knight_2": "drone-06",
    "rook_1": "rover-01",
    "rook_2": "rover-02",
    **{f"pawn_{i}": f"peshka-0{i}" for i in range(1, 9)},
}


def make_app_state(**overrides):
    state = {
        "board": initial_board("white", BINDINGS),
        "mode": "manual",
        "our_color": "white",
        "side_to_move": "white",
        "bindings": BINDINGS,
    }
    state.update(overrides)
    return state


async def _noop_broadcast(state):
    return None


def _sequence_strong_model(*results):
    it = iter(results)

    def _call(fen, color, feedback=None):
        return next(it)

    return _call


# --- to_validator_board -----------------------------------------------------


def test_to_validator_board_converts_shape():
    board = {"e2": {"color": "white", "piece": "pawn", "robot_id": "peshka-05", "role": "pawn_5"}}
    result = move_orchestrator.to_validator_board(board, "white")
    assert result == {"board": {"e2": ("white", "pawn")}, "side_to_move": "white"}


# --- parse_vote --------------------------------------------------------------


def test_parse_vote_yes():
    assert move_orchestrator.parse_vote("ДА: выглядит нормально") == {
        "kind": "yes",
        "reason": "выглядит нормально",
    }


def test_parse_vote_no():
    assert move_orchestrator.parse_vote("НЕТ: подставляет ферзя") == {
        "kind": "no",
        "reason": "подставляет ферзя",
    }


def test_parse_vote_move():
    result = move_orchestrator.parse_vote("ХОД: d2-d4: сильнее в центре")
    assert result == {
        "kind": "move",
        "move": {"from": "d2", "to": "d4"},
        "reason": "сильнее в центре",
    }


def test_parse_vote_move_case_insensitive():
    result = move_orchestrator.parse_vote("ход: g1-f3: развитие")
    assert result["kind"] == "move"
    assert result["move"] == {"from": "g1", "to": "f3"}


def test_parse_vote_noise_for_unrecognized_text():
    assert move_orchestrator.parse_vote("не знаю что сказать")["kind"] == "noise"


def test_parse_vote_noise_for_empty_answer():
    assert move_orchestrator.parse_vote("")["kind"] == "noise"


# --- decide_round --------------------------------------------------------------


def _board():
    return initial_board("white", BINDINGS)


def test_decide_round_accepted_when_all_yes():
    votes = [{"kind": "yes", "reason": "", "robot_id": "drone-06"}]
    assert move_orchestrator.decide_round(votes, _board(), "white")["outcome"] == "accepted"


def test_decide_round_accepted_when_no_votes_at_all():
    assert move_orchestrator.decide_round([], _board(), "white")["outcome"] == "accepted"


def test_decide_round_vetoed_on_single_no():
    votes = [{"kind": "no", "reason": "плохо", "robot_id": "drone-06"}]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "vetoed"
    assert decision["no_votes"] == votes


def test_decide_round_single_alternative_below_threshold_falls_back_to_veto():
    votes = [
        {"kind": "move", "move": {"from": "g1", "to": "f3"}, "reason": "", "robot_id": "drone-06"},
        {"kind": "no", "reason": "плохо", "robot_id": "drone-01"},
    ]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "vetoed"


def test_decide_round_escalates_alternative_at_threshold():
    votes = [
        {"kind": "move", "move": {"from": "g1", "to": "f3"}, "reason": "центр", "robot_id": "drone-06"},
        {"kind": "move", "move": {"from": "g1", "to": "f3"}, "reason": "центр", "robot_id": "drone-05"},
    ]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "escalated_alternative"
    assert decision["alternative"] == {"from": "g1", "to": "f3"}
    assert len(decision["supporters"]) == 2


def test_decide_round_alternative_beats_veto_at_threshold():
    votes = [
        {"kind": "move", "move": {"from": "g1", "to": "f3"}, "reason": "", "robot_id": "drone-06"},
        {"kind": "move", "move": {"from": "g1", "to": "f3"}, "reason": "", "robot_id": "drone-05"},
        {"kind": "no", "reason": "плохо", "robot_id": "drone-01"},
    ]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "escalated_alternative"


def test_decide_round_illegal_alternative_dropped_as_noise():
    # e1-e2: king one square forward, but e2 is occupied by our own pawn.
    votes = [
        {"kind": "move", "move": {"from": "e1", "to": "e2"}, "reason": "", "robot_id": "drone-06"},
        {"kind": "move", "move": {"from": "e1", "to": "e2"}, "reason": "", "robot_id": "drone-05"},
    ]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "accepted"


def test_decide_round_pawn_alternative_escalates():
    # Pawn moves are legal proposals now (they just have no per-piece voting
    # agent) - a repeated pawn alternative escalates like any other piece.
    votes = [
        {"kind": "move", "move": {"from": "e2", "to": "e4"}, "reason": "", "robot_id": "drone-06"},
        {"kind": "move", "move": {"from": "e2", "to": "e4"}, "reason": "", "robot_id": "drone-05"},
    ]
    decision = move_orchestrator.decide_round(votes, _board(), "white")
    assert decision["outcome"] == "escalated_alternative"
    assert decision["alternative"] == {"from": "e2", "to": "e4"}


# --- compute_quorum --------------------------------------------------------


def test_compute_quorum_excludes_pawns_offline_and_off_board_robots():
    board = initial_board("white", BINDINGS)
    fake_robots = {
        "ok": True,
        "robots": [
            {"robot_id": "drone-01", "type": "ros1_drone", "online": True, "enabled": True},
            {"robot_id": "drone-02", "type": "ros1_drone", "online": False, "enabled": True},
            {"robot_id": "rover-01", "type": "ros2_rover", "online": True, "enabled": True},
            {"robot_id": "peshka-05", "type": "peshka", "online": True, "enabled": True},
            {"robot_id": "drone-99", "type": "ros1_drone", "online": True, "enabled": True},
        ],
    }
    with patch("move_orchestrator.get_robots", return_value=fake_robots):
        quorum = move_orchestrator.compute_quorum({"board": board})

    # drone-02 offline, peshka-05 is a pawn, drone-99 online but not bound to
    # any piece currently on the board - all excluded.
    assert quorum == ["drone-01", "rover-01"]


def test_compute_quorum_empty_when_gateway_unreachable():
    with patch("move_orchestrator.get_robots", return_value={"ok": False, "error": "down"}):
        quorum = move_orchestrator.compute_quorum({"board": initial_board("white", BINDINGS)})
    assert quorum == []


# --- _collect_votes --------------------------------------------------------


def test_collect_votes_parses_and_filters_results():
    fake_dispatch = {
        "ok": True,
        "response": {
            "results": [
                {"robot_id": "drone-01", "success": True, "answer": "ДА: ок"},
                {"robot_id": "drone-02", "success": False, "answer": None},
                {"robot_id": "drone-03", "success": True, "answer": None},
                {"robot_id": "drone-04", "success": True, "answer": "НЕТ: плохо"},
            ]
        },
    }
    with patch("move_orchestrator.ask_robots", return_value=fake_dispatch) as mock_ask:
        votes = move_orchestrator._collect_votes(
            ["drone-01", "drone-02", "drone-03", "drone-04"], "fen", "knight", "g1", "f3", "развитие"
        )

    assert votes == [
        {"kind": "yes", "reason": "ок", "robot_id": "drone-01"},
        {"kind": "no", "reason": "плохо", "robot_id": "drone-04"},
    ]
    assert mock_ask.call_args[0][0] == ["drone-01", "drone-02", "drone-03", "drone-04"]


def test_collect_votes_empty_quorum_skips_gateway_call():
    with patch("move_orchestrator.ask_robots") as mock_ask:
        votes = move_orchestrator._collect_votes([], "fen", "knight", "g1", "f3", "x")
    assert votes == []
    mock_ask.assert_not_called()


def test_collect_votes_gateway_unreachable_returns_empty():
    with patch("move_orchestrator.ask_robots", return_value={"ok": False, "error": "down"}):
        votes = move_orchestrator._collect_votes(["drone-01"], "fen", "knight", "g1", "f3", "x")
    assert votes == []


# --- call_strong_model --------------------------------------------------------


def test_call_strong_model_success(monkeypatch):
    monkeypatch.setattr(move_orchestrator, "STRONG_MODEL_API_KEY", "test-key")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"from": "g1", "to": "f3", "reasoning": "развитие"}'}}]
    }
    with patch("move_orchestrator.httpx.post", return_value=mock_response):
        result = move_orchestrator.call_strong_model("fen", "white")

    assert result == {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"}


def test_call_strong_model_missing_key(monkeypatch):
    monkeypatch.setattr(move_orchestrator, "STRONG_MODEL_API_KEY", "")
    result = move_orchestrator.call_strong_model("fen", "white")
    assert result["ok"] is False


def test_call_strong_model_bad_json_content(monkeypatch):
    monkeypatch.setattr(move_orchestrator, "STRONG_MODEL_API_KEY", "test-key")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    with patch("move_orchestrator.httpx.post", return_value=mock_response):
        result = move_orchestrator.call_strong_model("fen", "white")
    assert result["ok"] is False


def test_call_strong_model_network_error(monkeypatch):
    monkeypatch.setattr(move_orchestrator, "STRONG_MODEL_API_KEY", "test-key")
    with patch("move_orchestrator.httpx.post", side_effect=httpx.ConnectError("down")):
        result = move_orchestrator.call_strong_model("fen", "white")
    assert result["ok"] is False


# --- execute_move --------------------------------------------------------


def test_execute_move_dispatches_to_gateway_and_flips_side_to_move():
    app_state = make_app_state()
    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        result = move_orchestrator.execute_move(app_state, "g1", "f3")

    assert result["ok"] is True
    mock_send.assert_called_once_with("drone-06", "f3")
    assert app_state["board"]["f3"]["piece"] == "knight"
    assert app_state["side_to_move"] == "black"


def test_execute_move_rejects_wrong_turn():
    app_state = make_app_state(side_to_move="black")
    with patch("move_orchestrator.send_fly_command") as mock_send:
        result = move_orchestrator.execute_move(app_state, "g1", "f3")
    assert result["ok"] is False
    mock_send.assert_not_called()


# --- propose_and_execute_move (full round) --------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_and_execute_move_rejects_wrong_mode():
    app_state = make_app_state(mode="correct")
    result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_propose_and_execute_move_allowed_in_view_mode(monkeypatch):
    # TEMPORARY debug relaxation (see move_orchestrator.py) - view mode is
    # allowed alongside manual until the orchestrator is stable.
    app_state = make_app_state(mode="view")
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {
            "ok": True, "from": "b1", "to": "c3", "reasoning": "test"
        },
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: [])
    with patch("move_orchestrator.send_fly_command", return_value={"ok": True}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_propose_and_execute_move_rejects_when_not_our_turn():
    app_state = make_app_state(side_to_move="black")
    result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_propose_and_execute_move_model_error_aborts(monkeypatch):
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {"ok": False, "error": "модель недоступна"},
    )
    result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)
    assert result["ok"] is False
    assert "недоступна" in result["error"]


@pytest.mark.asyncio
async def test_propose_and_execute_move_accepted_no_quorum(monkeypatch):
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: [])

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["f3"]["piece"] == "knight"
    assert result["round"]["attempts"][0]["outcome"] == "accepted_no_quorum"


@pytest.mark.asyncio
async def test_propose_and_execute_move_accepted_all_yes(monkeypatch):
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: ["drone-06"])
    monkeypatch.setattr(
        move_orchestrator,
        "_collect_votes",
        lambda *args, **kwargs: [{"kind": "yes", "reason": "ок", "robot_id": "drone-06"}],
    )

    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    mock_send.assert_called_once_with("drone-06", "f3")
    assert app_state["board"]["f3"]["piece"] == "knight"
    assert app_state["orchestrator_log"][-1] == result["round"]


@pytest.mark.asyncio
async def test_propose_and_execute_move_pawn_proposal_accepted(monkeypatch):
    # Pawns should move too via the orchestrator - they just have no
    # per-piece voting agent (compute_quorum already excludes pawn robots;
    # this is about the model being ALLOWED to propose one in the first
    # place, which used to be rejected).
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {
            "ok": True, "from": "e2", "to": "e4", "reasoning": "пешка вперёд"
        },
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: [])

    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["e4"]["piece"] == "pawn"
    mock_send.assert_called_once_with("peshka-05", "e4")
    assert len(result["round"]["attempts"]) == 1


@pytest.mark.asyncio
async def test_propose_and_execute_move_vetoed_then_regenerated_and_accepted(monkeypatch):
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        _sequence_strong_model(
            {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие коня"},
            {"ok": True, "from": "b1", "to": "c3", "reasoning": "другое развитие"},
        ),
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: ["drone-06"])

    vote_sequence = [
        [{"kind": "no", "reason": "плохо", "robot_id": "drone-06"}],
        [{"kind": "yes", "reason": "ок", "robot_id": "drone-06"}],
    ]
    monkeypatch.setattr(
        move_orchestrator, "_collect_votes", lambda *args, **kwargs: vote_sequence.pop(0)
    )

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["c3"]["piece"] == "knight"
    attempts = result["round"]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["outcome"] == "vetoed"
    assert attempts[1]["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_propose_and_execute_move_escalated_alternative_feeds_back_to_model(monkeypatch):
    app_state = make_app_state()
    calls = []

    def fake_call_strong_model(fen, color, feedback=None):
        calls.append(feedback)
        if len(calls) == 1:
            return {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие коня"}
        return {"ok": True, "from": "b1", "to": "c3", "reasoning": "как посоветовали"}

    monkeypatch.setattr(move_orchestrator, "call_strong_model", fake_call_strong_model)
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: ["drone-05", "drone-06"])

    vote_sequence = [
        [
            {"kind": "move", "move": {"from": "b1", "to": "c3"}, "reason": "центр", "robot_id": "drone-05"},
            {"kind": "move", "move": {"from": "b1", "to": "c3"}, "reason": "центр", "robot_id": "drone-06"},
        ],
        [{"kind": "yes", "reason": "ок", "robot_id": "drone-05"}],
    ]
    monkeypatch.setattr(
        move_orchestrator, "_collect_votes", lambda *args, **kwargs: vote_sequence.pop(0)
    )

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["c3"]["piece"] == "knight"
    assert calls[0] is None
    assert "b1-c3" in calls[1]
    assert result["round"]["attempts"][0]["outcome"] == "escalated_alternative"


@pytest.mark.asyncio
async def test_propose_and_execute_move_forced_after_regeneration_limit(monkeypatch):
    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: ["drone-06"])
    monkeypatch.setattr(
        move_orchestrator,
        "_collect_votes",
        lambda *args, **kwargs: [{"kind": "no", "reason": "всегда плохо", "robot_id": "drone-06"}],
    )

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["f3"]["piece"] == "knight"
    attempts = result["round"]["attempts"]
    assert len(attempts) == move_orchestrator.MAX_REGENERATIONS + 1
    assert attempts[-1].get("forced_after_regeneration_limit") is True
