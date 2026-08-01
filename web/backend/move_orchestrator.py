"""AI-driven move proposal, negotiation with piece agents, and execution.

See docs/superpowers/specs/2026-07-31-ai-move-negotiation-design.md for the
full design. High-level flow per round: a strong model proposes a move for
our side, for any piece including pawns -> validated locally for legality
-> broadcast to the online piece agents bound to our still-on-board,
non-pawn pieces for a да/нет/ход vote (pawns have no per-piece agent - they
are excluded from the voting quorum, per the regulation's single pawn
dispatcher, but a pawn CAN still be the piece the model proposes and moves)
-> a repeated alternative move wins over a plain veto -> up to two
regenerations -> the last locally-valid proposal is executed either way
(fail-open) via the same apply_move + send_fly_command path "manual"
drag-and-drop already uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable

import httpx

# move_validator lives at the repo root, not under web/backend - add it to
# sys.path the same way the test suite already does one level closer
# (see tests/test_*.py's sys.path.insert for web/backend itself).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from move_validator import validate_move  # noqa: E402 (see sys.path setup above)

import peshka_client
from gateway_client import ask_robots, get_robots, send_fly_command
from match_clock import sync_active_color
from state import apply_move
from stockfish_client import board_to_fen

STRONG_MODEL_BASE_URL = os.environ.get("STRONG_MODEL_BASE_URL", "https://ai.sverk.io/v1")
STRONG_MODEL_API_KEY = os.environ.get("STRONG_MODEL_API_KEY", "")
STRONG_MODEL_NAME = os.environ.get("STRONG_MODEL_NAME", "deepseek-v4-pro")

MAX_REGENERATIONS = 2
# Illegal proposals rejected by our own local validator, before ever talking
# to the drones - cheap, doesn't spend the regeneration budget above.
MAX_LOCAL_RETRIES = 3
VOTE_ANSWER_TIMEOUT_SEC = 30.0
ALTERNATIVE_ESCALATION_THRESHOLD = 2

PIECE_RU = {
    "king": "короля",
    "queen": "ферзя",
    "rook": "ладью",
    "bishop": "слона",
    "knight": "коня",
    "pawn": "пешку",
}

STRONG_MODEL_SYSTEM_PROMPT = (
    "Ты выбираешь ход за сторону {color} в упрощённых шахматах (без рокировки, "
    "взятия на проходе, превращения пешки). Ходить можно любой своей фигурой, "
    "включая пешки. Верни только JSON без markdown и пояснений вне полей: "
    '{{"from": "e2", "to": "e4", "reasoning": "короткое обоснование по-русски"}}.'
)

_MOVE_ANSWER_RE = re.compile(
    r"^ход\s*:\s*([a-h][1-8])\s*-\s*([a-h][1-8])\s*:?\s*(.*)$", re.IGNORECASE
)


def to_validator_board(board: dict, side_to_move: str) -> dict:
    """Adapts state.py's board format ({"e2": {"color": ..., "piece": ...}})
    to move_validator's expected format ({"e2": ("color", "piece")})."""

    return {
        "board": {sq: (occupant["color"], occupant["piece"]) for sq, occupant in board.items()},
        "side_to_move": side_to_move,
    }


def _is_legal_move(
    board: dict, side_to_move: str, from_sq: str, to_sq: str, excluded_roles: list[str] = ()
) -> tuple[bool, str | None]:
    occupant = board.get(from_sq)
    if occupant is None:
        return False, f"На клетке {from_sq} нет фигуры"

    if occupant.get("role") in excluded_roles:
        return False, f"Фигура «{occupant['role']}» исключена из ходов оператором"

    result = validate_move(
        to_validator_board(board, side_to_move),
        {"piece": occupant["piece"], "from": from_sq, "to": to_sq},
    )
    if not result["legal"]:
        return False, result["reason"]
    return True, None


