"""Tests for diagnostics redaction."""

from __future__ import annotations

import json
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox.const import CONF_DEVICE_NAME, CONF_SERIAL, DOMAIN
from custom_components.haikubox.diagnostics import (
    async_get_config_entry_diagnostics,
)

SERIAL = "100000003d7c9f2b"


async def test_diagnostics_redacts_every_serial_bearing_field(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title=f"Haikubox {SERIAL}",  # fallback title embeds the serial
        data={CONF_SERIAL: SERIAL, CONF_DEVICE_NAME: f"Haikubox {SERIAL}"},
        options={"audio_enabled": True},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        last_update_success=True,
        baseline_species_count=42,
        lifetime_species_count=87,
        data={"recent_detections": []},
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # The serial must not survive anywhere in the dump.
    assert SERIAL not in json.dumps(diag, default=str)
    e = diag["entry"]
    assert e["data"][CONF_SERIAL] == "**REDACTED**"
    assert e["data"][CONF_DEVICE_NAME] == "**REDACTED**"
    assert e["unique_id"] == "**REDACTED**"
    assert e["title"] == "**REDACTED**"
    # Non-sensitive options pass through.
    assert e["options"] == {"audio_enabled": True}

    # Coordinator summary + data are included.
    assert diag["coordinator"]["baseline_species_count"] == 42
    assert diag["coordinator"]["lifetime_species_count"] == 87
    assert diag["data"] == {"recent_detections": []}
