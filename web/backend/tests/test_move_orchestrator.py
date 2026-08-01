import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        # execute_move() calls match_clock.sync_active_color(), which reads
        # these two keys - idle/unset is the fixture default so it stays a
        # no-op unless a test explicitly overrides it.
        "match_clock": {"status": "idle", "active_color": None},
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
        result = move_orchestrator._collect_votes(
            ["drone-01", "drone-02", "drone-03", "drone-04"], "fen", "knight", "g1", "f3", "развитие"
        )

    assert result["votes"] == [
        {"kind": "yes", "reason": "ок", "robot_id": "drone-01"},
        {"kind": "no", "reason": "плохо", "robot_id": "drone-04"},
    ]
    # drone-02 (success=False) and drone-03 (no answer text) asked but never
    # returned a usable vote - distinct from drone-01/04 who actually voted.
    assert result["no_response"] == ["drone-02", "drone-03"]
    assert mock_ask.call_args[0][0] == ["drone-01", "drone-02", "drone-03", "drone-04"]


def test_collect_votes_empty_quorum_skips_gateway_call():
    with patch("move_orchestrator.ask_robots") as mock_ask:
        result = move_orchestrator._collect_votes([], "fen", "knight", "g1", "f3", "x")
    assert result == {"votes": [], "no_response": []}
    mock_ask.assert_not_called()


def test_collect_votes_gateway_unreachable_treats_whole_quorum_as_no_response():
    with patch("move_orchestrator.ask_robots", return_value={"ok": False, "error": "down"}):
        result = move_orchestrator._collect_votes(["drone-01"], "fen", "knight", "g1", "f3", "x")
    assert result == {"votes": [], "no_response": ["drone-01"]}


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


def test_execute_move_allows_out_of_turn_move():
    # execute_move() itself does not gate on side_to_move - "manual" mode is
    # a debug mode that allows moving any piece regardless of whose turn it
    # officially is. The AI orchestrator enforces the turn check itself,
    # before ever calling execute_move (see propose_and_execute_move).
    app_state = make_app_state(side_to_move="black")
    with patch(
        "move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}
    ) as mock_send:
        result = move_orchestrator.execute_move(app_state, "g1", "f3")
    assert result["ok"] is True
    mock_send.assert_called_once_with("drone-06", "f3")


def test_execute_move_refuses_excluded_role_without_dispatching():
    app_state = make_app_state(excluded_roles=["knight_2"])
    with patch("move_orchestrator.send_fly_command") as mock_send:
        result = move_orchestrator.execute_move(app_state, "g1", "f3")
    assert result["ok"] is False
    assert "исключена" in result["error"]
    mock_send.assert_not_called()
    assert app_state["board"]["g1"]["piece"] == "knight"  # board unchanged


def test_execute_move_records_captured_piece_in_app_state():
    app_state = make_app_state()
    app_state["board"]["f3"] = {"color": "black", "piece": "pawn"}
    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        move_orchestrator.execute_move(app_state, "g1", "f3")
    assert app_state["captured_pieces"] == [{"color": "black", "piece": "pawn"}]


def test_execute_move_does_not_record_capture_on_non_capturing_move():
    app_state = make_app_state()
    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        move_orchestrator.execute_move(app_state, "g1", "f3")
    assert app_state.get("captured_pieces", []) == []


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
async def test_propose_and_execute_move_rejects_excluded_role_proposal(monkeypatch):
    # g1 is knight_2 for white (see state.py's BACK_RANK) - excluding it and
    # having the model keep proposing exactly that move should exhaust the
    # local retry budget without ever calling execute_move/the Gateway.
    app_state = make_app_state(excluded_roles=["knight_2"])
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
    )

    with patch("move_orchestrator.send_fly_command") as mock_send:
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is False
    assert result["attempts"][-1]["outcome"] == "local_validation_exhausted"
    mock_send.assert_not_called()
    assert app_state["board"]["g1"]["piece"] == "knight"


@pytest.mark.asyncio
async def test_propose_and_execute_move_model_error_retries_then_fails(monkeypatch):
    # A network blip talking to the strong model shouldn't abort the whole
    # round on the very first failure - it retries within the same
    # MAX_LOCAL_RETRIES budget used for illegal-move retries, so a
    # consistently-unavailable model still eventually fails, but only after
    # actually trying a few times.
    call_count = {"n": 0}

    def fake_call(fen, color, feedback=None):
        call_count["n"] += 1
        return {"ok": False, "error": "модель недоступна"}

    app_state = make_app_state()
    monkeypatch.setattr(move_orchestrator, "call_strong_model", fake_call)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is False
    assert "недоступна" in result["error"]
    assert call_count["n"] == move_orchestrator.MAX_LOCAL_RETRIES
    model_error_attempts = [a for a in result["attempts"] if a.get("outcome") == "model_error"]
    assert len(model_error_attempts) == move_orchestrator.MAX_LOCAL_RETRIES


