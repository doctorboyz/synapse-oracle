"""Tests for daemon — PID file management, Docker detection, signal handling."""

import os
import signal
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.daemon import (
    is_running_in_docker,
    get_docker_container_status,
    write_pid,
    read_pid,
    remove_pid,
    is_running,
    stop_daemon,
    get_status,
    setup_signals,
)


class TestIsRunningInDocker:
    def test_dockerenv_exists(self, monkeypatch, tmp_path):
        dockerenv = tmp_path / ".dockerenv"
        dockerenv.write_text("", encoding="utf-8")
        with patch("src.daemon.Path", side_effect=lambda p: Path(p) if p != "/.dockerenv" else dockerenv):
            assert is_running_in_docker() is True

    def test_cgroup_contains_docker(self, monkeypatch, tmp_path):
        cgroup = tmp_path / "cgroup"
        cgroup.write_text("12:pids:/docker/abc123\n", encoding="utf-8")
        with patch("src.daemon.Path", side_effect=lambda p: Path(p) if p != "/proc/self/cgroup" else cgroup):
            assert is_running_in_docker() is True

    def test_cgroup_contains_containerd(self, monkeypatch, tmp_path):
        cgroup = tmp_path / "cgroup"
        cgroup.write_text("12:pids:/containerd/abc123\n", encoding="utf-8")
        with patch("src.daemon.Path", side_effect=lambda p: Path(p) if p != "/proc/self/cgroup" else cgroup):
            assert is_running_in_docker() is True

    def test_not_in_docker(self, monkeypatch, tmp_path):
        cgroup = tmp_path / "cgroup"
        cgroup.write_text("12:pids:/user.slice\n", encoding="utf-8")
        with patch("src.daemon.Path", side_effect=lambda p: Path(p) if p != "/proc/self/cgroup" else cgroup):
            assert is_running_in_docker() is False

    def test_cgroup_file_not_found(self, monkeypatch):
        with patch("src.daemon.Path.exists", return_value=False):
            with patch("src.daemon.Path.read_text", side_effect=FileNotFoundError):
                assert is_running_in_docker() is False

    def test_cgroup_permission_error(self, monkeypatch):
        with patch("src.daemon.Path.exists", return_value=False):
            with patch("src.daemon.Path.read_text", side_effect=PermissionError):
                assert is_running_in_docker() is False


class TestGetDockerContainerStatus:
    def test_inside_container_returns_none(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: True)
        assert get_docker_container_status() is None

    def test_container_running(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: False)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "synapse\tUp 2 hours\t0.0.0.0:8420->8420/tcp\n"
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        status = get_docker_container_status()
        assert status is not None
        assert status["container"] == "synapse"
        assert status["status"] == "Up 2 hours"
        assert status["ports"] == "0.0.0.0:8420->8420/tcp"

    def test_legacy_mysynapse_container(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: False)
        mock_result_synapse = MagicMock()
        mock_result_synapse.returncode = 0
        mock_result_synapse.stdout = ""
        mock_result_mysynapse = MagicMock()
        mock_result_mysynapse.returncode = 0
        mock_result_mysynapse.stdout = "mysynapse\tUp 1 hour\t8080/tcp\n"

        call_count = [0]

        def mock_run(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result_synapse
            return mock_result_mysynapse

        monkeypatch.setattr("subprocess.run", mock_run)
        status = get_docker_container_status()
        assert status is not None
        assert status["container"] == "mysynapse"

    def test_no_container_running(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: False)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)
        assert get_docker_container_status() is None

    def test_docker_not_found(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: False)
        monkeypatch.setattr(
            "subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError())
        )
        assert get_docker_container_status() is None

    def test_docker_timeout(self, monkeypatch):
        monkeypatch.setattr("src.daemon.is_running_in_docker", lambda: False)
        monkeypatch.setattr(
            "subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("docker", 5))
        )
        assert get_docker_container_status() is None


