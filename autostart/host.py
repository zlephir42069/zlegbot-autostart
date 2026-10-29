"""Machine operations. Tests pass a fake; the CLI uses :class:`SystemHost`.

``SystemHost`` looks up ``crontab`` and ``pgrep`` on ``PATH``. It never calls
``systemctl``. Signal 0 is a liveness check and does not kill the process.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from autostart.crontab import empty_means_remove
from autostart.errors import HostError, StepError


class SystemHost:
    def read_crontab(self) -> str:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        if empty_means_remove(result.stderr):
            return ""
        raise HostError(f"crontab -l exited {result.returncode}")

    def write_crontab(self, text: str) -> None:
        if text.strip() == "":
            result = subprocess.run(
                ["crontab", "-r"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 and not empty_means_remove(result.stderr):
                raise HostError(f"crontab -r exited {result.returncode}")
            return
        result = subprocess.run(
            ["crontab", "-"],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise HostError(f"crontab - exited {result.returncode}")

    def pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def pgrep(self, pattern: str) -> list[int]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "--", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise StepError("pgrep is not available") from exc
        if result.returncode == 1:
            return []
        if result.returncode != 0:
            raise StepError(f"pgrep exited {result.returncode}")
        me = os.getpid()
        found = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit() and int(line) != me:
                found.append(int(line))
        return found

    def spawn(self, command: str, cwd: Path) -> None:
        try:
            subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise StepError(f"could not start process: {exc.__class__.__name__}") from exc

    def run(self, command: str, cwd: Path, timeout: float) -> int:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StepError(f"timed out after {timeout:g}s") from exc
        return completed.returncode
