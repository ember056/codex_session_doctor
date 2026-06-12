from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .io import detect_newline, read_first_line_and_rest, write_first_line_json, write_text_atomic
from .models import ThreadRecord
from .paths import CodexPaths, add_windows_long_path_prefix, normalize_path_for_compare
from .scanner import connect_db, load_threads


def build_preview(thread: ThreadRecord, limit: int = 500) -> str:
    value = (thread.first_user_message or thread.title or thread.id).replace("\r\n", "\n").replace("\r", "\n").strip()
    return value[:limit]


def repair_previews(paths: CodexPaths, project: str | None = None, dry_run: bool = True, include_subagents: bool = False) -> list[str]:
    threads = load_threads(paths)
    project_cwd = add_windows_long_path_prefix(str(Path(project))) if project else None
    changed: list[str] = []
    conn = connect_db(paths)
    try:
        for thread in threads:
            if thread.archived or thread.preview.strip():
                continue
            if thread.is_subagent_review and not include_subagents:
                continue
            if project_cwd and thread.cwd != project_cwd:
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
        entries_by_id[thread.id] = {
            "id": thread.id,
            "thread_name": thread.title or thread.first_user_message or thread.id,
            "updated_at": timestamp,
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


def set_provider_model(paths: CodexPaths, provider: str, model: str, dry_run: bool = True) -> list[str]:
    changed: list[str] = []
    conn = connect_db(paths)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE model_provider IS NULL OR model_provider <> ? OR model IS NULL OR model <> ?",
            (provider, model),
        ).fetchone()[0]
        changed.append(f"threads provider/model <- {provider}/{model} ({count} rows)")
        if not dry_run:
            conn.execute("UPDATE threads SET model_provider = ?, model = ?", (provider, model))
            conn.commit()
    finally:
        conn.close()
    return changed
