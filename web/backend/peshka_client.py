"""Pawn (peshka) move classification for the Gateway's peshka-agent bridge.

Pawns are reachable through the organizers' Gateway (sverk_ai_communication_server)
the same way every other robot is now - it used to be that there was no MQTT
bridge for them, only a direct HTTP API on their own IP (see
peshka-documentation.pdf), which is why this module originally drove that
API directly. The Gateway repo has since added one
(simulator/peshka_chess_agent.py in dark516/sverk_ai_communication_server):
a pseudo-agent that subscribes to the pawn's robot_id on MQTT and drives
that same HTTP API on our behalf, exposing a restricted RU vocabulary
instead of raw turn/distance commands: "вперёд на одну/две клетки" or "по
диагонали влево/вправо". That is not a limitation for chess - a pawn can
only ever move straight forward 1-2 squares or diagonally 1 square to
capture, so this vocabulary covers every legal pawn move exactly, and we
dispatch through the Gateway (gateway_client.ask_robots) like every other
piece instead of needing our own per-pawn IP config.

The bridge also has no absolute-heading concept and doesn't need one: a
pawn stays physically facing "forward" for its own color for the whole
match - no chess move ever turns it away and leaves it there (a diagonal
capture's turn is auto-restored by the bridge right after the move). So
unlike drones/rovers, nothing about a pawn's orientation needs to be
tracked on our side at all - "forward" always means "whatever way it's
currently facing", and left/right are fixed by color (see
classify_pawn_move)."""

from __future__ import annotations

FILES = "abcdefgh"


def classify_pawn_move(from_sq: str, to_sq: str, color: str) -> tuple[str, int | str] | None:
    """Classifies a chess move as ("forward", 1|2) or ("diagonal", "L"|"R")
    from the pawn's own physical point of view, or None if it isn't a shape
    a real pawn move can ever take - the caller should treat that as
    unsupported/illegal rather than send it to the robot.

    "L"/"R" are the pawn's own left/right while facing its color's advance
    direction: board file direction maps directly for white (increasing
    file is the robot's right, the same way it would be for a person
    standing on the white side facing the same way), and mirrored for
    black, which physically faces the opposite way down the board."""

    from_file, from_rank = FILES.index(from_sq[0]), int(from_sq[1])
    to_file, to_rank = FILES.index(to_sq[0]), int(to_sq[1])
    file_delta = to_file - from_file
    rank_dir = 1 if color == "white" else -1
    forward_delta = (to_rank - from_rank) * rank_dir

    if file_delta == 0 and forward_delta in (1, 2):
        return ("forward", forward_delta)

    if abs(file_delta) == 1 and forward_delta == 1:
        file_increasing_is_right = color == "white"
        turn_right = (file_delta > 0) == file_increasing_is_right
        return ("diagonal", "R" if turn_right else "L")

    return None


def pawn_move_text(move: tuple[str, int | str]) -> str:
    """RU command text matching peshka_chess_agent.PeshkaChessAgent.parse()
    in dark516/sverk_ai_communication_server exactly (see its `parse`
    method: "вперёд"/"клет" for forward, "две"/"два"/"2" for two cells,
    "диагонал"/"лев"/"прав" for a capture)."""

    kind, value = move
    if kind == "forward":
        return "вперёд на одну клетку" if value == 1 else "вперёд на две клетки"
    return f"по диагонали {'влево' if value == 'L' else 'вправо'}"
