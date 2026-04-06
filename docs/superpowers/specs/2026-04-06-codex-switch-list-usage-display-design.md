# codex-switch List Usage Display Design

## Summary

Extend `codex-switch list` so it can show per-alias account type plus remaining 5-hour and weekly usage. The command remains cache-first and performs a one-shot live refresh when plan type or rate-limit data is missing. Output format is controlled by a minimal persisted config file at `~/.codex-switch/config.json`.

Default output stays human-readable and compact:

```text
* beta -- plus -- 5h left: 42% -- weekly left: 71%
```

An optional ASCII table mode is also supported through config.

## Goals

- Show remaining 5-hour and weekly usage for each configured alias in `codex-switch list`.
- Preserve the existing plan-type display.
- Keep `list` safe and resilient: cache-first, best-effort refresh, no hard failure when telemetry is unavailable.
- Add a minimal persistent config mechanism for selecting list output mode.

## Non-Goals

- No CLI `--format` flag in v1.
- No general-purpose config command surface such as `codex-switch config get/set`.
- No new daemon behavior or background refresh logic.
- No warnings or diagnostic noise in normal `list` output.

## User Experience

### Labelled Mode

Labelled mode is the default when `config.json` is missing, unreadable, or invalid.

Examples:

```text
* beta -- plus -- 5h left: 42% -- weekly left: 71%
  gamma -- 5h left: ? -- weekly left: ?
  delta -- pro -- 5h left: 88% -- weekly left: 12%
```

Rules:

- The active alias keeps the `* ` prefix.
- `plan_type` is shown only when known and non-blank.
- `5h left` and `weekly left` are always rendered.
- Missing usage values render as `?` to keep line shape consistent.

### Table Mode

When `~/.codex-switch/config.json` sets `list_format` to `table`, `codex-switch list` renders a fixed-width ASCII table.

Columns:

- active
- alias
- type
- 5h left
- weekly left

Rules:

- Missing `type` renders as an empty cell.
- Missing `5h left` and `weekly left` render as `?`.
- No color or terminal-width-dependent formatting is introduced in v1.

## Config

Add a minimal persisted config file at `~/.codex-switch/config.json`.

Initial schema:

```json
{
  "list_format": "labelled"
}
```

Accepted values:

- `labelled`
- `table`

Behavior:

- Missing config file: use `labelled`.
- Invalid JSON: use `labelled`.
- Unknown `list_format` value: use `labelled`.
- `list` does not fail because of config problems.

This config layer is intentionally narrow and exists only to support list formatting in v1.

## Data Flow

`codex-switch list` remains cache-first.

For each alias, it reads:

- alias metadata from `aliases`
- latest rate-limit snapshot from `rate_limits`

Remaining percentages are derived from stored usage:

- `5h left = 100 - primary_used_percent`
- `weekly left = 100 - secondary_used_percent`

If plan type, 5-hour usage, or weekly usage is missing for any alias, `list` performs a one-shot live refresh using the existing safe probing model:

- active alias can be probed directly
- inactive aliases are only probed when auth mutation is safe
- successful probe results are written back into the local automation DB
- failed or skipped probes do not abort `list`

## Probe Contract

The current alias metadata probe is too narrow for this feature because it only returns identity metadata. Replace it with a richer observation contract that can carry both identity and rate-limit results.

The new observation should support:

- account email
- account plan type
- account fingerprint
- observation timestamp
- zero or more rate-limit snapshots

Source behavior:

- RPC remains the preferred source and should provide both identity and rate limits.
- PTY fallback may provide rate-limit usage without reliable plan type.
- When PTY fallback cannot provide plan type, plan type remains cached-only or unknown.

This keeps one probing interface for `list` rather than adding separate metadata and usage fetch paths.

## Manager Responsibilities

`CodexSwitchManager.list_aliases()` should return richer `AliasListEntry` values containing:

- alias
- plan type
- remaining 5-hour percentage
- remaining weekly percentage

Manager flow:

1. Read configured aliases.
2. Read cached alias metadata and latest cached rate-limit snapshot per alias.
3. Build list entries from cache.
4. Identify aliases missing plan type or either remaining usage field.
5. Run best-effort one-shot refresh for unresolved aliases when probing is available.
6. Rebuild entries from the updated cache and return them.

The existing auth-restore safety rules for inactive alias probing remain unchanged.

## Formatting Responsibilities

Formatting stays in `cli.py`.

Two formatters should exist:

- labelled line formatter
- ASCII table formatter

`codex-switch list` should:

- load config
- choose the formatter
- render the returned entries without embedding formatting logic in manager code

This keeps presentation concerns out of manager and automation storage code.

## Error Handling

- `codex-switch list` must not fail because config is missing, malformed, or contains an unknown format.
- `codex-switch list` must not fail because telemetry is missing or refresh probing is unavailable.
- Automation DB read failures should continue to fall back to plain cache-miss behavior, as they do today.
- Inactive alias refresh must still fail closed when auth mutation is unsafe.
- Missing usage values render as `?`, not as errors or warnings.

## Testing

Add or update tests for:

- config loading with missing file, invalid JSON, unknown format, and valid `table`
- manager cache-only list entries with remaining usage populated from stored rate-limit snapshots
- manager one-shot refresh for missing usage on active aliases
- manager one-shot refresh for missing usage on inactive aliases with safe auth restoration
- labelled formatter output with known and unknown plan/usage fields
- table formatter output with known and unknown plan/usage fields
- CLI `list` rendering using config-selected labelled and table modes

Full-suite `pytest` remains the verification gate before merge.

## Implementation Notes

- Keep the config scope deliberately small; do not introduce a generic settings subsystem.
- Reuse the existing automation DB schema and `latest_rate_limit_for_alias()` reads rather than adding duplicate storage.
- Prefer deriving remaining percentages at read time instead of storing duplicate `left_percent` values.
- Preserve existing exact output stability where possible, except for the intentional `list` format expansion.
