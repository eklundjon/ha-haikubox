from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import HaikuboxCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HaikuboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    serial = entry.data[CONF_SERIAL]

    async_add_entities(
        [
            HaikuboxRecentDetectionsSensor(coordinator, serial),
            HaikuboxLastDetectedSensor(coordinator, serial),
            HaikuboxDailyCountSensor(coordinator, serial),
            HaikuboxDailySpeciesSensor(coordinator, serial),
            HaikuboxNotableDetectionSensor(coordinator, serial),
            HaikuboxNewSpeciesSensor(coordinator, serial),
            HaikuboxYearlyTopSensor(coordinator, serial),
            HaikuboxDailyTopSensor(coordinator, serial),
            HaikuboxSevenDayRareSensor(coordinator, serial),
        ]
    )


class _HaikuboxSensor(CoordinatorEntity[HaikuboxCoordinator], SensorEntity):
    """Base class for Haikubox sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self.coordinator.device_name,
            manufacturer="Haikubox",
            model="Haikubox",
        )


class HaikuboxRecentDetectionsSensor(_HaikuboxSensor):
    """Number of species detected in the past hour."""

    _attr_translation_key = "recent_detections"
    _attr_icon = "mdi:bird"
    _attr_native_unit_of_measurement = "species"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_recent_detections"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("detections", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "detections": self.coordinator.data.get("detections", []),
        }


class HaikuboxLastDetectedSensor(_HaikuboxSensor):
    """Name of the most recently detected species."""

    _attr_translation_key = "last_detected"
    _attr_icon = "mdi:bird"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_last_detected"

    def _latest(self) -> dict | None:
        return self.coordinator.data.get("last_detected")

    @property
    def native_value(self) -> str | None:
        d = self._latest()
        return d.get("species") if d else None

    @property
    def entity_picture(self) -> str | None:
        d = self._latest()
        return d.get("image_url") if d else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self._latest()
        if not d:
            return {}
        return {
            "scientific_name": d.get("scientific_name"),
            "sp_code": d.get("sp_code"),
            "last_seen": d.get("last_seen"),
            "image_url": d.get("image_url"),
        }


class HaikuboxDailyCountSensor(_HaikuboxSensor):
    """Total individual detections recorded today."""

    _attr_translation_key = "daily_count"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "detections"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_daily_count"

    @property
    def native_value(self) -> int:
        return sum(
            s.get("count", 0) for s in self.coordinator.data.get("daily_count", [])
        )

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "species_counts": self.coordinator.data.get("daily_count", []),
        }


class HaikuboxDailySpeciesSensor(_HaikuboxSensor):
    """Number of distinct species heard today."""

    _attr_translation_key = "daily_species"
    _attr_icon = "mdi:bird"
    _attr_native_unit_of_measurement = "species"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_daily_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("daily_count", []))


class HaikuboxNotableDetectionSensor(_HaikuboxSensor):
    """Most unusual species detected in the recent window.

    Rarity is measured against this box's own yearly baseline — a species
    ranked low (or absent) in the yearly top-75 scores close to 1.0.
    State persists after the detection window empties.
    """

    _attr_translation_key = "notable_detection"
    _attr_icon = "mdi:bird-off"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_notable_detection"

    def _top(self) -> dict | None:
        return self.coordinator.data.get("last_notable")

    @property
    def native_value(self) -> str | None:
        d = self._top()
        return d.get("species") if d else None

    @property
    def entity_picture(self) -> str | None:
        d = self._top()
        return d.get("image_url") if d else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self._top()
        base: dict = {
            "notable_detections": self.coordinator.data.get("notable_detections", []),
        }
        if d:
            base.update({
                "scientific_name": d.get("scientific_name"),
                "sp_code": d.get("sp_code"),
                "last_seen": d.get("last_seen"),
                "rarity_score": d.get("rarity_score"),
                "yearly_rank": d.get("yearly_rank"),
                "image_url": d.get("image_url"),
            })
        return base


class HaikuboxNewSpeciesSensor(_HaikuboxSensor):
    """Tracks species never previously detected on this Haikubox.

    State: common name of the most recently first-detected species.
    First-detection log is persisted across HA restarts in
    .storage/haikubox.<serial>.seen_species.
    """

    _attr_translation_key = "new_species"
    _attr_icon = "mdi:new-box"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_new_species"

    def _new(self) -> list[dict]:
        return self.coordinator.data.get("new_species", [])

    @property
    def native_value(self) -> str | None:
        new = self._new()
        return new[0].get("species") if new else None

    @property
    def entity_picture(self) -> str | None:
        new = self._new()
        return new[0].get("image_url") if new else None

    @property
    def extra_state_attributes(self) -> dict:
        new = self._new()
        return {
            "new_today": [
                {
                    "species": d.get("species"),
                    "scientific_name": d.get("scientific_name"),
                    "sp_code": d.get("sp_code"),
                    "first_seen": d.get("first_seen") or d.get("last_seen"),
                    "image_url": d.get("image_url"),
                }
                for d in new
            ],
            "lifetime_species_count": self.coordinator.data.get("lifetime_species_count", 0),
        }


class HaikuboxYearlyTopSensor(_HaikuboxSensor):
    """Top species by detection count for the current calendar year."""

    _attr_translation_key = "yearly_top"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_yearly_top"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("yearly_top", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"items": self.coordinator.data.get("yearly_top", [])}


class HaikuboxDailyTopSensor(_HaikuboxSensor):
    """Top species by detection count for today."""

    _attr_translation_key = "daily_top"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_daily_top"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("daily_top", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"items": self.coordinator.data.get("daily_top", [])}


class HaikuboxSevenDayRareSensor(_HaikuboxSensor):
    """Species with the highest rarity score seen in the rolling 7-day window."""

    _attr_translation_key = "seven_day_rare"
    _attr_icon = "mdi:star-shooting"
    _attr_native_unit_of_measurement = "species"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_seven_day_rare"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("seven_day_rare", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"items": self.coordinator.data.get("seven_day_rare", [])}