def _build_strong_model_messages(fen: str, our_color: str, feedback: str | None) -> list[dict]:
    system = STRONG_MODEL_SYSTEM_PROMPT.format(color="белых" if our_color == "white" else "чёрных")
    user = f"Позиция (FEN): {fen}."
    if feedback:
        user += f" {feedback}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_strong_model(fen: str, our_color: str, feedback: str | None = None) -> dict:
    """Asks the strong model for a move. Returns
    {"ok": True, "from": ..., "to": ..., "reasoning": ...} or
    {"ok": False, "error": ...} - same shape convention as gateway_client/
    stockfish_client, never raises."""

    if not STRONG_MODEL_API_KEY:
        return {"ok": False, "error": "STRONG_MODEL_API_KEY не задан"}

    payload = {
        "model": STRONG_MODEL_NAME,
        "messages": _build_strong_model_messages(fen, our_color, feedback),
        "temperature": 0.2,
    }
    try:
        response = httpx.post(
            f"{STRONG_MODEL_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {STRONG_MODEL_API_KEY}"},
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {
            "ok": True,
            "from": parsed["from"],
            "to": parsed["to"],
            "reasoning": str(parsed.get("reasoning", "")),
        }
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"Некорректный ответ модели: {exc}"}


def _build_vote_message(fen: str, piece: str, from_sq: str, to_sq: str, reasoning: str) -> str:
    return (
        f"[ГОЛОСОВАНИЕ] Позиция: {fen}. Предложен ход {PIECE_RU.get(piece, piece)} "
        f"{from_sq}-{to_sq}. Обоснование: {reasoning}. "
        'Ответь строго одной строкой в одном из форматов: '
        '"ДА: <причина>", "НЕТ: <причина>" или "ХОД: <клетка>-<клетка>: <причина>".'
    )


def parse_vote(text: str) -> dict:
    """Classifies one agent's raw answer text into да ("yes") / нет ("no") /
    ход ("move") / anything else ("noise", ignored by the decision rule)."""

    stripped = (text or "").strip()
    upper = stripped.upper()

    if upper.startswith("ДА"):
        return {"kind": "yes", "reason": stripped[2:].lstrip(": ").strip()}
    if upper.startswith("НЕТ"):
        return {"kind": "no", "reason": stripped[3:].lstrip(": ").strip()}

    match = _MOVE_ANSWER_RE.match(stripped)
    if match:
        return {
            "kind": "move",
            "move": {"from": match.group(1).lower(), "to": match.group(2).lower()},
            "reason": match.group(3).strip(),
        }

    return {"kind": "noise", "reason": stripped}


def compute_quorum(app_state: dict) -> list[str]:
    """Robots eligible to vote this round: online, not a pawn, and bound to
    one of our own pieces still on the board. Deliberately dynamic rather
    than a hardcoded roster - a rover joins automatically once it is online
    with a working agent, and a drone that drops offline (observed on
    sverk-8) is automatically excluded instead of stalling the round on its
    timeout."""

    robots_result = get_robots()
    if not robots_result.get("ok"):
        return []

    online_non_pawn = {
        robot["robot_id"]
        for robot in robots_result["robots"]
        if robot.get("online") and robot.get("enabled") and robot.get("type") != "peshka"
    }
    on_board_robot_ids = {
        occupant["robot_id"] for occupant in app_state["board"].values() if "robot_id" in occupant
    }
    return sorted(online_non_pawn & on_board_robot_ids)


