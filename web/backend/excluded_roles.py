"""Loads/saves which piece roles are excluded from being moved (see
state.py for role names) - an operator-set flag for a piece whose robot is
known broken/unavailable (e.g. a stuck kill switch), so the AI orchestrator
stops proposing moves for it and manual dispatch refuses to send it a
command. Persisted the same way bindings.py persists role->robot_id, so it
survives a server restart mid-match."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_EXCLUDED_ROLES_PATH = Path(__file__).parent / "config" / "excluded_roles.json"


def load_excluded_roles(path: Path = DEFAULT_EXCLUDED_ROLES_PATH) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_excluded_roles(
    excluded_roles: list[str], path: Path = DEFAULT_EXCLUDED_ROLES_PATH
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(excluded_roles), f, ensure_ascii=False, indent=2)
        f.write("\n")
