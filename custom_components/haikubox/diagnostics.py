from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_NAME, CONF_SERIAL
from .coordinator import HaikuboxConfigEntry

# The serial identifies the physical device; redact it from diagnostics shared
# in bug reports. entry.as_dict() exposes it in several places, so redact them
# all: data[serial], the unique_id (which IS the serial), and title /
# device_name (both fall back to f"Haikubox {serial}" when the box reports no
# name). async_redact_data matches these keys at any depth.
TO_REDACT = {CONF_SERIAL, CONF_DEVICE_NAME, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HaikuboxConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "baseline_species_count": coordinator.baseline_species_count,
            "lifetime_species_count": coordinator.lifetime_species_count,
        },
        "data": coordinator.data,
    }