def _collect_votes(
    quorum: list[str], fen: str, piece: str, from_sq: str, to_sq: str, reasoning: str
) -> dict:
    """Returns {"votes": [...], "no_response": [robot_id, ...]}.

    no_response lists quorum members who were asked to vote but never
    returned a usable answer - a Gateway dispatch failure, the robot's own
    LLM connection timing out or being unreachable, a malformed non-JSON
    plan from its fallback planner, etc. (observed in practice for all of
    these - see chat_history.jsonl "Ошибка агента: LLM connection error"/
    "LLM JSON planner returned non-JSON content" entries). All of these
    look identical from here (just a missing/unsuccessful result), but
    surfacing *which* robot_ids didn't answer at all - as opposed to a
    round that got real "да"/"нет" votes - is what lets an operator tell
    "no one objected" apart from "half the quorum's LLMs are failing"."""

    if not quorum:
        return {"votes": [], "no_response": []}

    text = _build_vote_message(fen, piece, from_sq, to_sq, reasoning)
    dispatch = ask_robots(quorum, text, timeout_sec=VOTE_ANSWER_TIMEOUT_SEC)
    if not dispatch.get("ok"):
        return {"votes": [], "no_response": list(quorum)}

    votes = []
    answered: set[str] = set()
    for item in dispatch["response"].get("results", []):
        if not item.get("success") or not item.get("answer"):
            continue
        parsed = parse_vote(item["answer"])
        parsed["robot_id"] = item["robot_id"]
        votes.append(parsed)
        answered.add(item["robot_id"])

    no_response = [robot_id for robot_id in quorum if robot_id not in answered]
    return {"votes": votes, "no_response": no_response}


def decide_round(votes: list[dict], board: dict, side_to_move: str) -> dict:
    """Applies the priority rule over one round's votes: an alternative move
    that at least ALTERNATIVE_ESCALATION_THRESHOLD independent agents agree
    on outranks a plain veto (it carries more information for the strong
    model to act on than a bare "no"). Alternatives are re-validated locally
    before counting toward the threshold, so a hallucinated/illegal
    suggestion is dropped as noise rather than counted."""

    alt_supporters: dict[tuple[str, str], list[dict]] = {}
    for vote in votes:
        if vote["kind"] != "move":
            continue
        move = vote["move"]
        legal, _reason = _is_legal_move(board, side_to_move, move["from"], move["to"])
        if not legal:
            continue
        alt_supporters.setdefault((move["from"], move["to"]), []).append(vote)

    for (from_sq, to_sq), supporters in alt_supporters.items():
        if len(supporters) >= ALTERNATIVE_ESCALATION_THRESHOLD:
            return {
                "outcome": "escalated_alternative",
                "alternative": {"from": from_sq, "to": to_sq},
                "supporters": supporters,
            }

    no_votes = [v for v in votes if v["kind"] == "no"]
    if no_votes:
        return {"outcome": "vetoed", "no_votes": no_votes}

    return {"outcome": "accepted"}


