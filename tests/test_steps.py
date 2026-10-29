"""Step behavior with a fake host, plus one real pid and pgrep check."""

import os
import shlex
import signal
import subprocess
import sys
import time

from autostart.config import load_config
from autostart.errors import HostError
from autostart.host import SystemHost
from autostart.steps import run_step

from support import Clock, FakeHost, write_config


def _step(tmp_path, text):
    config = load_config(write_config(tmp_path, text))
    return config, config.steps[0]


def test_ensure_dir_restore_and_checksum(tmp_path):
    data = tmp_path / "data"
    backup = tmp_path / "backup" / "note.txt"
    backup.parent.mkdir()
    backup.write_text("ok\n", encoding="utf-8")
    digest = "dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22"
    host = FakeHost()

    config, step = _step(
        tmp_path,
        """
steps:
  - name: dirs
    type: ensure_dir
    paths:
      - ./data
      - ./run
""",
    )
    created = run_step(step, base=config.base, host=host)
    assert created.ok and created.detail == "created=2 present=0"
    again = run_step(step, base=config.base, host=host)
    assert again.detail == "created=0 present=2"

    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    _config, bad = _step(
        tmp_path,
        """
steps:
  - name: dirs
    type: ensure_dir
    path: ./blocked
""",
    )
    failed = run_step(bad, base=_config.base, host=host)
    assert not failed.ok
    assert "not a directory" in failed.detail

    _config, restore = _step(
        tmp_path,
        """
steps:
  - name: note
    type: restore
    dest: ./data/note.txt
    backup: ./backup/note.txt
""",
    )
    restored = run_step(restore, base=_config.base, host=host)
    assert restored.detail == "restored=1 kept=0"
    assert (data / "note.txt").read_text(encoding="utf-8") == "ok\n"
    (data / "note.txt").write_text("edited\n", encoding="utf-8")
    kept = run_step(restore, base=_config.base, host=host)
    assert kept.detail == "restored=0 kept=1"
    assert (data / "note.txt").read_text(encoding="utf-8") == "edited\n"

    _config, check = _step(
        tmp_path,
        f"""
steps:
  - name: note-hash
    type: checksum
    path: ./data/note.txt
    sha256: {digest}
""",
    )
    mismatch = run_step(check, base=_config.base, host=host)
    assert not mismatch.ok and "mismatch" in mismatch.detail
    (data / "note.txt").write_text("ok\n", encoding="utf-8")
    matched = run_step(check, base=_config.base, host=host)
    assert matched.ok and matched.detail == "ok=1"

    missing_backup = tmp_path / "nope"
    _config, restore_missing = _step(
        tmp_path,
        """
steps:
  - name: other
    type: restore
    dest: ./data/other.txt
    backup: ./missing.txt
""",
    )
    assert not missing_backup.exists()
    missed = run_step(restore_missing, base=_config.base, host=host)
    assert "backup missing" in missed.detail
    assert not (data / "other.txt").exists()


def test_crontab_step_is_idempotent_and_does_not_write_on_read_error(tmp_path):
    config, step = _step(
        tmp_path,
        """
steps:
  - name: jobs
    type: crontab
    marker: jobs
    lines:
      - "15 * * * * /usr/local/bin/hourly-job"
""",
    )
    host = FakeHost()
    host.crontab_text = "* * * * * echo SUPERSECRETTOKEN\n"
    first = run_step(step, base=config.base, host=host)
    assert first.detail == "updated"
    assert host.writes == 1
    assert "SUPERSECRETTOKEN" in host.crontab_text
    assert "hourly-job" in host.crontab_text
    second = run_step(step, base=config.base, host=host)
    assert second.detail == "unchanged"
    assert host.writes == 1

    broken = FakeHost()
    broken.crontab_text = "# BEGIN autostart:jobs\nno end\n"
    broken.fail_read = None
    failed = run_step(step, base=config.base, host=broken)
    assert not failed.ok
    assert broken.writes == 0
    assert broken.crontab_text.startswith("# BEGIN")

    denied = FakeHost()
    denied.fail_read = HostError("crontab -l exited 1")
    denied.crontab_text = "* * * * * echo keep\n"
    result = run_step(step, base=config.base, host=denied)
    assert not result.ok
    assert denied.writes == 0
    assert denied.crontab_text == "* * * * * echo keep\n"


