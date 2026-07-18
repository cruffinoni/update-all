"""Tests for sudo keepalive behavior."""

from unittest.mock import patch

from update_all.sudo import SudoKeepalive


def test_keepalive_refresh_is_non_interactive():
    keepalive = SudoKeepalive(interval=0)

    def fake_run(args, **_kwargs):
        keepalive._stop_event.set()
        assert args == ["sudo", "-n", "-v"]
        return None

    with patch("update_all.sudo.subprocess.run", side_effect=fake_run):
        keepalive._loop()