def execute_move(app_state: dict, from_sq: str, to_sq: str) -> dict:
    """Applies a move exactly like POST /api/move does in "manual" mode:
    applies the board move, and if the moved piece is ours (bound to a
    robot_id), dispatches the physical flight command through the Gateway.
    Shared by the manual drag-and-drop endpoint and this orchestrator so
    both execute a move identically.

    Does not itself gate on side_to_move - "manual" (debug) mode
    deliberately allows moving any piece regardless of whose turn it
    officially is. The AI orchestrator still only ever proposes a move for
    the correct side (checked in propose_and_execute_move before this is
    ever called), so nothing upstream relies on this function refusing an
    out-of-turn move."""

    occupant = app_state["board"].get(from_sq)
    excluded_role = occupant.get("role") if occupant else None
    if excluded_role and excluded_role in app_state.get("excluded_roles", []):
        return {
            "ok": False,
            "error": (
                f"фигура «{excluded_role}» исключена из ходов оператором "
                "(см. вкладку «Привязка роботов»)"
            ),
        }

    new_board, result = apply_move(
        app_state["board"], "manual", from_sq, to_sq, our_color=app_state["our_color"]
    )
    if not result["ok"]:
        return result

    app_state["board"] = new_board
    app_state["side_to_move"] = "black" if new_board[to_sq]["color"] == "white" else "white"
    app_state["match_clock"] = sync_active_color(app_state["match_clock"], app_state["side_to_move"])
    app_state["last_move"] = {
        "from": from_sq,
        "to": to_sq,
        "color": new_board[to_sq]["color"],
        "piece": new_board[to_sq]["piece"],
    }
    if result.get("captured_piece"):
        app_state.setdefault("captured_pieces", []).append(result["captured_piece"])

    if result["moved_robot_id"]:
        robot_id = result["moved_robot_id"]
        if new_board[to_sq]["piece"] == "pawn":
            # Pawns aren't reachable through the Gateway at all - no MQTT
            # bridge exists for them, only a direct HTTP API on their own IP
            # (see peshka_client.py). This call is synchronous and already
            # waits for the robot to report the real outcome, so none of the
            # fire-and-forget/offline-tracking machinery below applies here.
            result["gateway_result"] = dispatch_pawn_move(app_state, robot_id, from_sq, to_sq)
        else:
            gateway_result = send_fly_command(robot_id, to_sq)
            result["gateway_result"] = gateway_result
            # gateway_result["ok"] only means the HTTP call to Gateway itself
            # succeeded - Gateway still answers with HTTP 200 + success=False
            # (and no message_id) when it rejects the command outright, e.g. the
            # target was already known offline before we ever tried (see
            # reject_offline_commands in the Gateway). Only a real message_id
            # means the robot actually received the command and is now supposed
            # to be doing something - that's the only case worth watching for a
            # later "went offline mid-flight" alert (see
            # chat_feed.check_pending_robot_move). Dispatch is fire-and-forget
            # (send_fly_command doesn't wait for an answer), so this pending-move
            # record is the only trace that anything is in flight at all.
            message_id = (gateway_result.get("response") or {}).get("message_id")
            if message_id:
                app_state.setdefault("pending_robot_moves", {})[robot_id] = {
                    "message_id": message_id,
                    "from": from_sq,
                    "to": to_sq,
                }

    return result


def dispatch_pawn_move(app_state: dict, robot_id: str, from_sq: str, to_sq: str) -> dict:
    """Drives a pawn robot from from_sq to to_sq over its direct HTTP API
    and keeps our own heading tracking (app_state["peshka_headings"]) in
    sync with what it actually did - the robot itself has no absolute
    heading, only wheel encoder counters, so this is the only place that
    knows which way it's currently facing on the board."""

    ip = app_state.get("peshka_ips", {}).get(robot_id)
    if not ip:
        return {
            "ok": False,
            "error": f"IP пешки {robot_id} не настроен (см. web/backend/config/peshka_ips.json)",
        }

    headings = app_state.setdefault("peshka_headings", {})
    current_heading = headings.get(
        robot_id, peshka_client.initial_heading_deg(app_state["our_color"])
    )

    result = peshka_client.move_pawn_to_cell(ip, from_sq, to_sq, current_heading)
    if result.get("ok"):
        headings[robot_id] = result["resulting_heading_deg"]
    return result


