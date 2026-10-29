"""Status reports only what the log file contains."""

from autostart.config import resolve_log_path
from autostart.status import read_status, render_status

from support import write_config


def test_missing_incomplete_and_last_run(tmp_path):
    log = tmp_path / "autostart.log"
    assert read_status(log) is None
    assert "no runs yet" in render_status(log)

    log.write_text("step ts=2026-10-29T00:00:00+00:00 name=dirs type=ensure_dir status=ok detail=created=1 present=0\n", encoding="utf-8")
    assert "no complete run" in render_status(log)

    log.write_text(
        "\n".join(
            [
                "run ts=2026-10-29T00:00:00+00:00 status=ok steps=1 failed=",
                "not a record",
                "run ts=2026-10-29T00:01:00+00:00 status=failed steps=2 failed=health,notify",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    found = read_status(log)
    assert found["status"] == "failed"
    assert found["steps"] == 2
    assert found["failed"] == ["health", "notify"]
    text = render_status(log)
    assert "status: failed" in text
    assert "2026-10-29T00:01:00+00:00" in text
    assert "failed: health,notify" in text
    assert "2026-10-29T00:00:00+00:00" not in text.split("time: ", 1)[1].split("\n", 1)[0]


def test_status_redacts_a_secret_in_the_log_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "SUPERSECRETTOKEN")
    path = write_config(
        tmp_path,
        """
log: ${TOKEN}/autostart.log
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    log_path, redactor = resolve_log_path(path)
    text = redactor.text(render_status(log_path))
    assert "no runs yet" in text
    assert "SUPERSECRETTOKEN" not in text
    assert "***" in text
