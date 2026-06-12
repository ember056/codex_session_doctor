from __future__ import annotations

"""Command line entrypoint.

命令行入口：负责 scan / diagnose / repair / gui 四类命令的参数解析和输出。
"""

import argparse
import json
import sys

from .backup import create_backup
from .diagnostics import diagnose_threads, format_project_report, group_diagnoses_by_project, summarize_threads
from .paths import resolve_paths
from .repair import rebuild_session_index, repair_cwd, repair_previews, set_provider_model
from .scanner import load_session_index_ids, load_session_meta, load_threads


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-session-doctor")
    parser.add_argument("--codex-home", help="Path to the Codex data directory. Defaults to ~/.codex.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("scan", help="Print a compact summary of local Codex history data.")
    subparsers.add_parser("gui", help="Open the Windows-friendly graphical interface.")

    diagnose = subparsers.add_parser("diagnose", help="Print detected problems and suggested repairs.")
    diagnose.add_argument("--project", help="Limit diagnostics to a project cwd.")
    diagnose.add_argument("--include-subagents", action="store_true", help="Include guardian/subagent review threads.")

    repair = subparsers.add_parser("repair", help="Apply selected repairs, or preview them with --dry-run.")
    repair.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    repair.add_argument("--project", help="Target project cwd for cwd repair and preview filtering.")
    repair.add_argument("--from-project", help="Source project cwd for cwd repair. Defaults to --project.")
    repair.add_argument("--thread-id", action="append", default=[], help="Repair a specific thread id. Can be repeated.")
    repair.add_argument("--include-subagents", action="store_true", help="Include guardian/subagent review threads.")
    repair.add_argument("--fix-preview", action="store_true", help="Fill empty previews from first user message or title.")
    repair.add_argument("--fix-index", action="store_true", help="Rebuild session_index.jsonl from SQLite threads.")
    repair.add_argument("--fix-cwd", action="store_true", help="Set selected threads to --project cwd and update rollout metadata.")
    repair.add_argument("--set-provider", help="Set model_provider for all threads.")
    repair.add_argument("--set-model", help="Set model for all threads.")
    repair.add_argument("--yes", action="store_true", help="Required for real writes. Omit with --dry-run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = resolve_paths(args.codex_home)

    if args.command == "scan":
        return cmd_scan(args, paths)
    if args.command == "diagnose":
        return cmd_diagnose(args, paths)
    if args.command == "repair":
        return cmd_repair(args, paths)
    if args.command == "gui":
        from .gui import run_gui

        run_gui(str(paths.codex_home))
        return 0
    raise AssertionError(args.command)


def cmd_scan(args: argparse.Namespace, paths) -> int:
    threads = load_threads(paths)
    session_meta = load_session_meta(paths)
    session_index_ids = load_session_index_ids(paths)
    payload = {
        "codex_home": str(paths.codex_home),
        "db_path": str(paths.db_path),
        "session_index_path": str(paths.session_index_path),
        "session_files": len(session_meta),
        "indexed_threads": len(session_index_ids),
        **summarize_threads(threads),
    }
    print_output(payload, args.json)
    return 0


def cmd_diagnose(args: argparse.Namespace, paths) -> int:
    threads = load_threads(paths)
    diagnoses = diagnose_threads(
        threads,
        load_session_meta(paths),
        load_session_index_ids(paths),
        project=args.project,
        include_subagents=args.include_subagents,
    )
    groups = group_diagnoses_by_project(diagnoses, threads)
    payload = {
        "count": len(diagnoses),
        "diagnoses": [diagnosis.__dict__ for diagnosis in diagnoses],
        "projects": groups,
    }
    if not args.json:
        print(format_project_report(groups))
        return 1 if diagnoses else 0
    print_output(payload, args.json)
    return 1 if diagnoses else 0


def cmd_repair(args: argparse.Namespace, paths) -> int:
    if args.fix_cwd and not args.project:
        print("--fix-cwd requires --project", file=sys.stderr)
        return 2
    if (args.set_provider and not args.set_model) or (args.set_model and not args.set_provider):
        print("--set-provider and --set-model must be used together", file=sys.stderr)
        return 2
    if not any([args.fix_preview, args.fix_index, args.fix_cwd, args.set_provider]):
        print("No repair selected. Use --fix-preview, --fix-index, --fix-cwd, or --set-provider/--set-model.", file=sys.stderr)
        return 2
    if not args.dry_run and not args.yes:
        print("Real writes require --yes. Use --dry-run to preview changes.", file=sys.stderr)
        return 2

    changes: list[str] = []
    backup_path = None
    if not args.dry_run:
        backup_path = create_backup(paths)

    if args.fix_preview:
        changes.extend(
            repair_previews(
                paths,
                project=args.project,
                dry_run=args.dry_run,
                include_subagents=args.include_subagents,
            )
        )
    if args.fix_index:
        changes.extend(rebuild_session_index(paths, dry_run=args.dry_run))
    if args.fix_cwd:
        changes.extend(
            repair_cwd(
                paths,
                project=args.project,
                from_project=args.from_project,
                thread_ids=args.thread_id,
                dry_run=args.dry_run,
                include_subagents=args.include_subagents,
            )
        )
    if args.set_provider:
        changes.extend(set_provider_model(paths, args.set_provider, args.set_model, dry_run=args.dry_run))

    payload = {
        "dry_run": args.dry_run,
        "backup_path": str(backup_path) if backup_path else None,
        "changes": changes,
    }
    print_output(payload, args.json)
    return 0


def print_output(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        if key in {"diagnoses", "changes"} and isinstance(value, list):
            print(f"{key}:")
            if not value:
                print("  none")
            for item in value:
                if isinstance(item, dict):
                    print(f"  - [{item.get('code')}] {item.get('thread_id')}: {item.get('message')} ({item.get('repair')})")
                else:
                    print(f"  - {item}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
