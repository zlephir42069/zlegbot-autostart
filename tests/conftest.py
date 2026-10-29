"""Keep every test off the real crontab and the real systemd."""

from __future__ import annotations

import os

import pytest

from support import PROXY_KEYS, Shadow


@pytest.fixture(autouse=True)
def shadow(tmp_path, monkeypatch):
    bindir = tmp_path / "host-bin"
    bindir.mkdir()
    store = tmp_path / "crontab-store"
    calls = tmp_path / "host-calls"
    _write(bindir / "crontab", _CRONTAB.format(store=repr(str(store)), calls=repr(str(calls))))
    _write(bindir / "systemctl", _SYSTEMCTL.format(calls=repr(str(calls))))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    # Leave HOME alone. The user-scheme console script path is derived from it,
    # and XDG_CONFIG_HOME already keeps hook files inside the test tmp dir.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for key in PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield Shadow(bindir, store, calls)


@pytest.fixture
def server():
    from support import LocalServer

    running = LocalServer()
    yield running
    running.close()


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


_CRONTAB = """#!/usr/bin/env python3
import pathlib, sys
store = pathlib.Path({store})
calls = pathlib.Path({calls})
with calls.open("a", encoding="utf-8") as handle:
    handle.write("crontab " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args == ["-l"]:
    if not store.exists():
        sys.stderr.write("no crontab for user\\n")
        raise SystemExit(1)
    sys.stdout.write(store.read_text(encoding="utf-8"))
    raise SystemExit(0)
if args == ["-r"]:
    store.unlink(missing_ok=True)
    raise SystemExit(0)
if args == ["-"]:
    store.write_text(sys.stdin.read(), encoding="utf-8")
    raise SystemExit(0)
sys.stderr.write("unsupported crontab args\\n")
raise SystemExit(2)
"""

_SYSTEMCTL = """#!/usr/bin/env python3
import pathlib, sys
calls = pathlib.Path({calls})
with calls.open("a", encoding="utf-8") as handle:
    handle.write("systemctl " + " ".join(sys.argv[1:]) + "\\n")
raise SystemExit(97)
"""
