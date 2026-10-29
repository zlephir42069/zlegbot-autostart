"""Read the last completed run from the rotating log."""

from __future__ import annotations

import re
from pathlib import Path

_RUN = re.compile(
    r"run ts=(\S+) status=(ok|failed) steps=(\d+) failed=([A-Za-z0-9_.,-]*)"
)


def read_status(log_path: Path) -> dict | None:
    if not log_path.is_file():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    found = None
    for line in text.splitlines():
        match = _RUN.search(line)
        if not match:
            continue
        failed = [part for part in match.group(4).split(",") if part]
        found = {
            "time": match.group(1),
            "status": match.group(2),
            "steps": int(match.group(3)),
            "failed": failed,
        }
    return found


def render_status(log_path: Path) -> str:
    log_line = f"log: {log_path}\n"
    if not log_path.is_file():
        return "status: none\nno runs yet\n" + log_line
    found = read_status(log_path)
    if found is None:
        return "status: none\nno complete run\n" + log_line
    failed = ",".join(found["failed"])
    return (
        f"status: {found['status']}\n"
        f"time: {found['time']}\n"
        f"steps: {found['steps']}\n"
        f"failed: {failed}\n"
        + log_line
    )