def test_process_and_command_use_the_fake_host(tmp_path):
    pidfile = tmp_path / "run" / "worker.pid"
    pidfile.parent.mkdir()
    pidfile.write_text("9\n", encoding="utf-8")
    config, step = _step(
        tmp_path,
        """
steps:
  - name: worker
    type: process
    pidfile: ./run/worker.pid
    match: autostart-worker
    start: ./bin/worker
    timeout: 10
""",
    )
    host = FakeHost()
    host.alive.add(9)
    clock = Clock()
    running = run_step(step, base=config.base, host=host, sleeper=clock.sleep, clock=clock)
    assert running.detail == "already running"
    assert host.spawned == []
    assert clock.slept == []

    host.alive.clear()
    host.on_spawn = lambda _command: host.matches.__setitem__("autostart-worker", [50])
    started = run_step(step, base=config.base, host=host, sleeper=clock.sleep, clock=clock)
    assert started.detail == "started"
    assert len(host.spawned) == 1
    assert host.spawned[0][1] == config.base

    quiet = FakeHost()
    clock = Clock()
    timed = run_step(step, base=config.base, host=quiet, sleeper=clock.sleep, clock=clock)
    assert timed.detail == "timed out"
    assert len(quiet.spawned) == 1
    assert clock.slept

    _config, verify = _step(
        tmp_path,
        """
steps:
  - name: worker
    type: process
    match: autostart-worker
""",
    )
    down = run_step(verify, base=_config.base, host=FakeHost())
    assert down.detail == "not running"

    _config, command = _step(
        tmp_path,
        """
steps:
  - name: health
    type: command
    run: test -f ./data/note.txt
    timeout: 5
""",
    )
    commands = FakeHost()
    ok = run_step(command, base=_config.base, host=commands)
    assert ok.detail == "exit 0"
    assert commands.commands[0][1] == _config.base
    commands.command_codes["test -f ./data/note.txt"] = 3
    failed = run_step(command, base=_config.base, host=commands)
    assert failed.detail == "exit 3"
    commands.command_codes["test -f ./data/note.txt"] = "timeout"
    expired = run_step(command, base=_config.base, host=commands)
    assert "timed out" in expired.detail


def test_real_pidfile_and_pgrep(tmp_path):
    script = tmp_path / "worker.py"
    pidfile = tmp_path / "worker.pid"
    script.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    command = " ".join(shlex.quote(part) for part in (sys.executable, str(script), str(pidfile)))
    config, step = _step(
        tmp_path,
        f"""
steps:
  - name: worker
    type: process
    pidfile: {pidfile}
    start: "{command}"
    timeout: 5
""",
    )
    try:
        result = run_step(step, base=config.base, host=SystemHost())
        assert result.ok, result.detail
        assert result.detail == "started"
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        assert pid != os.getpid()
        again = run_step(step, base=config.base, host=SystemHost())
        assert again.detail == "already running"
    finally:
        _kill_pattern(str(script))

    token = "autostart-token-" + str(os.getpid()) + "-" + tmp_path.name
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", token],
        start_new_session=True,
    )
    try:
        deadline = time.time() + 2
        while time.time() < deadline:
            seen_now = subprocess.run(
                ["pgrep", "-f", "--", token],
                capture_output=True,
                text=True,
                check=False,
            )
            if seen_now.returncode == 0:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("sleeper did not appear")
        _config, match = _step(
            tmp_path,
            f"""
steps:
  - name: sleeper
    type: process
    match: "{token}"
""",
        )
        seen = run_step(match, base=_config.base, host=SystemHost())
        assert seen.ok, seen.detail
        assert seen.detail == "already running"
    finally:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait(timeout=5)


def test_real_command_timeout(tmp_path):
    config, step = _step(
        tmp_path,
        f"""
steps:
  - name: health
    type: command
    run: "{sys.executable} -c 'import time; time.sleep(5)'"
    timeout: 0.3
""",
    )
    result = run_step(step, base=config.base, host=SystemHost())
    assert not result.ok
    assert "timed out" in result.detail


def _kill_pattern(pattern: str) -> None:
    result = subprocess.run(
        ["pgrep", "-f", "--", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if not line.strip().isdigit():
            continue
        pid = int(line.strip())
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
