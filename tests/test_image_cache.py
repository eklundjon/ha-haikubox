"""Tests for ImageCache.async_fetch (download / cache / fallback)."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant

from custom_components.haikubox.const import CACHE_URL_BASE, IMAGES_BASE
from custom_components.haikubox.image_cache import ImageCache


class _Resp:
    def __init__(self, status: int, data: bytes = b""):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self) -> bytes:
        return self._data


class _Session:
    def __init__(self, resp: _Resp | None = None, exc: Exception | None = None):
        self._resp = resp
        self._exc = exc

    def get(self, url):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _fresh(hass: HomeAssistant, session) -> ImageCache:
    # The test config dir is shared/persistent; start from a clean image dir so
    # stale .jpeg files don't get indexed as already-cached.
    ic = ImageCache(hass, session)
    ic._dir.mkdir(parents=True, exist_ok=True)
    for p in ic._dir.glob("*.jpeg"):
        p.unlink()
    return ic


async def test_fetch_caches_on_200(hass: HomeAssistant) -> None:
    ic = _fresh(hass, _Session(_Resp(200, b"jpegbytes")))
    await ic.async_init()

    url = await ic.async_fetch("amerob")

    assert url == f"{CACHE_URL_BASE}/amerob.jpeg"
    assert "amerob" in ic._cached
    assert (ic._dir / "amerob.jpeg").read_bytes() == b"jpegbytes"


async def test_fetch_returns_remote_on_non_200(hass: HomeAssistant) -> None:
    ic = _fresh(hass, _Session(_Resp(404)))
    await ic.async_init()

    url = await ic.async_fetch("brdowl")

    assert url == f"{IMAGES_BASE}/brdowl.jpeg"  # not rewritten to local
    assert "brdowl" not in ic._cached


async def test_fetch_returns_remote_on_client_error(hass: HomeAssistant) -> None:
    ic = _fresh(hass, _Session(exc=aiohttp.ClientError("boom")))
    await ic.async_init()
    assert await ic.async_fetch("norcar") == f"{IMAGES_BASE}/norcar.jpeg"


async def test_fetch_uses_cache_second_time(hass: HomeAssistant) -> None:
    ic = _fresh(hass, _Session(_Resp(200, b"x")))
    await ic.async_init()
    assert await ic.async_fetch("amerob") == f"{CACHE_URL_BASE}/amerob.jpeg"

    # second call must resolve from the in-memory cache without the session
    ic._session = None
    assert await ic.async_fetch("amerob") == f"{CACHE_URL_BASE}/amerob.jpeg"
