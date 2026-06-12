from __future__ import annotations

"""Repair operations for local Codex Desktop metadata.

修复本地 Codex Desktop 元数据的操作，所有真实写入都应先由调用方创建备份。
"""

import json
import sqlite3
from pathlib import Path

from .io import detect_newline, read_first_line_and_rest, write_first_line_json, write_text_atomic
from .models import ThreadRecord
from .paths import CodexPaths, add_windows_long_path_prefix, normalize_path_for_compare
from .scanner import connect_db, get_thread_columns, load_session_meta, load_threads


def build_preview(thread: ThreadRecord, limit: int = 500) -> str:
    value = (thread.first_user_message or thread.title or thread.id).replace("\r\n", "\n").replace("\r", "\n").strip()
    return value[:limit]


def repair_previews(paths: CodexPaths, project: str | None = None, dry_run: bool = True, include_subagents: bool = False) -> list[str]:
    """Fill empty preview fields from the first user message or title.

    用首条用户消息或标题补齐空 preview，避免侧边栏过滤这些会话。
    """
    threads = load_threads(paths)
    project_key = normalize_path_for_compare(project) if project else None
    changed: list[str] = []
    conn = connect_db(paths)
    try:
        for thread in threads:
            if thread.archived or thread.preview.strip():
                continue
            if thread.is_subagent_review and not include_subagents:
                continue
            if project_key and normalize_path_for_compare(thread.cwd) != project_key:
                continue
            preview = build_preview(thread)
            if not preview:
                continue
            changed.append(f"{thread.id}: preview <- {preview[:80]}")
            if not dry_run:
                conn.execute("UPDATE threads SET preview = ? WHERE id = ?", (preview, thread.id))
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return changed


def rebuild_session_index(paths: CodexPaths, dry_run: bool = True, include_archived: bool = False) -> list[str]:
    """Merge SQLite threads into session_index.jsonl without dropping existing entries.

    将 SQLite 里的会话合并到 session_index.jsonl，同时保留已有索引项。
    """
    threads = load_threads(paths)
    entries_by_id = _read_existing_session_index(paths)
    before_count = len(entries_by_id)
    changed: list[str] = []
    for thread in sorted(threads, key=lambda item: item.id):
        if thread.archived and not include_archived:
            continue
        if thread.is_subagent_review:
            continue
        updated = thread.updated_at
        timestamp = ""
        if updated:
            from datetime import UTC, datetime

            timestamp = datetime.fromtimestamp(updated, tz=UTC).isoformat().replace("+00:00", "Z")
        existing = entries_by_id.get(thread.id)
        thread_name = ""
        if existing:
            thread_name = str(existing.get("thread_name") or "")
        entries_by_id[thread.id] = {
            "id": thread.id,
            "thread_name": thread_name or thread.title or thread.first_user_message or thread.id,
            "updated_at": timestamp or (str(existing.get("updated_at") or "") if existing else ""),
        }
    entries = list(entries_by_id.values())
    changed.append(f"session_index.jsonl <- {len(entries)} entries (was {before_count})")
    if not dry_run:
        content = "".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n" for entry in entries)
        write_text_atomic(paths.session_index_path, content)
    return changed


def _read_existing_session_index(paths: CodexPaths) -> dict[str, dict[str, str]]:
    if not paths.session_index_path.exists():
        return {}
    entries: dict[str, dict[str, str]] = {}
    with paths.session_index_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            thread_id = str(item.get("id") or "").strip()
            if not thread_id:
                continue
            entries[thread_id] = {
                "id": thread_id,
                "thread_name": str(item.get("thread_name") or thread_id),
                "updated_at": str(item.get("updated_at") or ""),
            }
    return entries


