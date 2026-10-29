"""Run one recovery step. Failures are results, not uncaught exceptions."""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from autostart.crontab import install_lines
from autostart.errors import CrontabError, HostError, StepError

_POLL = 0.2


@dataclass
class StepResult:
    name: str
    type: str
    ok: bool
    detail: str


def run_step(step, *, base: Path, host, sleeper=time.sleep, clock=time.monotonic) -> StepResult:
    try:
        detail = _HANDLERS[step.type](step, base=base, host=host, sleeper=sleeper, clock=clock)
    except (StepError, CrontabError, HostError) as exc:
        return StepResult(step.name, step.type, False, _one(str(exc)))
    except OSError as exc:
        return StepResult(step.name, step.type, False, exc.__class__.__name__)
    return StepResult(step.name, step.type, True, _one(detail))


def _ensure_dir(step, *, base, host, sleeper, clock) -> str:
    del base, host, sleeper, clock
    created = 0
    present = 0
    for path, display in step.paths:
        if path.exists() and not path.is_dir():
            raise StepError(f"not a directory: {display}")
        if path.is_dir():
            present += 1
            continue
        path.mkdir(parents=True, exist_ok=True)
        created += 1
    return f"created={created} present={present}"


def _restore(step, *, base, host, sleeper, clock) -> str:
    del base, host, sleeper, clock
    pending = []
    kept = 0
    for dest, backup, dest_display, backup_display in step.restores:
        if dest.is_symlink() or dest.exists():
            if dest.is_file() or dest.is_symlink():
                kept += 1
                continue
            raise StepError(f"dest is not a file: {dest_display}")
        if not backup.is_file():
            raise StepError(f"backup missing: {backup_display}")
        pending.append((dest, backup, dest_display))
    for dest, backup, _display in pending:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backup, dest)
        try:
            shutil.copymode(backup, dest)
        except OSError:
            pass
    return f"restored={len(pending)} kept={kept}"


def _checksum(step, *, base, host, sleeper, clock) -> str:
    del base, host, sleeper, clock
    for path, digest, display in step.hashes:
        if not path.exists() and not path.is_symlink():
            raise StepError(f"missing {display}")
        if not path.is_file():
            raise StepError(f"not a file: {display}")
        actual = _sha256(path)
        if actual != digest:
            raise StepError(f"mismatch {display}")
    return f"ok={len(step.hashes)}"


def _crontab(step, *, base, host, sleeper, clock) -> str:
    del base, sleeper, clock
    return install_lines(host, step.marker, step.lines)


def _process(step, *, base, host, sleeper, clock) -> str:
    if _running(step, host):
        return "already running"
    if not step.start:
        raise StepError("not running")
    host.spawn(step.start, base)
    if _wait(lambda: _running(step, host), step.timeout, sleeper, clock):
        return "started"
    raise StepError("timed out")


def _command(step, *, base, host, sleeper, clock) -> str:
    del sleeper, clock
    code = host.run(step.run, base, step.timeout)
    if code != 0:
        raise StepError(f"exit {code}")
    return "exit 0"


_HANDLERS = {
    "ensure_dir": _ensure_dir,
    "restore": _restore,
    "checksum": _checksum,
    "crontab": _crontab,
    "process": _process,
    "command": _command,
}


def _running(step, host) -> bool:
    if step.pidfile is not None and _pidfile_alive(step.pidfile, host):
        return True
    if step.match and host.pgrep(step.match):
        return True
    return False


def _pidfile_alive(path: Path, host) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.readline(128)
    except OSError as exc:
        raise StepError(exc.__class__.__name__) from exc
    text = text.strip()
    if not text.isdigit():
        return False
    return host.pid_alive(int(text))


def _wait(ready, timeout: float, sleeper, clock) -> bool:
    start = clock()
    while True:
        if ready():
            return True
        elapsed = clock() - start
        if elapsed >= timeout:
            return False
        sleeper(min(_POLL, timeout - elapsed))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one(text: str) -> str:
    cleaned = text.replace("\r", " ").replace("\n", " ").strip()
    return cleaned or "-"
