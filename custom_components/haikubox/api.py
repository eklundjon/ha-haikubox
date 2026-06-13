"""HTTP access to the Haikubox API.

All network calls to api.haikubox.com live here: the per-box polling client
(detections, daily counts, the box timezone) and the one-shot device-info probe
used by the config flow.
"""

from __future__ import annotations

import logging
from datetime import tzinfo
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """The Haikubox API could not be reached (network/transport failure)."""


async def async_get_device_info(hass: HomeAssistant, serial: str) -> dict | None:
    """Fetch the box's device info from the API (config-flow setup probe).

    Returns the info dict for a valid, shared box. Returns ``None`` when the API
    answers but rejects the serial (unknown serial, or a box that isn't shared).
    Raises ``CannotConnect`` on a network/transport failure (no answer at all),
    so the caller can tell "fix your serial/sharing" from "check your network".
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{API_BASE}/haikubox/{serial}") as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except aiohttp.ClientError as err:
        raise CannotConnect from err


class HaikuboxApiClient:
    """Per-box HTTP client: detections, daily counts, and the box timezone."""

    def __init__(self, session: aiohttp.ClientSession, serial: str) -> None:
        self._session = session
        self._serial = serial
        self._box_tz: tzinfo | None = None

    @property
    def box_tz(self) -> tzinfo | None:
        """The resolved box timezone, or None until the first lookup succeeds."""
        return self._box_tz

    async def async_box_tz(self) -> tzinfo | None:
        """The box's own timezone, from the box-info endpoint (cached).

        Resolved once and reused. Returns ``None`` until the lookup succeeds, in
        which case callers fall back to Home Assistant's configured tz. Day-
        boundary math needs the *box's* local day because /daily-count is keyed
        to it, and the box can live in a different timezone than the HA host.
        """
        if self._box_tz is not None:
            return self._box_tz
        try:
            async with self._session.get(f"{API_BASE}/haikubox/{self._serial}") as resp:
                resp.raise_for_status()
                info = await resp.json()
            name = (info or {}).get("tz")
            if name:
                self._box_tz = await dt_util.async_get_time_zone(name)
        except (aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug(
                "Could not resolve box timezone (falling back to HA tz): %s", err
            )
        return self._box_tz

    async def fetch_detections(self, hours: int) -> Any:
        url = f"{API_BASE}/haikubox/{self._serial}/detections"
        async with self._session.get(url, params={"hours": hours}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def fetch_daily_count(self, date_str: str) -> dict[str, int] | None:
        """One calendar day's per-species counts as {species: count}.

        Returns **None only for a 404** — a date before the box existed, the
        backfill floor signal. A 200 with an empty or unparseable body returns
        `{}` ("the day exists, just no data"), which the backfill treats as a
        recorded no-data day rather than a floor hit. This distinction is what
        lets an in-history outage gap (offline days) be told apart from the
        pre-install void.
        """
        url = f"{API_BASE}/haikubox/{self._serial}/daily-count"
        async with self._session.get(url, params={"date": date_str}) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            try:
                data = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                return {}
        if not isinstance(data, list):
            return {}
        out: dict[str, int] = {}
        for item in data:
            if isinstance(item, dict) and item.get("bird"):
                out[item["bird"]] = int(item.get("count") or 0)
        return out