def repair_cwd(
    paths: CodexPaths,
    project: str,
    from_project: str | None = None,
    thread_ids: list[str] | None = None,
    dry_run: bool = True,
    include_subagents: bool = False,
) -> list[str]:
    target_db_cwd = add_windows_long_path_prefix(str(Path(project)))
    target_meta_cwd = str(Path(project))
    threads = load_threads(paths)
    changed: list[str] = []
    ids = set(thread_ids or [])
    target_key = normalize_path_for_compare(project)
    from_key = normalize_path_for_compare(from_project) if from_project else target_key
    selected = [
        thread
        for thread in threads
        if not thread.archived
        and (not ids or thread.id in ids)
        and (include_subagents or not thread.is_subagent_review)
        and (bool(ids) or normalize_path_for_compare(thread.cwd) == from_key)
    ]
    conn = connect_db(paths)
    try:
        for thread in selected:
            if thread.cwd != target_db_cwd:
                changed.append(f"{thread.id}: db.cwd <- {target_db_cwd}")
                if not dry_run:
                    conn.execute("UPDATE threads SET cwd = ? WHERE id = ?", (target_db_cwd, thread.id))
            if thread.rollout_path and Path(thread.rollout_path).exists():
                if _update_session_meta_cwd(Path(thread.rollout_path), target_meta_cwd, dry_run):
                    changed.append(f"{thread.id}: session_meta.cwd <- {target_meta_cwd}")
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return changed


def _update_session_meta_cwd(path: Path, target_cwd: str, dry_run: bool) -> bool:
    first_line, rest = read_first_line_and_rest(path)
    if not first_line:
        return False
    try:
        item = json.loads(first_line.rstrip(b"\r\n").decode("utf-8"))
    except json.JSONDecodeError:
        return False
    if item.get("type") != "session_meta":
        return False
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return False
    if payload.get("cwd") == target_cwd:
        return False
    payload["cwd"] = target_cwd
    if not dry_run:
        write_first_line_json(path, item, rest, detect_newline(first_line))
    return True


def sync_provider_model(paths: CodexPaths, provider: str | None, model: str | None, dry_run: bool = True) -> list[str]:
    changed: list[str] = []
    if not provider and not model:
        return changed

    threads = load_threads(paths)
    db_mismatch_ids: set[str] = set()
    conn = connect_db(paths)
    try:
        columns = get_thread_columns(conn)
        set_parts: list[str] = []
        set_values: list[str] = []
        where_parts: list[str] = []
        where_values: list[str] = []

        if provider:
            set_parts.append("model_provider = ?")
            set_values.append(provider)
            where_parts.append("model_provider IS NULL OR model_provider <> ?")
            where_values.append(provider)
            db_mismatch_ids.update(thread.id for thread in threads if thread.model_provider != provider)

        if model and "model" in columns:
            set_parts.append("model = ?")
            set_values.append(model)
            where_parts.append("model IS NULL OR model <> ?")
            where_values.append(model)
            db_mismatch_ids.update(thread.id for thread in threads if thread.model != model)

        if set_parts and where_parts:
            changed.append(f"threads provider/model <- {provider or '(unchanged)'}/{model or '(unchanged)'} ({len(db_mismatch_ids)} rows)")
            if not dry_run:
                where_sql = " OR ".join(f"({part})" for part in where_parts)
                conn.execute(f"UPDATE threads SET {', '.join(set_parts)} WHERE {where_sql}", (*set_values, *where_values))
                conn.commit()
    finally:
        conn.close()

    updated_session_files = 0
    for meta in load_session_meta(paths).values():
        if _update_session_meta_provider_model(meta.path, provider, model, dry_run):
            updated_session_files += 1
    changed.append(f"session_meta provider/model <- {provider or '(unchanged)'}/{model or '(unchanged)'} ({updated_session_files} files)")
    return changed


def set_provider_model(paths: CodexPaths, provider: str, model: str, dry_run: bool = True) -> list[str]:
    return sync_provider_model(paths, provider, model, dry_run=dry_run)


def _update_session_meta_provider_model(path: Path, provider: str | None, model: str | None, dry_run: bool) -> bool:
    first_line, rest = read_first_line_and_rest(path)
    if not first_line:
        return False
    try:
        item = json.loads(first_line.rstrip(b"\r\n").decode("utf-8"))
    except json.JSONDecodeError:
        return False
    if item.get("type") != "session_meta":
        return False
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return False

    changed = False
    if provider and payload.get("model_provider") != provider:
        payload["model_provider"] = provider
        changed = True
    if model and payload.get("model") != model:
        payload["model"] = model
        changed = True
    if changed and not dry_run:
        write_first_line_json(path, item, rest, detect_newline(first_line))
    return changed
