from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    AUDIO_NORM_MAX_GAIN_DB,
    AUDIO_SILENCE_FLOOR_DB,
    DEFAULT_AUDIO_NORM_TARGET,
)

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

    Clips are namespaced per box under `audio/<serial>/`, so each box's
    retention window and clip cap are independent and removing one box's cache
    never disturbs another's (unlike the image cache, which holds global
    Haikubox assets shared across boxes).
    """

    @staticmethod
    def dir_for(hass: HomeAssistant, serial: str) -> Path:
        """The per-box audio cache directory (`www/haikubox/audio/<serial>`)."""
        return Path(hass.config.path("www", "haikubox", "audio", serial))

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        serial: str,
        ffmpeg_bin: str | None = None,
        norm_target_db: float = DEFAULT_AUDIO_NORM_TARGET,
    ) -> None:
        self._hass = hass
        self._session = session
        self._serial = serial
        self._ffmpeg = ffmpeg_bin
        self._norm_target = norm_target_db
        self._dir: Path = self.dir_for(hass, serial)
        self._cached: set[str] = set()
        # Clips found to have no real signal (peak < AUDIO_SILENCE_FLOOR_DB) —
        # remembered so we don't re-download them every poll. Not persisted, so a
        # silent clip is re-checked once after a restart.
        self._silent: set[str] = set()

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
            return f"/local/haikubox/audio/{self._serial}/{cid}.flac"
        return None

    async def async_fetch(self, wav_url: str | None) -> str | None:
        """Download the clip if needed; return its /local URL (None on failure)."""
        cid = self.clip_id(wav_url)
        if not cid:
            return None
        if cid in self._cached:
            return f"/local/haikubox/audio/{self._serial}/{cid}.flac"
        if cid in self._silent:
            return None  # known to have no real signal; don't re-download
        try:
            async with self._session.get(wav_url) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Audio clip fetch HTTP %s", resp.status)
                    return None
                data = await resp.read()
            path = self._dir / f"{cid}.flac"
            async with aiofiles.open(path, "wb") as f:
                await f.write(data)
        except (aiohttp.ClientError, OSError) as err:
            _LOGGER.debug("Could not cache audio clip: %s", err)
            return None
        if self._ffmpeg:
            peak = await self._measure_peak(path)
            if peak is not None and peak < AUDIO_SILENCE_FLOOR_DB:
                # No real signal — treat the clip as missing so the card shows no
                # play button (better than a "Playing…" state with no output).
                self._silent.add(cid)
                await self._hass.async_add_executor_job(self._unlink, path)
                return None
            await self._normalize(path, peak)
        self._cached.add(cid)
        return f"/local/haikubox/audio/{self._serial}/{cid}.flac"

    async def _normalize(self, path: Path, peak: float | None) -> None:
        """Peak-normalize a freshly cached clip in place (best-effort).

        Detection clips are often very quiet, so faint calls are inaudible at the
        raw level. We apply a *per-file* gain to bring the clip's peak to the
        configured target (self._norm_target, so loud clips aren't blown out),
        capping the boost at AUDIO_NORM_MAX_GAIN_DB so a near-silent clip isn't
        amplified into full-scale noise. `peak` is the clip's measured max_volume
        (dBFS) from async_fetch. Any failure leaves the raw clip untouched;
        re-running on an already-normalized clip computes ~0 gain and skips
        (idempotent).
        """
        if peak is None:
            return
        try:
            gain = min(self._norm_target - peak, AUDIO_NORM_MAX_GAIN_DB)
            if abs(gain) < 0.5:
                return  # already at target
            tmp = path.with_name(f"{path.stem}.norm.flac")
            code = await self._run_ffmpeg(
                "-y", "-i", str(path), "-af", f"volume={gain:.1f}dB",
                "-c:a", "flac", str(tmp),
            )
            await self._hass.async_add_executor_job(self._swap_norm, tmp, path, code == 0)
        except (OSError, ValueError) as err:
            _LOGGER.debug("Audio normalize failed: %s", err)

    async def _measure_peak(self, path: Path) -> float | None:
        """Return the clip's max_volume in dBFS via ffmpeg volumedetect."""
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg, "-hide_banner", "-nostdin",
            "-i", str(path), "-af", "volumedetect", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        for line in stderr.decode("utf-8", "replace").splitlines():
            if "max_volume:" in line:
                try:
                    return float(line.split("max_volume:")[1].split("dB")[0])
                except (IndexError, ValueError):
                    return None
        return None

    async def _run_ffmpeg(self, *args: str) -> int | None:
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg, "-hide_banner", "-nostdin", *args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode

    @staticmethod
    def _swap_norm(tmp: Path, path: Path, ok: bool) -> None:
        """Replace the raw clip with the normalized temp on success, else drop it."""
        try:
            if ok and tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, path)
                return
        except OSError:
            pass
        try:
            tmp.unlink()
        except OSError:
            pass

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
