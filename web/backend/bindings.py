"""Loads the robot-to-piece-role bindings config (see state.py for the role
names). Bindings are static for the whole match - loaded once at startup."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_BINDINGS_PATH = Path(__file__).parent / "config" / "bindings.json"


def load_bindings(path: Path = DEFAULT_BINDINGS_PATH) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
