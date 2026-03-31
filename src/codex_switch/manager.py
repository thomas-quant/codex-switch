from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from codex_switch.accounts import AccountStore
from codex_switch.errors import ActiveAliasRemovalError
from codex_switch.fs import atomic_write_bytes, file_digest
from codex_switch.models import AppPaths, StatusResult
from codex_switch.state import StateStore


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CodexSwitchManager:
    def __init__(
        self,
        paths: AppPaths,
        accounts: AccountStore,
        state: StateStore,
        ensure_safe_to_mutate: Callable[[], None],
        login_runner: Callable[[], None],
    ) -> None:
        self._paths = paths
        self._accounts = accounts
        self._state = state
        self._ensure_safe_to_mutate = ensure_safe_to_mutate
        self._login_runner = login_runner

    def list_aliases(self) -> tuple[list[str], str | None]:
        current = self._state.load()
        return self._accounts.list_aliases(), current.active_alias

    def status(self) -> StatusResult:
        current = self._state.load()
        active_alias = current.active_alias
        live_auth_exists = self._paths.live_auth_file.exists()
        snapshot_exists = False
        in_sync: bool | None = None

        if active_alias is not None:
            snapshot_exists = self._accounts.exists(active_alias)
            if snapshot_exists and live_auth_exists:
                in_sync = (
                    file_digest(self._accounts.snapshot_path(active_alias))
                    == file_digest(self._paths.live_auth_file)
                )

        return StatusResult(
            active_alias=active_alias,
            snapshot_exists=snapshot_exists,
            live_auth_exists=live_auth_exists,
            in_sync=in_sync,
        )

    def use(self, alias: str) -> None:
        self._ensure_safe_to_mutate()
        current = self._state.load()
        target_snapshot = self._accounts.read_snapshot(alias)

        if (
            current.active_alias is not None
            and self._paths.live_auth_file.exists()
            and self._accounts.exists(current.active_alias)
        ):
            atomic_write_bytes(
                self._accounts.snapshot_path(current.active_alias),
                self._paths.live_auth_file.read_bytes(),
                mode=0o600,
                root=self._paths.switch_root,
            )

        atomic_write_bytes(
            self._paths.live_auth_file,
            target_snapshot,
            mode=0o600,
            root=self._paths.codex_root,
        )
        self._state.save(replace(current, active_alias=alias, updated_at=utc_now()))

    def remove(self, alias: str) -> None:
        self._ensure_safe_to_mutate()
        current = self._state.load()
        if current.active_alias == alias:
            raise ActiveAliasRemovalError(f"Cannot remove active alias '{alias}'")
        self._accounts.delete(alias)
