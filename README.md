# autostart

zlegbot-autostart is a recovery hook for a Linux machine that runs automation. After a reboot or a reset it replays a list of steps you declared: create directories, copy missing files back from a backup, check checksums, reinstall one block of crontab lines, start long-running processes, and run health-check commands. The steps are files and processes. No model is called.

The hook is the thing that runs at boot. An agent is not in that path. A webhook, when you configure one, only receives a single status line after the steps finish.

This is one piece of the toolkit at [github.com/zlephir42069](https://github.com/zlephir42069). [wakegate](https://github.com/zlephir42069/zlegbot-wakegate) is the companion that watches cheap signals and starts an agent only when one of them fires. autostart brings the machine back. wakegate decides whether an agent is needed after that.

## Why this saves credits

A reboot checklist handed to an agent is a model call that repeats the same file and process checks. Point boot at `autostart run` instead. The process creates directories, copies files, hashes them, edits a crontab block, and checks pids, then exits. Nothing in this repository calls a model, estimates a price, or reports a savings figure. What an avoided agent turn would have cost depends on the agent you did not call.

## 60-second quickstart

Requires Python 3.10+ and a POSIX system (`crontab` and `pgrep` are used when a step asks for them).

```bash
python -m pip install -e .
cp autostart.example.yaml autostart.yaml
# Edit paths and commands in autostart.yaml.
export AUTOSTART_STATUS_URL="https://example.com/hooks/autostart"
autostart validate
autostart run
autostart status
```

`python -m autostart` is the same entry point. Delete the `notify` block if you do not want a status post. `validate` does not create directories, touch the crontab, or contact the network.

Put `run` on a boot hook:

```bash
autostart install --desktop --systemd --crontab
autostart install --crontab --dry-run
```

`--dry-run` prints the hook and does not write it. Passing no method flag is an error. See [Install the hook](#install-the-hook).

## Install the hook

`autostart install` validates the config, then writes the methods you name. Running it again with the same config rewrites nothing when the bytes already match. Webhook URLs stay in the environment. They are not copied into the desktop file, the unit, or the crontab line.

| Flag | What it writes |
| --- | --- |
| `--desktop` | `$XDG_CONFIG_HOME/autostart/zlegbot-autostart.desktop` (default `$HOME/.config`) |
| `--systemd` | `$XDG_CONFIG_HOME/systemd/user/zlegbot-autostart.service` |
| `--crontab` | one `@reboot` line inside a marker block in the user crontab |
| `--dry-run` | print those contents and do not write |

`install` does not run `systemctl`. After `--systemd` it prints:

```bash
systemctl --user daemon-reload && systemctl --user enable --now zlegbot-autostart.service
```

A user unit starts at boot without a login only when lingering is enabled (`loginctl enable-linger`). The desktop entry runs at graphical login. The `@reboot` crontab line runs at boot for that user when cron is installed. On a headless machine, prefer `--crontab` or a lingering user unit.

`autostart uninstall` takes the same method flags and removes those hooks. It does not read the config file. `--config` is accepted so an `install` command can be edited into `uninstall`. `--dry-run` prints the removals and does not change anything. A missing file or a missing marker is success.

The generated command is absolute: the `autostart` executable on `PATH`, or `python -m autostart` when the console script is not installed, plus `run --config` and the absolute config path. Shell commands inside steps run with the config file's directory as the working directory. Relative paths in the config are resolved from that directory.

Static illustrations, with placeholder paths, live in `examples/autostart.desktop`, `examples/autostart.service`, and `examples/crontab`.

## Config reference

`autostart.yaml` is the default path.

| Setting | Default | Meaning |
| --- | --- | --- |
| `log` | `.autostart/autostart.log` | Rotating log. One line per step and one line per run. |
| `log_max_bytes` | `1048576` | Rotate at this size. `0` turns rotation off. |
| `log_backups` | `3` | Older files kept as `autostart.log.1` and so on. |
| `stop_on_error` | `false` | When `true`, skip later steps after the first failure. |
| `notify` | omitted | Optional status post. Omit it, or set it to `null`, to skip. |
| `steps` | required | List of steps, run from top to bottom. |

Every step needs a unique `name` and a `type`. Names are short identifiers: letters, numbers, `.`, `_`, and `-`.

`${NAME}` anywhere in a string is replaced from the environment at load time. A referenced variable that is unset is a config error. `$${NAME}` becomes a literal `${NAME}` so a shell command can keep its own variable. Values substituted into commands, crontab lines, pgrep patterns, and notify URLs are redacted from stdout, stderr, and the log. A variable whose name looks like a secret (`URL`, `TOKEN`, `SECRET`, and similar) is redacted wherever it was substituted. Incoming-webhook URLs are redacted even when they were pasted as literals.

Quote crontab lines (`"15 * * * * /usr/local/bin/hourly-job"`). Unquoted `*` is a YAML alias.

`autostart validate` checks the file and exits non-zero with one message per problem. It does not contact the network, create the log, or read the crontab. A notify URL must already be in the environment when the `notify` block is present.

Exit codes: `0` ok, `1` a step failed, the status post failed, the log could not be written, or `crontab` failed, `2` config or usage error. `autostart status` exits `0` when it can print a report, including when nothing has run yet. It does not copy the run's failure into its own exit code.

When `stop_on_error` is false, later steps still run after a failure. The process exits `1` if any step failed. The status line lists the failed step names.

## Steps

### `ensure_dir`

Creates each directory, including parents. A path that is already a directory counts as present. A path that exists and is not a directory fails the step.

```yaml
- name: dirs
  type: ensure_dir
  paths:
    - ./data
    - ./run
```

`path` is the one-directory form of `paths`.

### `restore`

Copies `backup` to `dest` when `dest` is missing. An existing file or symlink is left in place, even when the bytes differ. A destination that is a directory fails the step. A missing backup fails the step, and nothing in that step is copied. Parent directories of a missing destination are created. `files` is a list of `{dest, backup}` mappings and can be combined with the single pair.

```yaml
- name: note
  type: restore
  dest: ./data/note.txt
  backup: ./backup/note.txt
```

### `checksum`

SHA-256 of a file, compared as lowercase hex. A missing file, a directory, or a different hash fails the step. The expected hash is 64 hex characters. `files` is a list of `{path, sha256}` mappings.

```yaml
- name: note-hash
  type: checksum
  path: ./data/note.txt
  sha256: dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22
```

### `crontab`

Reinstalls one block in the user crontab. The marker defaults to the step name. `zlegbot-autostart` is reserved for `autostart install`.

```text
# BEGIN autostart:jobs
15 * * * * /usr/local/bin/hourly-job
# END autostart:jobs
```

Lines outside the block are preserved. A second run with the same lines does not call `crontab` to write. An unclosed marker fails the step and does not write. A missing crontab is an empty one, which is how `crontab -l` reports `no crontab`. Any other `crontab` error fails the step and does not write.

```yaml
- name: jobs
  type: crontab
  marker: jobs
  lines:
    - "15 * * * * /usr/local/bin/hourly-job"
```

### `process`

The process counts as running when the pidfile names a live pid, or when `pgrep -f` finds `match`. If you set both, either one is enough. Signal 0 is the liveness check. It does not signal the process.

When neither check sees a process and `start` is set, the command is started once in the background (working directory is the config directory) and the step polls until a check passes or `timeout` seconds elapse (default 10). The start command is responsible for writing the pidfile. When `start` is omitted and the process is down, the step fails. Stdout and stderr from the start command are discarded.

```yaml
- name: worker
  type: process
  pidfile: ./run/worker.pid
  match: autostart-worker
  start: ./bin/worker
  timeout: 10
```

`match` is a `pgrep` regular expression, passed as an argument, not through a shell. Use a specific token. The autostart process's own pid is ignored, so a pattern that also appears in this command line does not count as the worker.

### `command`

Runs a health-check command with `timeout` seconds (default 30). The config file is trusted. Exit 0 passes. Any other exit fails the step. A timeout fails the step. Stdout and stderr are not stored or logged.

```yaml
- name: ready
  type: command
  run: test -f ./data/note.txt
  timeout: 10
```

## Status webhook

`notify` posts one line after the steps. The line is `autostart ok: N steps` or `autostart failed: name, name`. A failed post fails the run. The URL is not written to the log.

| `type` | Body |
| --- | --- |
| `discord` | `content` set to the line, plus `allowed_mentions: {"parse": []}` so the message cannot mass-ping. This is always set. |
| `slack` | `{"text": "<line>"}` |
| `webhook` | `{"text": "<line>"}`. `generic` is the same type. |

Retries default to 3. The backoff starts at 0.5 seconds and doubles after each failure. The timeout default is 30 seconds. Placeholders only:

```bash
export AUTOSTART_STATUS_URL="https://example.com/hooks/autostart"
export AUTOSTART_STATUS_URL="https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN"
export AUTOSTART_STATUS_URL="https://hooks.slack.com/services/T000/B000/XXXXXXXX"
```

Do not commit a real URL. `validate` fails when `notify` is set and the variable is missing, so a configured post cannot be skipped by accident.

## `autostart run` and `autostart status`

`run` executes the steps in order, then the optional post. Each step prints `ok <name>: <detail>` or `failed <name>: <detail>`. The same text is appended to the rotating log, with a timestamp:

```text
step ts=2026-10-29T12:00:00+00:00 name=dirs type=ensure_dir status=ok detail=created=2 present=0
run ts=2026-10-29T12:00:01+00:00 status=ok steps=6 failed=
```

`steps` in that line is how many steps ran. `failed` is a comma-separated list, and includes `notify` when the post failed.

```bash
autostart status
autostart status --config /opt/autostart/autostart.yaml
```

`status` prints the last `run` line in the current log file. It does not need the webhook variable. When the log file is missing it prints `no runs yet`.

## Scheduling when the machine is off

`examples/github-actions.yml` is a schedule-triggered workflow. Copy it to `.github/workflows/autostart.yml`. It installs this package and runs `examples/cloud.yaml`, which only creates a directory, restores `examples/note.txt`, checks its checksum, and runs `test -s`. That is the portable part of a recovery list. It runs on a fresh runner, so it cannot put a crontab or a daemon back on hardware that is powered off. Keep those steps in the on-machine config.

Scheduled workflows can start late. `workflow_dispatch` runs the same job on demand. The cloud config has no `notify` block, so the workflow does not need a secret. Add a `notify` block that references `${AUTOSTART_STATUS_URL}` and pass that Actions secret if you want the status line there too.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -v
```

Tests are offline. They use temporary directories and a fake `crontab` on `PATH`. They do not call the network, and they do not read or write the real user crontab or systemd. See `CONTRIBUTING.md`.

The license is MIT, copyright zlephir42069.
