from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            tmp.write(content)
        replace_with_retry(Path(tmp_name), path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def replace_with_retry(source: Path, target: Path, attempts: int = 20, delay_seconds: float = 0.25) -> None:
    last_error: BaseException | None = None
    for _ in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"File is busy and could not be replaced: {target}") from last_error


def read_first_line_and_rest(path: Path) -> tuple[bytes, bytes]:
    with path.open("rb") as handle:
        first_line = handle.readline()
        rest = handle.read()
    return first_line, rest


def write_first_line_json(path: Path, item: dict[str, Any], rest: bytes, newline: bytes) -> None:
    first_line = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + newline
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(first_line)
            tmp.write(rest)
        replace_with_retry(Path(tmp_name), path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def detect_newline(first_line: bytes) -> bytes:
    if first_line.endswith(b"\r\n"):
        return b"\r\n"
    if first_line.endswith(b"\r"):
        return b"\r"
    return b"\n"

