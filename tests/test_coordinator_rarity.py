"""Tests for rarity ranking and the trailing-window baseline."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant

from custom_components.haikubox.const import CONF_RARITY_WINDOW_DAYS
from custom_components.haikubox.coordinator import (
    _apply_rarity_scores,
    _ranks_from_counts,
)

from .coordinator_helpers import make_coordinator


def test_ranks_from_counts_orders_by_count_desc() -> None:
    ranks, count, items = _ranks_from_counts({"Robin": 10, "Cardinal": 5, "Owl": 1})
    assert ranks == {"Robin": 1, "Cardinal": 2, "Owl": 3}
    assert count == 3
    assert [i["species"] for i in items] == ["Robin", "Cardinal", "Owl"]
    assert items[0] == {"species": "Robin", "count": 10, "rank": 1}


def test_ranks_from_counts_skips_blank_species() -> None:
    # A blank species name is dropped from the result (real names only ever
    # reach here — soundscape is filtered upstream). Note it still consumes a
    # rank slot, so a surviving species can land at rank 2; we assert only that
    # the blank is excluded, not the exact rank.
    ranks, count, items = _ranks_from_counts({"Robin": 3, "": 99})
    assert "" not in ranks
    assert list(ranks) == ["Robin"]
    assert count == 1
    assert [i["species"] for i in items] == ["Robin"]


def test_apply_rarity_scores_known_and_unknown() -> None:
    baseline = {"Robin": 1, "Cardinal": 2, "Owl": 3}
    detections = [
        {"species": "Robin"},  # most common -> low score
        {"species": "Owl"},  # rarest known -> 1.0
        {"species": "Mystery"},  # absent -> capped at the rarest known
    ]
    _apply_rarity_scores(detections, baseline, baseline_species_count=3)

    robin, owl, mystery = detections
    assert robin["yearly_rank"] == 1
    assert robin["rarity_score"] == round(1 / 3, 4)
    assert owl["yearly_rank"] == 3
    assert owl["rarity_score"] == 1.0
    # An unknown species ranks with the rarest known (rank == species count),
    # capping its score at 1.0 rather than overshooting.
    assert mystery["yearly_rank"] == 3
    assert mystery["rarity_score"] == 1.0


def test_apply_rarity_scores_empty_baseline_does_not_divide_by_zero() -> None:
    detections = [{"species": "Robin"}]
    _apply_rarity_scores(detections, {}, baseline_species_count=0)
    # denom is clamped to 1; an unknown species gets rank 0 -> score 0.0.
    assert detections[0]["yearly_rank"] == 0
    assert detections[0]["rarity_score"] == 0.0


async def test_rebuild_baseline_sums_window_and_excludes_old(
    hass: HomeAssistant,
) -> None:
    today = date(2026, 6, 1)
    c = make_coordinator(hass, options={CONF_RARITY_WINDOW_DAYS: 30})
    # Two in-window days plus one day outside the 30-day window.
    c._daily_counts = {
        (today - timedelta(days=2)).isoformat(): {"Robin": 5, "Owl": 1},
        (today - timedelta(days=5)).isoformat(): {"Robin": 3, "Cardinal": 4},
        (today - timedelta(days=400)).isoformat(): {"Owl": 999},  # excluded
    }
    c._rebuild_baseline(today)

    # Robin 8 (most common) > Cardinal 4 > Owl 1; the 400-day-old Owl is ignored.
    assert c._baseline_ranks == {"Robin": 1, "Cardinal": 2, "Owl": 3}
    assert c._baseline_species_count == 3
