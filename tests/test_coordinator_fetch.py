"""Tests for _fetch_daily_count / _fetch_detections response parsing.

The 404 -> None vs empty-200 -> {} distinction is the basis of the backfill's
pre-install floor, so it's worth pinning against real-shaped responses.
"""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from .coordinator_helpers import make_coordinator


class _Resp:
    def __init__(self, status=200, payload=None, json_exc=None):
        self.status = status
        self._payload = payload
        self._json_exc = json_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self, content_type=None):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


class _Session:
    def __init__(self, resp: _Resp):
        self._resp = resp

    def get(self, url, params=None):
        return self._resp


def _coord(hass, resp: _Resp):
    c = make_coordinator(hass)
    c._session = _Session(resp)
    return c


# ---- _fetch_daily_count ---------------------------------------------------- #


async def test_daily_count_404_is_none(hass: HomeAssistant) -> None:
    # None signals "before the box existed" (the backfill floor).
    c = _coord(hass, _Resp(status=404))
    assert await c._fetch_daily_count("2026-06-01") is None


async def test_daily_count_parses_list(hass: HomeAssistant) -> None:
    c = _coord(
        hass,
        _Resp(payload=[{"bird": "Robin", "count": 5}, {"bird": "Owl", "count": "2"}]),
    )
    assert await c._fetch_daily_count("2026-06-01") == {"Robin": 5, "Owl": 2}


async def test_daily_count_empty_list_is_empty_dict(hass: HomeAssistant) -> None:
    # A 200 with no data is "the day exists, just nothing" — not a floor hit.
    c = _coord(hass, _Resp(payload=[]))
    assert await c._fetch_daily_count("2026-06-01") == {}


async def test_daily_count_non_list_is_empty_dict(hass: HomeAssistant) -> None:
    c = _coord(hass, _Resp(payload={"unexpected": "shape"}))
    assert await c._fetch_daily_count("2026-06-01") == {}


async def test_daily_count_bad_json_is_empty_dict(hass: HomeAssistant) -> None:
    c = _coord(hass, _Resp(json_exc=ValueError("not json")))
    assert await c._fetch_daily_count("2026-06-01") == {}


async def test_daily_count_skips_entries_without_bird(hass: HomeAssistant) -> None:
    c = _coord(
        hass, _Resp(payload=[{"bird": "Robin", "count": 3}, {"count": 9}, {"bird": ""}])
    )
    assert await c._fetch_daily_count("2026-06-01") == {"Robin": 3}


async def test_daily_count_raises_on_5xx(hass: HomeAssistant) -> None:
    c = _coord(hass, _Resp(status=503))
    with pytest.raises(aiohttp.ClientResponseError):
        await c._fetch_daily_count("2026-06-01")


# ---- _fetch_detections ----------------------------------------------------- #


async def test_fetch_detections_returns_payload(hass: HomeAssistant) -> None:
    payload = {"detections": [{"cn": "Robin", "spCode": "amerob"}]}
    c = _coord(hass, _Resp(payload=payload))
    assert await c._fetch_detections(24) == payload
