"""CLI exit codes. 0 ok, 1 a run failure, 2 a config error."""

import os
import shutil
import subprocess
import sys
import sysconfig

from support import REPO, child_env


def _run(tmp_path, *args, **env):
    return subprocess.run(
        [sys.executable, "-m", "autostart", *args],
        cwd=tmp_path,
        env=child_env(tmp_path, **env),
        capture_output=True,
        text=True,
        check=False,
    )


def test_usage_validate_and_status(tmp_path, shadow):
    bare = _run(tmp_path)
    assert bare.returncode == 2

    missing = _run(tmp_path, "validate", "--config", "missing.yaml")
    assert missing.returncode == 2
    assert "config not found" in missing.stderr

    example = _run(
        tmp_path,
        "validate",
        "--config",
        str(REPO / "autostart.example.yaml"),
        AUTOSTART_STATUS_URL="https://discord.com/api/webhooks/123/SUPERSECRETTOKEN",
    )
    assert example.returncode == 0, example.stderr
    assert example.stdout.strip() == "ok"
    assert "SUPERSECRETTOKEN" not in example.stdout + example.stderr
    assert "discord.com/api/webhooks" not in example.stdout + example.stderr

    bad = tmp_path / "autostart.yaml"
    bad.write_text("steps: []\n", encoding="utf-8")
    invalid = _run(tmp_path, "validate")
    assert invalid.returncode == 2
    assert "config error:" in invalid.stderr

    status = _run(tmp_path, "status")
    assert status.returncode == 0, status.stderr
    assert "no runs yet" in status.stdout
    assert shadow.call_text() == ""


def test_run_install_and_uninstall(tmp_path, shadow):
    config = tmp_path / "autostart.yaml"
    config.write_text(
        """
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
  - name: health
    type: command
    run: test -d ./data
""",
        encoding="utf-8",
    )
    dry = _run(tmp_path, "install", "--desktop", "--systemd", "--crontab", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "dry-run desktop:" in dry.stdout
    assert "[Desktop Entry]" in dry.stdout
    assert "WantedBy=default.target" in dry.stdout
    assert "# BEGIN autostart:zlegbot-autostart" in dry.stdout
    assert not (tmp_path / "xdg").exists()
    assert shadow.call_text() == ""

    missing_flags = _run(tmp_path, "install")
    assert missing_flags.returncode == 2
    assert "--desktop" in missing_flags.stderr

    desktop = _run(tmp_path, "install", "--desktop", "--systemd")
    assert desktop.returncode == 0, desktop.stderr
    assert "wrote desktop:" in desktop.stdout
    assert "systemctl --user enable" in desktop.stdout
    unit = tmp_path / "xdg" / "systemd" / "user" / "zlegbot-autostart.service"
    entry = tmp_path / "xdg" / "autostart" / "zlegbot-autostart.desktop"
    assert unit.is_file()
    assert entry.is_file()
    assert "systemctl " not in shadow.call_text()
    assert shadow.call_text() == ""

    cron = _run(tmp_path, "install", "--crontab")
    assert cron.returncode == 0, cron.stderr
    assert "updated crontab" in cron.stdout
    assert "# BEGIN autostart:zlegbot-autostart" in shadow.crontab()
    assert "@reboot" in shadow.crontab()
    assert str(config.resolve()) in shadow.crontab()
    again = _run(tmp_path, "install", "--crontab")
    assert "unchanged crontab" in again.stdout
    assert shadow.crontab().count("# BEGIN autostart:zlegbot-autostart") == 1
    assert "systemctl" not in shadow.call_text()

    ran = _run(tmp_path, "run")
    assert ran.returncode == 0, ran.stderr
    assert (tmp_path / "data").is_dir()
    assert "ok dirs:" in ran.stdout
    status = _run(tmp_path, "status")
    assert status.returncode == 0
    assert "status: ok" in status.stdout

    failed = _run(tmp_path, "run", "--config", str(_fail_config(tmp_path)))
    assert failed.returncode == 1
    assert "failed health:" in failed.stderr
    assert "***" in failed.stderr
    assert "SUPERSECRETTOKEN" not in failed.stdout + failed.stderr
    log = (tmp_path / ".autostart" / "secret.log").read_text(encoding="utf-8")
    assert "SUPERSECRETTOKEN" not in log

    removed = _run(tmp_path, "uninstall", "--desktop", "--systemd", "--crontab")
    assert removed.returncode == 0, removed.stderr
    assert "removed desktop:" in removed.stdout
    assert "removed crontab" in removed.stdout
    assert not entry.exists()
    assert not unit.exists()
    assert "BEGIN" not in shadow.crontab()

    absent = _run(tmp_path, "uninstall", "--desktop", "--config", "missing.yaml")
    assert absent.returncode == 0, absent.stderr
    assert "absent desktop:" in absent.stdout


def test_console_script(monkeypatch):
    # pip may install the console script into the user scheme, which is not
    # always on PATH. CI's interpreter usually is. Search both.
    scripts = [
        sysconfig.get_path("scripts"),
        sysconfig.get_path("scripts", scheme="posix_user"),
    ]
    prefix = os.pathsep.join(path for path in scripts if path)
    monkeypatch.setenv("PATH", prefix + os.pathsep + os.environ.get("PATH", ""))
    script = shutil.which("autostart")
    assert script is not None
    result = subprocess.run(
        [script, "validate", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "validate" in result.stdout


def _fail_config(tmp_path):
    path = tmp_path / "fail.yaml"
    path.write_text(
        """
log: .autostart/secret.log
steps:
  - name: health
    type: checksum
    path: ${TOKEN}/missing
    sha256: dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22
""",
        encoding="utf-8",
    )
    return path
