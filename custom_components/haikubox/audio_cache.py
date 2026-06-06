from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import aiohttp

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AudioCache:
    """Downloads detection audio clips and serves them from /local/.

    Haikubox's `/detections` `wav` is a short FLAC behind an AWS *presigned*
    URL that expires in ~1 hour. Caching the clip locally makes "play the call"
    robust (survives expiry + restarts) and keeps the signed URL — which embeds
    a temporary AWS token — out of HA state entirely (we serve a /local path).

    Clips are keyed by a hash of the S3 object *path* (the query/signature
    changes every fetch, the path doesn't), so the same detection maps to the
    same cached file across polls. Bounded by a retention window + a hard cap;
    an in-memory index of cached ids avoids re-downloading.
    """

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession) -> None:
        self._hass = hass
        self._session = session
        self._dir: Path = Path(hass.config.path("www", "haikubox", "audio"))
        self._cached: set[str] = set()

    async def async_init(self) -> None:
        """Create the cache dir and index existing files (one executor hop)."""
        await self._hass.async_add_executor_job(self._index)

    def _index(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for p in self._dir.glob("*.flac"):
            self._cached.add(p.stem)

    @staticmethod
    def clip_id(wav_url: str | None) -> str | None:
        """Stable id for a clip from its presigned URL (hash of the object path)."""
        if not wav_url:
            return None
        path = urlparse(wav_url).path
        return hashlib.sha1(path.encode()).hexdigest()[:16] if path else None

    def url_for(self, wav_url: str | None) -> str | None:
        """Local /local URL if the clip is already cached, else None.

        Pure lookup (no download), so it cheaply resolves audio for *every*
        record — clips cached on an earlier poll resolve too.
        """
        cid = self.clip_id(wav_url)
        if cid and cid in self._cached:
            return f"/local/haikubox/audio/{cid}.flac"
        return None

    async def async_fetch(self, wav_url: str | None) -> str | None:
        """Download the clip if needed; return its /local URL (None on failure)."""
        cid = self.clip_id(wav_url)
        if not cid:
            return None
        if cid in self._cached:
            return f"/local/haikubox/audio/{cid}.flac"
        try:
            async with self._session.get(wav_url) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Audio clip fetch HTTP %s", resp.status)
                    return None
                data = await resp.read()
            async with aiofiles.open(self._dir / f"{cid}.flac", "wb") as f:
                await f.write(data)
        except (aiohttp.ClientError, OSError) as err:
            _LOGGER.debug("Could not cache audio clip: %s", err)
            return None
        self._cached.add(cid)
        return f"/local/haikubox/audio/{cid}.flac"

    async def async_prune(self, max_age_days: int, max_clips: int) -> None:
        """Delete clips older than max_age_days, then trim to max_clips (oldest first)."""
        await self._hass.async_add_executor_job(self._prune, max_age_days, max_clips)

    def _prune(self, max_age_days: int, max_clips: int) -> None:
        cutoff = time.time() - max_age_days * 86400
        kept: list[tuple[float, Path]] = []
        for p in self._dir.glob("*.flac"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                self._unlink(p)
            else:
                kept.append((mtime, p))
        if len(kept) > max_clips:
            kept.sort()  # oldest first
            for _, p in kept[: len(kept) - max_clips]:
                self._unlink(p)

    def _unlink(self, p: Path) -> None:
        try:
            p.unlink()
            self._cached.discard(p.stem)
        except OSError:
            pass
