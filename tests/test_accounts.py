import pytest

from codex_switch.accounts import AccountStore
from codex_switch.errors import AliasAlreadyExistsError, InvalidAliasError, SnapshotNotFoundError


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
    assert oct(store.snapshot_path("work-1").stat().st_mode & 0o777) == "0o600"


def test_invalid_alias_is_rejected(tmp_path):
    store = AccountStore(tmp_path / ".codex-switch" / "accounts")

    with pytest.raises(InvalidAliasError):
        store.write_snapshot_from_bytes("../bad", b"{}")


def test_snapshot_writes_reject_symlink_escape(tmp_path):
    switch_root = tmp_path / ".codex-switch"
    external_accounts = tmp_path / "elsewhere"
    external_accounts.mkdir()
    switch_root.mkdir()
    (switch_root / "accounts").symlink_to(external_accounts, target_is_directory=True)

    store = AccountStore(switch_root / "accounts")

    with pytest.raises(ValueError):
        store.write_snapshot_from_bytes("work-1", b"{}")


def test_missing_snapshot_raises(tmp_path):
    store = AccountStore(tmp_path / ".codex-switch" / "accounts")

    with pytest.raises(SnapshotNotFoundError):
        store.read_snapshot("missing")


def test_snapshot_bytes_write_and_crud_helpers(tmp_path):
    store = AccountStore(tmp_path / ".codex-switch" / "accounts")

    store.write_snapshot_from_bytes("work-3", b'{"token":"xyz"}')

    assert store.exists("work-3")
    assert store.read_snapshot("work-3") == b'{"token":"xyz"}'

    store.delete("work-3")

    assert not store.exists("work-3")
    store.assert_missing("work-3")

    store.write_snapshot_from_bytes("work-4", b"{}")
    with pytest.raises(AliasAlreadyExistsError):
        store.assert_missing("work-4")


def test_list_aliases_rejects_malformed_snapshot_names(tmp_path):
    accounts_dir = tmp_path / ".codex-switch" / "accounts"
    accounts_dir.mkdir(parents=True)
    (accounts_dir / "bad alias.json").write_bytes(b"{}")

    store = AccountStore(accounts_dir)

    with pytest.raises(InvalidAliasError):
        store.list_aliases()
