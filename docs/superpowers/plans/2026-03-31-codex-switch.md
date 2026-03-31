# Codex Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `codex-switch` CLI that stores one auth snapshot per alias, rotates `~/.codex/auth.json` on `use`, and leaves the stock `codex` CLI untouched.

**Architecture:** Implement a small Python package with isolated modules for filesystem operations, state persistence, account snapshot storage, process guarding, and command orchestration. The CLI layer should only parse arguments, call a `CodexSwitchManager`, and render human-readable output; all mutating flows should use atomic file replacement and rollback.

**Tech Stack:** Python 3.11+, `argparse`, `pathlib`, `json`, `subprocess`, `tempfile`, `hashlib`, `psutil`, `pytest`

---

## Planned File Layout

- `pyproject.toml`
  Package metadata, runtime dependency on `psutil`, test configuration, and the `codex-switch` console script entry point.
- `.gitignore`
  Ignore Python bytecode, pytest cache, and virtualenv directories.
- `README.md`
  Installation, command usage, and the shared-state trade-off that only auth rotates.
- `src/codex_switch/__init__.py`
  Package version marker.
- `src/codex_switch/cli.py`
  Argument parsing, output formatting, and top-level error handling.
- `src/codex_switch/errors.py`
  Shared exception types used across stores, manager logic, and the CLI.
- `src/codex_switch/models.py`
  Dataclasses for resolved paths, persisted state, and status output.
- `src/codex_switch/paths.py`
  Resolve the filesystem layout rooted at `Path.home()` or a test-provided home path.
- `src/codex_switch/fs.py`
  Private-directory creation, atomic write helpers, digest helpers, and safe file backup/restore.
- `src/codex_switch/state.py`
  Read and write `~/.codex-switch/state.json`.
- `src/codex_switch/accounts.py`
  Alias validation plus snapshot create/read/list/delete operations.
- `src/codex_switch/process_guard.py`
  Refuse mutating commands when another `codex` process is running.
- `src/codex_switch/codex_login.py`
  Small wrapper around `subprocess.run(["codex", "login"])`.
- `src/codex_switch/manager.py`
  Orchestrates `add`, `use`, `list`, `remove`, and `status`.
- `tests/conftest.py`
  Put `src/` on `sys.path` for tests.
- `tests/test_cli.py`
  Parser coverage and command-dispatch/output tests.
- `tests/test_state.py`
  State persistence and permission tests.
- `tests/test_accounts.py`
  Alias validation and snapshot storage tests.
- `tests/test_process_guard.py`
  Process guard behavior tests with `psutil.process_iter` monkeypatched.
- `tests/test_manager_basic.py`
  `use`, `list`, `status`, and `remove` manager tests.
- `tests/test_manager_add.py`
  `add` flow success and rollback tests.

## Task 1: Scaffold The Python CLI Package

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/codex_switch/__init__.py`
- Create: `src/codex_switch/cli.py`
- Create: `tests/conftest.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing parser test**

```python
# tests/conftest.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

```python
# tests/test_cli.py
from codex_switch.cli import build_parser


def test_build_parser_registers_expected_subcommands():
    parser = build_parser()
    subparsers = next(action for action in parser._actions if getattr(action, "choices", None))
    assert set(subparsers.choices) == {"add", "use", "list", "remove", "status"}
```

- [ ] **Step 2: Run the test to verify the package is missing**

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_registers_expected_subcommands -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codex_switch'`

- [ ] **Step 3: Add the package skeleton**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "codex-switch"
version = "0.1.0"
description = "Rotate Codex auth snapshots across multiple account aliases"
requires-python = ">=3.11"
dependencies = ["psutil>=6,<7"]

[project.optional-dependencies]
dev = ["pytest>=8,<9"]

[project.scripts]
codex-switch = "codex_switch.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

```gitignore
# .gitignore
__pycache__/
.pytest_cache/
.venv/
*.pyc
```

```python
# src/codex_switch/__init__.py
__all__ = ["__version__"]

__version__ = "0.1.0"
```

```python
# src/codex_switch/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-switch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("add", "use", "list", "remove", "status"):
        child = subparsers.add_parser(name)
        if name in {"add", "use", "remove"}:
            child.add_argument("alias")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(list(argv) if argv is not None else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the parser test again**

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_registers_expected_subcommands -q`
Expected: PASS

- [ ] **Step 5: Commit the scaffold**

```bash
git add .gitignore pyproject.toml src/codex_switch/__init__.py src/codex_switch/cli.py tests/conftest.py tests/test_cli.py
git commit -m "chore: scaffold codex-switch package"
```

## Task 2: Add Shared Models, Errors, Filesystem Helpers, And State Storage

