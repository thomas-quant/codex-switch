from types import ModuleType, SimpleNamespace
import sys

import getpass
import os

import pytest

from codex_switch.errors import CodexProcessRunningError

if "psutil" not in sys.modules:
    psutil_stub = ModuleType("psutil")
    psutil_stub.process_iter = lambda attrs=None: ()
    sys.modules["psutil"] = psutil_stub

from codex_switch.process_guard import ensure_codex_not_running, is_codex_running


def test_is_codex_running_returns_true_for_same_user(monkeypatch):
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

    assert is_codex_running() is True


def test_ensure_codex_not_running_uses_running_helper(monkeypatch):
    monkeypatch.setattr("codex_switch.process_guard.is_codex_running", lambda: True)

    with pytest.raises(
        CodexProcessRunningError,
        match="A codex process is running. Exit Codex before mutating account state.",
    ):
        ensure_codex_not_running()


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
