"""Bat support in a full poll: bats stay out of every bird figure, and with bat
support on they get their own records, sensors' data and events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox import bats
from custom_components.haikubox.const import (
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_SERIAL,
    CONF_WATCHED_SPECIES,
    DOMAIN,
    EVENT_HAIKUBOX,
)

from .coordinator_helpers import ENTRY_ID, make_coordinator

SERIAL = "E4B063BBB044"
_NOW = datetime.now(UTC)
_TODAY = _NOW.date()


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# Shaped like a real bat-capable box's /detections: bats share the feed and the
# fields, told apart only by their codes.
_DETECTIONS = {"detections": [
    {"cn": "Fringed Myotis", "sn": "Myotis thysanodes", "spCode": "MYOTHY", "dt": _iso(10)},
    {"cn": "Bat", "sn": "", "spCode": "batbatbat", "dt": _iso(20)},
    {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(30)},
    {"cn": "Northern Cardinal", "sn": "Cardinalis cardinalis", "spCode": "norcar", "dt": _iso(300)},
]}

# /daily-count names only; "California Myotis" never appears in /detections, so
# only the bundled list can identify it.
_TODAY_COUNTS = {
    "American Robin": 120, "Northern Cardinal": 44,
    "Bat": 30, "Fringed Myotis": 5, "California Myotis": 2,
}
_BAT_NAMES = {"Bat", "Fringed Myotis", "California Myotis"}


@pytest.fixture(autouse=True)
def bundled_names(monkeypatch):
    monkeypatch.setattr(bats, "_BAT_NAMES", bats._read_bat_names())


@pytest.fixture
def events(hass: HomeAssistant) -> list:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_SERIAL: SERIAL}, entry_id=ENTRY_ID
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}
    )
    captured: list = []
    hass.bus.async_listen(EVENT_HAIKUBOX, lambda e: captured.append(e.data))
    return captured


def _coordinator(hass, *, bat_support: bool, options: dict | None = None):
    c = make_coordinator(
        hass,
        options={CONF_NOTABLE_RARITY_WEIGHT: 100, **(options or {})},
        serial=SERIAL,
        _bat_support=bat_support,
    )
    c._daily_counts = {
        (_TODAY - timedelta(days=n)).isoformat(): {
            "American Robin": 80, "Northern Cardinal": 30, "Bat": 40, "California Myotis": 3,
        }
        for n in range(1, 9)
    }
    c._backfill_complete = True
    c._backfill_cursor = (_TODAY - timedelta(days=9)).isoformat()
    c._backfill_misses = 14

    async def fake_detections(hours):
        return _DETECTIONS

    async def fake_daily_count(date_str):
        if date_str == _TODAY.isoformat():
            return dict(_TODAY_COUNTS)
        return c._daily_counts.get(date_str, {})

    async def fake_box_tz():
        return UTC

    c._fetch_detections = fake_detections
    c._fetch_daily_count = fake_daily_count
    c._async_box_tz = fake_box_tz
    return c


def _species(records) -> set[str]:
    return {r["species"] for r in records or []}


def _assert_bird_figures_exclude_bats(data, c) -> None:
    assert data["today_total"] == 164
    assert set(data["today_species"]) == {"American Robin", "Northern Cardinal"}
    for key in ("recent_detections", "daily_top_species", "notable_detections",
                "rarest_species", "yearly_top_species", "new_detections", "detections_24h"):
        assert not _species(data[key]) & _BAT_NAMES, key
    assert not set(c._baseline_ranks) & _BAT_NAMES
    assert data["lifetime_species_count"] == 2


async def test_bats_ignored_without_bat_support(hass: HomeAssistant, events) -> None:
    c = _coordinator(hass, bat_support=False)
    data = await c._async_update_data()

    _assert_bird_figures_exclude_bats(data, c)
    assert data["last_detection"]["species"] == "American Robin"
    assert not _species(data["recent_events"]) & _BAT_NAMES
    assert data["bats_today"] == []
    assert data["bat_today_total"] == 0
    assert not set(c._seen_species) & _BAT_NAMES
    assert not set(c.known_species) & _BAT_NAMES


async def test_bat_support_adds_bat_data(hass: HomeAssistant, events) -> None:
    c = _coordinator(hass, bat_support=True)
    data = await c._async_update_data()

    _assert_bird_figures_exclude_bats(data, c)

    # last_detection is whatever was heard last, now a bat; the per-class
    # records split it out.
    assert data["last_detection"]["species"] == "Fringed Myotis"
    assert data["last_detection"]["classification"] == "bat"
    assert data["last_bird_detection"]["species"] == "American Robin"
    assert data["last_bat_detection"]["species"] == "Fringed Myotis"

    # Today's bats by true count, from /daily-count, including one known only
    # from the bundled list.
    assert [(r["species"], r["count"]) for r in data["bats_today"]] == [
        ("Bat", 30), ("Fringed Myotis", 5), ("California Myotis", 2),
    ]
    assert data["bat_today_total"] == 37

    # Bats are in the first-seen log (so new_species can fire for them) and
    # the watch-list picker, but not in the bird lifetime count.
    assert {"Bat", "Fringed Myotis", "California Myotis"} <= set(c._seen_species)
    assert {"Bat", "Fringed Myotis"} <= set(c.known_species)

    # Bird reference links and audio are dropped for bats; Wikipedia stays.
    bat = data["last_bat_detection"]
    assert bat["ebird_url"] is None
    assert bat["allaboutbirds_url"] is None
    assert bat["macaulay_url"] is None
    assert bat["wikipedia_url"]
    assert bat["audio_url"] is None
    assert data["last_bird_detection"]["ebird_url"]

    # The first poll establishes baselines without firing anything.
    await hass.async_block_till_done()
    assert events == []


async def test_new_bat_species_fires_new_species(hass: HomeAssistant, events) -> None:
    c = _coordinator(hass, bat_support=True)
    await c._async_update_data()

    _DETECTIONS["detections"].append(
        {"cn": "Hoary Bat", "sn": "Lasiurus cinereus", "spCode": "LASCIN", "dt": _iso(5)}
    )
    try:
        await c._async_update_data()
    finally:
        _DETECTIONS["detections"].pop()
    await hass.async_block_till_done()

    fired = [e for e in events if e["type"] == "new_species"]
    assert [e["species"] for e in fired] == ["Hoary Bat"]
    assert fired[0]["classification"] == "bat"
    assert fired[0]["ebird_url"] is None


async def test_watched_bat_fires_watched_species(hass: HomeAssistant, events) -> None:
    c = _coordinator(hass, bat_support=True, options={CONF_WATCHED_SPECIES: ["Bat"]})
    c._prev_recent_bats = set()  # not the first poll of the session
    await c._async_update_data()
    await hass.async_block_till_done()

    watched = [e for e in events if e["type"] == "watched_species"]
    assert [e["species"] for e in watched] == ["Bat"]


@pytest.mark.parametrize(
    ("prior_minutes_ago", "fires"),
    [
        (240, True),   # bats return after nearly four quiet hours
        (45, False),   # the previous bat was only 35 minutes before this one
        (None, False), # no previous bat: this poll only sets the baseline
    ],
)
async def test_bat_activity(hass: HomeAssistant, events, prior_minutes_ago, fires) -> None:
    c = _coordinator(hass, bat_support=True)
    if prior_minutes_ago is not None:
        c._last_by_class["bat"] = {
            "species": "Bat", "sp_code": "batbatbat", "classification": "bat",
            "last_seen": _iso(prior_minutes_ago),
        }
    await c._async_update_data()
    await hass.async_block_till_done()

    activity = [e for e in events if e["type"] == "bat_activity"]
    if not fires:
        assert activity == []
        return
    assert len(activity) == 1
    assert activity[0]["species"] == "Fringed Myotis"  # the newest bat
    assert activity[0]["count"] == 2                   # both bats since the prior one
    assert activity[0]["quiet_minutes"] == prior_minutes_ago - 20
    assert activity[0]["classification"] == "bat"


async def test_last_bird_survives_a_night_of_bats(hass: HomeAssistant, events) -> None:
    """The per-class records outlive the shared event buffer's turnover."""
    c = _coordinator(hass, bat_support=True)
    await c._async_update_data()

    # A night of bats fills the shared buffer completely.
    c._event_buffer = [
        {"species": "Bat", "sp_code": "batbatbat", "last_seen": _iso(i)} for i in range(50)
    ]
    assert c._class_head("bird")["species"] == "American Robin"


async def test_last_bat_found_under_a_morning_of_birds(hass: HomeAssistant, events) -> None:
    """More birds since the last bat than the shared event list holds: the bat
    record must come from the bats' own detections. (Found on a real box,
    where the overnight bats sat behind a morning's birdsong.)"""
    c = _coordinator(hass, bat_support=True)
    morning = [
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(i)}
        for i in range(1, 80)
    ]
    night = [{"cn": "Bat", "sn": "", "spCode": "batbatbat", "dt": _iso(600)}]

    async def busy_morning(hours):
        return {"detections": morning + night}

    c._fetch_detections = busy_morning
    data = await c._async_update_data()

    assert data["last_detection"]["species"] == "American Robin"
    assert data["last_bat_detection"]["species"] == "Bat"
