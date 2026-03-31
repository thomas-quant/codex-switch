from __future__ import annotations

import re
from pathlib import Path

from codex_switch.errors import (
    AliasAlreadyExistsError,
    InvalidAliasError,
    SnapshotNotFoundError,
)
from codex_switch.fs import atomic_copy_file, atomic_write_bytes, ensure_private_dir

ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class AccountStore:
    def __init__(self, accounts_dir: Path) -> None:
        self._accounts_dir = accounts_dir

    def _root(self) -> Path:
        return self._accounts_dir.parent

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
        aliases: list[str] = []
        for path in sorted(self._accounts_dir.glob("*.json")):
            alias = path.stem
            if not ALIAS_RE.fullmatch(alias):
                raise InvalidAliasError(f"Malformed snapshot filename: {path.name}")
            aliases.append(alias)
        return aliases

    def write_snapshot_from_file(self, alias: str, source: Path) -> None:
        target = self.snapshot_path(alias)
        root = self._root()
        ensure_private_dir(self._accounts_dir, root=root)
        atomic_copy_file(source, target, mode=0o600, root=root)

    def write_snapshot_from_bytes(self, alias: str, payload: bytes) -> None:
        target = self.snapshot_path(alias)
        root = self._root()
        ensure_private_dir(self._accounts_dir, root=root)
        atomic_write_bytes(target, payload, mode=0o600, root=root)

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
