"""Tests for the long-term statistics backfill (_import_history_statistics)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from .coordinator_helpers import make_coordinator

_ADD_STATS = (
    "homeassistant.components.recorder.statistics.async_add_external_statistics"
)


async def test_builds_detection_and_species_series(hass: HomeAssistant) -> None:
    c = make_coordinator(hass)
    c.serial = "10000000A684860E"  # uppercase -> lowercased in the statistic_id
    c.device_name = "Bird Shazam"
    c._daily_counts = {
        "2026-05-30": {"Robin": 5, "Owl": 1},
        "2026-05-31": {"Robin": 8},
    }

    with patch(_ADD_STATS) as mock_add:
        await c._import_history_statistics()

    assert mock_add.call_count == 2

    # detections series — metadata + a cumulative sum
    _, det_meta, det_stats = mock_add.call_args_list[0].args
    assert det_meta["statistic_id"] == "haikubox:box_10000000a684860e_daily_detections"
    assert det_meta["has_sum"] is True
    assert det_meta["unit_of_measurement"] == "detections"
    assert [s["state"] for s in det_stats] == [6.0, 8.0]
    assert [s["sum"] for s in det_stats] == [6.0, 14.0]  # cumulative

    # species series — daily richness as the mean
    _, sp_meta, sp_stats = mock_add.call_args_list[1].args
    assert sp_meta["statistic_id"] == "haikubox:box_10000000a684860e_daily_species"
    assert [s["mean"] for s in sp_stats] == [2.0, 1.0]


async def test_noop_when_no_history(hass: HomeAssistant) -> None:
    c = make_coordinator(hass)
    c._daily_counts = {}
    with patch(_ADD_STATS) as mock_add:
        await c._import_history_statistics()
    mock_add.assert_not_called()


async def test_skips_unparseable_day_keys(hass: HomeAssistant) -> None:
    c = make_coordinator(hass)
    c._daily_counts = {"not-a-date": {"Robin": 5}, "2026-05-31": {"Robin": 8}}
    with patch(_ADD_STATS) as mock_add:
        await c._import_history_statistics()
    _, _, det_stats = mock_add.call_args_list[0].args
    assert len(det_stats) == 1  # only the valid day
