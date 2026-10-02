"""Telling bats from birds.

Haikubox's bat-capable boxes report bats through the same public endpoints and
in the same shape as birds, with no field saying which is which. Two things
tell them apart:

  * **Species codes.** Birds carry lowercase eBird codes (`amerob`); bats carry
    the uppercase NABat six-letter codes (`MYOTHY`), and an unidentified bat
    is "Bat" with the code `batbatbat`.
  * **Names**, for /daily-count, which gives common names only: the bundled
    USGS list of North American bats (data/bat_species.json), plus "Bat", plus
    any name the integration has learned a bat code for from /detections.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BIRD = "bird"
BAT = "bat"

GENERIC_BAT_CODE = "batbatbat"
GENERIC_BAT_NAME = "Bat"

# Name keys of the bundled bat list, loaded once off the event loop.
_BAT_NAMES: frozenset[str] | None = None


def name_key(name: str) -> str:
    """Comparison key for a common name: Haikubox writes "Long-Eared Myotis"
    and "Townsend's" where the USGS list has "Long-eared myotis" and
    "Townsend’s", so ignore case, apostrophe style and spacing."""
    return " ".join(name.replace("’", "'").casefold().split())


def is_bat_code(sp_code: str | None) -> bool:
    """A NABat code (six uppercase letters) or the generic bat code."""
    if not sp_code:
        return False
    return sp_code == GENERIC_BAT_CODE or (
        len(sp_code) == 6 and sp_code.isalpha() and sp_code.isupper()
    )


def _read_bat_names() -> frozenset[str]:
    """Blocking read of the bundled bat list. Call only via the executor."""
    path = Path(__file__).parent / "data" / "bat_species.json"
    try:
        species = json.loads(path.read_text(encoding="utf-8")).get("species", [])
    except (OSError, ValueError):
        _LOGGER.warning("Could not load bundled bat species list")
        species = []
    return frozenset(name_key(s["common"]) for s in species if s.get("common"))


async def async_load_bat_names(hass: HomeAssistant) -> None:
    """Populate the bundled bat-name cache once, off the event loop."""
    global _BAT_NAMES
    if _BAT_NAMES is None:
        _BAT_NAMES = await hass.async_add_executor_job(_read_bat_names)


def is_bat_name(name: str | None, learned_codes: Mapping[str, str]) -> bool:
    """Whether a common name is a bat: one we've seen with a bat code, the
    generic "Bat", or a name on the bundled USGS list."""
    if not name:
        return False
    if is_bat_code(learned_codes.get(name)):
        return True
    key = name_key(name)
    return key == name_key(GENERIC_BAT_NAME) or key in (_BAT_NAMES or ())


def classification(sp_code: str | None) -> str:
    """BIRD or BAT for a /detections item, from its species code."""
    return BAT if is_bat_code(sp_code) else BIRD


def split_detections(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a /detections payload into (birds, bats), each in the same
    `{"detections": [...]}` shape the normalizers expect. Anything that isn't
    a well-formed item stays with the birds, which already ignore it."""
    items = raw.get("detections", []) if isinstance(raw, dict) else []
    if not isinstance(items, list):
        items = []
    birds, bats = [], []
    for item in items:
        is_bat = isinstance(item, dict) and is_bat_code(item.get("spCode"))
        (bats if is_bat else birds).append(item)
    return {"detections": birds}, {"detections": bats}


def split_counts(
    counts: Mapping[str, int], is_bat: Callable[[str], bool]
) -> tuple[dict[str, int], dict[str, int]]:
    """Split a {species: count} map into (birds, bats)."""
    birds: dict[str, int] = {}
    bats: dict[str, int] = {}
    for species, count in counts.items():
        (bats if is_bat(species) else birds)[species] = count
    return birds, bats
