"""Tests for bats.py: telling bats from birds by code and by name."""

from __future__ import annotations

import pytest

from custom_components.haikubox import bats
from custom_components.haikubox.bats import (
    BAT,
    BIRD,
    classification,
    is_bat_code,
    is_bat_name,
    name_key,
    split_counts,
    split_detections,
)


@pytest.fixture(autouse=True)
def bundled_names(monkeypatch):
    monkeypatch.setattr(bats, "_BAT_NAMES", bats._read_bat_names())


def test_bundled_list_covers_the_codes_haikubox_reports() -> None:
    names = bats._read_bat_names()
    assert len(names) == 46
    # Species reported by a real bat-capable box, by name.
    for name in ("Fringed myotis", "Big brown bat", "Brazilian free-tailed bat"):
        assert name_key(name) in names


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("MYOTHY", True),     # NABat code
        ("batbatbat", True),  # unidentified bat
        ("amerob", False),    # eBird code
        ("belkin1", False),   # eBird code with a digit
        ("AMEROB1", False),   # not six letters
        ("", False),
        (None, False),
    ],
)
def test_is_bat_code(code, expected) -> None:
    assert is_bat_code(code) is expected


def test_name_key_ignores_case_apostrophes_and_spacing() -> None:
    assert name_key("Townsend’s Big-Eared  Bat") == name_key("Townsend's big-eared bat")


@pytest.mark.parametrize(
    ("name", "learned", "expected"),
    [
        ("Long-Eared Myotis", {}, True),         # bundled, Haikubox's capitalisation
        ("Bat", {}, True),                       # generic
        ("Mystery Bat", {"Mystery Bat": "MYSBAT"}, True),  # learned from /detections
        ("American Robin", {"American Robin": "amerob"}, False),
        ("Batis", {}, False),                    # not a bat just because it starts "Bat"
        ("", {}, False),
    ],
)
def test_is_bat_name(name, learned, expected) -> None:
    assert is_bat_name(name, learned) is expected


def test_classification() -> None:
    assert classification("MYOEVO") == BAT
    assert classification("amerob") == BIRD
    assert classification(None) == BIRD


def test_split_detections() -> None:
    raw = {"detections": [
        {"cn": "American Robin", "spCode": "amerob"},
        {"cn": "Fringed Myotis", "spCode": "MYOTHY"},
        {"cn": "Bat", "spCode": "batbatbat"},
        "not a dict",
    ]}
    birds, found_bats = split_detections(raw)
    assert [d["cn"] for d in found_bats["detections"]] == ["Fringed Myotis", "Bat"]
    assert [d["cn"] for d in birds["detections"] if isinstance(d, dict)] == ["American Robin"]


@pytest.mark.parametrize("raw", [None, [], {"detections": "nope"}])
def test_split_detections_tolerates_bad_payloads(raw) -> None:
    assert split_detections(raw) == ({"detections": []}, {"detections": []})


def test_split_counts() -> None:
    birds, found_bats = split_counts(
        {"American Robin": 10, "Bat": 4, "California Myotis": 2},
        lambda sp: is_bat_name(sp, {}),
    )
    assert birds == {"American Robin": 10}
    assert found_bats == {"Bat": 4, "California Myotis": 2}
