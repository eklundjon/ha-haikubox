"""Tests for the Haikubox config flow."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox import config_flow
from custom_components.haikubox.const import (
    API_BASE,
    CONF_DEVICE_NAME,
    CONF_SERIAL,
    DOMAIN,
)

SERIAL = "100000003d7c9f2b"
DEVICE_URL = f"{API_BASE}/haikubox/{SERIAL}"
_PATCH_SETUP = "custom_components.haikubox.async_setup"
_PATCH_SETUP_ENTRY = "custom_components.haikubox.async_setup_entry"


# --------------------------------------------------------------------------- #
# _get_device_info — the HTTP layer that the flow maps to errors
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status = status
        self._body = body or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._body


class _FakeSession:
    def __init__(self, resp: _FakeResp | None = None, exc: Exception | None = None):
        self._resp = resp
        self._exc = exc

    def get(self, url: str):
        if self._exc is not None:
            raise self._exc
        return self._resp


async def test_get_device_info_ok() -> None:
    """A 200 returns the parsed device info."""
    with patch.object(
        config_flow,
        "async_get_clientsession",
        lambda hass: _FakeSession(_FakeResp(200, {"haikuboxName": "Bird Shazam"})),
    ):
        info = await config_flow._get_device_info(None, SERIAL)
    assert info == {"haikuboxName": "Bird Shazam"}


async def test_get_device_info_rejected_returns_none() -> None:
    """A non-200 (unknown serial / box not shared) returns None."""
    with patch.object(
        config_flow,
        "async_get_clientsession",
        lambda hass: _FakeSession(_FakeResp(404)),
    ):
        info = await config_flow._get_device_info(None, SERIAL)
    assert info is None


async def test_get_device_info_network_error_raises() -> None:
    """A transport error raises _CannotConnect (vs. None for a rejection)."""
    with patch.object(
        config_flow,
        "async_get_clientsession",
        lambda hass: _FakeSession(exc=aiohttp.ClientError("boom")),
    ):
        try:
            await config_flow._get_device_info(None, SERIAL)
        except config_flow._CannotConnect:
            pass
        else:  # pragma: no cover - explicit failure
            raise AssertionError("_CannotConnect was not raised")


# --------------------------------------------------------------------------- #
# User step
# --------------------------------------------------------------------------- #


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """Happy path: a valid, shared serial creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(
            "custom_components.haikubox.config_flow._get_device_info",
            return_value={"haikuboxName": "Bird Shazam"},
        ),
        patch(_PATCH_SETUP, return_value=True),
        patch(_PATCH_SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL: SERIAL}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bird Shazam"
    assert result["data"] == {
        CONF_SERIAL: SERIAL,
        CONF_DEVICE_NAME: "Bird Shazam",
    }


async def test_user_flow_falls_back_to_serial_name(hass: HomeAssistant) -> None:
    """When the API reports no name, the device name falls back to the serial."""
    with (
        patch(
            "custom_components.haikubox.config_flow._get_device_info",
            return_value={},  # no haikuboxName
        ),
        patch(_PATCH_SETUP, return_value=True),
        patch(_PATCH_SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL: SERIAL}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_NAME] == f"Haikubox {SERIAL}"


async def test_user_flow_invalid_serial(hass: HomeAssistant) -> None:
    """A rejected serial (None) surfaces as invalid_serial, not cannot_connect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.haikubox.config_flow._get_device_info",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL: SERIAL}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_serial"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A transport failure surfaces as cannot_connect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.haikubox.config_flow._get_device_info",
        side_effect=config_flow._CannotConnect,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL: SERIAL}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """A serial that's already set up aborts before any API call."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_SERIAL: SERIAL}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    # _abort_if_unique_id_configured runs before _get_device_info, so no mock
    # is needed — assert it aborts without hitting the network.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERIAL: SERIAL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --------------------------------------------------------------------------- #
# Reconfigure step
# --------------------------------------------------------------------------- #


async def test_reconfigure_updates_entry(hass: HomeAssistant) -> None:
    """Reconfigure with the same serial validates and reloads the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_SERIAL: SERIAL, CONF_DEVICE_NAME: "Old Name"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with (
        patch(
            "custom_components.haikubox.config_flow._get_device_info",
            return_value={"haikuboxName": "Bird Shazam"},
        ),
        patch(_PATCH_SETUP, return_value=True),
        patch(_PATCH_SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL: SERIAL}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_DEVICE_NAME] == "Bird Shazam"
