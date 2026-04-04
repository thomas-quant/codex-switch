from __future__ import annotations

from codex_switch.paths import resolve_paths


def test_resolve_paths_includes_automation_files(tmp_path):
    paths = resolve_paths(tmp_path)

    assert paths.automation_db_file == tmp_path / ".codex-switch" / "automation.sqlite"
    assert paths.daemon_pid_file == tmp_path / ".codex-switch" / "daemon.pid"
    assert paths.daemon_log_dir == tmp_path / ".codex-switch" / "logs"
