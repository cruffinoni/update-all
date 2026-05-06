"""Tests for update_all.agent."""

import plistlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

import update_all.agent as agent_module
from update_all.agent import install, uninstall


def _make_console() -> Console:
    return Console(quiet=True)


@pytest.fixture()
def patched_agent(tmp_path, monkeypatch):
    plist_path = tmp_path / "com.user.update-all.plist"
    log_path = tmp_path / "update-all.log"
    monkeypatch.setattr(agent_module, "PLIST_PATH", plist_path)
    monkeypatch.setattr(agent_module, "LOG_PATH", log_path)
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    with patch("update_all.agent.subprocess.run", return_value=mock_result) as mock_run:
        with patch("update_all.agent.shutil.which", return_value="/usr/local/bin/update-all"):
            with patch("update_all.agent.sys.platform", "darwin"):
                yield plist_path, log_path, mock_run


@pytest.fixture()
def patched_agent_linux(tmp_path, monkeypatch):
    service_path = tmp_path / "update-all.service"
    timer_path = tmp_path / "update-all.timer"
    log_path = tmp_path / "update-all.log"
    monkeypatch.setattr(agent_module, "SERVICE_PATH", service_path)
    monkeypatch.setattr(agent_module, "TIMER_PATH", timer_path)
    monkeypatch.setattr(agent_module, "LOG_PATH", log_path)
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 0
    with patch("update_all.agent.subprocess.run", return_value=mock_result) as mock_run:
        with patch("update_all.agent.shutil.which", return_value="/usr/local/bin/update-all"):
            with patch("update_all.agent.sys.platform", "linux"):
                yield service_path, timer_path, log_path, mock_run


def test_install_creates_plist(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    assert plist_path.exists()


def test_install_plist_has_label(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == "com.user.update-all"


def test_install_plist_has_run_at_load(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["RunAtLoad"] is True


def test_install_plist_has_start_interval(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["StartInterval"] == 3600


def test_install_plist_program_args_ends_with_background(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["ProgramArguments"][-1] == "--background"


def test_install_plist_content(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == "com.user.update-all"
    assert data["RunAtLoad"] is True
    assert data["StartInterval"] == 3600
    assert data["ProgramArguments"][-1] == "--background"
    assert data["StandardOutPath"] == str(log_path)
    assert data["StandardErrorPath"] == str(log_path)
    assert "PATH" in data["EnvironmentVariables"]
    assert "/opt/homebrew/bin" in data["EnvironmentVariables"]["PATH"]


def test_install_calls_launchctl_bootstrap(patched_agent, monkeypatch):
    plist_path, log_path, mock_run = patched_agent
    monkeypatch.setattr(agent_module.os, "getuid", lambda: 501)
    install(_make_console())
    calls = mock_run.call_args_list
    launchctl_calls = [c for c in calls if c[0][0][0] == "launchctl"]
    assert len(launchctl_calls) == 1
    assert launchctl_calls[0][0][0] == ["launchctl", "bootstrap", "gui/501", str(plist_path)]


def test_uninstall_calls_launchctl_bootout(patched_agent, monkeypatch):
    plist_path, log_path, mock_run = patched_agent
    monkeypatch.setattr(agent_module.os, "getuid", lambda: 501)
    plist_path.write_bytes(b"dummy")
    uninstall(_make_console())
    calls = mock_run.call_args_list
    launchctl_calls = [c for c in calls if c[0][0][0] == "launchctl"]
    assert len(launchctl_calls) == 1
    assert launchctl_calls[0][0][0] == ["launchctl", "bootout", "gui/501", str(plist_path)]


def test_uninstall_deletes_plist_after_unload(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    plist_path.write_bytes(b"dummy")
    uninstall(_make_console())
    assert not plist_path.exists()


def test_uninstall_does_not_delete_plist_on_failure(tmp_path, monkeypatch):
    plist_path = tmp_path / "com.user.update-all.plist"
    log_path = tmp_path / "update-all.log"
    monkeypatch.setattr(agent_module, "PLIST_PATH", plist_path)
    monkeypatch.setattr(agent_module, "LOG_PATH", log_path)
    plist_path.write_bytes(b"dummy")
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 1
    with patch("update_all.agent.subprocess.run", return_value=mock_result):
        with patch("update_all.agent.sys.platform", "darwin"):
            uninstall(_make_console())
    assert plist_path.exists()


def test_install_fallback_binary_path(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    with patch("update_all.agent.shutil.which", return_value=None), \
         patch("update_all.agent.sys.argv", ["/tmp/fake/update-all"]):
        install(_make_console())
    with plist_path.open("rb") as f:
        data = plistlib.load(f)
    assert data["ProgramArguments"][0] != "None"
    assert "update-all" in data["ProgramArguments"][0]


def test_uninstall_no_plist_does_not_call_launchctl(patched_agent):
    plist_path, log_path, mock_run = patched_agent
    assert not plist_path.exists()
    uninstall(_make_console())
    mock_run.assert_not_called()


def test_linux_install_creates_service_file(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    install(_make_console())
    assert service_path.exists()


def test_linux_install_creates_timer_file(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    install(_make_console())
    assert timer_path.exists()


def test_linux_install_service_contains_background_flag(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    install(_make_console())
    assert "--background" in service_path.read_text()


def test_linux_install_service_has_path_env(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    install(_make_console())
    content = service_path.read_text()
    assert "PATH=" in content
    assert "/usr/bin" in content


def test_linux_install_calls_daemon_reload(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    install(_make_console())
    calls = [c[0][0] for c in mock_run.call_args_list]
    assert any("daemon-reload" in str(c) for c in calls)


def test_linux_uninstall_deletes_unit_files(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    service_path.write_text("[Service]\n")
    timer_path.write_text("[Timer]\n")
    uninstall(_make_console())
    assert not service_path.exists()
    assert not timer_path.exists()


def test_linux_uninstall_no_files_does_not_call_systemctl(patched_agent_linux):
    service_path, timer_path, log_path, mock_run = patched_agent_linux
    uninstall(_make_console())
    mock_run.assert_not_called()
