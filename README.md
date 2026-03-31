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

## Important behavior

`codex-switch` does not create isolated Codex homes. It only rotates `~/.codex/auth.json` so account login can change while the rest of the Codex directory stays shared.

For safety, mutating commands such as `add`, `use`, and `remove` refuse to run while Codex is active.
