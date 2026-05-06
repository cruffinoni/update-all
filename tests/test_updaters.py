"""Tests for update_all.updaters."""

import shutil
import subprocess
from unittest.mock import patch

from update_all.updaters import all_updaters, _brew_commands, _yarn_v1_present, _cargo_install_update_present

EXPECTED_LABELS = [
    "BREW", "APT", "SNAP", "FLATPAK",
    "MAS", "NPM", "PNPM", "YARN", "PIPX",
    "RUST", "CARGO", "ASDF", "MISE", "VSCODE", "CLAUDE", "OMZ",
]


def test_all_updaters_count():
    assert len(all_updaters()) == len(EXPECTED_LABELS)


def test_all_updaters_labels_order():
    labels = [u.label for u in all_updaters()]
    assert labels == EXPECTED_LABELS


def test_sequential_updaters():
    sequential = [u for u in all_updaters() if u.is_sequential]
    assert [u.label for u in sequential] == ["BREW", "APT"]


def test_all_checks_are_callable():
    for updater in all_updaters():
        assert callable(updater.check), f"{updater.label}.check is not callable"


def test_all_updaters_have_commands():
    for updater in all_updaters():
        assert updater.commands, f"{updater.label} has empty commands"


def test_all_updaters_have_description():
    for updater in all_updaters():
        assert updater.description, f"{updater.label} has empty description"


def test_brew_commands_cask_on_macos():
    with patch("update_all.updaters.sys") as mock_sys:
        mock_sys.platform = "darwin"
        cmds = _brew_commands()
    assert any("--cask" in c for c in cmds)


def test_brew_commands_no_cask_on_linux():
    with patch("update_all.updaters.sys") as mock_sys:
        mock_sys.platform = "linux"
        cmds = _brew_commands()
    assert not any("--cask" in c for c in cmds)


def test_yarn_check_no_yarn_in_path():
    with patch("update_all.updaters.shutil.which", return_value=None):
        assert _yarn_v1_present() is False


def test_yarn_check_yarn_v2():
    with patch("update_all.updaters.shutil.which", return_value="/usr/local/bin/yarn"):
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.0.0", stderr="")
        with patch("update_all.updaters.subprocess.run", return_value=mock_result):
            assert _yarn_v1_present() is False


def test_yarn_check_yarn_v1():
    with patch("update_all.updaters.shutil.which", return_value="/usr/local/bin/yarn"):
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.22.19", stderr="")
        with patch("update_all.updaters.subprocess.run", return_value=mock_result):
            assert _yarn_v1_present() is True


def test_cargo_check_not_in_path():
    with patch("update_all.updaters.shutil.which", return_value=None):
        assert _cargo_install_update_present() is False


def test_cargo_check_in_path():
    from update_all.updaters import _cargo_install_update_present
    with patch("update_all.updaters.shutil.which", return_value="/usr/local/bin/cargo-install-update"):
        assert _cargo_install_update_present() is True
