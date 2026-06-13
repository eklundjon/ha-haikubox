"""Tests for AudioCache behaviour without ffmpeg."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from custom_components.haikubox.audio_cache import AudioCache

SERIAL = "100000003d7c9f2b"
_MARKER = "ffmpeg is unavailable"


async def test_async_init_warns_when_ffmpeg_missing(
    hass: HomeAssistant, caplog
) -> None:
    cache = AudioCache(hass, None, SERIAL, ffmpeg_bin=None)
    with caplog.at_level(logging.WARNING):
        await cache.async_init()
    assert _MARKER in caplog.text


async def test_async_init_silent_when_ffmpeg_present(
    hass: HomeAssistant, caplog
) -> None:
    cache = AudioCache(hass, None, SERIAL, ffmpeg_bin="/usr/bin/ffmpeg")
    with caplog.at_level(logging.WARNING):
        await cache.async_init()
    assert _MARKER not in caplog.text
