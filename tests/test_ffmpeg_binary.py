"""Tests for _ffmpeg_binary's graceful fallback when ffmpeg isn't available.

_ffmpeg_binary does a local `from homeassistant.components.ffmpeg import
get_ffmpeg_manager`. That module needs the `haffmpeg` library, which isn't in
the test environment, so we inject a fake module into sys.modules to drive
get_ffmpeg_manager's behaviour directly.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

from custom_components.haikubox.coordinator import _ffmpeg_binary

_FFMPEG_MOD = "homeassistant.components.ffmpeg"


def _fake_ffmpeg_module(get_manager):
    mod = ModuleType(_FFMPEG_MOD)
    mod.get_ffmpeg_manager = get_manager
    return mod


def test_uses_ffmpeg_component_when_available() -> None:
    manager = type("_Mgr", (), {"binary": "/opt/ffmpeg"})()
    fake = _fake_ffmpeg_module(lambda hass: manager)
    with patch.dict(sys.modules, {_FFMPEG_MOD: fake}):
        assert _ffmpeg_binary(None) == "/opt/ffmpeg"


def test_falls_back_to_path_when_component_not_initialized() -> None:
    # get_ffmpeg_manager raises ValueError when the ffmpeg component isn't set
    # up (it's only an after-dependency). We must not let that propagate — it
    # would fail the whole coordinator construction.
    def _boom(hass):
        raise ValueError("ffmpeg component not initialized")

    fake = _fake_ffmpeg_module(_boom)
    with (
        patch.dict(sys.modules, {_FFMPEG_MOD: fake}),
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
    ):
        assert _ffmpeg_binary(None) == "/usr/bin/ffmpeg"


def test_returns_none_when_ffmpeg_entirely_absent() -> None:
    def _boom(hass):
        raise ValueError("ffmpeg component not initialized")

    fake = _fake_ffmpeg_module(_boom)
    with (
        patch.dict(sys.modules, {_FFMPEG_MOD: fake}),
        patch("shutil.which", return_value=None),
    ):
        assert _ffmpeg_binary(None) is None
