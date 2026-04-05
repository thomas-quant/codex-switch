from __future__ import annotations

import subprocess

import pytest

from codex_switch.codex_login import run_codex_login
from codex_switch.errors import LoginCaptureError
from codex_switch.models import LoginMode


def test_run_codex_login_normalizes_process_launch_failure(monkeypatch):
    def fail_run(*args, **kwargs):
        raise FileNotFoundError("codex not found")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(LoginCaptureError, match="codex login did not complete successfully"):
        run_codex_login()


def test_run_codex_login_adds_device_auth_flag(monkeypatch):
    calls = []

    def fake_run(command, check):
        calls.append((command, check))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_codex_login(LoginMode.DEVICE_AUTH)

    assert calls == [(["codex", "login", "--device-auth"], False)]