@pytest.mark.asyncio
async def test_propose_and_execute_move_recovers_after_transient_model_error(monkeypatch):
    responses = [
        {"ok": False, "error": "таймаут"},
        {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
    ]

    def fake_call(fen, color, feedback=None):
        return responses.pop(0)

    app_state = make_app_state()
    monkeypatch.setattr(move_orchestrator, "call_strong_model", fake_call)
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: [])
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["f3"]["piece"] == "knight"


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
        lambda *args, **kwargs: {
            "votes": [{"kind": "yes", "reason": "ок", "robot_id": "drone-06"}],
            "no_response": [],
        },
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
async def test_propose_and_execute_move_records_no_response_robots():
    # A quorum member whose LLM never answered (network failure, malformed
    # plan, etc.) should be visible in the round log, not silently dropped -
    # otherwise "accepted because nobody said no" is indistinguishable from
    # "accepted because half the quorum's LLMs are down".
    app_state = make_app_state()
    with (
        patch(
            "move_orchestrator.call_strong_model",
            return_value={"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
        ),
        patch("move_orchestrator.compute_quorum", return_value=["drone-06", "drone-05"]),
        patch(
            "move_orchestrator.ask_robots",
            return_value={
                "ok": True,
                "response": {
                    "results": [
                        {"robot_id": "drone-06", "success": True, "answer": "ДА: ок"},
                        {"robot_id": "drone-05", "success": False, "answer": None},
                    ]
                },
            },
        ),
        patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}),
    ):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert result["round"]["attempts"][0]["no_response"] == ["drone-05"]


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

    # Pawns are dispatched through dispatch_pawn_move (Gateway + the
    # peshka-agent bridge's own RU vocabulary), not send_fly_command.
    with (
        patch(
            "move_orchestrator.dispatch_pawn_move",
            return_value={"ok": True, "answer": "Сходила вперёд на две клетки."},
        ) as mock_dispatch,
        patch("move_orchestrator.send_fly_command") as mock_send,
    ):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["e4"]["piece"] == "pawn"
    mock_dispatch.assert_called_once_with(app_state, "peshka-05", "e2", "e4")
    mock_send.assert_not_called()
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
        {"votes": [{"kind": "no", "reason": "плохо", "robot_id": "drone-06"}], "no_response": []},
        {"votes": [{"kind": "yes", "reason": "ок", "robot_id": "drone-06"}], "no_response": []},
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
        {
            "votes": [
                {"kind": "move", "move": {"from": "b1", "to": "c3"}, "reason": "центр", "robot_id": "drone-05"},
                {"kind": "move", "move": {"from": "b1", "to": "c3"}, "reason": "центр", "robot_id": "drone-06"},
            ],
            "no_response": [],
        },
        {"votes": [{"kind": "yes", "reason": "ок", "robot_id": "drone-05"}], "no_response": []},
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
        lambda *args, **kwargs: {
            "votes": [{"kind": "no", "reason": "всегда плохо", "robot_id": "drone-06"}],
            "no_response": [],
        },
    )

    with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
        result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)

    assert result["ok"] is True
    assert app_state["board"]["f3"]["piece"] == "knight"
    attempts = result["round"]["attempts"]
    assert len(attempts) == move_orchestrator.MAX_REGENERATIONS + 1
    assert attempts[-1].get("forced_after_regeneration_limit") is True


# --- execute_move tracks pending robot moves for chat_feed.check_pending_robot_move ---


def test_execute_move_tracks_pending_move_on_successful_dispatch():
    app_state = make_app_state()
    gateway_response = {"ok": True, "response": {"message_id": "msg-123"}}
    with patch("move_orchestrator.send_fly_command", return_value=gateway_response):
        move_orchestrator.execute_move(app_state, "g1", "f3")

    assert app_state["pending_robot_moves"]["drone-06"] == {
        "message_id": "msg-123",
        "from": "g1",
        "to": "f3",
    }


def test_execute_move_does_not_track_when_dispatch_fails():
    app_state = make_app_state()
    with patch(
        "move_orchestrator.send_fly_command",
        return_value={"ok": False, "error": "Robot drone-06 is offline"},
    ):
        move_orchestrator.execute_move(app_state, "g1", "f3")

    assert app_state.get("pending_robot_moves", {}) == {}


def test_execute_move_overwrites_previous_pending_entry_for_same_robot():
    app_state = make_app_state(
        pending_robot_moves={"drone-06": {"message_id": "old", "from": "g1", "to": "h3"}}
    )
    gateway_response = {"ok": True, "response": {"message_id": "new-msg"}}
    with patch("move_orchestrator.send_fly_command", return_value=gateway_response):
        move_orchestrator.execute_move(app_state, "g1", "f3")

    assert app_state["pending_robot_moves"]["drone-06"]["message_id"] == "new-msg"
    assert app_state["pending_robot_moves"]["drone-06"]["to"] == "f3"


