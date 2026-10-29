"""Install and uninstall write hooks and do not call systemctl."""

import pytest

from autostart.config import load_config
from autostart.errors import HostError
from autostart.host import SystemHost
from autostart.install import (
    SYSTEMD_HINT,
    install_hooks,
    recovery_command,
    render_unit,
    uninstall_hooks,
)

from support import FakeHost, write_config


def _config(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "SUPERSECRETTOKEN")
    path = write_config(
        tmp_path,
        """
steps:
  - name: leak
    type: command
    run: echo ${TOKEN}
""",
    )
    return load_config(path)


def test_dry_run_prints_hooks_and_writes_nothing(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    host = FakeHost()
    home = tmp_path / "xdg"
    text = install_hooks(
        config,
        ["desktop", "systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=True,
    )
    assert "dry-run desktop:" in text
    assert "[Desktop Entry]" in text
    assert "dry-run systemd:" in text
    assert "WantedBy=default.target" in text
    assert "dry-run crontab:" in text
    assert "# BEGIN autostart:zlegbot-autostart" in text
    assert "@reboot" in text
    assert f"systemd enable hint: {SYSTEMD_HINT}" in text
    assert "SUPERSECRETTOKEN" not in text
    assert host.reads == 0
    assert host.writes == 0
    assert not home.exists()


def test_install_is_idempotent_and_preserves_foreign_crontab(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    host = FakeHost()
    host.crontab_text = "* * * * * echo SUPERSECRETTOKEN\n"
    home = tmp_path / "xdg"
    first = install_hooks(
        config,
        ["desktop", "systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=False,
    )
    assert "wrote desktop:" in first
    assert "wrote systemd:" in first
    assert "updated crontab" in first
    assert "SUPERSECRETTOKEN" not in first
    desktop = home / "autostart" / "zlegbot-autostart.desktop"
    unit = home / "systemd" / "user" / "zlegbot-autostart.service"
    assert "run --config" in desktop.read_text(encoding="utf-8")
    assert str(config.path) in desktop.read_text(encoding="utf-8")
    assert "WantedBy=default.target" in unit.read_text(encoding="utf-8")
    assert "SUPERSECRETTOKEN" in host.crontab_text
    assert host.crontab_text.count("# BEGIN autostart:zlegbot-autostart") == 1
    assert host.writes == 1

    second = install_hooks(
        config,
        ["desktop", "systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=False,
    )
    assert "unchanged desktop:" in second
    assert "unchanged systemd:" in second
    assert "unchanged crontab" in second
    assert host.writes == 1


def test_uninstall_removes_hooks_and_is_idempotent(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    host = FakeHost()
    home = tmp_path / "xdg"
    install_hooks(
        config,
        ["desktop", "systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=False,
    )
    host.crontab_text = host.crontab_text + "* * * * * echo keep\n"
    # The extra line was appended after the block. uninstall removes only the marker.
    removed = uninstall_hooks(
        ["desktop", "systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=False,
    )
    assert "removed desktop:" in removed
    assert "removed systemd:" in removed
    assert "removed crontab" in removed
    assert not (home / "autostart" / "zlegbot-autostart.desktop").exists()
    assert not (home / "systemd" / "user" / "zlegbot-autostart.service").exists()
    assert "BEGIN" not in host.crontab_text
    assert "echo keep" in host.crontab_text

    again = uninstall_hooks(
        ["desktop", "crontab"],
        config_home=home,
        host=host,
        dry_run=False,
    )
    assert "absent desktop:" in again
    assert "unchanged crontab" in again

    preview = uninstall_hooks(
        ["systemd", "crontab"],
        config_home=home,
        host=host,
        dry_run=True,
    )
    assert "absent systemd:" in preview
    assert "would remove crontab marker zlegbot-autostart" in preview
    assert host.writes == 2


def test_percent_is_escaped_in_the_unit_and_command_is_absolute(tmp_path):
    unit = render_unit("echo %PATH", tmp_path / "%dir")
    assert "echo %%PATH" in unit
    assert "%dir" not in unit or "%%dir" in unit
    command = recovery_command(tmp_path / "autostart.yaml")
    assert "run --config" in command
    assert str((tmp_path / "autostart.yaml").resolve()) in command


def test_system_host_refuses_to_write_when_the_read_fails(shadow):
    script = shadow.bindir / "crontab"
    script.write_text(
        "#!/bin/sh\n"
        f"echo crontab \"$@\" >> {shadow.calls}\n"
        "echo permission denied >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    host = SystemHost()
    with pytest.raises(HostError):
        host.read_crontab()
    assert not shadow.store.exists()
    assert "systemctl" not in shadow.call_text()
