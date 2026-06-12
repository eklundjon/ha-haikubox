"""Tests for _fire_detection_events: the new/unusual/watched edge-gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox.const import (
    CONF_ABSENCE_DAYS,
    CONF_SERIAL,
    CONF_WATCHED_SPECIES,
    DOMAIN,
    EVENT_HAIKUBOX,
    TRIGGER_NEW_SPECIES,
    TRIGGER_UNUSUAL_VISITOR,
    TRIGGER_WATCHED_SPECIES,
)

from .coordinator_helpers import make_coordinator

SERIAL = "100000003d7c9f2b"


def _rec(species: str, sp_code: str = "xxxxxx", **extra) -> dict:
    return {
        "species": species,
        "sp_code": sp_code,
        "scientific_name": f"{species} scientificus",
        "last_seen": "2026-06-01T12:00:00Z",
        "count": 1,
        "image_url": None,
        **extra,
    }


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


@pytest.fixture
def fire_ctx(hass: HomeAssistant):
    """Register the device + a bus capture; return a coordinator factory.

    `_fire_event` resolves the device from the registry by its serial
    identifiers (not via the config entry), so the coordinator only needs a
    plain options dict — supplied per test through the factory.
    """
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_SERIAL: SERIAL})
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}
    )
    events: list = []
    hass.bus.async_listen(EVENT_HAIKUBOX, lambda e: events.append(e))

    def _make(options: dict | None = None):
        return make_coordinator(
            hass, options=options or {}, serial=SERIAL, device_name="Test Box"
        )

    return _make, events


async def _fire(hass, coordinator, events, detections, newly_seen, prior_last_seen):
    coordinator._fire_detection_events(detections, newly_seen, prior_last_seen)
    await hass.async_block_till_done()
    return [e.data for e in events]


async def test_first_poll_is_silent(hass: HomeAssistant, fire_ctx) -> None:
    """With no previous window (session start), unusual/watched never fire."""
    make, events = fire_ctx
    c = make({CONF_WATCHED_SPECIES: ["Northern Cardinal"]})
    c._prev_recent_species = None

    fired = await _fire(hass, c, events, [_rec("Northern Cardinal")], set(), {})
    assert fired == []
    # the window is recorded for next time
    assert c._prev_recent_species == {"Northern Cardinal"}


async def test_new_species_fires_with_lifetime_count(
    hass: HomeAssistant, fire_ctx
) -> None:
    make, events = fire_ctx
    c = make()
    c._seen_species = {"A": "x", "B": "x", "Barred Owl": "x"}  # 3 lifetime

    fired = await _fire(
        hass, c, events, [_rec("Barred Owl", "brdowl")], {"Barred Owl"}, {}
    )
    assert len(fired) == 1
    assert fired[0]["type"] == TRIGGER_NEW_SPECIES
    assert fired[0]["species"] == "Barred Owl"
    assert fired[0]["lifetime_species_count"] == 3
    assert fired[0]["device_id"]  # resolved from the registry


async def test_unusual_visitor_fires_past_threshold(
    hass: HomeAssistant, fire_ctx
) -> None:
    make, events = fire_ctx
    c = make({CONF_ABSENCE_DAYS: 30})
    c._prev_recent_species = set()  # established session, empty last window

    fired = await _fire(
        hass,
        c,
        events,
        [_rec("Northern Cardinal", "norcar")],
        set(),
        {"Northern Cardinal": _days_ago(40)},
    )
    assert len(fired) == 1
    assert fired[0]["type"] == TRIGGER_UNUSUAL_VISITOR
    assert fired[0]["days_absent"] >= 30


async def test_unusual_visitor_silent_below_threshold(
    hass: HomeAssistant, fire_ctx
) -> None:
    make, events = fire_ctx
    c = make({CONF_ABSENCE_DAYS: 30})
    c._prev_recent_species = set()

    fired = await _fire(
        hass,
        c,
        events,
        [_rec("Northern Cardinal", "norcar")],
        set(),
        {"Northern Cardinal": _days_ago(10)},  # only 10 days -> not unusual
    )
    assert fired == []


async def test_no_refire_while_species_lingers(
    hass: HomeAssistant, fire_ctx
) -> None:
    """A species present last poll and this poll is not 'newly present'."""
    make, events = fire_ctx
    c = make({CONF_ABSENCE_DAYS: 30})
    c._prev_recent_species = {"Northern Cardinal"}

    fired = await _fire(
        hass,
        c,
        events,
        [_rec("Northern Cardinal", "norcar")],
        set(),
        {"Northern Cardinal": _days_ago(40)},
    )
    assert fired == []


async def test_watched_species_fires(hass: HomeAssistant, fire_ctx) -> None:
    make, events = fire_ctx
    c = make({CONF_WATCHED_SPECIES: ["Northern Cardinal"]})
    c._prev_recent_species = set()  # established session

    fired = await _fire(
        hass, c, events, [_rec("Northern Cardinal", "norcar")], set(), {}
    )
    assert len(fired) == 1
    assert fired[0]["type"] == TRIGGER_WATCHED_SPECIES
    assert fired[0]["species"] == "Northern Cardinal"
