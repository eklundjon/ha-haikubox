"""Long-term statistics backfill (extracted from the coordinator).

Builds Home Assistant external statistics from the per-day counts store — no
API call. The recorder imports stay lazy (inside the function) so importing
this module doesn't pull in recorder internals unless a backfill actually runs.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN


async def async_import_history_statistics(
    hass: HomeAssistant,
    serial: str,
    device_name: str,
    daily_counts: dict[str, dict[str, int]],
    box_tz: tzinfo | None,
) -> None:
    """Backfill HA long-term statistics from the per-day counts store (no API
    call): detection totals (cumulative `sum` → the Statistics card shows
    detections per day/week/month) and species richness (daily `mean`), over the
    box's full recorded history. Each day is anchored at the box's local midnight
    (its /daily-count days are box-local). Idempotent on (statistic_id, day), so
    it also picks up days as the deep backfill keeps extending the store."""
    # Lazy imports: only pull in recorder internals when actually backfilling.
    from homeassistant.components.recorder.models import (  # noqa: PLC0415
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
        async_add_external_statistics,
    )

    # statistic_id must be lowercase (like an entity_id); some serials are
    # uppercase hex (e.g. 348518979FA0) → valid_statistic_id rejects them.
    sid = serial.lower()
    det_stats: list[StatisticData] = []
    sp_stats: list[StatisticData] = []
    cumulative = 0.0
    for day_str in sorted(daily_counts):
        try:
            day = date.fromisoformat(day_str)
        except (TypeError, ValueError):
            continue
        counts = daily_counts[day_str] or {}
        total = sum(counts.values())
        species = float(len(counts))
        start = (
            datetime(day.year, day.month, day.day, tzinfo=box_tz)
            if box_tz
            else dt_util.start_of_local_day(day)
        )
        cumulative += total
        det_stats.append(
            StatisticData(start=start, state=float(total), sum=cumulative)
        )
        sp_stats.append(
            StatisticData(start=start, mean=species, min=species, max=species)
        )
    if not det_stats:
        return

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_sum=True,
            has_mean=False,
            mean_type=StatisticMeanType.NONE,
            name=f"{device_name} daily detections",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:box_{sid}_daily_detections",
            unit_of_measurement="detections",
            unit_class=None,
        ),
        det_stats,
    )
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_sum=False,
            mean_type=StatisticMeanType.ARITHMETIC,
            name=f"{device_name} daily species",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:box_{sid}_daily_species",
            unit_of_measurement="species",
            unit_class=None,
        ),
        sp_stats,
    )
