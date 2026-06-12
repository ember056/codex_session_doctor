# Codex Session Doctor

A local recovery and repair tool for Codex Desktop conversations that still exist on disk but disappear from the sidebar.

Codex Desktop history is stored across several local files:

- `%USERPROFILE%\.codex\state_5.sqlite`
- `%USERPROFILE%\.codex\session_index.jsonl`
- `%USERPROFILE%\.codex\sessions\**\rollout-*.jsonl`

When these files get out of sync, conversations may still be present on disk but hidden from the project sidebar. This tool diagnoses those problems and can repair common metadata issues.

## Features

- Detect missing `session_index.jsonl` entries
- Detect empty `threads.preview` values that may hide conversations in the sidebar
- Detect project `cwd` mismatches between SQLite and rollout JSONL metadata
- Detect missing rollout files
- Rebuild `session_index.jsonl`
- Fill missing previews from the first user message or title
- Normalize Windows paths such as `C:\...` and `\\?\C:\...`
- Backup SQLite, session index, and rollout metadata before writing
- Skip guardian/subagent review threads by default

## Requirements

- Windows, macOS, or Linux
- Python 3.10+
- A local Codex Desktop data directory, usually `%USERPROFILE%\.codex`

## Quick Start

```powershell
py -3 -m codex_session_doctor scan
py -3 -m codex_session_doctor diagnose
py -3 -m codex_session_doctor gui
py -3 -m codex_session_doctor repair --dry-run --fix-preview --fix-index
py -3 -m codex_session_doctor repair --fix-preview --fix-index
py -3 -m codex_session_doctor --json scan
```

On Windows, you can also launch the graphical interface:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_gui.ps1
```

Use a custom Codex data directory:

```powershell
py -3 -m codex_session_doctor diagnose --codex-home "D:\codex-data"
```

Repair a specific project directory:

```powershell
py -3 -m codex_session_doctor repair --project "C:\Users\bobo\Desktop\Onecall" --fix-preview --fix-cwd
```

## Safety

`repair` runs in dry-run mode unless you omit `--dry-run`. Before any real write, the tool creates a backup under:

```text
%USERPROFILE%\.codex\session_doctor_backups
```

The backup includes:

- a copy of `state_5.sqlite`
- a copy of `session_index.jsonl`
- the first `session_meta` line from each rollout JSONL file

## Commands

```text
scan       Print a compact summary of local Codex history data
diagnose   Print detected problems grouped by project cwd
repair     Apply selected repairs, or preview them with --dry-run
gui        Open the Windows-friendly graphical interface
```

Example grouped diagnosis report:

```text
Project: \\?\C:\Users\bobo\Desktop\Onecall
  Issues: 3
  Summary: empty-preview=3
  Thread: 启动项目
    id: 019e495f-697f-7720-a4ef-63f2373531f1
    - [empty-preview] Preview is empty; the sidebar may hide this thread. -> fix-preview
```

## GUI

The GUI is built with Python's standard `tkinter` library, so it does not require extra packages.

It can:

- scan local Codex history
- show diagnosis results grouped by project
- preview common repairs with dry-run
- apply safe repairs after creating a backup

The first GUI repair options are intentionally conservative:

- fill empty previews
- merge missing `session_index.jsonl` entries

## Notes

This tool modifies local Codex Desktop metadata only. It does not upload conversations, call OpenAI APIs, or modify project source code.

Close Codex Desktop before applying repairs when possible. Windows may lock active rollout files while Codex is writing to them.
