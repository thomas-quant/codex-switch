# Codex Switch Isolated Add, Parallel Refresh, And Safe Remove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `codex-switch add --isolated`, make `list --refresh` probe aliases concurrently without mutating live auth, and allow `remove` while Codex is running only when the target alias is provably not the live account.

**Architecture:** Extract the temporary Codex-home logic into a shared helper so isolated login, isolated probing, and live-auth identity checks all use the same path. Keep plain `add` and `use` on the current guarded flow, but teach `manager.py` a separate isolated add path, a parallel refresh pipeline with serial DB persistence, and a proof-based remove path that fails closed when live identity is ambiguous.

**Tech Stack:** Python 3.11+, pytest, argparse, sqlite3, concurrent.futures

---

## File Map

- Create: `src/codex_switch/isolated_codex.py`
  Responsibility: shared temporary `HOME` / `CODEX_HOME` helper for isolated login and probing.
- Modify: `src/codex_switch/cli.py`
  Responsibility: CLI flag parsing, default manager wiring, shared isolated probing callbacks, add dispatch.
- Modify: `src/codex_switch/codex_login.py`
  Responsibility: mode-aware login command with optional env override.
- Modify: `src/codex_switch/process_guard.py`
  Responsibility: expose a non-raising running-state helper while keeping the current guard API.
- Modify: `src/codex_switch/errors.py`
  Responsibility: add a dedicated user-facing safety error for guarded remove.
- Modify: `src/codex_switch/manager.py`
  Responsibility: isolated add, non-mutating parallel refresh, live-account proof checks for remove.
- Modify: `tests/test_cli.py`
  Responsibility: parser, dispatch, and default-manager wiring coverage for `--isolated` and shared probing.
- Modify: `tests/test_manager_add.py`
  Responsibility: red-green coverage for isolated add and plain-add process-running hint behavior.
- Modify: `tests/test_manager_list.py`
  Responsibility: red-green coverage for parallel refresh and the removal of live-auth mutation fallback during refresh.
- Modify: `tests/test_manager_basic.py`
  Responsibility: red-green coverage for guarded remove while Codex is running.
- Modify: `tests/test_process_guard.py`
  Responsibility: running-state helper coverage.

### Task 1: Add `--isolated` Command Surface And Shared Isolated Login Path

**Files:**
- Create: `src/codex_switch/isolated_codex.py`
- Modify: `src/codex_switch/cli.py`
- Modify: `src/codex_switch/codex_login.py`
- Modify: `src/codex_switch/manager.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_manager_add.py`

- [ ] **Step 1: Write the failing parser and dispatch tests**

```python
def test_build_parser_add_accepts_isolated_flag():
    parser = build_parser()

    namespace = parser.parse_args(["add", "work", "--isolated", "--device-auth"])

    assert namespace.command == "add"
    assert namespace.alias == "work"
    assert namespace.isolated is True
    assert namespace.device_auth is True


def test_main_dispatches_add_isolated_device_auth(monkeypatch, capsys):
    calls: list[tuple[str, LoginMode, bool]] = []

    class FakeManager:
        def add(
            self,
            alias: str,
            *,
            login_mode: LoginMode = LoginMode.BROWSER,
            isolated: bool = False,
        ) -> None:
            calls.append((alias, login_mode, isolated))

    monkeypatch.setattr("codex_switch.cli.build_default_manager", lambda: FakeManager())

    result = main(["add", "work", "--isolated", "--device-auth"])

    assert result == 0
    assert calls == [("work", LoginMode.DEVICE_AUTH, True)]
    assert capsys.readouterr().out == "added alias: work\n"
```

