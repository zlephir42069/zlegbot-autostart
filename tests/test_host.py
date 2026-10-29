"""SystemHost crontab goes through PATH and treats only 'no crontab' as empty."""

from autostart.host import SystemHost


def test_crontab_roundtrip_uses_the_fake_binary(shadow):
    host = SystemHost()
    assert host.read_crontab() == ""
    host.write_crontab("# job\n")
    assert host.read_crontab() == "# job\n"
    assert shadow.crontab() == "# job\n"
    host.write_crontab("")
    assert host.read_crontab() == ""
    assert shadow.crontab() == ""
    assert "systemctl" not in shadow.call_text()
    assert "crontab -l" in shadow.call_text()
    assert "crontab -r" in shadow.call_text()
    assert "/usr/bin/crontab" not in shadow.call_text()
