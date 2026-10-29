"""Run every step in order and append a rotating log."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from autostart.errors import NotifyError
from autostart.host import SystemHost
from autostart.notify import post_status
from autostart.steps import run_step


def execute(config, *, host=None, sleeper=None, clock=None) -> int:
    """Run ``config.steps``. Returns 0, or 1 if a step or the status post failed.

    Later steps still run when an earlier one fails, unless ``stop_on_error``
    is set. The status webhook, when configured, runs after the steps.
    """
    import time

    host = host or SystemHost()
    sleeper = time.sleep if sleeper is None else sleeper
    clock = time.monotonic if clock is None else clock
    try:
        logger = open_log(config)
    except OSError:
        print("log error: could not open log", file=sys.stderr, flush=True)
        return 1

    failed: list[str] = []
    ran = 0
    try:
        for step in config.steps:
            result = run_step(step, base=config.base, host=host, sleeper=sleeper, clock=clock)
            ran += 1
            detail = config.redactor.text(result.detail)
            _emit_step(logger, result, detail)
            _print_step(result, detail)
            if not result.ok:
                failed.append(result.name)
                if config.stop_on_error:
                    break
        if config.notify is not None:
            if not _notify(config, failed, ran, logger, sleeper):
                failed.append("notify")
        status = "ok" if not failed else "failed"
        _emit(
            logger,
            f"run ts={_ts()} status={status} steps={ran} failed={','.join(failed)}",
        )
        return 0 if status == "ok" else 1
    except OSError:
        print("log error: could not write log", file=sys.stderr, flush=True)
        return 1
    finally:
        close_log(logger)


def open_log(config) -> logging.Logger:
    logger = logging.getLogger("autostart.run")
    close_log(logger)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.log_path,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backups,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def close_log(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _notify(config, failed: list[str], ran: int, logger, sleeper) -> bool:
    line = status_line(failed, ran)
    try:
        post_status(config.notify, line, sleeper=sleeper)
    except NotifyError as exc:
        detail = config.redactor.text(str(exc)).replace("\n", " ").strip() or "-"
        _emit(logger, f"notify ts={_ts()} status=failed detail={detail}")
        print(f"failed notify: {detail}", file=sys.stderr, flush=True)
        return False
    _emit(logger, f"notify ts={_ts()} status=ok detail=posted")
    return True


def status_line(failed: list[str], ran: int) -> str:
    if not failed:
        return f"autostart ok: {ran} steps"
    return "autostart failed: " + ", ".join(failed)


def _emit_step(logger, result, detail: str) -> None:
    state = "ok" if result.ok else "failed"
    cleaned = detail.replace("\r", " ").replace("\n", " ").strip() or "-"
    _emit(
        logger,
        f"step ts={_ts()} name={result.name} type={result.type} status={state} detail={cleaned}",
    )


def _print_step(result, detail: str) -> None:
    label = "ok" if result.ok else "failed"
    stream = sys.stdout if result.ok else sys.stderr
    print(f"{label} {result.name}: {detail}", file=stream, flush=True)


def _emit(logger, message: str) -> None:
    logger.info(message)
    for handler in logger.handlers:
        handler.flush()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
