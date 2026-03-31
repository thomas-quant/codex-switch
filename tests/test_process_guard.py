from types import SimpleNamespace

import getpass
import os

import pytest

from codex_switch.errors import CodexProcessRunningError
from codex_switch.process_guard import ensure_codex_not_running


def test_ensure_codex_not_running_raises_for_same_user(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 999)
    monkeypatch.setattr(getpass, "getuser", lambda: "root")
    monkeypatch.setattr(
        "codex_switch.process_guard.psutil.process_iter",
        lambda attrs: [
            SimpleNamespace(
                info={
                    "pid": 1001,
                    "username": "root",
                    "name": "codex",
                    "cmdline": ["/usr/bin/codex"],
                }
            )
        ],
    )

    with pytest.raises(
        CodexProcessRunningError,
        match="A codex process is running. Exit Codex before mutating account state.",
    ):
        ensure_codex_not_running()


def test_ensure_codex_not_running_ignores_other_users(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 999)
    monkeypatch.setattr(getpass, "getuser", lambda: "root")
    monkeypatch.setattr(
        "codex_switch.process_guard.psutil.process_iter",
        lambda attrs: [
            SimpleNamespace(
                info={
                    "pid": 1001,
                    "username": "someone-else",
                    "name": "codex",
                    "cmdline": ["/usr/bin/codex"],
                }
            )
        ],
    )

    ensure_codex_not_running()
