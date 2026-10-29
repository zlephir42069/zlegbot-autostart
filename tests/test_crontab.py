"""Marker blocks are idempotent and do not touch text outside the markers."""

import pytest

from autostart.crontab import INSTALL_MARKER, remove_block, upsert
from autostart.errors import CrontabError


def test_insert_preserve_and_replace():
    original = "* * * * * echo keep\n"
    updated, changed = upsert(original, "jobs", ["15 * * * * /usr/local/bin/hourly-job"])
    assert changed
    assert "* * * * * echo keep" in updated
    assert "# BEGIN autostart:jobs" in updated
    assert "15 * * * * /usr/local/bin/hourly-job" in updated
    assert updated.endswith("# END autostart:jobs\n")

    again, changed_again = upsert(updated, "jobs", ["15 * * * * /usr/local/bin/hourly-job"])
    assert changed_again is False
    assert again == updated

    replaced, changed_replaced = upsert(updated, "jobs", ["0 * * * * /usr/local/bin/other"])
    assert changed_replaced
    assert "hourly-job" not in replaced
    assert "echo keep" in replaced
    assert replaced.count("# BEGIN autostart:jobs") == 1


def test_two_markers_coexist():
    first, _ = upsert("", INSTALL_MARKER, ["@reboot /usr/local/bin/autostart run"])
    both, changed = upsert(first, "jobs", ["15 * * * * /bin/true"])
    assert changed
    assert "# BEGIN autostart:zlegbot-autostart" in both
    assert "# BEGIN autostart:jobs" in both
    kept, changed_kept = upsert(both, "jobs", ["15 * * * * /bin/true"])
    assert changed_kept is False
    assert "@reboot /usr/local/bin/autostart run" in kept


def test_remove_is_idempotent_and_keeps_foreign_lines():
    text, _ = upsert("* * * * * echo keep\n", "jobs", ["15 * * * * /bin/true"])
    removed, changed = remove_block(text, "jobs")
    assert changed
    assert "BEGIN" not in removed
    assert "echo keep" in removed
    again, changed_again = remove_block(removed, "jobs")
    assert changed_again is False
    assert again == removed
    empty, changed_empty = remove_block("", "jobs")
    assert empty == ""
    assert changed_empty is False


def test_unbalanced_markers_raise_and_do_not_return_a_rewrite():
    broken = "# BEGIN autostart:jobs\n15 * * * * /bin/true\n"
    with pytest.raises(CrontabError, match="unclosed"):
        upsert(broken, "jobs", ["15 * * * * /bin/true"])
    with pytest.raises(CrontabError, match="unexpected end"):
        upsert("# END autostart:jobs\n", "jobs", ["15 * * * * /bin/true"])
