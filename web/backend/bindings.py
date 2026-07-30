"""Loads/saves the robot-to-piece-role bindings config (see state.py for the
role names). Bindings are set up once before a match but can now be edited
live through the UI/API, so they are persisted back to disk on every
change to survive a server restart."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_BINDINGS_PATH = Path(__file__).parent / "config" / "bindings.json"


def load_bindings(path: Path = DEFAULT_BINDINGS_PATH) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_bindings(bindings: dict[str, str], path: Path = DEFAULT_BINDINGS_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bindings, f, ensure_ascii=False, indent=2)
        f.write("\n")
