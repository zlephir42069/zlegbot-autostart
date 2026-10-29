"""Config validation, env substitution, and the example files."""

from pathlib import Path

import pytest

from autostart.config import configured_log_path, load_config
from autostart.errors import ConfigError

from support import REPO, write_config


def test_version_matches_the_package():
    import autostart

    assert autostart.__version__ == "0.1.0"


def test_example_covers_every_type(monkeypatch):
    monkeypatch.setenv("AUTOSTART_STATUS_URL", "https://example.com/hooks/autostart")
    config = load_config(REPO / "autostart.example.yaml")
    assert {step.type for step in config.steps} == {
        "ensure_dir",
        "restore",
        "checksum",
        "crontab",
        "process",
        "command",
    }
    assert config.notify is not None
    assert config.notify.type == "discord"
    assert config.notify.url == "https://example.com/hooks/autostart"
    assert config.redactor.text("url https://example.com/hooks/autostart") == "url ***"
    assert config.stop_on_error is False


def test_cloud_example_has_no_notify_and_resolves_beside_the_file():
    config = load_config(REPO / "examples" / "cloud.yaml")
    assert config.notify is None
    assert [step.type for step in config.steps] == ["ensure_dir", "restore", "checksum", "command"]
    note = config.steps[1]
    assert note.restores[0][1] == (REPO / "examples" / "note.txt").resolve()


def test_relative_paths_dollar_escape_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("TOKEN", "SUPERSECRETTOKEN")
    path = write_config(
        tmp_path,
        """
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
  - name: echo
    type: command
    run: echo $${HOME}
  - name: secret-path
    type: ensure_dir
    path: ${TOKEN}/data
""",
    )
    config = load_config(path)
    assert config.steps[0].paths[0][0] == (tmp_path / "data").resolve()
    assert config.steps[1].run == "echo ${HOME}"
    assert config.steps[2].paths[0][1] == "SUPERSECRETTOKEN/data"
    assert "SUPERSECRETTOKEN" not in config.redactor.text(config.steps[2].paths[0][1])


def test_generic_alias_and_status_without_credentials(tmp_path):
    path = write_config(
        tmp_path,
        """
log: custom/autostart.log
notify:
  type: generic
  url: ${AUTOSTART_DOES_NOT_EXIST}
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    assert configured_log_path(path) == tmp_path.resolve() / "custom" / "autostart.log"
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert "AUTOSTART_DOES_NOT_EXIST" in "\n".join(caught.value.messages)


def test_collects_independent_errors(tmp_path):
    path = write_config(
        tmp_path,
        """
log_max_bytes: -1
steps:
  - name: dirs
    type: ensure_dir
  - name: dirs
    type: no_such
  - name: note
    type: checksum
    path: ./data/note.txt
    sha256: abcd
  - name: jobs
    type: crontab
    marker: zlegbot-autostart
    lines:
      - "15 * * * * /bin/true"
  - name: worker
    type: process
    start: ./bin/worker
  - name: bad
    type: command
    run: ""
bonus: true
""",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    text = "\n".join(caught.value.messages)
    assert "unknown setting bonus" in text
    assert "log_max_bytes" in text
    assert "duplicate step name dirs" in text
    assert "unknown" in text or "type must be" in text
    assert "needs path or paths" in text
    assert "64 hex" in text
    assert "reserved" in text
    assert "pidfile or match" in text
    assert "must not be empty" in text


def test_rejects_bad_url_and_non_string_cron(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSTART_STATUS_URL", "file:///tmp/hook")
    path = write_config(
        tmp_path,
        """
notify:
  type: webhook
  url: ${AUTOSTART_STATUS_URL}
steps:
  - name: jobs
    type: crontab
    lines:
      - 15
""",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    text = "\n".join(caught.value.messages)
    assert "http(s)" in text
    assert "file://" not in text
    assert "must be a string" in text


def test_files_lists_and_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = write_config(
        tmp_path,
        """
steps:
  - name: note
    type: restore
    files:
      - dest: ~/data/a.txt
        backup: ~/backup/a.txt
  - name: hashes
    type: checksum
    files:
      - path: ~/data/a.txt
        sha256: dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22
""",
    )
    config = load_config(path)
    assert config.steps[0].restores[0][0] == tmp_path / "data" / "a.txt"
    assert config.steps[1].hashes[0][1] == "dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22"
    assert isinstance(config.log_path, Path)
