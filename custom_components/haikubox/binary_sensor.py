from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import HaikuboxConfigEntry, HaikuboxCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaikuboxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    serial = entry.data[CONF_SERIAL]
    async_add_entities([HaikuboxExtendedSilenceSensor(coordinator, serial)])


class HaikuboxExtendedSilenceSensor(
    CoordinatorEntity[HaikuboxCoordinator], BinarySensorEntity
):
    """Problem sensor: on when the box has logged no detections in the
    trailing 24-hour window (an "extended silence").

    An outdoor Haikubox going a full day with zero recognised detections
    almost always means a real problem — the box is offline, unpowered, or
    its microphone/connection has failed — rather than a genuinely silent
    day. Surfacing it as a PROBLEM binary sensor lets users alert on it
    directly instead of inferring it from an empty card.

    Derived from the 24-hour `detections_24h` list the coordinator already
    produces (empty list → no detections in 24 h). When the poll itself
    fails the coordinator goes unavailable, so this sensor is unavailable
    too — "we don't know" rather than a false problem.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "extended_silence"
    # Device-health signal (is the box alive?), not a bird observation — so it
    # belongs in the device's Diagnostic section. Still fully usable in
    # automations/alerts; entity_id and history are unchanged.
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_extended_silence"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self.coordinator.device_name,
            manufacturer="Haikubox",
            model="Haikubox",
        )

    @property
    def is_on(self) -> bool:
        # PROBLEM semantics: on = something's wrong = nothing detected in 24 h.
        return not (self.coordinator.data.get("detections_24h") or [])
