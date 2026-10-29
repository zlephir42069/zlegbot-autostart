"""Ordered runs, rotation, redaction, and the cloud example."""

import shutil

from autostart.config import load_config
from autostart.run import execute, status_line
from autostart.status import render_status

from support import REPO, Clock, FakeHost, write_config


def test_continues_after_failure_unless_stopped(tmp_path):
    backup = tmp_path / "backup.txt"
    backup.write_text("ok\n", encoding="utf-8")
    path = write_config(
        tmp_path,
        """
steps:
  - name: missing
    type: restore
    dest: ./data/note.txt
    backup: ./nope.txt
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    host = FakeHost()
    code = execute(load_config(path), host=host)
    assert code == 1
    assert (tmp_path / "data").is_dir()
    log = (tmp_path / ".autostart" / "autostart.log").read_text(encoding="utf-8")
    assert "status=failed" in log
    assert "failed=missing" in log
    assert "SUPERSECRETTOKEN" not in log

    stopped = write_config(
        tmp_path,
        """
log: .autostart/stop.log
stop_on_error: true
steps:
  - name: missing
    type: restore
    dest: ./data/other.txt
    backup: ./nope.txt
  - name: later
    type: ensure_dir
    path: ./later
""",
        name="stop.yaml",
    )
    code = execute(load_config(stopped), host=host)
    assert code == 1
    assert not (tmp_path / "later").exists()
    stop_log = (tmp_path / ".autostart" / "stop.log").read_text(encoding="utf-8")
    assert "name=later" not in stop_log
    assert "name=missing" in stop_log


def test_redacts_secret_paths_and_rotates(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "SUPERSECRETTOKEN")
    path = write_config(
        tmp_path,
        """
log_max_bytes: 120
log_backups: 2
steps:
  - name: hidden
    type: checksum
    path: ${TOKEN}/data
    sha256: dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22
""",
    )
    code = execute(load_config(path), host=FakeHost())
    assert code == 1
    # The step line is longer than log_max_bytes, so rotation may move it
    # into autostart.log.1 before the run summary is written.
    combined = _read_logs(tmp_path / ".autostart")
    assert "SUPERSECRETTOKEN" not in combined
    assert "missing ***" in combined
    for _ in range(4):
        assert execute(load_config(path), host=FakeHost()) == 1
    assert (tmp_path / ".autostart" / "autostart.log.1").is_file()
    combined = _read_logs(tmp_path / ".autostart")
    assert "SUPERSECRETTOKEN" not in combined


def test_notify_failure_fails_the_run_without_leaking_the_url(tmp_path, server):
    server.httpd.fail_remaining = 5
    path = write_config(
        tmp_path,
        f"""
notify:
  type: discord
  url: "{server.url}/hook/SUPERSECRETTOKEN"
  retries: 2
  backoff: 0
  timeout: 5
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    code = execute(load_config(path), host=FakeHost(), sleeper=lambda _seconds: None)
    assert code == 1
    assert (tmp_path / "data").is_dir()
    log = (tmp_path / ".autostart" / "autostart.log").read_text(encoding="utf-8")
    assert "SUPERSECRETTOKEN" not in log
    assert server.url not in log
    assert "failed=notify" in log
    assert len(server.httpd.posts) == 2
    rendered = render_status(tmp_path / ".autostart" / "autostart.log")
    assert "status: failed" in rendered
    assert "notify" in rendered


def test_cloud_example_runs_twice(tmp_path):
    shutil.copy(REPO / "examples" / "cloud.yaml", tmp_path / "cloud.yaml")
    shutil.copy(REPO / "examples" / "note.txt", tmp_path / "note.txt")
    config = load_config(tmp_path / "cloud.yaml")
    assert execute(config) == 0
    assert (tmp_path / "data" / "note.txt").read_text(encoding="utf-8") == "ok\n"
    assert execute(load_config(tmp_path / "cloud.yaml")) == 0
    log = (tmp_path / ".autostart" / "autostart.log").read_text(encoding="utf-8")
    assert "status=ok" in log
    assert "kept=1" in log


def _read_logs(directory):
    parts = []
    for path in sorted(directory.glob("autostart.log*")):
        parts.append(path.read_text(encoding="utf-8"))
    return "".join(parts)


def test_status_line_and_log_open_failure(tmp_path):
    assert status_line([], 3) == "autostart ok: 3 steps"
    assert status_line(["health"], 2) == "autostart failed: health"
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    path = write_config(
        tmp_path,
        """
log: not-a-directory/autostart.log
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    assert execute(load_config(path), host=FakeHost()) == 1
    assert not (tmp_path / "data").exists()


def test_process_timeout_does_not_sleep_for_real(tmp_path):
    path = write_config(
        tmp_path,
        """
steps:
  - name: worker
    type: process
    match: missing-worker
    start: ./bin/worker
    timeout: 30
""",
    )
    clock = Clock()
    host = FakeHost()
    code = execute(load_config(path), host=host, sleeper=clock.sleep, clock=clock)
    assert code == 1
    assert clock.now >= 30
    assert sum(clock.slept) >= 30
