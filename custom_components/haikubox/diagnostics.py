from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL
from .coordinator import HaikuboxConfigEntry

# The serial number identifies the physical device; redact it from
# diagnostics shared in bug reports.
TO_REDACT = {CONF_SERIAL}


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