**Files:**
- Create: `src/codex_switch/errors.py`
- Create: `src/codex_switch/models.py`
- Create: `src/codex_switch/paths.py`
- Create: `src/codex_switch/fs.py`
- Create: `src/codex_switch/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing state-store tests**

```python
# tests/test_state.py
from codex_switch.models import AppState
from codex_switch.paths import resolve_paths
from codex_switch.state import StateStore


def test_state_store_returns_default_when_file_is_missing(tmp_path):
    paths = resolve_paths(tmp_path)
    store = StateStore(paths.state_file)

    assert store.load() == AppState(version=1, active_alias=None, updated_at=None)


def test_state_store_round_trips_and_sets_private_permissions(tmp_path):
    paths = resolve_paths(tmp_path)
    store = StateStore(paths.state_file)
    state = AppState(version=1, active_alias="work-1", updated_at="2026-03-31T12:00:00Z")

    store.save(state)

    assert store.load() == state
    assert oct(paths.switch_root.stat().st_mode & 0o777) == "0o700"
    assert oct(paths.state_file.stat().st_mode & 0o777) == "0o600"
```

- [ ] **Step 2: Run the state tests to verify the modules do not exist yet**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: FAIL with `ModuleNotFoundError` for `codex_switch.models`

- [ ] **Step 3: Implement the shared types and state persistence**

```python
# src/codex_switch/errors.py
class CodexSwitchError(RuntimeError):
    """Base exception for user-facing CLI failures."""


class InvalidAliasError(CodexSwitchError):
    pass


class AliasAlreadyExistsError(CodexSwitchError):
    pass


class SnapshotNotFoundError(CodexSwitchError):
    pass


class ActiveAliasRemovalError(CodexSwitchError):
    pass


class CodexProcessRunningError(CodexSwitchError):
    pass


class StateFileError(CodexSwitchError):
    pass


class LoginCaptureError(CodexSwitchError):
    pass
```

```python
# src/codex_switch/models.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class AppPaths:
    home: Path
    codex_root: Path
    live_auth_file: Path
    switch_root: Path
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
```

```python
# src/codex_switch/paths.py
from __future__ import annotations

from pathlib import Path

from codex_switch.models import AppPaths


def resolve_paths(home: Path | None = None) -> AppPaths:
    root = Path(home) if home is not None else Path.home()
    codex_root = root / ".codex"
    switch_root = root / ".codex-switch"
    return AppPaths(
        home=root,
        codex_root=codex_root,
        live_auth_file=codex_root / "auth.json",
        switch_root=switch_root,
        accounts_dir=switch_root / "accounts",
        state_file=switch_root / "state.json",
    )
