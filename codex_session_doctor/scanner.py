from __future__ import annotations

"""Readers for local Codex Desktop history files.

读取本地 Codex Desktop 的 SQLite、session_index.jsonl 和 rollout JSONL 元数据。
"""

import json
import re
import sqlite3
from pathlib import Path

from .models import CurrentConfig, SessionMeta, ThreadRecord
from .paths import CodexPaths


def connect_db(paths: CodexPaths) -> sqlite3.Connection:
    conn = sqlite3.connect(paths.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_thread_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row["name"]) for row in conn.execute("PRAGMA table_info(threads)").fetchall()}


def load_current_config(paths: CodexPaths) -> CurrentConfig:
    if not paths.config_path.exists():
        return CurrentConfig(model_provider=None, model=None)
    text = paths.config_path.read_text(encoding="utf-8", errors="replace")
    provider_match = re.search(r'(?m)^\s*model_provider\s*=\s*"([^"]+)"', text)
    model_match = re.search(r'(?m)^\s*model\s*=\s*"([^"]+)"', text)
    return CurrentConfig(
        model_provider=provider_match.group(1) if provider_match else None,
        model=model_match.group(1) if model_match else None,
    )


def load_threads(paths: CodexPaths) -> list[ThreadRecord]:
    if not paths.db_path.exists():
        return []
    conn = connect_db(paths)
    try:
        columns = get_thread_columns(conn)
        if not columns:
            return []
        select_parts = [
            "id",
            "coalesce(title, '') as title",
            "coalesce(cwd, '') as cwd",
            "coalesce(rollout_path, '') as rollout_path",
            "coalesce(source, '') as source",
            "coalesce(model_provider, '') as model_provider",
            "coalesce(archived, 0) as archived",
            "coalesce(updated_at, 0) as updated_at",
            "coalesce(first_user_message, '') as first_user_message",
        ]
        if "model" in columns:
            select_parts.append("model")
        else:
            select_parts.append("NULL as model")
        if "preview" in columns:
            select_parts.append("coalesce(preview, '') as preview")
        else:
            select_parts.append("'' as preview")
        rows = conn.execute(f"SELECT {', '.join(select_parts)} FROM threads ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    return [
        ThreadRecord(
            id=str(row["id"]),
            title=str(row["title"] or ""),
            cwd=str(row["cwd"] or ""),
            rollout_path=str(row["rollout_path"] or ""),
            source=str(row["source"] or ""),
            model_provider=str(row["model_provider"] or ""),
            model=str(row["model"]) if row["model"] else None,
            archived=int(row["archived"] or 0),
            updated_at=int(row["updated_at"] or 0),
            preview=str(row["preview"] or ""),
            first_user_message=str(row["first_user_message"] or ""),
        )
        for row in rows
    ]


def iter_rollout_paths(paths: CodexPaths) -> list[Path]:
    found: list[Path] = []
    for root in (paths.sessions_dir, paths.archived_sessions_dir):
        if root.exists():
            found.extend(root.rglob("rollout-*.jsonl"))
    return sorted(found)


def parse_session_meta(path: Path) -> SessionMeta | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first_line = handle.readline()
        if not first_line:
            return None
        item = json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return None
    if item.get("type") != "session_meta":
        return None
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return None
    thread_id = str(payload.get("id") or "").strip()
    if not thread_id:
        return None
    model = payload.get("model")
    return SessionMeta(
        thread_id=thread_id,
        path=path,
        cwd=str(payload.get("cwd") or ""),
        model_provider=str(payload.get("model_provider") or ""),
        model=str(model) if model else None,
    )


def load_session_meta(paths: CodexPaths) -> dict[str, SessionMeta]:
    output: dict[str, SessionMeta] = {}
    for path in iter_rollout_paths(paths):
        meta = parse_session_meta(path)
        if meta:
            output[meta.thread_id] = meta
    return output


def load_session_index_ids(paths: CodexPaths) -> set[str]:
    if not paths.session_index_path.exists():
        return set()
    ids: set[str] = set()
    with paths.session_index_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            thread_id = str(item.get("id") or "").strip()
            if thread_id:
                ids.add(thread_id)
    return ids
