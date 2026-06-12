"""Tests for box-timezone resolution (used for box-local day boundaries)."""

from __future__ import annotations

from datetime import UTC

import aiohttp
from homeassistant.core import HomeAssistant

from .coordinator_helpers import make_coordinator


class _Resp:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        return None

    async def json(self):
        return self._body


class _Session:
    def __init__(self, body: dict | None = None, exc: Exception | None = None):
        self._body = body
        self._exc = exc

    def get(self, url, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _Resp(self._body or {})


async def test_box_tz_returns_cached_without_fetching(hass: HomeAssistant) -> None:
    """A resolved tz is reused; the endpoint isn't hit again."""

    c = make_coordinator(hass)
    c._box_tz = UTC
    # session would raise if touched — proves the cache short-circuits.
    c._session = _Session(exc=aiohttp.ClientError("should not be called"))
    assert await c._async_box_tz() is UTC


async def test_box_tz_resolves_from_api(hass: HomeAssistant) -> None:
    c = make_coordinator(hass)
    c._box_tz = None
    c._session = _Session(body={"tz": "America/Chicago"})

    tz = await c._async_box_tz()
    assert tz is not None
    assert getattr(tz, "key", str(tz)) == "America/Chicago"
    # and it's cached
    assert c._box_tz is tz


async def test_box_tz_falls_back_to_none_on_error(hass: HomeAssistant) -> None:
    c = make_coordinator(hass)
    c._box_tz = None
    c._session = _Session(exc=aiohttp.ClientError("boom"))
    assert await c._async_box_tz() is None
