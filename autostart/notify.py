"""Post one status line. Discord mentions are always disabled."""

from __future__ import annotations

import time

from autostart.errors import NotifyError
from autostart.http import post_json

_LIMIT = 1900


def post_status(spec, line: str, sleeper=time.sleep) -> None:
    """POST ``line``. Sleep grows as ``backoff * 2**attempt`` between failures."""
    delay = spec.backoff
    last = "notify failed"
    text = one_line(line)
    attempts = spec.retries
    for attempt in range(attempts):
        try:
            _once(spec, text)
            return
        except NotifyError as exc:
            last = str(exc)
            if attempt + 1 >= attempts:
                break
            sleeper(delay)
            delay *= 2
        except Exception as exc:
            last = exc.__class__.__name__
            if attempt + 1 >= attempts:
                break
            sleeper(delay)
            delay *= 2
    raise NotifyError(last)


def one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _LIMIT:
        return collapsed
    return collapsed[: _LIMIT - 3] + "..."


def _once(spec, text: str) -> None:
    if spec.type == "discord":
        # parse: [] disables @everyone, @here, user, and role mentions.
        payload = {"content": text, "allowed_mentions": {"parse": []}}
    elif spec.type in {"slack", "webhook"}:
        payload = {"text": text}
    else:
        raise NotifyError(f"unknown notify type {spec.type}")
    post_json(spec.url, payload, spec.timeout)
