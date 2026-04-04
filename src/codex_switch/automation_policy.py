from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterable

from codex_switch.automation_models import RateLimitSnapshot


def should_trigger_soft_switch(snapshot: RateLimitSnapshot, threshold: float) -> bool:
    return any(
        used_percent is not None and used_percent >= threshold
        for used_percent in (
            snapshot.primary_window.used_percent,
            snapshot.secondary_window.used_percent,
        )
    )


def choose_target_alias(
    active_alias: str,
    candidates: Iterable[RateLimitSnapshot],
    threshold: float,
) -> str | None:
    eligible_candidates = [
        snapshot
        for snapshot in candidates
        if snapshot.alias != active_alias and _has_authoritative_telemetry(snapshot)
    ]
    use_reset_tiebreak = bool(eligible_candidates) and all(
        _is_near_exhaustion(snapshot, threshold) for snapshot in eligible_candidates
    )
    if use_reset_tiebreak:
        eligible_candidates = [
            snapshot for snapshot in eligible_candidates if _has_rankable_reset(snapshot)
        ]

    best_score: tuple[int, int, float, float, tuple[int, datetime], str] | None = None

    for snapshot in eligible_candidates:
        score = _score_snapshot(snapshot, threshold, use_reset_tiebreak)

        if best_score is None or score < best_score:
            best_score = score

    if best_score is None:
        return None
    return best_score[5]


def _score_snapshot(
    snapshot: RateLimitSnapshot,
    threshold: float,
    use_reset_tiebreak: bool,
) -> tuple[int, int, float, float, tuple[int, datetime], str]:
    primary_used_percent = snapshot.primary_window.used_percent
    secondary_used_percent = snapshot.secondary_window.used_percent

    primary_below_threshold = int(not (primary_used_percent is not None and primary_used_percent < threshold))
    secondary_below_threshold = int(
        not (secondary_used_percent is not None and secondary_used_percent < threshold)
    )

    return (
        primary_below_threshold,
        secondary_below_threshold,
        _used_percent_rank(primary_used_percent),
        _used_percent_rank(secondary_used_percent),
        _reset_rank(snapshot) if use_reset_tiebreak else _neutral_reset_rank(),
        snapshot.alias,
    )


def _has_authoritative_telemetry(snapshot: RateLimitSnapshot) -> bool:
    return (
        snapshot.primary_window.used_percent is not None
        and snapshot.secondary_window.used_percent is not None
    )


def _is_near_exhaustion(snapshot: RateLimitSnapshot, threshold: float) -> bool:
    return (
        snapshot.primary_window.used_percent is not None
        and snapshot.secondary_window.used_percent is not None
        and snapshot.primary_window.used_percent >= threshold
        and snapshot.secondary_window.used_percent >= threshold
    )


def _used_percent_rank(used_percent: float | None) -> float:
    return used_percent if used_percent is not None else float("inf")


def _has_rankable_reset(snapshot: RateLimitSnapshot) -> bool:
    return _reset_rank(snapshot)[0] == 0


def _neutral_reset_rank() -> tuple[int, datetime]:
    return (1, datetime.max.replace(tzinfo=timezone.utc))


def _reset_rank(snapshot: RateLimitSnapshot) -> tuple[int, datetime]:
    reset_times = [
        reset_time
        for reset_time in (
            _parse_reset_time(snapshot.primary_window.resets_at),
            _parse_reset_time(snapshot.secondary_window.resets_at),
        )
        if reset_time is not None
    ]
    if not reset_times:
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    return (0, min(reset_times))


def _parse_reset_time(reset_at: str | None) -> datetime | None:
    if reset_at is None:
        return None
    try:
        parsed = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
