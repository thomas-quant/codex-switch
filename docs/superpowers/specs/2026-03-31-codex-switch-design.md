# Codex Switch Design

Date: 2026-03-31

## Summary

Build `codex-switch` as a standalone wrapper CLI for managing multiple ChatGPT/Codex account logins without modifying the upstream `codex` binary. The tool stores one auth snapshot per alias, keeps one globally active alias, and rotates the live `~/.codex/auth.json` file when the user switches accounts.

The design intentionally leaves the rest of the Codex home directory unchanged. `config.toml`, session history, logs, caches, and SQLite state remain shared across accounts. Only auth is switched.

## Goals

- Provide a one-time setup path to authenticate multiple accounts under user-chosen aliases.
- Allow global switching between accounts with a single CLI command.
- Keep the stock `codex` CLI untouched and continue using its normal login flow.
- Preserve token refreshes by syncing the current live auth back into the currently active alias before switching away.
- Keep the operational model simple enough to debug from the filesystem.

## Non-Goals

- No PATH shim or `codex` command interception.
- No separate config, sessions, logs, or history per account.
- No OS keychain integration in v1.
- No API-key-based auth capture in v1.
- No support for switching while a `codex` process is actively running.

## User Model

The user manages account aliases such as `work-1`, `work-2`, or `backup`. One alias is globally active at a time. The active alias determines which auth snapshot is copied into `~/.codex/auth.json`, and the stock `codex` CLI continues to use that file as usual.

The user flow is:

1. Run `codex-switch add <alias>` and complete the normal `codex login` flow for each account once.
2. Run `codex-switch use <alias>` whenever they hit limits and want to switch accounts.
3. Continue using the normal `codex` CLI directly.

## Why This Approach

Three options were considered:

1. Rotate `~/.codex/auth.json` on `codex-switch` commands.
2. Make `~/.codex/auth.json` a symlink to an alias-specific file.
3. Give each account a separate full Codex home directory.

Option 1 is the chosen design. It matches the requirement to avoid a shim, keeps shared config and history intact, and works with the stock CLI. Option 2 is fragile because upstream atomic writes could replace the symlink. Option 3 isolates more state than the user wants.

## Architecture

`codex-switch` is responsible for:

- account alias management
- auth snapshot storage
- active alias tracking
- concurrency checks before mutation
- atomic file replacement for auth and state

The upstream `codex` CLI remains responsible for:

- login UX
- token refresh behavior
- reading the live `~/.codex/auth.json`
- all config, history, logs, and runtime state outside auth

### On-Disk Layout

The wrapper stores its own metadata under `~/.codex-switch`:

- `~/.codex-switch/state.json`
- `~/.codex-switch/accounts/<alias>.json`

The live Codex auth file remains:

- `~/.codex/auth.json`

Directory and file permissions:

- `~/.codex-switch`: `0700`
- `~/.codex-switch/accounts`: `0700`
- `state.json`: `0600`
- `accounts/<alias>.json`: `0600`

### State File

`state.json` tracks the active alias and minimal metadata. Proposed schema:

```json
{
  "version": 1,
  "active_alias": "work-2",
  "updated_at": "2026-03-31T12:00:00Z"
}
```

The wrapper treats account snapshots as opaque JSON blobs copied from `~/.codex/auth.json`. It does not parse token contents.

## Command Surface

V1 commands:

- `codex-switch add <alias>`
- `codex-switch use <alias>`
- `codex-switch list`
- `codex-switch remove <alias>`
- `codex-switch status`

Deferred commands:

- `codex-switch rename <old> <new>`
- `codex-switch doctor`

### Alias Rules

Alias names must match:

```text
^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$
```

This keeps filenames safe and predictable.

## Command Behavior

### `add <alias>`

Purpose: capture a fresh login into a named alias snapshot.

Behavior:

1. Refuse if any `codex` process is running.
2. Refuse if the alias already exists.
3. Load `state.json` and determine the current active alias, if any.
4. If there is an active alias and a live `~/.codex/auth.json`, save the live auth back into that alias snapshot first.
5. If a live `~/.codex/auth.json` exists, move it aside to a temporary backup file so the next login is fresh.
6. Run the normal `codex login` flow.
7. If login succeeds and produces `~/.codex/auth.json`, copy that file into `~/.codex-switch/accounts/<alias>.json` with mode `0600`.
8. Restore the pre-`add` live auth. If there was a previously active alias, restore that alias's snapshot. If there was no active alias but there was a live auth file before `add`, restore the temporary backup file.
9. Restore the original `state.json` active alias.
10. If login fails or is interrupted, do not create the alias and restore the previous live auth and state.

Notes:

- V1 supports only the normal Codex login flow, not `--with-api-key`.
- Adding an alias does not change which alias is active.

### `use <alias>`

