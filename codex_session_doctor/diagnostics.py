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


def group_diagnoses_by_project(diagnoses: list[Diagnosis], threads: list[ThreadRecord]) -> list[dict[str, object]]:
    threads_by_id = {thread.id: thread for thread in threads}
    groups: dict[str, dict[str, object]] = {}
    for diagnosis in diagnoses:
        thread = threads_by_id.get(diagnosis.thread_id)
        cwd = thread.cwd if thread and thread.cwd else "(unknown project)"
        group = groups.setdefault(
            cwd,
            {
                "cwd": cwd,
                "issue_count": 0,
                "codes": Counter(),
                "threads": {},
            },
        )
        group["issue_count"] = int(group["issue_count"]) + 1
        group["codes"][diagnosis.code] += 1
        grouped_threads = group["threads"]
        item = grouped_threads.setdefault(
            diagnosis.thread_id,
            {
                "id": diagnosis.thread_id,
                "title": thread.title if thread else diagnosis.thread_id,
                "updated_at": thread.updated_at if thread else 0,
                "issues": [],
            },
        )
        item["issues"].append(
            {
                "code": diagnosis.code,
                "message": diagnosis.message,
                "repair": diagnosis.repair,
            }
        )

    output: list[dict[str, object]] = []
    for group in groups.values():
        codes = group["codes"]
        grouped_threads = group["threads"]
        output.append(
            {
                "cwd": group["cwd"],
                "issue_count": group["issue_count"],
                "codes": dict(codes),
                "threads": sorted(grouped_threads.values(), key=lambda item: int(item["updated_at"]), reverse=True),
            }
        )
    return sorted(output, key=lambda item: int(item["issue_count"]), reverse=True)


def format_project_report(groups: list[dict[str, object]]) -> str:
    if not groups:
        return "未发现需要修复的问题。"

    lines: list[str] = []
    for group in groups:
        lines.append(f"项目目录: {group['cwd']}")
        lines.append(f"  问题数: {group['issue_count']}")
        codes = group.get("codes", {})
        if codes:
            summary = "，".join(f"{describe_issue_code(code)}={count}" for code, count in sorted(codes.items()))
            lines.append(f"  概览: {summary}")
        for thread in group.get("threads", []):
            title = str(thread.get("title") or thread.get("id"))
            lines.append(f"  会话: {title}")
            lines.append(f"    id: {thread['id']}")
            for issue in thread.get("issues", []):
                lines.append(
                    f"    - [{describe_issue_code(issue['code'])}] "
                    f"{translate_issue_message(issue['code'], issue['message'])} -> {describe_repair(issue['repair'])}"
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def describe_issue_code(code: str) -> str:
    return {
        "missing-rollout-path": "缺少会话文件路径",
        "missing-rollout-file": "会话文件不存在",
        "empty-preview": "缺少侧边栏预览",
        "missing-index-entry": "缺少侧边栏索引",
        "cwd-mismatch": "项目目录不一致",
        "missing-session-meta": "缺少会话元数据",
    }.get(code, code)


def translate_issue_message(code: str, fallback: str) -> str:
    return {
        "missing-rollout-path": "数据库记录没有 rollout_path，会话文件位置未知。",
        "missing-rollout-file": "数据库指向的会话文件不存在。",
        "empty-preview": "preview 为空，Codex 侧边栏可能不会显示这个会话。",
        "missing-index-entry": "这个会话没有写入 session_index.jsonl。",
        "cwd-mismatch": "SQLite 里的项目目录和会话文件首行元数据不一致。",
        "missing-session-meta": "会话文件第一行没有可读取的 session_meta。",
    }.get(code, fallback)


def describe_repair(repair: str) -> str:
    return {
        "fix-preview": "补齐预览",
        "fix-index": "合并索引",
        "fix-cwd": "修正项目目录",
        "manual": "需要手动检查",
    }.get(repair, repair)
