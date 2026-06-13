"""End-to-end entry setup: a mocked poll wires up real entities + cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox.const import CONF_DEVICE_NAME, CONF_SERIAL, DOMAIN
from custom_components.haikubox.coordinator import HaikuboxCoordinator
from custom_components.haikubox.image_cache import ImageCache

SERIAL = "100000003d7c9f2b"
_NOW = datetime.now(UTC)
_TODAY = _NOW.date()


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


_DETECTIONS = {
    "detections": [
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(15)},
        {"cn": "Northern Cardinal", "sn": "Cardinalis cardinalis", "spCode": "norcar", "dt": _iso(50)},
        {"cn": "Barred Owl", "sn": "Strix varia", "spCode": "brdowl", "dt": _iso(600)},
    ]
}
_TODAY_COUNTS = {"American Robin": 120, "Northern Cardinal": 44, "Barred Owl": 2}
_HISTORY_DAY = {"American Robin": 50, "Northern Cardinal": 20, "Barred Owl": 1}


async def _fake_daily_count(self, date_str: str):
    if date_str == _TODAY.isoformat():
        return dict(_TODAY_COUNTS)
    return dict(_HISTORY_DAY)  # any past day has data -> a baseline builds


@pytest.fixture(autouse=True)
def _fast_backfill(monkeypatch):
    monkeypatch.setattr(
        "custom_components.haikubox.coordinator.BACKFILL_REQUEST_DELAY", 0
    )


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_SERIAL: SERIAL, CONF_DEVICE_NAME: "Bird Shazam"},
        options={},
    )
    entry.add_to_hass(hass)
    with (
        # The component-level async_setup only registers card JS + the cache
        # static path (needs the frontend wheel); not what we're exercising.
        patch("custom_components.haikubox.async_setup", return_value=True),
        patch.object(
            HaikuboxCoordinator, "_fetch_detections", AsyncMock(return_value=_DETECTIONS)
        ),
        patch.object(HaikuboxCoordinator, "_fetch_daily_count", _fake_daily_count),
        patch.object(
            HaikuboxCoordinator, "_async_box_tz", AsyncMock(return_value=UTC)
        ),
        # The image cache otherwise downloads species photos from S3.
        patch.object(
            ImageCache,
            "async_fetch",
            AsyncMock(return_value="/haikubox/cache/x.jpeg"),
        ),
    ):
        # ffmpeg isn't patched: _ffmpeg_binary now degrades gracefully when the
        # component/binary is absent, so setup must work regardless.
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_entry_setup_creates_entities_with_states(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, HaikuboxCoordinator)

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    # 14 sensors + 1 binary sensor.
    assert len(entities) == 15
    assert sum(e.domain == "sensor" for e in entities) == 14
    assert sum(e.domain == "binary_sensor" for e in entities) == 1

    def _state(unique_suffix: str) -> str:
        uid = f"{SERIAL}_{unique_suffix}"
        ent = next(e for e in entities if e.unique_id == uid)
        return hass.states.get(ent.entity_id).state

    # Today's true volume is the sum of the per-species /daily-count.
    assert _state("daily_count") == str(sum(_TODAY_COUNTS.values()))  # "166"
    # Two species in the 1-hour window (Robin 15m, Cardinal 50m; Owl is 600m).
    assert _state("recent_detections") == "2"
    # The sticky last-detection carries the most recent species.
    assert _state("last_detection") == "American Robin"


async def test_unload_entry(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_entry_cleans_storage(hass: HomeAssistant, hass_storage) -> None:
    # PHACC mocks Store I/O in-memory via hass_storage, so assert on that.
    entry = await _setup_entry(hass)
    prefix = f"{DOMAIN}.{SERIAL}."
    assert [k for k in hass_storage if k.startswith(prefix)]  # stores persisted

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    # async_remove_entry removed this box's per-serial stores
    assert not [k for k in hass_storage if k.startswith(prefix)]


async def test_entry_setup_without_ffmpeg(hass: HomeAssistant) -> None:
    """Setup succeeds when ffmpeg is unavailable (regression for the crash where
    _ffmpeg_binary let get_ffmpeg_manager's ValueError escape __init__)."""
    with patch(
        "custom_components.haikubox.coordinator._ffmpeg_binary", return_value=None
    ):
        entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, HaikuboxCoordinator)
