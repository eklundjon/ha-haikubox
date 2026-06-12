"""Helpers for building a HaikuboxCoordinator in unit tests.

The coordinator does all the real work, but its __init__ wires up an aiohttp
session, Store objects, image/audio caches and the DataUpdateCoordinator base.
For unit tests we bypass __init__ (via __new__) and set just the attributes the
method under test touches — the same approach scripts/coordinator_smoke.py uses
to drive _async_update_data deterministically.
"""

from __future__ import annotations

from datetime import UTC
from types import SimpleNamespace
from typing import Any

from custom_components.haikubox.coordinator import HaikuboxCoordinator

_STORE_ATTRS = (
    "_store",
    "_sp_codes_store",
    "_sci_names_store",
    "_last_seen_store",
    "_daily_store",
    "_events_store",
)


class FakeStore:
    """A Store that loads nothing and silently accepts saves/removes."""

    async def async_load(self) -> Any:
        return None

    async def async_save(self, data: Any) -> None:
        return None

    async def async_remove(self) -> None:
        return None


class FakeImages:
    """An ImageCache stand-in that resolves URLs without touching disk."""

    async def async_init(self) -> None:
        return None

    def url_for(self, sp_code: str | None) -> str | None:
        return f"/haikubox/cache/{sp_code}.jpeg" if sp_code else None

    async def async_fetch(self, sp_code: str) -> str:
        return f"/haikubox/cache/{sp_code}.jpeg"


def make_coordinator(hass, *, config_entry=None, options=None, **attrs):
    """Build a coordinator via __new__ with deterministic fakes.

    Pass `options` for a throwaway config entry, or `config_entry` to use a real
    one (needed when a test registers the device, e.g. for event firing). Any
    extra keyword overrides a default attribute (e.g. ``serial=...``).
    """
    c = HaikuboxCoordinator.__new__(HaikuboxCoordinator)
    c.hass = hass
    c.serial = "TESTSERIAL"
    c.device_name = "Test Box"
    c.config_entry = config_entry or SimpleNamespace(options=options or {})
    c._box_tz = UTC
    c._images = FakeImages()
    c._audio = None
    c._audio_enabled = False
    c._latest_wav_by_species = {}
    c._event_buffer = []
    c._prev_recent_species = None
    c._reconciled_once = False
    c._seen_species = {}
    c._sp_codes = {}
    c._sci_names = {}
    c._last_seen = {}
    c._baseline_ranks = {}
    c._baseline_species_count = 0
    c._baseline_items = []
    c._daily_counts = {}
    c._backfill_complete = False
    c._backfill_cursor = None
    c._backfill_misses = 0
    c._stats_imported_date = None
    for attr in _STORE_ATTRS:
        setattr(c, attr, FakeStore())
    for key, value in attrs.items():
        setattr(c, key, value)
    return c