```

```python
# src/codex_switch/fs.py
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def ensure_private_dir(path: Path, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def atomic_write_bytes(target: Path, data: bytes, mode: int = 0o600) -> None:
    ensure_private_dir(target.parent)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    os.chmod(temp_path, mode)
    os.replace(temp_path, target)


def atomic_copy_file(source: Path, target: Path, mode: int = 0o600) -> None:
    atomic_write_bytes(target, source.read_bytes(), mode=mode)


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
```

```python
# src/codex_switch/state.py
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from codex_switch.errors import StateFileError
from codex_switch.fs import atomic_write_bytes, ensure_private_dir
from codex_switch.models import AppState


class StateStore:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file

    def load(self) -> AppState:
        if not self._state_file.exists():
            return AppState()

        try:
            payload = json.loads(self._state_file.read_text())
        except json.JSONDecodeError as exc:
            raise StateFileError(f"Could not parse {self._state_file}") from exc

        return AppState(
            version=payload.get("version", 1),
            active_alias=payload.get("active_alias"),
            updated_at=payload.get("updated_at"),
        )

    def save(self, state: AppState) -> None:
        ensure_private_dir(self._state_file.parent)
        body = json.dumps(asdict(state), indent=2, sort_keys=True).encode("utf-8") + b"\n"
        atomic_write_bytes(self._state_file, body, mode=0o600)
```

- [ ] **Step 4: Run the state tests again**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: PASS

- [ ] **Step 5: Commit the state layer**

```bash
git add src/codex_switch/errors.py src/codex_switch/models.py src/codex_switch/paths.py src/codex_switch/fs.py src/codex_switch/state.py tests/test_state.py
git commit -m "feat: add state and filesystem helpers"
```

## Task 3: Add Alias Validation And Snapshot Storage

**Files:**
- Create: `src/codex_switch/accounts.py`
- Create: `tests/test_accounts.py`

- [ ] **Step 1: Write the failing account-store tests**

```python
# tests/test_accounts.py
import pytest

from codex_switch.accounts import AccountStore
from codex_switch.errors import InvalidAliasError, SnapshotNotFoundError


def test_write_and_list_snapshots(tmp_path):
    accounts_dir = tmp_path / ".codex-switch" / "accounts"
    source = tmp_path / "auth.json"
    source.write_text('{"token":"abc"}')

    store = AccountStore(accounts_dir)
    store.write_snapshot_from_file("work-1", source)
    store.write_snapshot_from_file("work-2", source)

    assert store.list_aliases() == ["work-1", "work-2"]
    assert store.read_snapshot("work-1") == b'{"token":"abc"}'
    assert oct(accounts_dir.stat().st_mode & 0o777) == "0o700"


def test_invalid_alias_is_rejected(tmp_path):
    store = AccountStore(tmp_path / ".codex-switch" / "accounts")

    with pytest.raises(InvalidAliasError):
        store.write_snapshot_from_bytes("../bad", b"{}")


def test_missing_snapshot_raises(tmp_path):
    store = AccountStore(tmp_path / ".codex-switch" / "accounts")

    with pytest.raises(SnapshotNotFoundError):
        store.read_snapshot("missing")
```

- [ ] **Step 2: Run the account-store tests to confirm they fail**

Run: `python3 -m pytest tests/test_accounts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codex_switch.accounts'`

- [ ] **Step 3: Implement alias validation and snapshot storage**

```python
# src/codex_switch/accounts.py
from __future__ import annotations

import re
from pathlib import Path

from codex_switch.errors import AliasAlreadyExistsError, InvalidAliasError, SnapshotNotFoundError
from codex_switch.fs import atomic_copy_file, atomic_write_bytes, ensure_private_dir

ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class AccountStore:
    def __init__(self, accounts_dir: Path) -> None:
        self._accounts_dir = accounts_dir

    def _validate_alias(self, alias: str) -> None:
        if not ALIAS_RE.fullmatch(alias):
            raise InvalidAliasError(
                "Alias must match ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$"
            )

    def snapshot_path(self, alias: str) -> Path:
        self._validate_alias(alias)
        return self._accounts_dir / f"{alias}.json"

    def exists(self, alias: str) -> bool:
        return self.snapshot_path(alias).exists()

    def list_aliases(self) -> list[str]:
        if not self._accounts_dir.exists():
            return []
        return sorted(path.stem for path in self._accounts_dir.glob("*.json"))

    def write_snapshot_from_file(self, alias: str, source: Path) -> None:
        ensure_private_dir(self._accounts_dir)
        atomic_copy_file(source, self.snapshot_path(alias), mode=0o600)

    def write_snapshot_from_bytes(self, alias: str, payload: bytes) -> None:
        ensure_private_dir(self._accounts_dir)
        atomic_write_bytes(self.snapshot_path(alias), payload, mode=0o600)

    def read_snapshot(self, alias: str) -> bytes:
        path = self.snapshot_path(alias)
        if not path.exists():
            raise SnapshotNotFoundError(f"Alias '{alias}' does not exist")
        return path.read_bytes()

    def delete(self, alias: str) -> None:
        path = self.snapshot_path(alias)
        if not path.exists():
            raise SnapshotNotFoundError(f"Alias '{alias}' does not exist")
        path.unlink()

    def assert_missing(self, alias: str) -> None:
        if self.exists(alias):
            raise AliasAlreadyExistsError(f"Alias '{alias}' already exists")
```

- [ ] **Step 4: Run the account-store tests again**

Run: `python3 -m pytest tests/test_accounts.py -q`
Expected: PASS

- [ ] **Step 5: Commit the account store**

```bash
git add src/codex_switch/accounts.py tests/test_accounts.py
git commit -m "feat: add account snapshot storage"
```

## Task 4: Block Mutations While Codex Is Running

**Files:**
- Create: `src/codex_switch/process_guard.py`
- Create: `tests/test_process_guard.py`

- [ ] **Step 1: Write the failing process-guard tests**

```python
# tests/test_process_guard.py
import pytest

from codex_switch.errors import CodexProcessRunningError
from codex_switch.process_guard import ensure_codex_not_running


class FakeProcess:
    def __init__(self, pid, username, name, cmdline):
        self.info = {
            "pid": pid,
            "username": username,
            "name": name,
            "cmdline": cmdline,
        }


def test_ensure_codex_not_running_raises_for_same_user(monkeypatch):
    monkeypatch.setattr("codex_switch.process_guard.os.getpid", lambda: 999)
    monkeypatch.setattr("codex_switch.process_guard.getpass.getuser", lambda: "root")
    monkeypatch.setattr(
        "codex_switch.process_guard.psutil.process_iter",
        lambda attrs: [FakeProcess(100, "root", "codex", ["codex"])],
    )

    with pytest.raises(CodexProcessRunningError):
        ensure_codex_not_running()


def test_ensure_codex_not_running_ignores_other_users(monkeypatch):
    monkeypatch.setattr("codex_switch.process_guard.os.getpid", lambda: 999)
    monkeypatch.setattr("codex_switch.process_guard.getpass.getuser", lambda: "root")
    monkeypatch.setattr(
        "codex_switch.process_guard.psutil.process_iter",
        lambda attrs: [FakeProcess(100, "someone-else", "codex", ["codex"])],
    )

    ensure_codex_not_running()
```

- [ ] **Step 2: Run the process-guard tests**

Run: `python3 -m pytest tests/test_process_guard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codex_switch.process_guard'`

- [ ] **Step 3: Implement the process guard**

```python
# src/codex_switch/process_guard.py
from __future__ import annotations

import getpass
import os
from pathlib import Path

import psutil

from codex_switch.errors import CodexProcessRunningError


def ensure_codex_not_running() -> None:
    current_pid = os.getpid()
    current_user = getpass.getuser()

    for process in psutil.process_iter(["pid", "username", "name", "cmdline"]):
        info = process.info
        if info["pid"] == current_pid or info["username"] != current_user:
            continue

        name = info["name"] or ""
        cmdline = info["cmdline"] or []
        executable = Path(cmdline[0]).name if cmdline else ""

        if name == "codex" or executable == "codex":
            raise CodexProcessRunningError(
                "A codex process is running. Exit Codex before mutating account state."
            )
```

- [ ] **Step 4: Run the process-guard tests again**

Run: `python3 -m pytest tests/test_process_guard.py -q`
Expected: PASS

- [ ] **Step 5: Commit the process guard**

```bash
git add src/codex_switch/process_guard.py tests/test_process_guard.py
git commit -m "feat: guard mutations while codex is running"
```

## Task 5: Implement `use`, `list`, `status`, And `remove`

**Files:**
- Create: `src/codex_switch/manager.py`
- Create: `tests/test_manager_basic.py`

- [ ] **Step 1: Write the failing manager tests for the non-login commands**

```python
# tests/test_manager_basic.py
from codex_switch.accounts import AccountStore
from codex_switch.errors import ActiveAliasRemovalError
from codex_switch.fs import atomic_write_bytes
from codex_switch.manager import CodexSwitchManager
from codex_switch.models import AppState
from codex_switch.paths import resolve_paths
from codex_switch.state import StateStore


def build_manager(tmp_path):
    paths = resolve_paths(tmp_path)
    accounts = AccountStore(paths.accounts_dir)
    state = StateStore(paths.state_file)
    manager = CodexSwitchManager(
        paths=paths,
        accounts=accounts,
        state=state,
        ensure_safe_to_mutate=lambda: None,
        login_runner=lambda: None,
    )
    return paths, accounts, state, manager


def test_use_syncs_current_alias_before_switching(tmp_path):
    paths, accounts, state, manager = build_manager(tmp_path)
    accounts.write_snapshot_from_bytes("work-1", b'{"token":"old"}')
    accounts.write_snapshot_from_bytes("work-2", b'{"token":"new"}')
    atomic_write_bytes(paths.live_auth_file, b'{"token":"live"}')
    state.save(AppState(active_alias="work-1", updated_at="2026-03-31T12:00:00Z"))

    manager.use("work-2")

    assert accounts.read_snapshot("work-1") == b'{"token":"live"}'
    assert paths.live_auth_file.read_text() == '{"token":"new"}'
    assert state.load().active_alias == "work-2"


def test_status_reports_dirty_live_auth(tmp_path):
    paths, accounts, state, manager = build_manager(tmp_path)
    accounts.write_snapshot_from_bytes("work-1", b'{"token":"snapshot"}')
    atomic_write_bytes(paths.live_auth_file, b'{"token":"live"}')
    state.save(AppState(active_alias="work-1", updated_at="2026-03-31T12:00:00Z"))

    status = manager.status()

    assert status.active_alias == "work-1"
    assert status.snapshot_exists is True
    assert status.live_auth_exists is True
    assert status.in_sync is False


def test_remove_rejects_active_alias(tmp_path):
    _, accounts, state, manager = build_manager(tmp_path)
    accounts.write_snapshot_from_bytes("work-1", b'{"token":"snapshot"}')
    state.save(AppState(active_alias="work-1", updated_at="2026-03-31T12:00:00Z"))

    try:
        manager.remove("work-1")
    except ActiveAliasRemovalError:
        pass
    else:
        raise AssertionError("Expected ActiveAliasRemovalError")


def test_list_aliases_returns_sorted_names_and_active_alias(tmp_path):
    _, accounts, state, manager = build_manager(tmp_path)
    accounts.write_snapshot_from_bytes("zeta", b"{}")
    accounts.write_snapshot_from_bytes("alpha", b"{}")
    state.save(AppState(active_alias="zeta", updated_at="2026-03-31T12:00:00Z"))

    aliases, active_alias = manager.list_aliases()

    assert aliases == ["alpha", "zeta"]
    assert active_alias == "zeta"
```

- [ ] **Step 2: Run the manager tests to verify the manager is missing**

Run: `python3 -m pytest tests/test_manager_basic.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codex_switch.manager'`

- [ ] **Step 3: Implement the manager for the non-login flows**

```python
# src/codex_switch/manager.py
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from codex_switch.accounts import AccountStore
from codex_switch.errors import ActiveAliasRemovalError
from codex_switch.fs import atomic_write_bytes, file_digest
from codex_switch.models import AppPaths, AppState, StatusResult
from codex_switch.state import StateStore


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CodexSwitchManager:
    def __init__(
        self,
        *,
        paths: AppPaths,
        accounts: AccountStore,
        state: StateStore,
        ensure_safe_to_mutate: Callable[[], None],
        login_runner: Callable[[], None],
    ) -> None:
        self.paths = paths
        self.accounts = accounts
        self.state = state
        self.ensure_safe_to_mutate = ensure_safe_to_mutate
        self.login_runner = login_runner

    def list_aliases(self) -> tuple[list[str], str | None]:
        current = self.state.load()
        return self.accounts.list_aliases(), current.active_alias

    def status(self) -> StatusResult:
        current = self.state.load()
        active = current.active_alias
        if active is None:
            return StatusResult(
                active_alias=None,
                snapshot_exists=False,
                live_auth_exists=self.paths.live_auth_file.exists(),
                in_sync=None,
            )

        snapshot_exists = self.accounts.exists(active)
        live_auth_exists = self.paths.live_auth_file.exists()
        if not snapshot_exists or not live_auth_exists:
            in_sync = None
        else:
            in_sync = (
                file_digest(self.paths.live_auth_file)
                == file_digest(self.accounts.snapshot_path(active))
            )

        return StatusResult(
            active_alias=active,
            snapshot_exists=snapshot_exists,
            live_auth_exists=live_auth_exists,
            in_sync=in_sync,
        )

    def use(self, alias: str) -> None:
        self.ensure_safe_to_mutate()
        target_payload = self.accounts.read_snapshot(alias)
        current = self.state.load()

        if current.active_alias and self.paths.live_auth_file.exists() and self.accounts.exists(current.active_alias):
            self.accounts.write_snapshot_from_file(current.active_alias, self.paths.live_auth_file)

        atomic_write_bytes(self.paths.live_auth_file, target_payload, mode=0o600)
        self.state.save(replace(current, active_alias=alias, updated_at=utc_now()))

    def remove(self, alias: str) -> None:
        self.ensure_safe_to_mutate()
        current = self.state.load()
        if current.active_alias == alias:
            raise ActiveAliasRemovalError(f"Cannot remove active alias '{alias}'")
        self.accounts.delete(alias)
```

- [ ] **Step 4: Run the manager tests again**

Run: `python3 -m pytest tests/test_manager_basic.py -q`
Expected: PASS

- [ ] **Step 5: Commit the non-login manager flows**

```bash
git add src/codex_switch/manager.py tests/test_manager_basic.py
git commit -m "feat: add use list status and remove flows"
```

## Task 6: Implement `add` With Login Capture And Rollback

**Files:**
- Create: `src/codex_switch/codex_login.py`
- Create: `tests/test_manager_add.py`
- Modify: `src/codex_switch/manager.py`

- [ ] **Step 1: Write the failing `add` tests**

```python
# tests/test_manager_add.py
import pytest

from codex_switch.accounts import AccountStore
from codex_switch.errors import AliasAlreadyExistsError, LoginCaptureError
from codex_switch.fs import atomic_write_bytes
from codex_switch.manager import CodexSwitchManager
from codex_switch.models import AppState
from codex_switch.paths import resolve_paths
from codex_switch.state import StateStore


def build_manager(tmp_path, login_runner):
    paths = resolve_paths(tmp_path)
    accounts = AccountStore(paths.accounts_dir)
    state = StateStore(paths.state_file)
    manager = CodexSwitchManager(
        paths=paths,
        accounts=accounts,
        state=state,
        ensure_safe_to_mutate=lambda: None,
        login_runner=login_runner,
    )
    return paths, accounts, state, manager


def test_add_captures_new_alias_and_restores_previous_active_auth(tmp_path):
    def fake_login():
        atomic_write_bytes(paths.live_auth_file, b'{"token":"captured"}')

    paths, accounts, state, manager = build_manager(tmp_path, fake_login)
    accounts.write_snapshot_from_bytes("work-1", b'{"token":"snapshot"}')
    atomic_write_bytes(paths.live_auth_file, b'{"token":"live"}')
    state.save(AppState(active_alias="work-1", updated_at="2026-03-31T12:00:00Z"))

    manager.add("work-2")

    assert accounts.read_snapshot("work-2") == b'{"token":"captured"}'
    assert paths.live_auth_file.read_text() == '{"token":"snapshot"}'
    assert state.load().active_alias == "work-1"


def test_add_rolls_back_when_login_does_not_produce_auth(tmp_path):
    paths, accounts, state, manager = build_manager(tmp_path, lambda: None)
    atomic_write_bytes(paths.live_auth_file, b'{"token":"live"}')

    with pytest.raises(LoginCaptureError):
        manager.add("work-2")

    assert paths.live_auth_file.read_text() == '{"token":"live"}'
    assert accounts.list_aliases() == []


def test_add_rejects_existing_alias(tmp_path):
    paths, accounts, state, manager = build_manager(tmp_path, lambda: None)
    accounts.write_snapshot_from_bytes("work-2", b"{}")

    with pytest.raises(AliasAlreadyExistsError):
        manager.add("work-2")
```

- [ ] **Step 2: Run the add-flow tests**

Run: `python3 -m pytest tests/test_manager_add.py -q`
Expected: FAIL with `AttributeError: 'CodexSwitchManager' object has no attribute 'add'`

- [ ] **Step 3: Add the `codex login` runner**

```python
# src/codex_switch/codex_login.py
from __future__ import annotations

import subprocess

from codex_switch.errors import LoginCaptureError


def run_codex_login() -> None:
    completed = subprocess.run(["codex", "login"], check=False)
    if completed.returncode != 0:
        raise LoginCaptureError("codex login did not complete successfully")
```

- [ ] **Step 4: Extend the manager with the `add` flow and rollback**

```python
# src/codex_switch/manager.py
from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from codex_switch.accounts import AccountStore
from codex_switch.errors import ActiveAliasRemovalError, AliasAlreadyExistsError, LoginCaptureError
from codex_switch.fs import atomic_write_bytes, file_digest
from codex_switch.models import AppPaths, AppState, StatusResult
from codex_switch.state import StateStore


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CodexSwitchManager:
    def __init__(
        self,
        *,
        paths: AppPaths,
        accounts: AccountStore,
        state: StateStore,
        ensure_safe_to_mutate: Callable[[], None],
        login_runner: Callable[[], None],
    ) -> None:
        self.paths = paths
        self.accounts = accounts
        self.state = state
        self.ensure_safe_to_mutate = ensure_safe_to_mutate
        self.login_runner = login_runner

    def list_aliases(self) -> tuple[list[str], str | None]:
        current = self.state.load()
        return self.accounts.list_aliases(), current.active_alias

    def status(self) -> StatusResult:
        current = self.state.load()
        active = current.active_alias
        if active is None:
            return StatusResult(
                active_alias=None,
                snapshot_exists=False,
                live_auth_exists=self.paths.live_auth_file.exists(),
                in_sync=None,
            )

        snapshot_exists = self.accounts.exists(active)
        live_auth_exists = self.paths.live_auth_file.exists()
        if not snapshot_exists or not live_auth_exists:
            in_sync = None
        else:
            in_sync = (
                file_digest(self.paths.live_auth_file)
                == file_digest(self.accounts.snapshot_path(active))
            )

        return StatusResult(
            active_alias=active,
            snapshot_exists=snapshot_exists,
            live_auth_exists=live_auth_exists,
            in_sync=in_sync,
        )

    def use(self, alias: str) -> None:
        self.ensure_safe_to_mutate()
        target_payload = self.accounts.read_snapshot(alias)
        current = self.state.load()

        if current.active_alias and self.paths.live_auth_file.exists() and self.accounts.exists(current.active_alias):
            self.accounts.write_snapshot_from_file(current.active_alias, self.paths.live_auth_file)

        atomic_write_bytes(self.paths.live_auth_file, target_payload, mode=0o600)
        self.state.save(replace(current, active_alias=alias, updated_at=utc_now()))

    def remove(self, alias: str) -> None:
        self.ensure_safe_to_mutate()
        current = self.state.load()
        if current.active_alias == alias:
            raise ActiveAliasRemovalError(f"Cannot remove active alias '{alias}'")
        self.accounts.delete(alias)

    def add(self, alias: str) -> None:
        self.ensure_safe_to_mutate()
        self.accounts.assert_missing(alias)
        previous_state = self.state.load()
        backup_path: Path | None = None

        if previous_state.active_alias and self.paths.live_auth_file.exists() and self.accounts.exists(previous_state.active_alias):
            self.accounts.write_snapshot_from_file(previous_state.active_alias, self.paths.live_auth_file)

        if self.paths.live_auth_file.exists():
            with tempfile.NamedTemporaryFile(dir=self.paths.live_auth_file.parent, delete=False) as handle:
                backup_path = Path(handle.name)
            backup_path.write_bytes(self.paths.live_auth_file.read_bytes())
            self.paths.live_auth_file.unlink()

        try:
            self.login_runner()
            if not self.paths.live_auth_file.exists():
                raise LoginCaptureError("codex login did not leave ~/.codex/auth.json behind")
            self.accounts.write_snapshot_from_file(alias, self.paths.live_auth_file)
        except Exception:
            self._restore_previous_live_auth(previous_state, backup_path)
            self.state.save(previous_state)
            raise

        self._restore_previous_live_auth(previous_state, backup_path)
        self.state.save(previous_state)

    def _restore_previous_live_auth(self, previous_state: AppState, backup_path: Path | None) -> None:
        if previous_state.active_alias and self.accounts.exists(previous_state.active_alias):
            atomic_write_bytes(
                self.paths.live_auth_file,
                self.accounts.read_snapshot(previous_state.active_alias),
                mode=0o600,
            )
            if backup_path and backup_path.exists():
                backup_path.unlink()
            return

        if backup_path and backup_path.exists():
            atomic_write_bytes(self.paths.live_auth_file, backup_path.read_bytes(), mode=0o600)
            backup_path.unlink()
            return

        if self.paths.live_auth_file.exists():
            self.paths.live_auth_file.unlink()
```

- [ ] **Step 5: Run the add-flow tests again**

Run: `python3 -m pytest tests/test_manager_add.py -q`
Expected: PASS

- [ ] **Step 6: Run the full manager test suite**

Run: `python3 -m pytest tests/test_manager_basic.py tests/test_manager_add.py -q`
Expected: PASS

- [ ] **Step 7: Commit the add flow**

```bash
git add src/codex_switch/codex_login.py src/codex_switch/manager.py tests/test_manager_add.py
git commit -m "feat: add account capture flow"
```

## Task 7: Wire The Real CLI, User Output, And README

**Files:**
- Modify: `src/codex_switch/cli.py`
- Modify: `tests/test_cli.py`
- Create: `README.md`

- [ ] **Step 1: Expand the CLI tests to cover dispatch and output**

```python
# tests/test_cli.py
from codex_switch.cli import build_parser, format_alias_lines, format_status_lines, main
from codex_switch.models import StatusResult


class FakeManager:
    def __init__(self):
        self.calls = []

    def add(self, alias):
        self.calls.append(("add", alias))

    def use(self, alias):
        self.calls.append(("use", alias))

    def remove(self, alias):
        self.calls.append(("remove", alias))

    def list_aliases(self):
        self.calls.append(("list", None))
        return ["backup", "work"], "work"

    def status(self):
        self.calls.append(("status", None))
        return StatusResult(
            active_alias="work",
            snapshot_exists=True,
            live_auth_exists=True,
            in_sync=False,
        )


def test_build_parser_registers_expected_subcommands():
    parser = build_parser()
    subparsers = next(action for action in parser._actions if getattr(action, "choices", None))
    assert set(subparsers.choices) == {"add", "use", "list", "remove", "status"}


def test_format_alias_lines_marks_active_alias():
    assert format_alias_lines(["backup", "work"], "work") == ["  backup", "* work"]


def test_format_status_lines_for_dirty_state():
    result = StatusResult(
        active_alias="work",
        snapshot_exists=True,
        live_auth_exists=True,
        in_sync=False,
    )
    assert format_status_lines(result) == [
        "active alias: work",
        "snapshot: present",
        "live auth: present",
        "sync: dirty",
    ]


def test_main_dispatches_add(monkeypatch, capsys):
    manager = FakeManager()
    monkeypatch.setattr("codex_switch.cli.build_default_manager", lambda: manager)

    exit_code = main(["add", "work"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert manager.calls == [("add", "work")]
    assert captured.out.strip() == "added alias: work"


def test_main_dispatches_list(monkeypatch, capsys):
    manager = FakeManager()
    monkeypatch.setattr("codex_switch.cli.build_default_manager", lambda: manager)

    exit_code = main(["list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert manager.calls == [("list", None)]
    assert captured.out.splitlines() == ["  backup", "* work"]
```

- [ ] **Step 2: Run the CLI tests to confirm the new helpers do not exist yet**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: FAIL with `ImportError` for `format_alias_lines`, `format_status_lines`, or `build_default_manager`

- [ ] **Step 3: Replace the CLI skeleton with the real command layer**

```python
# src/codex_switch/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence

from codex_switch.accounts import AccountStore
from codex_switch.codex_login import run_codex_login
from codex_switch.errors import CodexSwitchError
from codex_switch.manager import CodexSwitchManager
from codex_switch.models import StatusResult
from codex_switch.paths import resolve_paths
from codex_switch.process_guard import ensure_codex_not_running
from codex_switch.state import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-switch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("alias")

    use_parser = subparsers.add_parser("use")
    use_parser.add_argument("alias")

    subparsers.add_parser("list")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("alias")

    subparsers.add_parser("status")
    return parser


def build_default_manager() -> CodexSwitchManager:
    paths = resolve_paths()
    return CodexSwitchManager(
        paths=paths,
        accounts=AccountStore(paths.accounts_dir),
        state=StateStore(paths.state_file),
        ensure_safe_to_mutate=ensure_codex_not_running,
        login_runner=run_codex_login,
    )


def format_alias_lines(aliases: list[str], active_alias: str | None) -> list[str]:
    return [f"* {alias}" if alias == active_alias else f"  {alias}" for alias in aliases]


def format_status_lines(result: StatusResult) -> list[str]:
    if result.active_alias is None:
        return ["active alias: none", "live auth: present" if result.live_auth_exists else "live auth: missing"]

    snapshot_text = "present" if result.snapshot_exists else "missing"
    live_text = "present" if result.live_auth_exists else "missing"
    if result.in_sync is True:
        sync_text = "sync: clean"
    elif result.in_sync is False:
        sync_text = "sync: dirty"
    else:
        sync_text = "sync: unknown"

    return [
        f"active alias: {result.active_alias}",
        f"snapshot: {snapshot_text}",
        f"live auth: {live_text}",
        sync_text,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manager = build_default_manager()

    try:
        if args.command == "add":
            manager.add(args.alias)
            print(f"added alias: {args.alias}")
        elif args.command == "use":
            manager.use(args.alias)
            print(f"active alias: {args.alias}")
        elif args.command == "list":
            for line in format_alias_lines(*manager.list_aliases()):
                print(line)
        elif args.command == "remove":
            manager.remove(args.alias)
            print(f"removed alias: {args.alias}")
        elif args.command == "status":
            for line in format_status_lines(manager.status()):
                print(line)
        return 0
    except CodexSwitchError as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
```

````markdown
# README.md
# codex-switch

`codex-switch` stores multiple Codex auth snapshots under account aliases and swaps the live `~/.codex/auth.json` file when you change accounts.

## Install

```bash
python3 -m pip install -e '.[dev]'
```

## Commands

```bash
codex-switch add work-1
codex-switch add work-2
codex-switch list
codex-switch use work-2
codex-switch status
codex-switch remove work-1
```

## Important Behavior

- The upstream `codex` CLI is not modified.
- Only `~/.codex/auth.json` rotates between aliases.
- `~/.codex/config.toml`, history, logs, sessions, caches, and SQLite files remain shared across accounts.
- `add`, `use`, and `remove` refuse to run while another `codex` process is active.
````

- [ ] **Step 4: Run the CLI test suite**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit the CLI and docs**

```bash
git add README.md src/codex_switch/cli.py tests/test_cli.py
git commit -m "feat: wire codex-switch cli"
```

## Self-Review

### Spec coverage

- Multiple aliases with one-time setup: Task 6 implements `add`.
- Global switching via live auth rotation: Task 5 implements `use`.
- Shared config/history/logs: Task 7 README documents the trade-off; manager logic only touches auth/state files.
- Refuse mutations while Codex is running: Task 4 supplies the guard and Tasks 5-7 inject it into mutating commands.
- `list`, `remove`, and `status`: Task 5 implements the manager logic and Task 7 exposes it via the CLI.
- Preserve refreshed live auth before switching away: Task 5 writes the current live auth back into the active alias snapshot before `use`.
- Restore previous auth after `add`: Task 6 covers restore-on-success and rollback-on-failure.

### Placeholder scan

- No placeholder markers remain.
- Every code-writing step includes exact file content or exact method bodies.
- Every test step includes concrete commands and expected outputs.

### Type consistency

- `AppState`, `StatusResult`, `AccountStore`, and `CodexSwitchManager` names stay consistent across all tasks.
- `build_default_manager`, `format_alias_lines`, and `format_status_lines` are defined before the CLI tests rely on them.
- Exception names used in tests match the classes created in `src/codex_switch/errors.py`.
