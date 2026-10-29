# Contributing

Thanks for looking at autostart. Keep changes small, and cover them with tests.

## Setup

Python 3.10 or newer. The runtime dependencies are the standard library and PyYAML.

```bash
python -m pip install -e ".[dev]"
python -m pytest -v
```

Tests are offline. HTTP is a local `http.server` on `127.0.0.1`. The suite puts a fake `crontab` and a fake `systemctl` at the front of `PATH`. A test that reaches the real crontab or runs `systemctl` is a bug.

## Guidelines

- Do not add secrets, tokens, or personal data to the repo, tests, fixtures, or logs.
- Webhook URLs belong in environment variables referenced as `${NAME}`. Anything new that prints or writes a log line has to pass through the redactor.
- `install` writes unit files. It must not invoke `systemctl`.
- A crontab read error must not be followed by a write. An unbalanced marker must not be rewritten.
- A failed step must not hide later steps unless `stop_on_error` is set. The process still exits non-zero.
- Prefer a clear config key over a new feature. `autostart status` may only print what the log actually contains.
