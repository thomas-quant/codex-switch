# Repository Guidelines

## Project Structure & Module Organization
`src/codex_switch/` contains the packaged CLI and domain modules. `cli.py` is the user-facing entrypoint, `manager.py` coordinates snapshot rotation plus automation status/recovery flows, and supporting modules such as `accounts.py`, `state.py`, `paths.py`, and `process_guard.py` handle storage, filesystem paths, and safety checks. Automation and daemon logic lives in `automation_db.py`, `automation_models.py`, `automation_policy.py`, `automation_rpc.py`, `automation_pty.py`, `daemon_controller.py`, and `daemon_runtime.py`; `daemon_controller.py` now handles both the legacy pid-file daemon flow and the user-level `systemd` service path. Tests live in `tests/` and mirror the runtime modules with focused files such as `test_cli.py`, `test_manager_add.py`, `test_automation_rpc.py`, `test_daemon_controller.py`, and `test_daemon_runtime.py`. Design notes and implementation plans are kept in `docs/superpowers/`.

## Build, Test, and Development Commands
Use Python 3.11+.

- For normal local CLI usage, prefer `pipx install --editable .` so `codex-switch` and `codex-switchd` are on `PATH` without activating a virtual environment.
- `python3 -m pip install -e '.[dev]'` installs the package in editable mode with `pytest`.
- `python3 -m pytest` runs the full test suite defined in `pyproject.toml`.
- `python3 -m pytest tests/test_cli.py` runs a single test module while iterating.
- `python3 -m pytest tests/test_daemon_controller.py` is a useful focused check while iterating on daemon or `systemd` behavior.
- `python3 -m pytest tests/test_daemon_runtime.py` is a useful focused check while iterating on automation polling or handoff logic.
- `codex-switch status`, `codex-switch list --refresh`, `codex-switch daemon status`, and `codex-switch auto status` are useful manual smoke checks after CLI or automation changes.

There is no dedicated build script in this repository; editable install is the normal local workflow. `pyproject.toml` exposes both `codex-switch` and `codex-switchd` console scripts.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, standard-library imports first, and explicit type hints on public functions and constructors. Keep modules and functions in `snake_case`, classes in `PascalCase`, and CLI output strings short and stable because tests assert on exact text. Prefer small, single-purpose helpers over large branching functions.

## Testing Guidelines
Tests use `pytest` with quiet output (`-q`). Add tests beside the closest behavior surface and name files `test_*.py` and functions `test_<behavior>()`. Preserve the current pattern of isolating filesystem, subprocess, and process-guard behavior with fixtures, `tmp_path`, and `monkeypatch`; do not write tests that depend on a real `~/.codex` directory, a live Codex TUI session, or live app-server RPC access.

Recent behavior to keep in mind:
- Plain `codex-switch list` is cache-only.
- `codex-switch list --refresh` refreshes only aliases with missing or stale telemetry using the existing 15-minute freshness window.
- Alias telemetry refresh now uses isolated temporary Codex homes instead of rotating the live auth file.
- `codex-switch daemon enable|disable` manages a user-level `systemd` service, and `daemon start|stop|status` route through `systemctl --user` when that service file exists.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, and `chore:`. Keep commit subjects imperative and scoped to one change. Pull requests should summarize user-visible behavior, list verification steps (`python3 -m pytest`), and include sample CLI output when command text changes.

## Security & Configuration Tips
This tool manages authentication snapshots and automation telemetry. Preserve existing safeguards around atomic writes, private file permissions, and “Codex must not be running” checks when changing account or state management code. The daemon must fail closed on missing or stale telemetry, should only mutate auth state through `CodexSwitchManager`, and must not guess thread-resume state when RPC visibility is unavailable. Keep `list --refresh` probing isolated from the live `~/.codex/auth.json`, and keep the user-level `systemd` service path consistent with the pid-file fallback behavior.
