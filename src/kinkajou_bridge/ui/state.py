from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class UiState(BaseModel):
    welcome_completed: bool = False


class UiStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.state = UiState()

    def load(self) -> UiState:
        if not self.path.exists():
            self.state = UiState()
            return self.state
        self.state = UiState.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
        return self.state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.state.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    def mark_welcome_completed(self) -> UiState:
        self.state.welcome_completed = True
        self.save()
        return self.state
