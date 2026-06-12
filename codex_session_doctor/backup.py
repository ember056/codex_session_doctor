from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .paths import CodexPaths
from .scanner import iter_rollout_paths


def create_backup(paths: CodexPaths) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = paths.backup_dir / timestamp
    backup_root.mkdir(parents=True, exist_ok=True)

    if paths.db_path.exists():
        backup_database(paths.db_path, backup_root / paths.db_path.name)
    if paths.session_index_path.exists():
        shutil.copy2(paths.session_index_path, backup_root / paths.session_index_path.name)

    meta_items: list[dict[str, str]] = []
    for path in iter_rollout_paths(paths):
        try:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                first_line = handle.readline().rstrip("\r\n")
        except OSError:
            continue
        try:
            relative = path.relative_to(paths.codex_home)
            stored_path = str(relative)
        except ValueError:
            stored_path = str(path)
        meta_items.append({"path": stored_path, "first_line": first_line})

    (backup_root / "session_meta_first_lines.json").write_text(
        json.dumps(meta_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_root


def backup_database(source_path: Path, target_path: Path) -> None:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(target_path, timeout=30)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
