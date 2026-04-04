from __future__ import annotations

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
    best_score: tuple[float, float, str] | None = None

    for snapshot in candidates:
        if snapshot.alias == active_alias:
            continue

        score = _score_snapshot(snapshot, threshold)
        if score is None:
            continue

        if best_score is None or score < best_score:
            best_score = score

    if best_score is None:
        return None
    return best_score[2]


def _score_snapshot(snapshot: RateLimitSnapshot, threshold: float) -> tuple[float, float, str] | None:
    primary_used_percent = snapshot.primary_window.used_percent
    secondary_used_percent = snapshot.secondary_window.used_percent
    if primary_used_percent is None or secondary_used_percent is None:
        return None
    if primary_used_percent >= threshold or secondary_used_percent >= threshold:
        return None

    return (primary_used_percent, secondary_used_percent, snapshot.alias)
