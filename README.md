# codex-switch

`codex-switch` manages multiple Codex login snapshots behind short aliases and swaps the active login by rotating `~/.codex/auth.json`.

The tool is intentionally narrow:

- Only `~/.codex/auth.json` is rotated between aliases.
- Other Codex state such as config, history, logs, and related files remain shared in `~/.codex`.
- Mutating commands refuse to run while a Codex process is active.

## Install

```bash
python3 -m pip install -e '.[dev]'
```

If your system Python is PEP 668-managed, use a local virtual environment instead:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## Commands

### `codex-switch add <alias>`

Captures a fresh `codex login` session into a named snapshot. The existing active login is restored after capture.

### `codex-switch list`

Lists configured aliases. The active alias is marked with `*`.

### `codex-switch use <alias>`

Copies the stored snapshot for `<alias>` into `~/.codex/auth.json` and marks that alias active.

### `codex-switch status`

Shows the active alias, whether its snapshot exists, whether `~/.codex/auth.json` exists, and whether the live auth file has drifted from the stored snapshot.

### `codex-switch remove <alias>`

Deletes a stored alias snapshot. Removing the active alias is refused.

## Usage

Check the current state first:

```bash
codex-switch status
codex-switch list
```

If `codex-switch` shows `active alias: none` but your live `~/.codex/auth.json` already exists, bootstrap that current login once before adding the others:

```bash
python3 - <<'PY'
from dataclasses import replace

from codex_switch.accounts import AccountStore
from codex_switch.manager import utc_now
from codex_switch.paths import resolve_paths
from codex_switch.state import StateStore

paths = resolve_paths()
accounts = AccountStore(paths.accounts_dir)
state = StateStore(paths.state_file)
current = state.load()

accounts.assert_missing("alpha")
accounts.write_snapshot_from_file("alpha", paths.live_auth_file)
state.save(replace(current, active_alias="alpha", updated_at=utc_now()))
PY
```

Example first-time setup:

```bash
codex-switch add beta
codex-switch add gamma
codex-switch add delta
codex-switch add epsilon
codex-switch list
```

Switch accounts when you hit limits:

```bash
codex-switch use alpha
codex-switch use beta
codex-switch status
```

Remove an alias you no longer need:

```bash
codex-switch remove epsilon
```

## Important behavior

`codex-switch` does not create isolated Codex homes. It only rotates `~/.codex/auth.json` so account login can change while the rest of the Codex directory stays shared.

For safety, mutating commands such as `add`, `use`, and `remove` refuse to run while Codex is active.
