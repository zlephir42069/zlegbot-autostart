"""Small urllib wrapper. URLs are never included in raised messages."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from autostart import __version__
from autostart.errors import NotifyError

USER_AGENT = f"autostart/{__version__}"


def post_json(
    url: str,
    payload: dict,
    timeout: float,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1024)
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise NotifyError(_reason(exc)) from exc


def _reason(exc: urllib.error.URLError) -> str:
    """A short failure name. Never the URL, and never a string reason."""
    reason = exc.reason
    if isinstance(reason, str):
        return "request failed"
    text = getattr(reason, "strerror", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    return reason.__class__.__name__