Purpose: make one stored alias globally active.

Behavior:

1. Refuse if any `codex` process is running.
2. Refuse if the target alias does not exist.
3. Load `state.json` and determine the current active alias, if any.
4. If there is a current active alias and a live `~/.codex/auth.json`, copy the live auth back into that current alias snapshot first.
5. Copy the target alias snapshot into `~/.codex/auth.json` atomically.
6. Update `state.json` atomically to mark the target alias active.

This command changes the active account globally for the user profile until another `use` command is run.

### `list`

Purpose: show known aliases and which alias is active.

Behavior:

- Enumerate `~/.codex-switch/accounts/*.json`
- Read `state.json`
- Print aliases in a stable order
- Mark the active alias clearly

### `remove <alias>`

Purpose: delete a stored alias snapshot.

Behavior:

1. Refuse if any `codex` process is running.
2. Refuse if the alias does not exist.
3. Refuse if the alias is currently active.
4. Delete `~/.codex-switch/accounts/<alias>.json`.

This command does not change the live `~/.codex/auth.json`.

### `status`

Purpose: show the current active alias and whether the live auth appears aligned with the stored snapshot.

Behavior:

- Read `state.json`
- If no active alias exists, report that no alias is active
- If the active alias snapshot exists and live `~/.codex/auth.json` exists, compare file contents
- Report one of:
  - active and in sync
  - active but live auth differs from stored snapshot
  - active but live auth is missing
  - active alias recorded but snapshot file missing

## Concurrency Model

Mutating commands must refuse to run if a `codex` process is active. This applies to:

- `add`
- `use`
- `remove`

The goal is to avoid races where the upstream CLI reads or rewrites `~/.codex/auth.json` while `codex-switch` is replacing it.

The process check can be implemented by enumerating processes and matching the `codex` executable name and current user. If process inspection fails, the command should fail closed rather than proceed unsafely.

## Atomicity And Recovery

All writes to wrapper-managed files use a temp file in the same directory followed by rename. This applies to:

- `state.json`
- account snapshot files
- live auth replacement where feasible

If a command fails mid-flight:

- do not leave partially written files
- restore the previous live auth when possible
- leave `state.json` unchanged unless the switch completed successfully

`add` is the most failure-sensitive command and must be careful to restore prior auth on cancellation or login failure.

## Shared State Trade-Off

This design keeps `config.toml`, sessions, history, logs, caches, and SQLite state shared across accounts because the user explicitly wants that. The trade-off is that account-specific runtime artifacts are not isolated.

The main consequence is that token refreshes or auth changes made by the stock `codex` CLI are only persisted back into an alias snapshot when `codex-switch` later synchronizes the live auth file. In practice, that happens before switching away from the current alias or during another management command.

This behavior is acceptable for v1 and should be documented in CLI help and README text.

## Error Handling

Expected failures and responses:

- Invalid alias name: reject with a clear validation error.
- Alias already exists on `add`: reject without changing state.
- Alias missing on `use` or `remove`: reject without changing state.
- Active alias removal requested: reject without changing state.
- `codex` process active: reject mutating commands and instruct the user to exit Codex first.
- Missing live auth during `use`: allowed if the target alias snapshot exists.
- Missing live auth during `add`: allowed as part of the fresh-login flow.
- Pre-existing live auth with no active alias during `add`: preserve and restore it after the new alias is captured.
- Login cancelled during `add`: restore previous auth and leave no new alias.
- Corrupt or unreadable `state.json`: fail with a repair-oriented error rather than guessing.
- Snapshot write failure: fail and preserve the pre-command state as much as possible.

## Testing Strategy

Testing should cover:

- alias validation
- listing and active marker output
- status output for in-sync, dirty, missing-live-auth, and missing-snapshot states
- `use` persisting current live auth back to the current alias before switching
- `add` restoring previous auth after a successful capture
- `add` rollback when login fails or is interrupted
- `remove` refusing active aliases
- concurrency guard blocking mutating commands when `codex` is running
- file permission creation and repair behavior
- atomic replace behavior using temp files and rename

The implementation should separate filesystem/process abstractions enough to test core logic without requiring a real `codex login` for every case.

## Implementation Notes

The code should be structured around small units:

- state store for `state.json`
- account snapshot store
- live auth manager for reading/writing `~/.codex/auth.json`
- process guard for active `codex` detection
- command handlers for `add`, `use`, `list`, `remove`, and `status`

The command handlers should orchestrate these units without embedding filesystem details directly in CLI parsing code.

## Success Criteria

The design is successful if:

- the user can authenticate multiple accounts once with `codex-switch add <alias>`
- switching accounts only requires `codex-switch use <alias>`
- normal `codex` commands continue working unchanged after a switch
- the active alias is always knowable from wrapper state
- mutating commands fail safely when Codex is running or when file operations fail
