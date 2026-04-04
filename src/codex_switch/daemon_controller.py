from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from codex_switch.errors import DaemonAlreadyRunningError, DaemonNotRunningError
from codex_switch.fs import atomic_write_bytes, ensure_private_dir
from codex_switch.models import AppPaths, DaemonStatusResult

_DEFAULT_STOP_TIMEOUT_SECONDS = 5.0


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
