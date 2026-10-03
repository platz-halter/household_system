"""Unit tests for crud.week_bounds — the single function every weekly
computation in this service (points-this-week, the leaderboard's
This/Last week filters, the heatmap, the balancer's weekly period, the
nudge, auto-generated weekly reports) goes through, so they all agree on
where a week starts even after an admin changes
HouseholdSettings.week_start_weekday.
"""

from datetime import date

from household_service.crud import week_bounds


def test_monday_start_default():
    # 2026-10-07 is a Wednesday.
    start, end = week_bounds(date(2026, 10, 7), week_start=0)
    assert start == date(2026, 10, 5)  # Monday
    assert end == date(2026, 10, 11)  # Sunday


def test_sunday_start():
    # Same Wednesday, but weeks start on Sunday.
    start, end = week_bounds(date(2026, 10, 7), week_start=6)
    assert start == date(2026, 10, 4)  # Sunday
    assert end == date(2026, 10, 10)  # Saturday


def test_every_start_weekday_produces_a_contiguous_7_day_week():
    d = date(2026, 10, 7)
    for week_start in range(7):
        start, end = week_bounds(d, week_start)
        assert (end - start).days == 6
        assert start.weekday() == week_start
        assert start <= d <= end


def test_date_on_the_start_day_itself_is_its_own_week_start():
    # 2026-10-05 is a Monday; with a Monday start, that day IS the start.
    start, end = week_bounds(date(2026, 10, 5), week_start=0)
    assert start == date(2026, 10, 5)
    assert end == date(2026, 10, 11)


def test_date_on_the_last_day_of_a_custom_week():
    # With a Thursday start (3), the Wednesday right before is the LAST
    # day of the previous week, not the first of a new one.
    start, end = week_bounds(date(2026, 10, 7), week_start=3)  # Wed
    assert end == date(2026, 10, 7)
    assert start == date(2026, 10, 1)  # the preceding Thursday


def test_year_rollover():
    # 2026-01-01 is a Thursday. A Monday-start week spanning the
    # new year must still resolve correctly across the boundary.
    start, end = week_bounds(date(2026, 1, 1), week_start=0)
    assert start == date(2025, 12, 29)
    assert end == date(2026, 1, 4)


def test_deterministic_and_pure():
    d = date(2026, 6, 15)
    assert week_bounds(d, 2) == week_bounds(d, 2)
