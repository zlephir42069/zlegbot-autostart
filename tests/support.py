"""Shared fakes. HTTP stays on 127.0.0.1. Crontab is never the real binary."""

from __future__ import annotations

import os
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from autostart.errors import StepError

warnings.filterwarnings(
    "ignore",
    message=r"unclosed <socket\.socket",
    category=ResourceWarning,
)

REPO = Path(__file__).resolve().parents[1]
PROXY_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.posts.append(raw)
        self.server.paths.append(self.path)
        status = 200
        if self.server.fail_remaining > 0:
            self.server.fail_remaining -= 1
            status = 500
        body = b"ok" if status < 400 else b"err"
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class LocalServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.posts = []
        self.httpd.paths = []
        self.httpd.fail_remaining = 0
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


class FakeHost:
    """In-memory crontab and process table."""

    def __init__(self):
        self.crontab_text = ""
        self.writes = 0
        self.reads = 0
        self.spawned = []
        self.commands = []
        self.alive = set()
        self.matches = {}
        self.on_spawn = None
        self.command_codes = {}
        self.default_code = 0
        self.fail_read = None

    def read_crontab(self) -> str:
        self.reads += 1
        if self.fail_read is not None:
            raise self.fail_read
        return self.crontab_text

    def write_crontab(self, text: str) -> None:
        self.writes += 1
        self.crontab_text = text

    def pid_alive(self, pid: int) -> bool:
        return pid in self.alive

    def pgrep(self, pattern: str) -> list[int]:
        return list(self.matches.get(pattern, []))

    def spawn(self, command: str, cwd: Path) -> None:
        self.spawned.append((command, Path(cwd)))
        if self.on_spawn is not None:
            self.on_spawn(command)

    def run(self, command: str, cwd: Path, timeout: float) -> int:
        self.commands.append((command, Path(cwd), timeout))
        code = self.command_codes.get(command, self.default_code)
        if code == "timeout":
            raise StepError(f"timed out after {timeout:g}s")
        return code


class Clock:
    """Monotonic stand-in. ``sleep`` moves the clock forward and does not wait."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class Shadow:
    def __init__(self, bindir: Path, store: Path, calls: Path):
        self.bindir = bindir
        self.store = store
        self.calls = calls

    def call_text(self) -> str:
        if not self.calls.exists():
            return ""
        return self.calls.read_text(encoding="utf-8")

    def crontab(self) -> str:
        if not self.store.exists():
            return ""
        return self.store.read_text(encoding="utf-8")


def write_config(root: Path, text: str, name: str = "autostart.yaml") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def child_env(root: Path, **extra: str) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(root)
    env["XDG_CONFIG_HOME"] = str(root / "xdg")
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env["AUTOSTART_STATUS_URL"] = "https://example.com/hooks/autostart"
    env["TOKEN"] = "SUPERSECRETTOKEN"
    env.update(extra)
    return env
