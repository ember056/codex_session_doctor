from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexPaths:
    codex_home: Path
    db_path: Path
    session_index_path: Path
    sessions_dir: Path
    archived_sessions_dir: Path
    backup_dir: Path


def resolve_paths(codex_home: str | None = None) -> CodexPaths:
    home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return CodexPaths(
        codex_home=home,
        db_path=home / "state_5.sqlite",
        session_index_path=home / "session_index.jsonl",
        sessions_dir=home / "sessions",
        archived_sessions_dir=home / "archived_sessions",
        backup_dir=home / "session_doctor_backups",
    )


def add_windows_long_path_prefix(path: str) -> str:
    if path.startswith("\\\\?\\"):
        return path
    if len(path) >= 3 and path[1:3] == ":\\":
        return "\\\\?\\" + path
    return path


def remove_windows_long_path_prefix(path: str) -> str:
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def normalize_path_for_compare(path: str | None) -> str:
    if not path:
        return ""
    value = remove_windows_long_path_prefix(str(path)).replace("/", "\\")
    while "\\\\" in value and not value.startswith("\\\\"):
        value = value.replace("\\\\", "\\")
    return value.rstrip("\\").lower()

