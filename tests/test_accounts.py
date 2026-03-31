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
