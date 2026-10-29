"""Load and validate autostart YAML. Secrets stay in the environment."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

from autostart.crontab import INSTALL_MARKER
from autostart.errors import ConfigError
from autostart.redact import Redactor, scrub

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SENSITIVE_NAME = re.compile(
    r"(URL|URI|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|WEBHOOK|HOOK)",
    re.IGNORECASE,
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")

_TOP = {"log", "log_max_bytes", "log_backups", "stop_on_error", "notify", "steps"}
_NOTIFY_FIELDS = {"type", "url", "timeout", "retries", "backoff"}
_STEP_FIELDS = {
    "ensure_dir": {"name", "type", "path", "paths"},
    "restore": {"name", "type", "dest", "backup", "files"},
    "checksum": {"name", "type", "path", "sha256", "files"},
    "crontab": {"name", "type", "marker", "lines"},
    "process": {"name", "type", "start", "pidfile", "match", "timeout"},
    "command": {"name", "type", "run", "timeout"},
}
_NOTIFY_TYPES = {"discord": "discord", "slack": "slack", "webhook": "webhook", "generic": "webhook"}

_MAX_TIMEOUT = 86400.0
_MAX_BYTES = 1_073_741_824
_DEFAULT_LOG = ".autostart/autostart.log"
_DEFAULT_MAX_BYTES = 1_048_576
_DEFAULT_BACKUPS = 3


@dataclass
class NotifySpec:
    type: str
    url: str
    timeout: float = 30.0
    retries: int = 3
    backoff: float = 0.5


@dataclass
class StepSpec:
    name: str
    type: str
    paths: list[tuple[Path, str]] = field(default_factory=list)
    restores: list[tuple[Path, Path, str, str]] = field(default_factory=list)
    hashes: list[tuple[Path, str, str]] = field(default_factory=list)
    marker: str = ""
    lines: list[str] = field(default_factory=list)
    start: str = ""
    pidfile: Path | None = None
    pidfile_display: str = ""
    match: str = ""
    run: str = ""
    timeout: float = 30.0


@dataclass
class AppConfig:
    path: Path
    base: Path
    log_path: Path
    log_max_bytes: int
    log_backups: int
    stop_on_error: bool
    steps: list[StepSpec]
    notify: NotifySpec | None
    redactor: Redactor


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError("config must be a YAML mapping")

    errors: list[str] = []
    redactor = Redactor()
    base = path.parent.resolve()

    for key in sorted(set(data) - _TOP):
        errors.append(f"unknown setting {key}")

    log_path = _resolve(base, _log_value(data, errors, redactor))
    log_max_bytes = _int(
        data.get("log_max_bytes", _DEFAULT_MAX_BYTES),
        "log_max_bytes",
        errors,
        minimum=0,
        maximum=_MAX_BYTES,
    )
    log_backups = _int(
        data.get("log_backups", _DEFAULT_BACKUPS),
        "log_backups",
        errors,
        minimum=0,
        maximum=50,
    )
    stop_on_error = _bool(data.get("stop_on_error", False), "stop_on_error", errors)
    notify = _parse_notify(data.get("notify", None), "notify" in data, errors, redactor)
    steps = _parse_steps(data.get("steps", None), errors, redactor, base)

    if errors:
        raise ConfigError(errors)
    return AppConfig(
        path=path.resolve(),
        base=base,
        log_path=log_path,
        log_max_bytes=_DEFAULT_MAX_BYTES if log_max_bytes is None else log_max_bytes,
        log_backups=_DEFAULT_BACKUPS if log_backups is None else log_backups,
        stop_on_error=bool(stop_on_error),
        steps=steps,
        notify=notify,
        redactor=redactor,
    )


def configured_log_path(path: Path) -> Path:
    """Read only the log path, so `status` does not need a webhook URL."""
    resolved, _redactor = resolve_log_path(path)
    return resolved


def resolve_log_path(path: Path) -> tuple[Path, Redactor]:
    """Return the log path and a redactor for values substituted into it."""
    path = Path(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError("config must be a YAML mapping")
    raw = data.get("log", _DEFAULT_LOG)
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError("log must be a path")
    errors: list[str] = []
    redactor = Redactor()
    expanded = _expand(raw, sensitive=False, redactor=redactor, errors=errors, label="log")
    if errors:
        raise ConfigError(errors)
    return _resolve(path.parent.resolve(), expanded), redactor


def _read_yaml(path: Path):
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config: {exc.__class__.__name__}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(scrub(f"could not parse YAML: {exc}")) from exc


def _log_value(data: dict, errors: list[str], redactor: Redactor) -> str:
    if "log" not in data:
        return _DEFAULT_LOG
    raw = data.get("log")
    expanded = _expand(raw, sensitive=False, redactor=redactor, errors=errors, label="log")
    if not isinstance(raw, str):
        return _DEFAULT_LOG
    if not expanded.strip():
        errors.append("log must be a path")
        return _DEFAULT_LOG
    return expanded


def _parse_notify(raw, present: bool, errors: list[str], redactor: Redactor) -> NotifySpec | None:
    if not present or raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append("notify must be a mapping")
        return None
    for key in sorted(set(raw) - _NOTIFY_FIELDS):
        errors.append(f"notify: unknown setting {key}")
    kind = raw.get("type")
    if kind not in _NOTIFY_TYPES:
        errors.append("notify.type must be discord, slack, webhook, or generic")
        notify_type = "webhook"
    else:
        notify_type = _NOTIFY_TYPES[kind]
    url = ""
    if "url" not in raw:
        errors.append("notify.url is required")
    else:
        url = _expand(raw.get("url"), sensitive=True, redactor=redactor, errors=errors, label="notify.url")
        if isinstance(raw.get("url"), str):
            _require_http(url, "notify.url", errors)
    timeout = _seconds(raw.get("timeout", 30), "notify.timeout", errors, allow_zero=False)
    retries = _int(raw.get("retries", 3), "notify.retries", errors, minimum=1, maximum=20)
    backoff = _seconds(raw.get("backoff", 0.5), "notify.backoff", errors, allow_zero=True)
    if errors and (not url or "${" in url):
        return None
    return NotifySpec(
        type=notify_type,
        url=url,
        timeout=30.0 if timeout is None else timeout,
        retries=3 if retries is None else retries,
        backoff=0.5 if backoff is None else backoff,
    )


def _parse_steps(raw, errors: list[str], redactor: Redactor, base: Path) -> list[StepSpec]:
    if raw is None:
        errors.append("steps is required")
        return []
    if not isinstance(raw, list):
        errors.append("steps must be a list")
        return []
    if not raw:
        errors.append("steps must contain at least one step")
        return []
    parsed: list[StepSpec] = []
    seen: set[str] = set()
    for index, body in enumerate(raw):
        label = f"steps[{index}]"
        if not isinstance(body, dict):
            errors.append(f"{label} must be a mapping")
            continue
        name = body.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            errors.append(f"{label}.name must be a short letter-or-number identifier")
            step_name = f"step{index}"
            label_name = label
        else:
            step_name = name
            label_name = f"step {name}"
            if name in seen:
                errors.append(f"duplicate step name {name}")
            seen.add(name)
        step_type = body.get("type")
        if step_type not in _STEP_FIELDS:
            errors.append(
                f"{label_name}: type must be ensure_dir, restore, checksum, crontab, process, or command"
            )
            continue
        for key in sorted(set(body) - _STEP_FIELDS[step_type]):
            errors.append(f"{label_name}: unknown setting {key}")
        spec = StepSpec(name=step_name, type=step_type)
        if step_type == "ensure_dir":
            _fill_ensure_dir(body, spec, label_name, errors, redactor, base)
        elif step_type == "restore":
            _fill_restore(body, spec, label_name, errors, redactor, base)
        elif step_type == "checksum":
            _fill_checksum(body, spec, label_name, errors, redactor, base)
        elif step_type == "crontab":
            _fill_crontab(body, spec, label_name, errors, redactor)
        elif step_type == "process":
            _fill_process(body, spec, label_name, errors, redactor, base)
        else:
            _fill_command(body, spec, label_name, errors, redactor)
        parsed.append(spec)
    return parsed


def _fill_ensure_dir(body, spec: StepSpec, label, errors, redactor, base: Path) -> None:
    displays: list[str] = []
    if "path" in body:
        text = _expand(body.get("path"), sensitive=False, redactor=redactor, errors=errors, label=f"{label}.path")
        if isinstance(body.get("path"), str) and text.strip():
            displays.append(text)
        elif isinstance(body.get("path"), str):
            errors.append(f"{label}.path must not be empty")
    if "paths" in body:
        displays.extend(_path_list(body.get("paths"), f"{label}.paths", errors, redactor))
    if "path" not in body and "paths" not in body:
        errors.append(f"{label} needs path or paths")
    if not displays and ("path" in body or "paths" in body):
        return
    spec.paths = [(_resolve(base, item), item) for item in displays]


def _fill_restore(body, spec: StepSpec, label, errors, redactor, base: Path) -> None:
    jobs: list[tuple[str, str]] = []
    has_dest = "dest" in body
    has_backup = "backup" in body
    if has_dest or has_backup:
        if not has_dest or not has_backup:
            errors.append(f"{label} needs both dest and backup")
        else:
            dest = _expand(body.get("dest"), sensitive=False, redactor=redactor, errors=errors, label=f"{label}.dest")
            backup = _expand(
                body.get("backup"),
                sensitive=False,
                redactor=redactor,
                errors=errors,
                label=f"{label}.backup",
            )
            if isinstance(body.get("dest"), str) and isinstance(body.get("backup"), str):
                if dest.strip() and backup.strip():
                    jobs.append((dest, backup))
                else:
                    errors.append(f"{label} dest and backup must not be empty")
    if "files" in body:
        jobs.extend(_file_pairs(body.get("files"), f"{label}.files", errors, redactor))
    if "dest" not in body and "backup" not in body and "files" not in body:
        errors.append(f"{label} needs dest and backup, or files")
    spec.restores = [
        (_resolve(base, dest), _resolve(base, backup), dest, backup) for dest, backup in jobs
    ]


def _fill_checksum(body, spec: StepSpec, label, errors, redactor, base: Path) -> None:
    jobs: list[tuple[str, str]] = []
    if "path" in body or "sha256" in body:
        if "path" not in body or "sha256" not in body:
            errors.append(f"{label} needs both path and sha256")
        else:
            display = _expand(
                body.get("path"),
                sensitive=False,
                redactor=redactor,
                errors=errors,
                label=f"{label}.path",
            )
            digest = _digest(body.get("sha256"), f"{label}.sha256", errors)
            if isinstance(body.get("path"), str) and display.strip() and digest:
                jobs.append((display, digest))
            elif isinstance(body.get("path"), str) and not display.strip():
                errors.append(f"{label}.path must not be empty")
    if "files" in body:
        jobs.extend(_hash_list(body.get("files"), f"{label}.files", errors, redactor))
    if "path" not in body and "sha256" not in body and "files" not in body:
        errors.append(f"{label} needs path and sha256, or files")
    spec.hashes = [(_resolve(base, display), digest, display) for display, digest in jobs]


def _fill_crontab(body, spec: StepSpec, label, errors, redactor) -> None:
    marker = spec.name
    if "marker" in body:
        raw = body.get("marker")
        if not isinstance(raw, str) or not _NAME.fullmatch(raw):
            errors.append(f"{label}.marker must be a short letter-or-number identifier")
        else:
            marker = raw
    if marker == INSTALL_MARKER:
        errors.append(f"{label}.marker {INSTALL_MARKER} is reserved for autostart install")
    spec.marker = marker
    if "lines" not in body:
        errors.append(f"{label}.lines is required")
        return
    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        errors.append(f"{label}.lines must be a non-empty list")
        return
    begin = f"# BEGIN autostart:{marker}"
    end = f"# END autostart:{marker}"
    cleaned: list[str] = []
    for index, item in enumerate(raw_lines):
        item_label = f"{label}.lines[{index}]"
        text = _expand(item, sensitive=True, redactor=redactor, errors=errors, label=item_label)
        if not isinstance(item, str):
            continue
        if "\n" in text or "\r" in text or text.strip() == "":
            errors.append(f"{item_label} must be one non-empty crontab line")
            continue
        if text.strip() in {begin, end}:
            errors.append(f"{item_label} collides with the marker")
            continue
        cleaned.append(text)
    spec.lines = cleaned


def _fill_process(body, spec: StepSpec, label, errors, redactor, base: Path) -> None:
    if "start" in body:
        text = _expand(body.get("start"), sensitive=True, redactor=redactor, errors=errors, label=f"{label}.start")
        if isinstance(body.get("start"), str):
            if text.strip():
                spec.start = text
            else:
                errors.append(f"{label}.start must not be empty")
    if "pidfile" in body:
        display = _expand(
            body.get("pidfile"),
            sensitive=False,
            redactor=redactor,
            errors=errors,
            label=f"{label}.pidfile",
        )
        if isinstance(body.get("pidfile"), str):
            if display.strip():
                spec.pidfile = _resolve(base, display)
                spec.pidfile_display = display
            else:
                errors.append(f"{label}.pidfile must not be empty")
    if "match" in body:
        text = _expand(body.get("match"), sensitive=True, redactor=redactor, errors=errors, label=f"{label}.match")
        if isinstance(body.get("match"), str):
            if text.strip() and "\n" not in text:
                spec.match = text
            else:
                errors.append(f"{label}.match must be a single non-empty pattern")
    if spec.pidfile is None and not spec.match and ("pidfile" not in body and "match" not in body):
        errors.append(f"{label} needs pidfile or match")
    elif spec.pidfile is None and not spec.match:
        errors.append(f"{label} needs a usable pidfile or match")
    spec.timeout = _timeout(body, label, errors, default=10.0)


def _fill_command(body, spec: StepSpec, label, errors, redactor) -> None:
    if "run" not in body:
        errors.append(f"{label}.run is required")
    else:
        text = _expand(body.get("run"), sensitive=True, redactor=redactor, errors=errors, label=f"{label}.run")
        if isinstance(body.get("run"), str):
            if text.strip():
                spec.run = text
            else:
                errors.append(f"{label}.run must not be empty")
    spec.timeout = _timeout(body, label, errors, default=30.0)


def _path_list(raw, label, errors, redactor) -> list[str]:
    if not isinstance(raw, list) or not raw:
        errors.append(f"{label} must be a non-empty list")
        return []
    found = []
    for index, item in enumerate(raw):
        text = _expand(item, sensitive=False, redactor=redactor, errors=errors, label=f"{label}[{index}]")
        if isinstance(item, str) and text.strip():
            found.append(text)
        elif isinstance(item, str):
            errors.append(f"{label}[{index}] must not be empty")
    return found


def _file_pairs(raw, label, errors, redactor) -> list[tuple[str, str]]:
    if not isinstance(raw, list) or not raw:
        errors.append(f"{label} must be a non-empty list")
        return []
    jobs = []
    for index, item in enumerate(raw):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be a mapping")
            continue
        for key in sorted(set(item) - {"dest", "backup"}):
            errors.append(f"{item_label}: unknown setting {key}")
        if "dest" not in item or "backup" not in item:
            errors.append(f"{item_label} needs dest and backup")
            continue
        dest = _expand(item.get("dest"), sensitive=False, redactor=redactor, errors=errors, label=f"{item_label}.dest")
        backup = _expand(
            item.get("backup"),
            sensitive=False,
            redactor=redactor,
            errors=errors,
            label=f"{item_label}.backup",
        )
        if isinstance(item.get("dest"), str) and isinstance(item.get("backup"), str):
            if dest.strip() and backup.strip():
                jobs.append((dest, backup))
            else:
                errors.append(f"{item_label} dest and backup must not be empty")
    return jobs


def _hash_list(raw, label, errors, redactor) -> list[tuple[str, str]]:
    if not isinstance(raw, list) or not raw:
        errors.append(f"{label} must be a non-empty list")
        return []
    jobs = []
    for index, item in enumerate(raw):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be a mapping")
            continue
        for key in sorted(set(item) - {"path", "sha256"}):
            errors.append(f"{item_label}: unknown setting {key}")
        if "path" not in item or "sha256" not in item:
            errors.append(f"{item_label} needs path and sha256")
            continue
        display = _expand(
            item.get("path"),
            sensitive=False,
            redactor=redactor,
            errors=errors,
            label=f"{item_label}.path",
        )
        digest = _digest(item.get("sha256"), f"{item_label}.sha256", errors)
        if isinstance(item.get("path"), str) and display.strip() and digest:
            jobs.append((display, digest))
        elif isinstance(item.get("path"), str) and not display.strip():
            errors.append(f"{item_label}.path must not be empty")
    return jobs


def _digest(value, label, errors) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip()):
        errors.append(f"{label} must be 64 hex characters")
        return ""
    return value.strip().lower()


def _timeout(body, label, errors, *, default: float) -> float:
    if "timeout" not in body:
        return default
    parsed = _seconds(body.get("timeout"), f"{label}.timeout", errors, allow_zero=False)
    if parsed is None:
        return default
    return parsed


def _expand(value, *, sensitive: bool, redactor: Redactor, errors: list[str], label: str) -> str:
    if not isinstance(value, str):
        errors.append(f"{label} must be a string")
        return ""
    missing = []
    # `$${` is an escaped `${` so a shell command can keep a literal variable.
    sentinel = "\x00AUTOSTART_DOLLAR\x00"
    protected = value.replace("$${", sentinel)

    def repl(match):
        name = match.group(1)
        if name not in os.environ:
            missing.append(name)
            return match.group(0)
        env_value = os.environ[name]
        if sensitive or _SENSITIVE_NAME.search(name):
            redactor.add(env_value)
        return env_value

    expanded = _ENV.sub(repl, protected).replace(sentinel, "${")
    for name in sorted(set(missing)):
        errors.append(f"{label} references unset environment variable {name}")
    if missing:
        return expanded
    if sensitive and expanded != value and "://" in expanded:
        redactor.add(expanded)
    return expanded


def _require_http(url: str, label: str, errors: list[str]) -> bool:
    if "${" in url:
        return False
    if not url or not url.strip():
        errors.append(f"{label} must not be empty")
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append(f"{label} must be an http(s) URL")
        return False
    return True


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def _bool(value, label, errors) -> bool:
    if not isinstance(value, bool):
        errors.append(f"{label} must be true or false")
        return False
    return value


def _seconds(value, label, errors, *, allow_zero: bool):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{label} must be seconds")
        return None
    seconds = float(value)
    if seconds < 0 or seconds > _MAX_TIMEOUT or (not allow_zero and seconds <= 0):
        if allow_zero:
            errors.append(f"{label} must be between 0 and {_MAX_TIMEOUT:g} seconds")
        else:
            errors.append(f"{label} must be greater than 0 and at most {_MAX_TIMEOUT:g} seconds")
        return None
    return seconds


def _int(value, label, errors, *, minimum: int, maximum: int | None = None):
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{label} must be an integer")
        return None
    if value < minimum:
        errors.append(f"{label} must be >= {minimum}")
        return None
    if maximum is not None and value > maximum:
        errors.append(f"{label} must be <= {maximum}")
        return None
    return value
