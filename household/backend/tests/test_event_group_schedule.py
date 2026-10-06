"""Unit tests for crud._event_group_due — the pure predicate behind
run_scheduled_event_groups_if_due, kept separate from the DB-touching
tick itself so a schedule's edge cases don't need a real clock hour to
roll around or a live database to exercise.
"""

from datetime import UTC, datetime

from household_service.crud import _event_group_due


def _at(hour: int, weekday: int = 0) -> datetime:
    # 2026-10-05 is a Monday (weekday 0); +weekday days keeps that anchor.
    return datetime(2026, 10, 5 + weekday, hour, 0, tzinfo=UTC)


def test_unscheduled_group_is_never_due():
    assert not _event_group_due(None, None, 18, ran_today=False, now=_at(18))


def test_already_ran_today_is_not_due_again():
    assert not _event_group_due("daily", None, 18, ran_today=True, now=_at(18))


def test_daily_fires_at_exact_hour():
    assert _event_group_due("daily", None, 18, ran_today=False, now=_at(18))


def test_daily_does_not_fire_before_its_hour():
    assert not _event_group_due("daily", None, 18, ran_today=False, now=_at(17))


def test_daily_does_not_fire_after_its_hour():
    # Not >= — a restart hours late shouldn't fire a backlog, just stay due
    # for the one hour it actually matches (or wait for tomorrow's).
    assert not _event_group_due("daily", None, 18, ran_today=False, now=_at(19))


def test_weekly_fires_on_a_matching_weekday_at_its_hour():
    assert _event_group_due(
        "weekly", [0, 2], 18, ran_today=False, now=_at(18, weekday=0)
    )


def test_weekly_does_not_fire_on_a_non_matching_weekday():
    assert not _event_group_due(
        "weekly", [2], 18, ran_today=False, now=_at(18, weekday=0)
    )


def test_weekly_with_no_weekdays_never_fires():
    assert not _event_group_due("weekly", None, 18, ran_today=False, now=_at(18))


def test_weekly_with_empty_weekdays_never_fires():
    assert not _event_group_due("weekly", [], 18, ran_today=False, now=_at(18))


def test_tz_defaults_to_utc_so_old_behavior_is_unchanged():
    # No tz kwarg at all — every test above already covers this, but
    # spelling it out once guards against the default silently changing.
    assert _event_group_due("daily", None, 18, ran_today=False, now=_at(18))


def test_tz_hour_18_fires_at_16_utc_during_european_summer_time():
    # 2026-10-05 is still CEST (+2) in Europe/Berlin — DST doesn't end
    # there until the last Sunday of October (the 25th that year).
    now = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
    assert _event_group_due(
        "daily", None, 18, ran_today=False, now=now, tz="Europe/Berlin"
    )


def test_tz_does_not_fire_at_18_utc_during_european_summer_time():
    # 18:00 UTC is 20:00 in Berlin on that same CEST day, not 18:00.
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    assert not _event_group_due(
        "daily", None, 18, ran_today=False, now=now, tz="Europe/Berlin"
    )


def test_tz_hour_18_fires_at_17_utc_during_european_winter_time():
    # 2026-01-05 is CET (+1) — DST doesn't start until late March.
    now = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)
    assert _event_group_due(
        "daily", None, 18, ran_today=False, now=now, tz="Europe/Berlin"
    )


def test_tz_local_weekday_can_differ_from_utc_weekday():
    # 2026-10-06 03:00 UTC (a Tuesday in UTC) is still 2026-10-05 20:00
    # in America/Los_Angeles (PDT, UTC-7 in October) — Monday evening.
    # A Monday-only schedule must key off the LOCAL weekday, not UTC's.
    now = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)
    assert _event_group_due(
        "weekly", [0], 20, ran_today=False, now=now, tz="America/Los_Angeles"
    )
    # The same instant, read as raw UTC, is a Tuesday — so a
    # Tuesday-only schedule must NOT fire for Los Angeles at this hour,
    # since it's still Monday there.
    assert not _event_group_due(
        "weekly", [1], 20, ran_today=False, now=now, tz="America/Los_Angeles"
    )