- [ ] **Step 2: Run the focused CLI tests to verify RED**

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_add_accepts_isolated_flag tests/test_cli.py::test_main_dispatches_add_isolated_device_auth -q`
Expected: FAIL because `--isolated` is not parsed and `main()` does not thread `isolated` into `manager.add()`.

- [ ] **Step 3: Write the failing manager tests for isolated add**

```python
def test_add_isolated_captures_new_alias_without_touching_live_auth_or_state(tmp_path):
    isolated_envs: list[dict[str, str]] = []

    def login_runner(login_mode: LoginMode, *, env: dict[str, str] | None = None) -> None:
        assert login_mode == LoginMode.BROWSER
        assert env is not None
        isolated_envs.append(env)
        Path(env["CODEX_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(env["CODEX_HOME"], "auth.json").write_bytes(b'{"token":"isolated-login"}')

    manager, paths, accounts, state, guard = make_manager(tmp_path, login_runner)
    accounts.write_snapshot_from_bytes("work", b'{"token":"snapshot-work"}')
    state.save(AppState(active_alias="work", updated_at="2026-03-31T12:00:00Z"))
    paths.live_auth_file.parent.mkdir(parents=True, exist_ok=True)
    paths.live_auth_file.write_bytes(b'{"token":"live-work"}')

    manager.add("personal", isolated=True)

    assert guard.calls == 0
    assert len(isolated_envs) == 1
    assert accounts.read_snapshot("personal") == b'{"token":"isolated-login"}'
    assert accounts.read_snapshot("work") == b'{"token":"snapshot-work"}'
    assert paths.live_auth_file.read_bytes() == b'{"token":"live-work"}'
    assert state.load() == AppState(active_alias="work", updated_at="2026-03-31T12:00:00Z")


def test_add_isolated_passes_device_auth_mode(tmp_path):
    seen: list[tuple[LoginMode, bool]] = []

    def login_runner(login_mode: LoginMode, *, env: dict[str, str] | None = None) -> None:
        seen.append((login_mode, env is not None))
        Path(env["CODEX_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(env["CODEX_HOME"], "auth.json").write_bytes(b'{"token":"device-auth"}')

    manager, _paths, accounts, state, guard = make_manager(tmp_path, login_runner)
    state.save(AppState(active_alias=None, updated_at="2026-03-31T12:00:00Z"))

    manager.add("personal", login_mode=LoginMode.DEVICE_AUTH, isolated=True)

    assert guard.calls == 0
    assert seen == [(LoginMode.DEVICE_AUTH, True)]
    assert accounts.read_snapshot("personal") == b'{"token":"device-auth"}'
```

- [ ] **Step 4: Run the focused manager add tests to verify RED**

Run: `python3 -m pytest tests/test_manager_add.py::test_add_isolated_captures_new_alias_without_touching_live_auth_or_state tests/test_manager_add.py::test_add_isolated_passes_device_auth_mode -q`
Expected: FAIL because `manager.add()` and `login_runner` are not yet isolation-aware.

- [ ] **Step 5: Implement the shared isolated helper, CLI flag, and isolated add path**

```python
# src/codex_switch/isolated_codex.py
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from codex_switch.fs import atomic_write_bytes


@contextmanager
def isolated_codex_env(auth_bytes: bytes | None = None) -> Iterator[dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix="codex-switch-isolated-") as raw_home:
        home = Path(raw_home)
        codex_root = home / ".codex"
        if auth_bytes is not None:
            atomic_write_bytes(codex_root / "auth.json", auth_bytes, mode=0o600, root=home)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_root)
        yield env
```

```python
# src/codex_switch/codex_login.py
def run_codex_login(
    mode: LoginMode = LoginMode.BROWSER,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    ...
    result = subprocess.run(command, check=False, env=None if env is None else dict(env))
```

```python
# src/codex_switch/manager.py
def add(
    self,
    alias: str,
    *,
    login_mode: LoginMode = LoginMode.BROWSER,
    isolated: bool = False,
) -> None:
    if isolated:
        self._accounts.assert_missing(alias)
        with isolated_codex_env() as env:
            self._login_runner(login_mode, env=env)
            auth_file = Path(env["CODEX_HOME"]) / "auth.json"
            if not auth_file.exists():
                raise LoginCaptureError("codex login did not leave ~/.codex/auth.json behind")
            self._accounts.write_snapshot_from_file(alias, auth_file)
        return
    ...
```

```python
# src/codex_switch/cli.py
if name == "add":
    child.add_argument("--device-auth", action="store_true")
    child.add_argument("--isolated", action="store_true")

...
manager.add(
    args.alias,
    login_mode=LoginMode.DEVICE_AUTH if args.device_auth else LoginMode.BROWSER,
    isolated=args.isolated,
)
```

- [ ] **Step 6: Run the focused add tests to verify GREEN**

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_add_accepts_isolated_flag tests/test_cli.py::test_main_dispatches_add_isolated_device_auth tests/test_manager_add.py::test_add_isolated_captures_new_alias_without_touching_live_auth_or_state tests/test_manager_add.py::test_add_isolated_passes_device_auth_mode -q`
Expected: PASS

- [ ] **Step 7: Commit the isolated add command surface**

```bash
git add src/codex_switch/isolated_codex.py src/codex_switch/cli.py src/codex_switch/codex_login.py src/codex_switch/manager.py tests/test_cli.py tests/test_manager_add.py
git commit -m "feat: add isolated alias capture"
```

### Task 2: Keep Plain Add Guarded And Add The `--isolated` Hint

**Files:**
- Modify: `src/codex_switch/errors.py`
- Modify: `src/codex_switch/manager.py`
- Test: `tests/test_manager_add.py`

- [ ] **Step 1: Write the failing test for the plain-add guard hint**

```python
def test_add_process_running_error_suggests_isolated(tmp_path):
    manager, _paths, accounts, state, _guard = make_manager(tmp_path, lambda *_args, **_kwargs: None)
    state.save(AppState(active_alias=None, updated_at="2026-03-31T12:00:00Z"))

    def running_guard() -> None:
        raise CodexProcessRunningError(
            "A codex process is running. Exit Codex before mutating account state."
        )

    manager._ensure_safe_to_mutate = running_guard

    with pytest.raises(
        CodexProcessRunningError,
        match=r"use 'codex-switch add .* --isolated'",
    ):
        manager.add("personal")
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `python3 -m pytest tests/test_manager_add.py::test_add_process_running_error_suggests_isolated -q`
Expected: FAIL because plain add currently re-raises the generic process-running message without a hint.

- [ ] **Step 3: Implement the plain-add hint**

```python
def add(...):
    if isolated:
        ...
        return

    try:
        self._ensure_safe_to_mutate()
    except CodexProcessRunningError as exc:
        raise CodexProcessRunningError(
            f"{exc} Use 'codex-switch add {alias} --isolated' to capture a new alias without touching live auth."
        ) from exc
    ...
```

- [ ] **Step 4: Run the focused add hint test to verify GREEN**

Run: `python3 -m pytest tests/test_manager_add.py::test_add_process_running_error_suggests_isolated -q`
Expected: PASS

- [ ] **Step 5: Commit the plain-add hint**

```bash
git add src/codex_switch/manager.py tests/test_manager_add.py
git commit -m "fix: hint isolated add when codex is running"
```

### Task 3: Add A Non-Raising Process Running Helper

**Files:**
- Modify: `src/codex_switch/process_guard.py`
- Test: `tests/test_process_guard.py`

- [ ] **Step 1: Write the failing process guard helper tests**

```python
def test_is_codex_running_returns_true_for_matching_process(monkeypatch):
    monkeypatch.setattr(
        "codex_switch.process_guard.psutil.process_iter",
        lambda _fields: iter([FakeProcess(pid=100, username="root", name="codex", cmdline=["codex"])]),
    )
    monkeypatch.setattr("codex_switch.process_guard.os.getpid", lambda: 999)
    monkeypatch.setattr("codex_switch.process_guard.getpass.getuser", lambda: "root")

    assert is_codex_running() is True


def test_ensure_codex_not_running_uses_is_codex_running(monkeypatch):
    monkeypatch.setattr("codex_switch.process_guard.is_codex_running", lambda: True)

    with pytest.raises(CodexProcessRunningError):
        ensure_codex_not_running()
```

- [ ] **Step 2: Run the focused process guard tests to verify RED**

Run: `python3 -m pytest tests/test_process_guard.py::test_is_codex_running_returns_true_for_matching_process tests/test_process_guard.py::test_ensure_codex_not_running_uses_is_codex_running -q`
Expected: FAIL because `is_codex_running()` does not exist and `ensure_codex_not_running()` still owns the full scan.

- [ ] **Step 3: Implement the helper**

```python
def is_codex_running() -> bool:
    current_pid = os.getpid()
    current_user = getpass.getuser()
    for process in psutil.process_iter(["pid", "username", "name", "cmdline"]):
        ...
        if _is_codex_process(info.get("name")) or _is_codex_process_from_cmdline(info.get("cmdline")):
            return True
    return False


def ensure_codex_not_running() -> None:
    if is_codex_running():
        raise CodexProcessRunningError(_CODEX_PROCESS_MESSAGE)
```

- [ ] **Step 4: Run the focused process guard tests to verify GREEN**

Run: `python3 -m pytest tests/test_process_guard.py::test_is_codex_running_returns_true_for_matching_process tests/test_process_guard.py::test_ensure_codex_not_running_uses_is_codex_running -q`
Expected: PASS

- [ ] **Step 5: Commit the process guard helper**

```bash
git add src/codex_switch/process_guard.py tests/test_process_guard.py
git commit -m "refactor: expose codex running helper"
```

### Task 4: Make `list --refresh` Parallel And Explicitly Non-Mutating

**Files:**
- Modify: `src/codex_switch/cli.py`
- Modify: `src/codex_switch/manager.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_manager_list.py`

- [ ] **Step 1: Write the failing manager tests for parallel non-mutating refresh**

```python
def test_list_aliases_refreshes_unresolved_aliases_in_parallel(tmp_path):
    started: list[str] = []
    release = threading.Event()

    def alias_metadata_probe(alias: str) -> AliasTelemetryObservation | None:
        started.append(alias)
        if len(started) == 2:
            release.set()
        release.wait(timeout=1)
        return AliasTelemetryObservation(
            account_email=f"{alias}@example.com",
            account_plan_type="plus",
            account_fingerprint=f"fp-{alias}",
            observed_at="2026-04-13T10:00:00Z",
        )

    manager, _paths, accounts, state, store, _guard = make_manager(
        tmp_path,
        alias_metadata_probe=alias_metadata_probe,
    )
    accounts.write_snapshot_from_bytes("alpha", b"{}")
    accounts.write_snapshot_from_bytes("beta", b"{}")
    store.reconcile_aliases(["alpha", "beta"])
    state.save(AppState(active_alias=None, updated_at="2026-04-13T09:00:00Z"))

    entries, _active_alias = manager.list_aliases()

    assert [entry.plan_type for entry in entries] == ["plus", "plus"]
    assert started == ["alpha", "beta"]


def test_list_aliases_inactive_refresh_no_longer_mutates_live_auth(tmp_path, monkeypatch):
    manager, _paths, accounts, state, store, _guard = make_manager(
        tmp_path,
        alias_metadata_probe=lambda alias: AliasTelemetryObservation(
            account_email=f"{alias}@example.com",
            account_plan_type="pro",
            account_fingerprint=f"fp-{alias}",
            observed_at="2026-04-13T10:00:00Z",
        ),
    )
    accounts.write_snapshot_from_bytes("backup", b"{}")
    store.reconcile_aliases(["backup"])
    state.save(AppState(active_alias=None, updated_at="2026-04-13T09:00:00Z"))

    backup_calls = 0

    def fail_backup():
        nonlocal backup_calls
        backup_calls += 1
        raise AssertionError("list refresh should not back up live auth")

    monkeypatch.setattr(manager, "_backup_live_auth", fail_backup)

    entries, active_alias = manager.list_aliases()

    assert entries == [AliasListEntry(alias="backup", plan_type="pro", five_hour_left_percent=None, weekly_left_percent=None)]
    assert active_alias is None
    assert backup_calls == 0
```

- [ ] **Step 2: Run the focused refresh tests to verify RED**

Run: `python3 -m pytest tests/test_manager_list.py::test_list_aliases_refreshes_unresolved_aliases_in_parallel tests/test_manager_list.py::test_list_aliases_inactive_refresh_no_longer_mutates_live_auth -q`
Expected: FAIL because refresh is serial and the inactive-path fallback still reaches the live-auth mutation helpers.

- [ ] **Step 3: Implement isolated probe reuse and parallel refresh**

```python
# src/codex_switch/cli.py
def probe_alias_metadata(alias: str):
    auth_bytes = _load_probe_auth_bytes(...)
    return probe_alias_metadata_from_auth_bytes(alias=alias, auth_bytes=auth_bytes)
```

```python
# src/codex_switch/manager.py
from concurrent.futures import ThreadPoolExecutor, as_completed


def _refresh_missing_alias_metadata(...):
    observations: dict[str, AliasTelemetryObservation] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(unresolved_aliases))) as pool:
        futures = {
            pool.submit(self._probe_alias_metadata, alias=alias, previous_state=previous_state): alias
            for alias in unresolved_aliases
        }
        for future in as_completed(futures):
            alias = futures[future]
            observation = future.result()
            if observation is not None:
                observations[alias] = observation

    refreshed = False
    for alias in unresolved_aliases:
        observation = observations.get(alias)
        if observation is None:
            continue
        ...
```

```python
def _probe_alias_metadata(...):
    if self._alias_metadata_probe is None:
        return None
    try:
        return self._alias_metadata_probe(alias)
    except Exception:
        return None
```

- [ ] **Step 4: Run the focused refresh tests to verify GREEN**

Run: `python3 -m pytest tests/test_manager_list.py::test_list_aliases_refreshes_unresolved_aliases_in_parallel tests/test_manager_list.py::test_list_aliases_inactive_refresh_no_longer_mutates_live_auth -q`
Expected: PASS

- [ ] **Step 5: Commit the parallel refresh change**

```bash
git add src/codex_switch/cli.py src/codex_switch/manager.py tests/test_manager_list.py
git commit -m "feat: parallelize isolated list refresh"
```

### Task 5: Guard `remove` With Live-Account Proof Instead Of A Blanket Process Guard

**Files:**
- Modify: `src/codex_switch/errors.py`
- Modify: `src/codex_switch/cli.py`
- Modify: `src/codex_switch/manager.py`
- Modify: `tests/test_manager_basic.py`

- [ ] **Step 1: Write the failing remove safety tests**

```python
def test_remove_allows_inactive_alias_when_codex_is_running_and_identity_differs(tmp_path):
    manager, paths, accounts, state, guard = make_manager(tmp_path)
    accounts.write_snapshot_from_bytes("work", b'{"token":"snapshot-work"}')
    accounts.write_snapshot_from_bytes("backup", b'{"token":"snapshot-backup"}')
    state.save(AppState(active_alias="work", updated_at="2026-03-31T12:00:00Z"))
    paths.live_auth_file.parent.mkdir(parents=True, exist_ok=True)
    paths.live_auth_file.write_bytes(b'{"token":"live-work"}')

    manager._is_codex_running = lambda: True
    manager._identity_from_auth_bytes = lambda auth_bytes: (
        "fp-work" if auth_bytes == b'{"token":"live-work"}' else "fp-backup"
    )

    manager.remove("backup")

    assert not accounts.exists("backup")
    assert guard.calls == 0


def test_remove_rejects_when_codex_is_running_and_live_identity_is_unknown(tmp_path):
    manager, paths, accounts, state, _guard = make_manager(tmp_path)
    accounts.write_snapshot_from_bytes("work", b'{"token":"snapshot-work"}')
    accounts.write_snapshot_from_bytes("backup", b'{"token":"snapshot-backup"}')
    state.save(AppState(active_alias="work", updated_at="2026-03-31T12:00:00Z"))
    paths.live_auth_file.parent.mkdir(parents=True, exist_ok=True)
    paths.live_auth_file.write_bytes(b'{"token":"live-work"}')

    manager._is_codex_running = lambda: True
    manager._identity_from_auth_bytes = lambda _auth_bytes: None

    with pytest.raises(UnsafeAliasRemovalError, match="could not identify the live Codex account"):
        manager.remove("backup")

    assert accounts.exists("backup")
```

- [ ] **Step 2: Run the focused remove tests to verify RED**

Run: `python3 -m pytest tests/test_manager_basic.py::test_remove_allows_inactive_alias_when_codex_is_running_and_identity_differs tests/test_manager_basic.py::test_remove_rejects_when_codex_is_running_and_live_identity_is_unknown -q`
Expected: FAIL because `remove()` still calls the blanket process guard and has no proof-based safety path.

- [ ] **Step 3: Implement the proof-based remove path**

```python
# src/codex_switch/errors.py
class UnsafeAliasRemovalError(CodexSwitchError):
    pass
```

```python
# src/codex_switch/manager.py
def remove(self, alias: str) -> None:
    current = self._state.load()
    if current.active_alias == alias:
        raise ActiveAliasRemovalError(f"Cannot remove active alias '{alias}'")
    if not self._is_codex_running():
        self._accounts.delete(alias)
        return
    self._assert_alias_is_not_live_account(alias)
    self._accounts.delete(alias)
```

```python
def _assert_alias_is_not_live_account(self, alias: str) -> None:
    if not self._paths.live_auth_file.exists():
        raise UnsafeAliasRemovalError("Could not identify the live Codex account while Codex is running.")
    snapshot_digest = file_digest(self._accounts.snapshot_path(alias))
    live_digest = file_digest(self._paths.live_auth_file)
    if snapshot_digest == live_digest:
        raise UnsafeAliasRemovalError(f"Cannot remove alias '{alias}' because it matches the live Codex auth.")

    live_identity = self._identity_from_auth_bytes(self._paths.live_auth_file.read_bytes())
    alias_identity = self._identity_from_auth_bytes(self._accounts.read_snapshot(alias))
    if live_identity is None or alias_identity is None:
        raise UnsafeAliasRemovalError("Could not identify the live Codex account while Codex is running.")
    if live_identity == alias_identity:
        raise UnsafeAliasRemovalError(f"Cannot remove alias '{alias}' because it is the live Codex account.")
```

- [ ] **Step 4: Run the focused remove tests to verify GREEN**

Run: `python3 -m pytest tests/test_manager_basic.py::test_remove_allows_inactive_alias_when_codex_is_running_and_identity_differs tests/test_manager_basic.py::test_remove_rejects_when_codex_is_running_and_live_identity_is_unknown -q`
Expected: PASS

- [ ] **Step 5: Commit the guarded remove path**

```bash
git add src/codex_switch/errors.py src/codex_switch/manager.py tests/test_manager_basic.py
git commit -m "feat: allow safe remove while codex is running"
```

### Task 6: Wire Direct Identity Probing For Remove And Run End-To-End Verification

**Files:**
- Modify: `src/codex_switch/cli.py`
- Modify: `src/codex_switch/manager.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_manager_basic.py`

- [ ] **Step 1: Write the failing default-manager identity probe test**

```python
def test_build_default_manager_provides_identity_probe_from_auth_bytes(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeManager:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("codex_switch.cli.CodexSwitchManager", FakeManager)
    monkeypatch.setattr("codex_switch.cli.resolve_paths", lambda: resolve_paths(tmp_path))
    monkeypatch.setattr("codex_switch.cli.AccountStore", lambda _path: ProbeAccounts(_path))
    monkeypatch.setattr("codex_switch.cli.StateStore", lambda _path: ProbeStateStore(_path))
    monkeypatch.setattr("codex_switch.process_guard.ensure_codex_not_running", lambda: None)
    monkeypatch.setattr("codex_switch.process_guard.is_codex_running", lambda: False)
    monkeypatch.setattr("codex_switch.codex_login.run_codex_login", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "codex_switch.cli.probe_alias_metadata_from_auth_bytes",
        lambda *, alias, auth_bytes: AliasTelemetryObservation(
            account_email=f"{alias}@example.com",
            account_plan_type="plus",
            account_fingerprint="fp-live",
            observed_at="2026-04-13T10:00:00Z",
        ),
    )

    build_default_manager()

    identity = captured["identity_from_auth_bytes"](b'{"token":"live"}')

    assert identity == ("fp-live", "probe@example.com") or identity == ("fp-live", None)
```

- [ ] **Step 2: Run the focused default-manager test to verify RED**

Run: `python3 -m pytest tests/test_cli.py::test_build_default_manager_provides_identity_probe_from_auth_bytes -q`
Expected: FAIL because the default manager does not yet receive a direct auth-byte identity probe callback.

- [ ] **Step 3: Implement the shared direct identity probe wiring**

```python
# src/codex_switch/cli.py
def probe_alias_metadata_from_auth_bytes(*, alias: str, auth_bytes: bytes) -> AliasTelemetryObservation | None:
    with isolated_codex_env(auth_bytes) as env:
        ...


def identity_from_auth_bytes(auth_bytes: bytes) -> tuple[str | None, str | None] | None:
    observation = probe_alias_metadata_from_auth_bytes(alias="__live__", auth_bytes=auth_bytes)
    if observation is None:
        return None
    if observation.account_fingerprint:
        return (observation.account_fingerprint, observation.account_email)
    if observation.account_email:
        return (None, observation.account_email)
    return None

return CodexSwitchManager(
    ...
    identity_from_auth_bytes=identity_from_auth_bytes,
    is_codex_running=is_codex_running,
)
```

- [ ] **Step 4: Run the focused identity probe test to verify GREEN**

Run: `python3 -m pytest tests/test_cli.py::test_build_default_manager_provides_identity_probe_from_auth_bytes -q`
Expected: PASS

- [ ] **Step 5: Run the complete targeted suite for this feature**

Run: `python3 -m pytest tests/test_cli.py tests/test_manager_add.py tests/test_manager_basic.py tests/test_manager_list.py tests/test_process_guard.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit the final integration**

```bash
git add src/codex_switch/cli.py src/codex_switch/manager.py tests/test_cli.py tests/test_manager_basic.py tests/test_manager_list.py
git commit -m "feat: guard running remove with live identity checks"
```
