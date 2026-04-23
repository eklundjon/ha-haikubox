from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL, DOMAIN
from .coordinator import HaikuboxCoordinator

# The serial number identifies the physical device; redact it from
# diagnostics shared in bug reports.
TO_REDACT = {CONF_SERIAL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: HaikuboxCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "yearly_fetched_date": str(coordinator.yearly_fetched_date),
            "yearly_species_count": coordinator.yearly_total,
            "lifetime_species_count": coordinator.lifetime_species_count,
        },
        "data": coordinator.data,
    }
