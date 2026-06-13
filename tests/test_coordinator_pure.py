"""Tests for the coordinator's pure parsing/sanitizing helpers."""

from __future__ import annotations

from custom_components.haikubox.normalize import (
    _first_seen_per_species,
    _sanitize_daily_counts,
)


def test_first_seen_picks_earliest_and_skips_soundscape() -> None:
    raw = {
        "detections": [
            {"cn": "Robin", "spCode": "amerob", "dt": "2026-06-01T10:00:00Z"},
            {"cn": "Robin", "spCode": "amerob", "dt": "2026-06-01T08:00:00Z"},  # earlier
            {"cn": "soundscape", "spCode": "soundscape", "dt": "2026-06-01T07:00:00Z"},
            {"cn": "Owl", "spCode": "brdowl", "dt": "not-a-date"},  # unparseable
        ]
    }
    assert _first_seen_per_species(raw) == {"Robin": "2026-06-01T08:00:00Z"}


def test_first_seen_handles_bad_shapes() -> None:
    assert _first_seen_per_species(None) == {}
    assert _first_seen_per_species({"detections": "nope"}) == {}
    assert _first_seen_per_species({}) == {}


def test_sanitize_keeps_valid_and_coerces_counts() -> None:
    raw = {
        "2026-06-01": {"Robin": 5, "Owl": "2"},  # str count -> int
        "not-a-date": {"X": 1},  # bad date key dropped
        "2026-06-02": "not-a-dict",  # bad value dropped
        "2026-06-03": {"Robin": 3, 99: 1, "Bad": "x"},  # non-str key / bad count dropped
    }
    assert _sanitize_daily_counts(raw) == {
        "2026-06-01": {"Robin": 5, "Owl": 2},
        "2026-06-03": {"Robin": 3},
    }


def test_sanitize_non_dict_returns_empty() -> None:
    assert _sanitize_daily_counts("nope") == {}
    assert _sanitize_daily_counts(None) == {}
