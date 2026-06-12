from __future__ import annotations

from collections import Counter

from .models import Diagnosis, SessionMeta, ThreadRecord
from .paths import normalize_path_for_compare


def diagnose_threads(
    threads: list[ThreadRecord],
    session_meta: dict[str, SessionMeta],
    session_index_ids: set[str],
    project: str | None = None,
    include_subagents: bool = False,
) -> list[Diagnosis]:
    project_key = normalize_path_for_compare(project)
    output: list[Diagnosis] = []
    for thread in threads:
        if thread.archived:
            continue
        if thread.is_subagent_review and not include_subagents:
            continue
        if project_key and normalize_path_for_compare(thread.cwd) != project_key:
            continue

        if not thread.rollout_path:
            output.append(Diagnosis("missing-rollout-path", thread.id, "Database row has no rollout_path.", "manual"))
        elif not thread.rollout_exists:
            output.append(Diagnosis("missing-rollout-file", thread.id, f"Rollout file does not exist: {thread.rollout_path}", "manual"))

        if not thread.preview.strip():
            output.append(Diagnosis("empty-preview", thread.id, "Preview is empty; the sidebar may hide this thread.", "fix-preview"))

        if thread.id not in session_index_ids:
            output.append(Diagnosis("missing-index-entry", thread.id, "Thread is missing from session_index.jsonl.", "fix-index"))

        meta = session_meta.get(thread.id)
        if meta:
            db_cwd = normalize_path_for_compare(thread.cwd)
            meta_cwd = normalize_path_for_compare(meta.cwd)
            if db_cwd and meta_cwd and db_cwd != meta_cwd:
                output.append(Diagnosis("cwd-mismatch", thread.id, f"SQLite cwd differs from rollout metadata cwd: {thread.cwd} != {meta.cwd}", "fix-cwd"))
        elif thread.rollout_exists:
            output.append(Diagnosis("missing-session-meta", thread.id, "Rollout file has no readable session_meta first line.", "manual"))

    return output


def summarize_threads(threads: list[ThreadRecord]) -> dict[str, object]:
    provider_counts = Counter(thread.model_provider or "(empty)" for thread in threads)
    model_counts = Counter(thread.model or "(empty)" for thread in threads)
    cwd_counts = Counter(thread.cwd or "(empty)" for thread in threads)
    return {
        "total_threads": len(threads),
        "active_threads": sum(1 for thread in threads if not thread.archived),
        "archived_threads": sum(1 for thread in threads if thread.archived),
        "empty_preview_threads": sum(1 for thread in threads if not thread.preview.strip() and not thread.archived),
        "missing_rollout_files": sum(1 for thread in threads if not thread.archived and thread.rollout_path and not thread.rollout_exists),
        "provider_counts": provider_counts.most_common(10),
        "model_counts": model_counts.most_common(10),
        "cwd_counts": cwd_counts.most_common(20),
    }

