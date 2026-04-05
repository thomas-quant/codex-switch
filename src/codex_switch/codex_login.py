from __future__ import annotations

import subprocess

from codex_switch.errors import LoginCaptureError
from codex_switch.models import LoginMode


def run_codex_login(login_mode: LoginMode = LoginMode.BROWSER) -> None:
    command = ["codex", "login"]
    if login_mode == LoginMode.DEVICE_AUTH:
        command.append("--device-auth")
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise LoginCaptureError("codex login did not complete successfully") from exc
    if result.returncode != 0:
        raise LoginCaptureError("codex login did not complete successfully")
