"""Write login and boot hooks. This module never calls systemctl."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from autostart.crontab import INSTALL_MARKER, install_lines, uninstall_marker, upsert
from autostart.errors import ConfigError, HostError

DESKTOP_NAME = "zlegbot-autostart.desktop"
UNIT_NAME = "zlegbot-autostart.service"
SYSTEMD_HINT = (
    "systemctl --user daemon-reload && "
    "systemctl --user enable --now zlegbot-autostart.service"
)


def resolve_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config"


def desktop_path(config_home: Path) -> Path:
    return config_home / "autostart" / DESKTOP_NAME


def unit_path(config_home: Path) -> Path:
    return config_home / "systemd" / "user" / UNIT_NAME


def recovery_argv() -> list[str]:
    found = shutil.which("autostart")
    if found:
        return [found]
    return [sys.executable, "-m", "autostart"]


def recovery_command(config_path: Path) -> str:
    parts = recovery_argv() + ["run", "--config", str(Path(config_path).resolve())]
    return " ".join(shlex.quote(part) for part in parts)


def render_desktop(command: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=zlegbot-autostart\n"
        "Comment=Run declared recovery steps after login\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def render_unit(command: str, workdir: Path) -> str:
    # systemd treats % as a specifier. A literal percent in a path is %%.
    exec_start = command.replace("%", "%%")
    directory = str(workdir).replace("%", "%%")
    return (
        "[Unit]\n"
        "Description=Run zlegbot-autostart recovery steps\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={directory}\n"
        f"ExecStart={exec_start}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install_hooks(config, methods, *, config_home: Path, host, dry_run: bool) -> str:
    chosen = _methods(methods)
    command = recovery_command(config.path)
    lines: list[str] = []
    if "desktop" in chosen:
        path = desktop_path(config_home)
        text = render_desktop(command)
        if dry_run:
            lines.append(f"dry-run desktop: {path}")
            lines.append(text.rstrip("\n"))
        else:
            lines.append(f"{write_if_changed(path, text)} desktop: {path}")
    if "systemd" in chosen:
        path = unit_path(config_home)
        text = render_unit(command, config.base)
        if dry_run:
            lines.append(f"dry-run systemd: {path}")
            lines.append(text.rstrip("\n"))
        else:
            lines.append(f"{write_if_changed(path, text)} systemd: {path}")
        lines.append(f"systemd enable hint: {SYSTEMD_HINT}")
    if "crontab" in chosen:
        block = [f"@reboot {command}"]
        if dry_run:
            preview, _changed = upsert("", INSTALL_MARKER, block)
            lines.append("dry-run crontab:")
            lines.append(preview.rstrip("\n"))
        else:
            lines.append(f"{install_lines(host, INSTALL_MARKER, block)} crontab")
    return "\n".join(lines) + "\n"


def uninstall_hooks(methods, *, config_home: Path, host, dry_run: bool) -> str:
    chosen = _methods(methods)
    lines: list[str] = []
    if "desktop" in chosen:
        path = desktop_path(config_home)
        if dry_run:
            state = "would remove" if path.exists() else "absent"
            lines.append(f"{state} desktop: {path}")
        else:
            lines.append(f"{remove_file(path)} desktop: {path}")
    if "systemd" in chosen:
        path = unit_path(config_home)
        if dry_run:
            state = "would remove" if path.exists() else "absent"
            lines.append(f"{state} systemd: {path}")
        else:
            lines.append(f"{remove_file(path)} systemd: {path}")
    if "crontab" in chosen:
        if dry_run:
            lines.append(f"would remove crontab marker {INSTALL_MARKER}")
        else:
            lines.append(f"{uninstall_marker(host, INSTALL_MARKER)} crontab")
    return "\n".join(lines) + "\n"


def write_if_changed(path: Path, text: str) -> str:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return "unchanged"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise HostError(f"could not write {path.name}: {exc.__class__.__name__}") from exc
    return "wrote"


def remove_file(path: Path) -> str:
    try:
        if not path.exists() and not path.is_symlink():
            return "absent"
        path.unlink()
    except OSError as exc:
        raise HostError(f"could not remove {path.name}: {exc.__class__.__name__}") from exc
    return "removed"


def _methods(methods) -> set[str]:
    chosen = set(methods)
    unknown = chosen - {"desktop", "systemd", "crontab"}
    if unknown:
        raise ConfigError(f"unknown install method {sorted(unknown)[0]}")
    if not chosen:
        raise ConfigError("choose at least one of --desktop, --systemd, --crontab")
    return chosen
