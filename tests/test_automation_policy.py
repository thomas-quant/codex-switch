from __future__ import annotations

from codex_switch.automation_models import RateLimitSnapshot, RateLimitWindow, UsageSource
from codex_switch.automation_policy import choose_target_alias, should_trigger_soft_switch


def make_snapshot(
    alias: str,
    primary_used_percent: float | None,
    secondary_used_percent: float | None,
    *,
    primary_resets_at: str = "2026-04-04T00:00:00Z",
    secondary_resets_at: str | None = "2026-04-05T00:00:00Z",
) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        alias=alias,
        limit_id=None,
        limit_name="Daily limit",
        observed_via=UsageSource.RPC,
        plan_type="pro",
        primary_window=RateLimitWindow(
            used_percent=primary_used_percent,
            resets_at=primary_resets_at,
            window_duration_mins=60,
        ),
        secondary_window=RateLimitWindow(
            used_percent=secondary_used_percent,
            resets_at=secondary_resets_at,
            window_duration_mins=10080,
        ),
        credits_has_credits=True,
        credits_unlimited=False,
        credits_balance="5.25",
        observed_at="2026-04-04T00:00:00Z",
    )


def test_should_trigger_soft_switch_at_threshold_boundary() -> None:
    assert should_trigger_soft_switch(make_snapshot("work", 95, 10), 95) is True
    assert should_trigger_soft_switch(make_snapshot("work", 94, 10), 95) is False
    assert should_trigger_soft_switch(make_snapshot("work", 10, 95), 95) is True
    assert should_trigger_soft_switch(make_snapshot("work", 10, 94), 95) is False


def test_choose_target_alias_ranks_primary_then_secondary_for_mixed_limit_states() -> None:
    candidates = [
        make_snapshot("alpha", 40, 30),
        make_snapshot("beta", 40, 20),
        make_snapshot("gamma", 55, 10),
    ]

    assert choose_target_alias("work", candidates, 95) == "beta"


def test_choose_target_alias_rejects_candidates_with_partial_telemetry() -> None:
    candidates = [
        make_snapshot("work", 5, 5),
        make_snapshot("alpha", 10, None),
        make_snapshot("beta", 20, 15),
    ]

    assert choose_target_alias("work", candidates, 95) == "beta"


def test_choose_target_alias_uses_earliest_reset_time_when_all_aliases_near_exhaustion() -> None:
    candidates = [
        make_snapshot(
            "alpha",
            98,
            99,
            primary_resets_at="2026-04-06T00:00:00Z",
            secondary_resets_at="2026-04-07T00:00:00Z",
        ),
        make_snapshot(
            "beta",
            98,
            99,
            primary_resets_at="2026-04-05T00:00:00Z",
            secondary_resets_at="2026-04-08T00:00:00Z",
        ),
    ]

    assert choose_target_alias("work", candidates, 95) == "beta"


def test_choose_target_alias_skips_unparseable_reset_data_in_near_exhaustion_tiebreak() -> None:
    candidates = [
        make_snapshot(
            "alpha",
            98,
            99,
            primary_resets_at="not-an-iso-timestamp",
            secondary_resets_at=None,
        ),
        make_snapshot(
            "beta",
            98,
            99,
            primary_resets_at="2026-04-05T00:00:00Z",
            secondary_resets_at=None,
        ),
    ]

    assert choose_target_alias("work", candidates, 95) == "beta"


def test_choose_target_alias_ignores_reset_time_when_aliases_are_not_near_exhaustion() -> None:
    candidates = [
        make_snapshot(
            "alpha",
            40,
            40,
            primary_resets_at="2026-04-07T00:00:00Z",
            secondary_resets_at="2026-04-08T00:00:00Z",
        ),
        make_snapshot(
            "beta",
            40,
            40,
            primary_resets_at="2026-04-05T00:00:00Z",
            secondary_resets_at="2026-04-06T00:00:00Z",
        ),
    ]

    assert choose_target_alias("work", candidates, 95) == "alpha"


def test_choose_target_alias_returns_none_when_all_candidate_telemetry_is_partial_or_unknown() -> None:
    candidates = [
        make_snapshot("alpha", 25, None),
        make_snapshot("beta", None, 30),
    ]

    assert choose_target_alias("work", candidates, 95) is None
