"""End-to-end test of _async_update_data with canned, deterministic inputs.

A pytest port of scripts/coordinator_smoke.py: drive a full poll with a fixed
/detections payload and per-day history, and assert the headline outputs. Uses
pure-rarity notability (weight 100) so the result doesn't depend on "now".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant

from custom_components.haikubox.const import CONF_NOTABLE_RARITY_WEIGHT

from .coordinator_helpers import make_coordinator

_NOW = datetime.now(timezone.utc)
_TODAY = _NOW.date()


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


_DETECTIONS = {
    "detections": [
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(15)},
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(40)},
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(200)},
        {"cn": "Northern Cardinal", "sn": "Cardinalis cardinalis", "spCode": "norcar", "dt": _iso(50)},
        {"cn": "Barred Owl", "sn": "Strix varia", "spCode": "brdowl", "dt": _iso(600)},
        {"cn": "soundscape", "sn": "", "spCode": "soundscape", "dt": _iso(5)},
    ]
}

_TODAY_COUNTS = {"American Robin": 120, "Northern Cardinal": 44, "Barred Owl": 2}


def _seed_history(c) -> None:
    """8 completed days fully covering the window, so no backfill fetch fires."""
    c._daily_counts = {}
    for n in range(1, 9):
        day = (_TODAY - timedelta(days=n)).isoformat()
        c._daily_counts[day] = {
            "American Robin": 80 + n,
            "Northern Cardinal": 30,
            "Barred Owl": 1 if n % 4 == 0 else 0,
        }
    c._backfill_complete = True
    c._backfill_cursor = (_TODAY - timedelta(days=9)).isoformat()
    c._backfill_misses = 14


async def _run_poll(hass) -> dict:
    c = make_coordinator(hass, options={CONF_NOTABLE_RARITY_WEIGHT: 100})
    _seed_history(c)

    async def fake_detections(hours):
        return _DETECTIONS

    async def fake_daily_count(date_str):
        if date_str == _TODAY.isoformat():
            return dict(_TODAY_COUNTS)
        return c._daily_counts.get(date_str, {})

    async def fake_box_tz():
        return timezone.utc

    c._fetch_detections = fake_detections
    c._fetch_daily_count = fake_daily_count
    c._async_box_tz = fake_box_tz
    return await c._async_update_data(), c


async def test_update_data_headline_outputs(hass: HomeAssistant) -> None:
    data, coordinator = await _run_poll(hass)

    # A rich result dict, not a stub.
    assert isinstance(data, dict)
    assert len(data) > 15

    # Today's true volume is the sum of the per-species /daily-count.
    assert data["today_total"] == sum(_TODAY_COUNTS.values())  # 166

    # Most-recent event (15 min ago) is the last_detection.
    assert data["last_detection"]["species"] == "American Robin"

    # The 1-hour recent window: Robin (15/40 min) and Cardinal (50 min); the
    # Owl (600 min) and the older Robin (200 min) are outside it.
    assert {r["species"] for r in data["recent_detections"]} == {
        "American Robin",
        "Northern Cardinal",
    }

    # Rarest by the trailing baseline is the Barred Owl (lowest totals).
    assert data["rarest_species"][0]["species"] == "Barred Owl"

    # The fresh-install bootstrap seeded the lifetime log from the 24h window.
    assert coordinator._seen_species


async def test_update_data_filters_soundscape(hass: HomeAssistant) -> None:
    data, _ = await _run_poll(hass)
    for key in ("recent_detections", "daily_top_species", "notable_detections"):
        species = {r["species"] for r in (data.get(key) or [])}
        assert "soundscape" not in species
