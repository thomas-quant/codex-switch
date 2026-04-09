from __future__ import annotations

import signal
import subprocess
import sys

import pytest

from codex_switch.daemon_controller import DaemonController
from codex_switch.errors import DaemonAlreadyRunningError, DaemonNotRunningError
from codex_switch.paths import resolve_paths


def test_daemon_start_writes_pid_file_and_returns_running_status(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    controller = DaemonController(paths, poll_interval_seconds=12.5)
    captured: dict[str, object] = {}

    class DummyProcess:
        pid = 4321

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("codex_switch.daemon_controller._pid_is_alive", lambda _pid: True)

    status = controller.start()

    assert status.running is True
    assert status.pid == 4321
    assert paths.daemon_pid_file.read_text(encoding="utf-8").strip() == "4321"
    assert captured["args"] == [
        sys.executable,
        "-m",
        "codex_switch.daemon_runtime",
        "run",
        "--home",
        str(paths.home),
        "--poll-interval",
        "12.5",
    ]


def test_daemon_start_rejects_when_pid_file_points_to_running_process(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    paths.daemon_pid_file.parent.mkdir(parents=True, exist_ok=True)
    paths.daemon_pid_file.write_text("555\n", encoding="utf-8")
    controller = DaemonController(paths)
    monkeypatch.setattr("codex_switch.daemon_controller._pid_is_alive", lambda _pid: True)

    with pytest.raises(DaemonAlreadyRunningError, match="pid 555"):
        controller.start()


def test_daemon_stop_terminates_process_and_clears_pid_file(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    controller = DaemonController(paths)
    paths.daemon_pid_file.parent.mkdir(parents=True, exist_ok=True)
    paths.daemon_pid_file.write_text("777\n", encoding="utf-8")

    state = {"alive": True, "signals": []}

    def fake_pid_is_alive(_pid: int) -> bool:
        return state["alive"]

    def fake_kill(pid: int, sig: int) -> None:
        state["signals"].append((pid, sig))
        if sig == signal.SIGTERM:
            state["alive"] = False

    monkeypatch.setattr("codex_switch.daemon_controller._pid_is_alive", fake_pid_is_alive)
    monkeypatch.setattr("codex_switch.daemon_controller.os.kill", fake_kill)

    status = controller.stop(timeout_seconds=0.1)

    assert state["signals"] == [(777, signal.SIGTERM)]
    assert status.running is False
    assert paths.daemon_pid_file.exists() is False


def test_daemon_stop_raises_when_not_running(tmp_path):
    controller = DaemonController(resolve_paths(tmp_path))

    with pytest.raises(DaemonNotRunningError, match="Daemon is not running"):
        controller.stop()


def test_daemon_status_marks_stale_pid_file_when_content_is_invalid(tmp_path):
    paths = resolve_paths(tmp_path)
    paths.daemon_pid_file.parent.mkdir(parents=True, exist_ok=True)
    paths.daemon_pid_file.write_text("invalid\n", encoding="utf-8")
    controller = DaemonController(paths)

    status = controller.status()

    assert status.running is False
    assert status.pid_file_exists is True
    assert status.stale_pid_file is True


def test_daemon_enable_writes_systemd_unit_and_enables_service(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    controller = DaemonController(paths)
    systemctl_calls: list[list[str]] = []

    monkeypatch.setattr("codex_switch.daemon_controller.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(args, **kwargs):
        systemctl_calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("codex_switch.daemon_controller.subprocess.run", fake_run)

    status = controller.enable()

    unit_file = paths.home / ".config" / "systemd" / "user" / "codex-switchd.service"
    assert unit_file.exists()
    contents = unit_file.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/codex-switchd run --home" in contents
    assert str(paths.home) in contents
    assert systemctl_calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "codex-switchd.service"],
        [
            "systemctl",
            "--user",
            "show",
            "codex-switchd.service",
            "--property",
            "ActiveState",
            "--property",
            "MainPID",
            "--property",
            "UnitFileState",
            "--value",
        ],
    ]
    assert status.running is False


def test_daemon_disable_stops_and_disables_systemd_service(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    unit_file = paths.home / ".config" / "systemd" / "user" / "codex-switchd.service"
    unit_file.parent.mkdir(parents=True, exist_ok=True)
    unit_file.write_text("[Unit]\nDescription=test\n", encoding="utf-8")
    controller = DaemonController(paths)
    systemctl_calls: list[list[str]] = []

    monkeypatch.setattr("codex_switch.daemon_controller.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(args, **kwargs):
        systemctl_calls.append(args)
        if args[2] == "show":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="inactive\n0\ndisabled\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("codex_switch.daemon_controller.subprocess.run", fake_run)

    status = controller.disable()

    assert systemctl_calls == [
        ["systemctl", "--user", "disable", "--now", "codex-switchd.service"],
        [
            "systemctl",
            "--user",
            "show",
            "codex-switchd.service",
            "--property",
            "ActiveState",
            "--property",
            "MainPID",
            "--property",
            "UnitFileState",
            "--value",
        ],
    ]
    assert status.running is False


def test_daemon_status_uses_systemd_when_unit_file_exists(tmp_path, monkeypatch):
    paths = resolve_paths(tmp_path)
    unit_file = paths.home / ".config" / "systemd" / "user" / "codex-switchd.service"
    unit_file.parent.mkdir(parents=True, exist_ok=True)
    unit_file.write_text("[Unit]\nDescription=test\n", encoding="utf-8")
    controller = DaemonController(paths)

    monkeypatch.setattr("codex_switch.daemon_controller.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="active\n4321\nenabled\n", stderr="")

    monkeypatch.setattr("codex_switch.daemon_controller.subprocess.run", fake_run)

    status = controller.status()

    assert status.running is True
    assert status.pid == 4321
