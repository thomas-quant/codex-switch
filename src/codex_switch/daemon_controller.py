from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from codex_switch.errors import DaemonAlreadyRunningError, DaemonControlError, DaemonNotRunningError
from codex_switch.fs import atomic_write_bytes, ensure_private_dir
from codex_switch.models import AppPaths, DaemonStatusResult

_DEFAULT_STOP_TIMEOUT_SECONDS = 5.0
_SYSTEMD_SERVICE_NAME = "codex-switchd.service"
_SYSTEMD_ACTIVE_STATE_PROPERTY = "ActiveState"
_SYSTEMD_MAIN_PID_PROPERTY = "MainPID"
_SYSTEMD_UNIT_FILE_STATE_PROPERTY = "UnitFileState"


class DaemonController:
    def __init__(
        self,
        paths: AppPaths,
        *,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        self._paths = paths
        self._poll_interval_seconds = poll_interval_seconds

    def install(self) -> None:
        ensure_private_dir(self._paths.switch_root, root=self._paths.switch_root)
        ensure_private_dir(self._paths.daemon_log_dir, root=self._paths.switch_root)

    def status(self) -> DaemonStatusResult:
        if self._systemd_unit_file().exists():
            return self._systemd_status()

        if not self._paths.daemon_pid_file.exists():
            return DaemonStatusResult(
                running=False,
                pid=None,
                pid_file_exists=False,
                stale_pid_file=False,
            )

        pid = _read_pid_file(self._paths.daemon_pid_file)
        if pid is None:
            return DaemonStatusResult(
                running=False,
                pid=None,
                pid_file_exists=True,
                stale_pid_file=True,
            )

        running = _pid_is_alive(pid)
        return DaemonStatusResult(
            running=running,
            pid=pid,
            pid_file_exists=True,
                stale_pid_file=not running,
            )

    def start(self) -> DaemonStatusResult:
        if self._systemd_unit_file().exists():
            self._run_systemctl("start", _SYSTEMD_SERVICE_NAME)
            return self.status()

        current = self.status()
        if current.running:
            raise DaemonAlreadyRunningError(f"Daemon already running with pid {current.pid}")
        if current.pid_file_exists:
            self._paths.daemon_pid_file.unlink(missing_ok=True)

        self.install()
        log_file = self._paths.daemon_log_dir / "daemon.log"
        if not log_file.exists():
            atomic_write_bytes(log_file, b"", mode=0o600, root=self._paths.switch_root)
        else:
            os.chmod(log_file, 0o600)

        with log_file.open("ab", buffering=0) as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "codex_switch.daemon_runtime",
                    "run",
                    "--home",
                    str(self._paths.home),
                    "--poll-interval",
                    str(self._poll_interval_seconds),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )

        atomic_write_bytes(
            self._paths.daemon_pid_file,
            f"{process.pid}\n".encode("utf-8"),
            mode=0o600,
            root=self._paths.switch_root,
        )
        return self.status()

    def stop(self, timeout_seconds: float = _DEFAULT_STOP_TIMEOUT_SECONDS) -> DaemonStatusResult:
        if self._systemd_unit_file().exists():
            self._run_systemctl("stop", _SYSTEMD_SERVICE_NAME)
            return self.status()

        current = self.status()
        if not current.pid_file_exists or current.pid is None or not current.running:
            self._paths.daemon_pid_file.unlink(missing_ok=True)
            raise DaemonNotRunningError("Daemon is not running")

        os.kill(current.pid, signal.SIGTERM)

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not _pid_is_alive(current.pid):
                break
            time.sleep(0.1)

        if _pid_is_alive(current.pid):
            os.kill(current.pid, signal.SIGKILL)

        self._paths.daemon_pid_file.unlink(missing_ok=True)
        return self.status()

    def enable(self) -> DaemonStatusResult:
        self.install()
        unit_file = self._systemd_unit_file()
        ensure_private_dir(unit_file.parent)
        atomic_write_bytes(
            unit_file,
            self._systemd_unit_contents().encode("utf-8"),
            mode=0o644,
        )
        self._run_systemctl("daemon-reload")
        self._run_systemctl("enable", "--now", _SYSTEMD_SERVICE_NAME)
        return self.status()

    def disable(self) -> DaemonStatusResult:
        if not self._systemd_unit_file().exists():
            return DaemonStatusResult(
                running=False,
                pid=None,
                pid_file_exists=False,
                stale_pid_file=False,
                managed_by="systemd",
                service_enabled=False,
            )
        self._run_systemctl("disable", "--now", _SYSTEMD_SERVICE_NAME)
        return self.status()

    def _systemd_unit_file(self) -> Path:
        return self._paths.home / ".config" / "systemd" / "user" / _SYSTEMD_SERVICE_NAME

    def _systemd_unit_contents(self) -> str:
        daemon_executable = shutil.which("codex-switchd")
        if daemon_executable is None:
            exec_start = (
                f"{sys.executable} -m codex_switch.daemon_runtime run "
                f"--home {self._paths.home} --poll-interval {self._poll_interval_seconds}"
            )
        else:
            exec_start = (
                f"{daemon_executable} run "
                f"--home {self._paths.home} --poll-interval {self._poll_interval_seconds}"
            )
        return "\n".join(
            [
                "[Unit]",
                "Description=codex-switch automation daemon",
                "",
                "[Service]",
                "Type=simple",
                f"ExecStart={exec_start}",
                "Restart=on-failure",
                "RestartSec=5",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            ]
        )

    def _run_systemctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        if shutil.which("systemctl") is None:
            raise DaemonControlError("systemctl --user is unavailable")
        completed = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "systemctl --user command failed"
            raise DaemonControlError(message)
        return completed

    def _systemd_status(self) -> DaemonStatusResult:
        response = self._run_systemctl(
            "show",
            _SYSTEMD_SERVICE_NAME,
            "--property",
            _SYSTEMD_ACTIVE_STATE_PROPERTY,
            "--property",
            _SYSTEMD_MAIN_PID_PROPERTY,
            "--property",
            _SYSTEMD_UNIT_FILE_STATE_PROPERTY,
            "--value",
        )
        lines = response.stdout.splitlines()
        while len(lines) < 3:
            lines.append("")
        active_state, raw_pid, unit_file_state = lines[:3]
        pid = int(raw_pid) if raw_pid.isdigit() and int(raw_pid) > 0 else None
        enabled = unit_file_state == "enabled"
        running = active_state == "active"
        return DaemonStatusResult(
            running=running,
            pid=pid,
            pid_file_exists=True,
            stale_pid_file=not running,
            managed_by="systemd",
            service_enabled=enabled,
        )


def _read_pid_file(pid_file: Path) -> int | None:
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or not raw.isdigit():
        return None
    pid = int(raw)
    if pid <= 0:
        return None
    return pid


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
