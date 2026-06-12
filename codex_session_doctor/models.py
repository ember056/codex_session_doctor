from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThreadRecord:
    id: str
    title: str
    cwd: str
    rollout_path: str
    source: str
    model_provider: str
    model: str | None
    archived: int
    updated_at: int
    preview: str
    first_user_message: str

    @property
    def is_subagent_review(self) -> bool:
        return "subagent" in (self.source or "").lower() or "guardian" in (self.source or "").lower()

    @property
    def rollout_exists(self) -> bool:
        return bool(self.rollout_path) and Path(self.rollout_path).exists()


@dataclass(frozen=True)
class SessionMeta:
    thread_id: str
    path: Path
    cwd: str
    model_provider: str
    model: str | None


@dataclass(frozen=True)
class Diagnosis:
    code: str
    thread_id: str
    message: str
    repair: str


@dataclass(frozen=True)
class CurrentConfig:
    model_provider: str | None
    model: str | None