async def propose_and_execute_move(
    app_state: dict, broadcast: Callable[[dict], Awaitable[None]]
) -> dict:
    # TEMPORARY: also allowed in "view" for debugging the orchestrator
    # end-to-end without switching modes. execute_move() below already
    # hardcodes apply_move's mode to "manual" regardless of app_state["mode"],
    # so this is the only gate that needs relaxing. Narrow this back to
    # "manual" only once the orchestrator is stable (per user request).
    if app_state["mode"] not in ("manual", "view"):
        return {"ok": False, "error": "Предложение хода доступно только в режиме «Ручные ходы»"}

    our_color = app_state["our_color"]
    side_to_move = app_state["side_to_move"]
    if side_to_move != our_color:
        return {"ok": False, "error": "Сейчас не ваш ход"}

    # The round is visible to every connected client from the moment it
    # starts (not just once it finishes) - a full round (model calls +
    # up to 3 vote-collection timeouts of up to VOTE_ANSWER_TIMEOUT_SEC each)
    # can take minutes, and clicking the button then waiting on a single
    # static "Идёт согласование хода…" with no visible progress made it
    # impossible to tell a slow round from a stuck one. `attempts` is the
    # same list object as round_log["attempts"], so appending to it and
    # broadcasting after each step makes every attempt appear live.
    round_log: dict = {"attempts": [], "final_proposal": None, "execution": None, "in_progress": True}
    app_state.setdefault("orchestrator_log", []).append(round_log)
    await broadcast(app_state)

    attempts: list[dict] = round_log["attempts"]
    feedback: str | None = None
    regenerations = 0
    accepted_proposal: dict | None = None

    while True:
        proposal = None
        for _ in range(MAX_LOCAL_RETRIES):
            # call_strong_model/compute_quorum/_collect_votes/execute_move are
            # all plain blocking calls (sync httpx, even time.sleep() polling
            # inside peshka_client) - run in a worker thread via to_thread so
            # a single round (which can take minutes) doesn't freeze the
            # entire asyncio event loop. Without this, Stockfish's continuous
            # analysis background task and every other request to this
            # backend would stall for the whole duration of the round.
            candidate = await asyncio.to_thread(
                call_strong_model, board_to_fen(app_state["board"], side_to_move), our_color, feedback
            )
            if not candidate.get("ok"):
                attempts.append({"proposal": candidate, "outcome": "model_error"})
                round_log["in_progress"] = False
                await broadcast(app_state)
                return {"ok": False, "error": candidate.get("error"), "attempts": attempts}

            legal, reason = _is_legal_move(
                app_state["board"],
                side_to_move,
                candidate["from"],
                candidate["to"],
                app_state.get("excluded_roles", []),
            )
            if legal:
                proposal = {**candidate, "piece": app_state["board"][candidate["from"]]["piece"]}
                break
            feedback = (
                f"Предыдущее предложение {candidate.get('from')}-{candidate.get('to')} "
                f"отклонено локальной проверкой: {reason}. Предложи другой ход."
            )

        if proposal is None:
            attempts.append({"outcome": "local_validation_exhausted"})
            round_log["in_progress"] = False
            await broadcast(app_state)
            return {
                "ok": False,
                "error": "Не удалось получить легальный ход от модели",
                "attempts": attempts,
            }

        quorum = await asyncio.to_thread(compute_quorum, app_state)
        if not quorum:
            attempts.append({"proposal": proposal, "outcome": "accepted_no_quorum", "quorum": []})
            await broadcast(app_state)
            accepted_proposal = proposal
            break

        vote_result = await asyncio.to_thread(
            _collect_votes,
            quorum,
            board_to_fen(app_state["board"], side_to_move),
            proposal["piece"],
            proposal["from"],
            proposal["to"],
            proposal["reasoning"],
        )
        votes = vote_result["votes"]
        decision = decide_round(votes, app_state["board"], side_to_move)
        attempts.append({
            "proposal": proposal,
            "votes": votes,
            "no_response": vote_result["no_response"],
            "quorum": quorum,
            **decision,
        })
        await broadcast(app_state)

        if decision["outcome"] == "accepted":
            accepted_proposal = proposal
            break

        regenerations += 1
        if regenerations > MAX_REGENERATIONS:
            accepted_proposal = proposal
            attempts[-1]["forced_after_regeneration_limit"] = True
            break

        if decision["outcome"] == "escalated_alternative":
            alt = decision["alternative"]
            feedback = (
                f"{len(decision['supporters'])} агентов предложили другой ход "
                f"{alt['from']}-{alt['to']}. Учти это при выборе следующего хода."
            )
        else:  # vetoed
            reasons = "; ".join(v["reason"] for v in decision["no_votes"] if v["reason"])
            feedback = (
                f"Ход {proposal['from']}-{proposal['to']} отклонён голосованием. "
                f"Причины: {reasons or 'без деталей'}. Предложи другой ход."
            )

    result = await asyncio.to_thread(
        execute_move, app_state, accepted_proposal["from"], accepted_proposal["to"]
    )
    round_log["final_proposal"] = accepted_proposal
    round_log["execution"] = result
    round_log["in_progress"] = False
    await broadcast(app_state)
    return {"ok": bool(result.get("ok")), "round": round_log}
