from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
import aiofiles

from homeassistant.core import HomeAssistant

from .const import CACHE_DIR_NAME, CACHE_URL_BASE, IMAGES_BASE

_LOGGER = logging.getLogger(__name__)


class ImageCache:
    """Downloads species photos once and serves them from the integration's
    own static path (see CACHE_URL_BASE) rather than HA's /local.

    An in-memory index of cached sp_codes is built once at startup so
    URL lookups never touch the filesystem afterwards.
    """

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession) -> None:
        self._hass = hass
        self._session = session
        self._dir: Path = Path(hass.config.path(CACHE_DIR_NAME))
        self._cached: set[str] = set()

    async def async_init(self) -> None:
        """Create the cache dir and index existing files (one executor hop)."""
        await self._hass.async_add_executor_job(self._index)

    def _index(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for p in self._dir.glob("*.jpeg"):
            self._cached.add(p.stem)

    def url_for(self, sp_code: str) -> str | None:
        """Local cached image URL if available, else the remote S3 URL.

        Mirrors async_fetch's fallback so the list cards show the photo
        instead of a placeholder before it has been cached locally. None
        only when there is no species code at all.
        """
        if not sp_code:
            return None
        if sp_code in self._cached:
            return f"{CACHE_URL_BASE}/{sp_code}.jpeg"
        return f"{IMAGES_BASE}/{sp_code}.jpeg"

    async def async_fetch(self, sp_code: str) -> str:
        """Return a URL for the species image, downloading it if needed."""
        if sp_code in self._cached:
            return f"{CACHE_URL_BASE}/{sp_code}.jpeg"

        local_path = self._dir / f"{sp_code}.jpeg"
        url = f"{IMAGES_BASE}/{sp_code}.jpeg"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(local_path, "wb") as f:
                        await f.write(data)
                    self._cached.add(sp_code)
                else:
                    _LOGGER.debug("No image for %s (HTTP %s)", sp_code, resp.status)
                    return url
        except aiohttp.ClientError as err:
            _LOGGER.debug("Could not cache image for %s: %s", sp_code, err)
            return url
        return f"{CACHE_URL_BASE}/{sp_code}.jpeg"
