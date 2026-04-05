from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class AppPaths:
    home: Path
    codex_root: Path
    live_auth_file: Path
    switch_root: Path
    automation_db_file: Path
    daemon_pid_file: Path
    daemon_log_dir: Path
    accounts_dir: Path
    state_file: Path


@dataclass(slots=True, frozen=True)
class AppState:
    version: int = 1
    active_alias: str | None = None
    updated_at: str | None = None


@dataclass(slots=True, frozen=True)
class StatusResult:
    active_alias: str | None
    snapshot_exists: bool
    live_auth_exists: bool
    in_sync: bool | None


@dataclass(slots=True, frozen=True)
class DaemonStatusResult:
    running: bool
    pid: int | None
    pid_file_exists: bool
    stale_pid_file: bool


@dataclass(slots=True, frozen=True)
class AutoStatusResult:
    active_alias: str | None
    active_observed_via: str | None
    active_observed_at: str | None
    soft_switch_triggered: bool
    target_alias: str | None


@dataclass(slots=True, frozen=True)
class AutoSourceResult:
    alias: str
    observed_via: str | None
    observed_at: str | None


class LoginMode(Enum):
    BROWSER = "browser"
    DEVICE_AUTH = "device-auth"