def test_execute_move_does_not_track_when_gateway_rejects_without_message_id():
    # Gateway answers HTTP 200 (so gateway_client reports ok=True) but the
    # target was already known offline, so it refused to actually queue the
    # command - no message_id means nothing was ever dispatched to track.
    app_state = make_app_state()
    gateway_response = {
        "ok": True,
        "response": {"success": False, "message_id": None, "error": "Robot drone-06 is offline"},
    }
    with patch("move_orchestrator.send_fly_command", return_value=gateway_response):
        move_orchestrator.execute_move(app_state, "g1", "f3")

    assert app_state.get("pending_robot_moves", {}) == {}


# --- pawn moves dispatch through the Gateway's peshka-agent bridge -------------------


def _gateway_dispatch_ok(answer="Сходила вперёд на одну клетку."):
    return {"ok": True, "response": {"results": [
        {"robot_id": "peshka-05", "success": True, "answer": answer}
    ]}}


def test_execute_move_routes_pawn_through_gateway():
    app_state = make_app_state()
    with (
        patch(
            "move_orchestrator.ask_robots", return_value=_gateway_dispatch_ok()
        ) as mock_ask,
        patch("move_orchestrator.send_fly_command") as mock_send,
    ):
        result = move_orchestrator.execute_move(app_state, "e2", "e4")

    assert result["ok"] is True
    assert result["gateway_result"]["ok"] is True
    mock_ask.assert_called_once_with(
        ["peshka-05"], "вперёд на две клетки", timeout_sec=move_orchestrator.PAWN_MOVE_TIMEOUT_SEC
    )
    mock_send.assert_not_called()


def test_dispatch_pawn_move_sends_diagonal_text_for_capture():
    app_state = make_app_state()
    with patch(
        "move_orchestrator.ask_robots", return_value=_gateway_dispatch_ok("Сходила по диагонали.")
    ) as mock_ask:
        result = move_orchestrator.dispatch_pawn_move(app_state, "peshka-05", "e4", "f5")

    assert result["ok"] is True
    mock_ask.assert_called_once_with(
        ["peshka-05"], "по диагонали вправо", timeout_sec=move_orchestrator.PAWN_MOVE_TIMEOUT_SEC
    )


def test_dispatch_pawn_move_rejects_shape_no_pawn_can_take_without_network_call():
    app_state = make_app_state()
    with patch("move_orchestrator.ask_robots") as mock_ask:
        result = move_orchestrator.dispatch_pawn_move(app_state, "peshka-05", "b1", "c3")

    assert result["ok"] is False
    assert "e2" not in result["error"]  # sanity: real error mentions b1-c3, not a stale square
    assert "b1" in result["error"] and "c3" in result["error"]
    mock_ask.assert_not_called()


def test_dispatch_pawn_move_gateway_unreachable():
    app_state = make_app_state()
    with patch(
        "move_orchestrator.ask_robots", return_value={"ok": False, "error": "connection refused"}
    ):
        result = move_orchestrator.dispatch_pawn_move(app_state, "peshka-05", "e2", "e4")

    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_dispatch_pawn_move_robot_reports_failure():
    app_state = make_app_state()
    dispatch = {"ok": True, "response": {"results": [
        {"robot_id": "peshka-05", "success": False, "answer": "Занята, выполняю предыдущий ход."}
    ]}}
    with patch("move_orchestrator.ask_robots", return_value=dispatch):
        result = move_orchestrator.dispatch_pawn_move(app_state, "peshka-05", "e2", "e4")

    assert result["ok"] is False
    assert "Занята" in result["error"]


# --- propose_and_execute_move must not block the event loop -------------------------


@pytest.mark.asyncio
async def test_propose_and_execute_move_does_not_block_event_loop(monkeypatch):
    # call_strong_model is a plain blocking call (sync httpx under the hood);
    # simulating that with a real blocking time.sleep() here and proving a
    # concurrently-running coroutine keeps making progress is what actually
    # demonstrates the event loop wasn't frozen for the duration - a mock
    # that returns instantly wouldn't catch a regression back to a bare
    # (unwrapped) synchronous call.
    import time

    app_state = make_app_state()
    monkeypatch.setattr(
        move_orchestrator,
        "call_strong_model",
        lambda fen, color, feedback=None: (
            time.sleep(0.3),
            {"ok": True, "from": "g1", "to": "f3", "reasoning": "развитие"},
        )[1],
    )
    monkeypatch.setattr(move_orchestrator, "compute_quorum", lambda app_state: [])

    tick_count = 0

    async def ticker():
        nonlocal tick_count
        while True:
            await asyncio.sleep(0.02)
            tick_count += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        with patch("move_orchestrator.send_fly_command", return_value={"ok": True, "response": {}}):
            result = await move_orchestrator.propose_and_execute_move(app_state, _noop_broadcast)
    finally:
        ticker_task.cancel()

    assert result["ok"] is True
    # A blocked event loop would let the 0.3s sleep starve the ticker
    # entirely (0-1 ticks); a healthy one lets it fire roughly every 20ms.
    assert tick_count >= 5
