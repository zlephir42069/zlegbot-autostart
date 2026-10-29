"""Status posts. Discord mentions stay disabled. URLs stay out of errors."""

import json

import pytest

from autostart.config import NotifySpec, load_config
from autostart.errors import NotifyError
from autostart.http import post_json
from autostart.notify import post_status

from support import write_config


def _spec(tmp_path, url, kind="discord", retries=1, backoff=0, timeout=5):
    path = write_config(
        tmp_path,
        f"""
notify:
  type: {kind}
  url: "{url}"
  retries: {retries}
  backoff: {backoff}
  timeout: {timeout}
steps:
  - name: dirs
    type: ensure_dir
    path: ./data
""",
    )
    config = load_config(path)
    assert config.notify is not None
    return config.notify


def test_discord_slack_and_generic_payloads(tmp_path, server):
    discord = _spec(tmp_path, server.url + "/hook", "discord")
    post_status(discord, "autostart ok: 2 steps")
    body = json.loads(server.httpd.posts[-1])
    assert body["content"] == "autostart ok: 2 steps"
    assert body["allowed_mentions"] == {"parse": []}

    long_line = "autostart failed: " + ("x" * 4000)
    post_status(discord, long_line)
    truncated = json.loads(server.httpd.posts[-1])
    assert len(truncated["content"]) <= 1900
    assert truncated["content"].endswith("...")
    assert truncated["allowed_mentions"] == {"parse": []}

    slack = _spec(tmp_path, server.url + "/hook", "slack")
    post_status(slack, "autostart ok: 1 steps")
    assert json.loads(server.httpd.posts[-1]) == {"text": "autostart ok: 1 steps"}

    generic = _spec(tmp_path, server.url + "/hook", "generic")
    assert generic.type == "webhook"
    post_status(generic, "autostart failed: health")
    assert json.loads(server.httpd.posts[-1]) == {"text": "autostart failed: health"}


def test_retry_then_success_and_exhausted_retries(tmp_path, server):
    server.httpd.fail_remaining = 2
    delays = []
    spec = _spec(tmp_path, server.url + "/hook", "webhook", retries=3, backoff=0.25)
    post_status(spec, "autostart ok: 1 steps", sleeper=delays.append)
    assert len(server.httpd.posts) == 3
    assert delays == [0.25, 0.5]

    server.httpd.posts.clear()
    server.httpd.fail_remaining = 5
    spec = _spec(tmp_path, server.url + "/hook", "webhook", retries=2, backoff=0)
    with pytest.raises(NotifyError, match="HTTP 500"):
        post_status(spec, "autostart ok: 1 steps")
    assert len(server.httpd.posts) == 2


def test_http_error_does_not_include_the_url(server):
    server.httpd.fail_remaining = 1
    with pytest.raises(NotifyError) as caught:
        post_json(server.url + "/hook/SUPERSECRETTOKEN", {"text": "hi"}, 5)
    assert "SUPERSECRETTOKEN" not in str(caught.value)
    assert "HTTP 500" in str(caught.value)
    assert server.url not in str(caught.value)


def test_direct_spec_rejects_unknown_type():
    spec = NotifySpec(type="email", url="http://127.0.0.1/hook", retries=1, backoff=0, timeout=1)
    with pytest.raises(NotifyError, match="unknown notify type"):
        post_status(spec, "autostart ok: 1 steps")
