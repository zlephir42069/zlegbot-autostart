"""Command line: install, uninstall, run, validate, status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autostart.errors import ConfigError, CrontabError, HostError, NotifyError
from autostart.redact import scrub


def main(argv=None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)

    try:
        if args.command == "validate":
            return _validate(args)
        if args.command == "run":
            return _run(args)
        if args.command == "status":
            return _status(args)
        if args.command == "install":
            return _install(args)
        if args.command == "uninstall":
            return _uninstall(args)
    except ConfigError as exc:
        for message in exc.messages:
            print(f"config error: {scrub(message)}", file=sys.stderr, flush=True)
        return 2
    except (HostError, CrontabError, NotifyError, OSError) as exc:
        print(f"error: {scrub(str(exc))}", file=sys.stderr, flush=True)
        return 1
    except BrokenPipeError:
        return 0
    print("config error: unknown command", file=sys.stderr, flush=True)
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autostart",
        description="Replay declared recovery steps after a reboot without calling an AI agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install", help="write a login or boot hook")
    _add_config(install_parser)
    _add_methods(install_parser)
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the hook contents and do not write them",
    )

    uninstall_parser = sub.add_parser(
        "uninstall",
        help="remove a login or boot hook",
        description="Remove the selected hooks. The config file is not read.",
    )
    _add_config(uninstall_parser)
    _add_methods(uninstall_parser)
    uninstall_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be removed and do not change it",
    )

    run_parser = sub.add_parser("run", help="run recovery steps in order")
    _add_config(run_parser)

    validate_parser = sub.add_parser("validate", help="validate the config and exit")
    _add_config(validate_parser)

    status_parser = sub.add_parser("status", help="show the last completed run")
    _add_config(status_parser)
    return parser


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default="autostart.yaml",
        help="path to the config file (default: autostart.yaml)",
    )


def _add_methods(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--desktop", action="store_true", help="XDG autostart .desktop entry")
    parser.add_argument("--systemd", action="store_true", help="systemd --user unit file")
    parser.add_argument("--crontab", action="store_true", help="@reboot line in the user crontab")


def _methods(args) -> list[str]:
    chosen = []
    if args.desktop:
        chosen.append("desktop")
    if args.systemd:
        chosen.append("systemd")
    if args.crontab:
        chosen.append("crontab")
    if not chosen:
        raise ConfigError("choose at least one of --desktop, --systemd, --crontab")
    return chosen


def _validate(args) -> int:
    from autostart.config import load_config

    load_config(Path(args.config))
    print("ok", flush=True)
    return 0


def _run(args) -> int:
    from autostart.config import load_config
    from autostart.run import execute

    config = load_config(Path(args.config))
    return execute(config)


def _status(args) -> int:
    from autostart.config import resolve_log_path
    from autostart.status import render_status

    log_path, redactor = resolve_log_path(Path(args.config))
    print(redactor.text(render_status(log_path)), end="")
    return 0


def _install(args) -> int:
    from autostart.config import load_config
    from autostart.host import SystemHost
    from autostart.install import install_hooks, resolve_config_home

    config = load_config(Path(args.config))
    text = install_hooks(
        config,
        _methods(args),
        config_home=resolve_config_home(),
        host=SystemHost(),
        dry_run=args.dry_run,
    )
    print(text, end="")
    return 0


def _uninstall(args) -> int:
    from autostart.host import SystemHost
    from autostart.install import resolve_config_home, uninstall_hooks

    text = uninstall_hooks(
        _methods(args),
        config_home=resolve_config_home(),
        host=SystemHost(),
        dry_run=args.dry_run,
    )
    print(text, end="")
    return 0
