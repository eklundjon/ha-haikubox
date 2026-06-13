"""Tests for the Haikubox API client and the device-info probe."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.haikubox import api
from custom_components.haikubox.api import CannotConnect, HaikuboxApiClient

SERIAL = "100000003d7c9f2b"


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
    def __init__(self, resp: _Resp | None = None, exc: Exception | None = None):
        self._resp = resp
        self._exc = exc

    def get(self, url, params=None):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _client(resp: _Resp | None = None, exc: Exception | None = None) -> HaikuboxApiClient:
    return HaikuboxApiClient(_Session(resp, exc), SERIAL)


# ---- fetch_daily_count: the 404 vs empty contract ------------------------- #


async def test_daily_count_404_is_none() -> None:
    # None signals "before the box existed" (the backfill floor).
    assert await _client(_Resp(status=404)).fetch_daily_count("2026-06-01") is None


async def test_daily_count_parses_list() -> None:
    c = _client(_Resp(payload=[{"bird": "Robin", "count": 5}, {"bird": "Owl", "count": "2"}]))
    assert await c.fetch_daily_count("2026-06-01") == {"Robin": 5, "Owl": 2}


async def test_daily_count_empty_list_is_empty_dict() -> None:
    assert await _client(_Resp(payload=[])).fetch_daily_count("2026-06-01") == {}


async def test_daily_count_non_list_is_empty_dict() -> None:
    c = _client(_Resp(payload={"unexpected": "shape"}))
    assert await c.fetch_daily_count("2026-06-01") == {}


async def test_daily_count_bad_json_is_empty_dict() -> None:
    assert await _client(_Resp(json_exc=ValueError("x"))).fetch_daily_count("d") == {}


async def test_daily_count_skips_entries_without_bird() -> None:
    c = _client(_Resp(payload=[{"bird": "Robin", "count": 3}, {"count": 9}, {"bird": ""}]))
    assert await c.fetch_daily_count("2026-06-01") == {"Robin": 3}


async def test_daily_count_raises_on_5xx() -> None:
    with pytest.raises(aiohttp.ClientResponseError):
        await _client(_Resp(status=503)).fetch_daily_count("2026-06-01")


# ---- fetch_detections ------------------------------------------------------ #


async def test_fetch_detections_returns_payload() -> None:
    payload = {"detections": [{"cn": "Robin", "spCode": "amerob"}]}
    assert await _client(_Resp(payload=payload)).fetch_detections(24) == payload


# ---- async_box_tz ---------------------------------------------------------- #


async def test_box_tz_cached_without_fetching() -> None:
    c = _client(exc=aiohttp.ClientError("should not be called"))
    c._box_tz = UTC
    assert await c.async_box_tz() is UTC


async def test_box_tz_resolves_from_api() -> None:
    c = _client(_Resp(payload={"tz": "America/Chicago"}))
    tz = await c.async_box_tz()
    assert tz is not None
    assert getattr(tz, "key", str(tz)) == "America/Chicago"
    assert c.box_tz is tz  # cached


async def test_box_tz_none_on_error() -> None:
    assert await _client(exc=aiohttp.ClientError("boom")).async_box_tz() is None


# ---- async_get_device_info (config-flow probe) ----------------------------- #


async def test_device_info_ok() -> None:
    with patch.object(
        api, "async_get_clientsession",
        lambda hass: _Session(_Resp(payload={"haikuboxName": "Bird Shazam"})),
    ):
        assert await api.async_get_device_info(None, SERIAL) == {
            "haikuboxName": "Bird Shazam"
        }


async def test_device_info_rejected_returns_none() -> None:
    with patch.object(
        api, "async_get_clientsession", lambda hass: _Session(_Resp(status=404))
    ):
        assert await api.async_get_device_info(None, SERIAL) is None


async def test_device_info_network_error_raises() -> None:
    with patch.object(
        api, "async_get_clientsession",
        lambda hass: _Session(exc=aiohttp.ClientError("boom")),
    ):
        with pytest.raises(CannotConnect):
            await api.async_get_device_info(None, SERIAL)