class TestWritePid:
    def test_write_pid_custom_path(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        with patch("os.getpid", return_value=12345):
            path = write_pid(str(pid_file))
        assert path == str(pid_file)
        assert pid_file.read_text(encoding="utf-8") == "12345"

    def test_write_pid_creates_parent_dirs(self, tmp_path):
        pid_file = tmp_path / "nested" / "deep" / "test.pid"
        with patch("os.getpid", return_value=99999):
            write_pid(str(pid_file))
        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == "99999"


class TestReadPid:
    def test_read_pid_valid(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("  42  \n", encoding="utf-8")
        assert read_pid(str(pid_file)) == 42

    def test_read_pid_missing_file(self, tmp_path):
        assert read_pid(str(tmp_path / "missing.pid")) is None

    def test_read_pid_invalid_content(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not-a-number", encoding="utf-8")
        assert read_pid(str(pid_file)) is None


class TestRemovePid:
    def test_remove_pid_existing(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")
        remove_pid(str(pid_file))
        assert not pid_file.exists()

    def test_remove_pid_missing_no_error(self, tmp_path):
        # Should not raise
        remove_pid(str(tmp_path / "missing.pid"))

    def test_remove_pid_oserror_logs_warning(self, tmp_path, monkeypatch, caplog):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")

        def raise_oserror(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "unlink", raise_oserror)
        with caplog.at_level("WARNING", logger="synapse.daemon"):
            remove_pid(str(pid_file))
        assert "permission denied" in caplog.text


class TestIsRunning:
    def test_no_pid_file(self, tmp_path):
        assert is_running(str(tmp_path / "missing.pid")) is False

    def test_process_exists(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")
        monkeypatch.setattr("os.kill", lambda pid, sig: None)
        assert is_running(str(pid_file)) is True

    def test_stale_pid_file(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")

        def raise_process_lookup(*args, **kwargs):
            raise ProcessLookupError()

        monkeypatch.setattr("os.kill", raise_process_lookup)
        assert is_running(str(pid_file)) is False
        assert not pid_file.exists()  # stale file removed

    def test_permission_error(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("1", encoding="utf-8")

        def raise_permission(*args, **kwargs):
            raise PermissionError()

        monkeypatch.setattr("os.kill", raise_permission)
        assert is_running(str(pid_file)) is True


class TestStopDaemon:
    def test_stop_by_sigterm(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")

        def mock_kill(pid, sig):
            if sig == signal.SIGTERM:
                return
            if sig == 0:
                raise ProcessLookupError()

        monkeypatch.setattr("os.kill", mock_kill)
        result = stop_daemon(str(pid_file))
        assert result["status"] == "stopped"
        assert result["pid"] == 42
        assert not pid_file.exists()

    def test_stop_needs_sigkill(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")

        call_count = [0]

        def mock_kill(pid, sig):
            call_count[0] += 1
            if sig == 0:
                if call_count[0] < 35:
                    return
                raise ProcessLookupError()

        monkeypatch.setattr("os.kill", mock_kill)
        monkeypatch.setattr("time.sleep", lambda x: None)
        result = stop_daemon(str(pid_file))
        assert result["status"] == "killed"
        assert result["pid"] == 42

    def test_stop_already_stopped(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")

        def mock_kill(pid, sig):
            raise ProcessLookupError()

        monkeypatch.setattr("os.kill", mock_kill)
        result = stop_daemon(str(pid_file))
        assert result["status"] == "not_running"
        assert result["pid"] == 42
        assert "already stopped" in result["message"]
        assert not pid_file.exists()

    def test_stop_permission_denied(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("1", encoding="utf-8")

        def mock_kill(pid, sig):
            raise PermissionError()

        monkeypatch.setattr("os.kill", mock_kill)
        result = stop_daemon(str(pid_file))
        assert result["status"] == "error"
        assert "Permission denied" in result["message"]

    def test_stop_docker_container(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.daemon.read_pid", lambda path: None)
        monkeypatch.setattr(
            "src.daemon.get_docker_container_status",
            lambda name="synapse": {"container": "synapse", "status": "Up 2 hours"},
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        result = stop_daemon()
        assert result["status"] == "stopped"
        assert result["mode"] == "docker"
        assert result["container"] == "synapse"

    def test_stop_docker_stop_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.daemon.read_pid", lambda path: None)
        monkeypatch.setattr(
            "src.daemon.get_docker_container_status",
            lambda name="synapse": {"container": "synapse", "status": "Up 2 hours"},
        )
        monkeypatch.setattr(
            "subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError())
        )

        result = stop_daemon()
        assert result["status"] == "error"
        assert result["mode"] == "docker"

    def test_stop_nothing_running(self, monkeypatch):
        monkeypatch.setattr("src.daemon.read_pid", lambda path: None)
        monkeypatch.setattr("src.daemon.get_docker_container_status", lambda name="synapse": None)

        result = stop_daemon()
        assert result["status"] == "not_running"
        assert "No PID file found" in result["message"]


class TestGetStatus:
    def test_status_running_pid(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("42", encoding="utf-8")
        monkeypatch.setattr("os.kill", lambda pid, sig: None)

        status = get_status(str(pid_file))
        assert status["running"] is True
        assert status["pid"] == 42
        assert status["mode"] == "pid"

    def test_status_running_docker(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("src.daemon.read_pid", lambda path: None)
        monkeypatch.setattr("src.daemon.is_running", lambda path: False)
        monkeypatch.setattr(
            "src.daemon.get_docker_container_status",
            lambda name="synapse": {"container": "synapse", "status": "Up 2 hours"},
        )

        status = get_status(str(pid_file))
        assert status["running"] is True
        assert status["pid"] is None
        assert status["mode"] == "docker"
        assert status["container"] == "synapse"

    def test_status_not_running(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("src.daemon.read_pid", lambda path: None)
        monkeypatch.setattr("src.daemon.is_running", lambda path: False)
        monkeypatch.setattr("src.daemon.get_docker_container_status", lambda name="synapse": None)

        status = get_status(str(pid_file))
        assert status["running"] is False
        assert status["pid"] is None
        assert status["mode"] == "none"


class TestSetupSignals:
    def test_setup_signals_registers_handlers(self, monkeypatch):
        registered = {}

        def mock_signal(sig, handler):
            registered[sig] = handler

        monkeypatch.setattr("signal.signal", mock_signal)
        setup_signals()
        assert signal.SIGTERM in registered
        assert signal.SIGINT in registered
        assert signal.SIGHUP in registered

    def test_sigterm_handler_calls_shutdown(self, monkeypatch):
        registered = {}
        shutdown_called = [False]
        reload_called = [False]

        def mock_signal(sig, handler):
            registered[sig] = handler

        monkeypatch.setattr("signal.signal", mock_signal)
        setup_signals(on_reload=lambda: reload_called.__setitem__(0, True), on_shutdown=lambda: shutdown_called.__setitem__(0, True))

        registered[signal.SIGTERM](signal.SIGTERM, None)
        assert shutdown_called[0] is True
        assert reload_called[0] is False

    def test_sighup_handler_calls_reload(self, monkeypatch):
        registered = {}
        reload_called = [False]

        def mock_signal(sig, handler):
            registered[sig] = handler

        monkeypatch.setattr("signal.signal", mock_signal)
        setup_signals(on_reload=lambda: reload_called.__setitem__(0, True))

        registered[signal.SIGHUP](signal.SIGHUP, None)
        assert reload_called[0] is True

    def test_setup_signals_graceful_on_windows(self, monkeypatch):
        registered = {}

        def mock_signal(sig, handler):
            if sig == signal.SIGHUP:
                raise ValueError("SIGHUP not supported")
            registered[sig] = handler

        monkeypatch.setattr("signal.signal", mock_signal)
        setup_signals()
        assert signal.SIGTERM in registered
        assert signal.SIGINT in registered
        assert signal.SIGHUP not in registered
