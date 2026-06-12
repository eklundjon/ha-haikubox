"""Tests for _ensure_daily_counts: gap-fill, deep backfill, and the floor."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from homeassistant.core import HomeAssistant

from custom_components.haikubox.const import BACKFILL_STOP_AFTER_404

from .coordinator_helpers import make_coordinator

TODAY = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _no_backfill_delay(monkeypatch):
    """Drop the politeness sleep between backfill requests so tests are fast."""
    monkeypatch.setattr(
        "custom_components.haikubox.coordinator.BACKFILL_REQUEST_DELAY", 0
    )


def _counter(responses: dict[str, dict | None], calls: list[str]):
    """A fake _fetch_daily_count: returns mapped responses (None = 404),
    defaulting to None (pre-install) for any unmapped date."""

    async def _fetch(date_str: str):
        calls.append(date_str)
        return responses.get(date_str)

    return _fetch


async def test_floor_reached_after_consecutive_404s(hass: HomeAssistant) -> None:
    """A fresh box whose history is all 404 stops at the pre-install floor."""
    calls: list[str] = []
    c = make_coordinator(hass)
    c._fetch_daily_count = _counter({}, calls)  # everything 404 -> None

    changed = await c._ensure_daily_counts(TODAY)

    assert changed is True
    assert c._backfill_complete is True
    assert c._backfill_misses == BACKFILL_STOP_AFTER_404
    # yesterday is probed in phase 1 (stored {}), then the floor count of 404s.
    assert len(calls) == BACKFILL_STOP_AFTER_404 + 1


async def test_forward_fill_adds_newly_completed_day(hass: HomeAssistant) -> None:
    """With history already covered, a newly-completed day is fetched and stored."""
    calls: list[str] = []
    c = make_coordinator(hass)
    c._backfill_complete = True  # phase 2 (deep backfill) is skipped
    c._daily_counts = {(TODAY - timedelta(days=2)).isoformat(): {"Robin": 5}}
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    c._fetch_daily_count = _counter({yesterday: {"Robin": 8}}, calls)

    changed = await c._ensure_daily_counts(TODAY)

    assert changed is True
    assert c._daily_counts[yesterday] == {"Robin": 8}
    assert calls == [yesterday]  # only the gap day was fetched


async def test_404_in_range_stored_as_empty_not_floor(hass: HomeAssistant) -> None:
    """A 404 *inside* the known range means 'no data that day' (stored {}),
    and must not count toward the pre-install floor."""
    calls: list[str] = []
    c = make_coordinator(hass)
    c._backfill_complete = True
    c._daily_counts = {(TODAY - timedelta(days=3)).isoformat(): {"Robin": 5}}
    d1 = (TODAY - timedelta(days=1)).isoformat()
    d2 = (TODAY - timedelta(days=2)).isoformat()
    c._fetch_daily_count = _counter({d1: None, d2: None}, calls)  # gap days 404

    changed = await c._ensure_daily_counts(TODAY)

    assert changed is True
    assert c._daily_counts[d1] == {}
    assert c._daily_counts[d2] == {}
    assert c._backfill_misses == 0  # in-range 404s never advance the floor
    assert c._backfill_complete is True


async def test_no_change_when_history_already_complete(hass: HomeAssistant) -> None:
    """When every day in range is known and backfill is done, nothing is fetched."""
    calls: list[str] = []
    c = make_coordinator(hass)
    c._backfill_complete = True
    c._daily_counts = {
        (TODAY - timedelta(days=1)).isoformat(): {"Robin": 1},
        (TODAY - timedelta(days=2)).isoformat(): {"Robin": 2},
    }
    c._fetch_daily_count = _counter({}, calls)

    changed = await c._ensure_daily_counts(TODAY)

    assert changed is False
    assert calls == []
