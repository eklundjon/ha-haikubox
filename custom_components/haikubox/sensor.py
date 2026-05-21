from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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

    async_add_entities(
        [
            HaikuboxRecentDetectionsSensor(coordinator, serial),
            HaikuboxLastDetectionSensor(coordinator, serial),
            HaikuboxDailyCountSensor(coordinator, serial),
            HaikuboxDailyTopSpeciesSensor(coordinator, serial),
            HaikuboxNotableSpeciesSensor(coordinator, serial),
            HaikuboxNewSpeciesSensor(coordinator, serial),
            HaikuboxYearlyTopSpeciesSensor(coordinator, serial),
            HaikuboxRarestSpeciesSensor(coordinator, serial),
        ]
    )


class _HaikuboxSensor(CoordinatorEntity[HaikuboxCoordinator], SensorEntity):
    """Base class for Haikubox sensors."""

    _attr_has_entity_name = True

    # Every listy sensor exposes its list under `detections`. It stays on
    # the live state object so the cards can read it, but the recorder must
    # not persist it on every state change — it can run to dozens of rows
    # with images/scientific names and would bloat the history DB and trip
    # HA's state-attribute size warnings.
    _unrecorded_attributes = frozenset({"detections"})

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
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_recent_detections"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("recent_detections", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "detections": self.coordinator.data.get("recent_detections", []),
        }


class HaikuboxLastDetectionSensor(_HaikuboxSensor):
    """Name of the most recently detected species."""

    _attr_translation_key = "last_detection"
    _attr_icon = "mdi:bird"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_last_detection"

    def _latest(self) -> dict | None:
        return self.coordinator.data.get("last_detection")

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
        # `detections` is per-event (one record per individual detection
        # in the trailing 24h, capped at LAST_DETECTION_EVENT_LIMIT), in
        # contrast to recent_detections.detections which is per-species.
        # Same attribute name; same field shape per record; different
        # records-per-X semantic. The bird card reads detections[0] for
        # rich data — no top-level scientific_name/sp_code/last_seen/
        # image_url duplicates needed.
        return {"detections": self.coordinator.data.get("recent_events", [])}


class HaikuboxDailyCountSensor(_HaikuboxSensor):
    """Total individual detections over the trailing 24 hours."""

    _attr_translation_key = "daily_count"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "detections"
    # Rolling 24h total: rises and falls as the window slides, so it is a
    # MEASUREMENT, not a TOTAL_INCREASING counter (which would treat every
    # decrease as a meter reset and corrupt long-term statistics).
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_daily_count"

    # Pure total counter — the 24h species list lives on daily_top_species.
    @property
    def native_value(self) -> int:
        return sum(
            s.get("count", 0) for s in self.coordinator.data.get("daily_count", [])
        )


class HaikuboxDailyTopSpeciesSensor(_HaikuboxSensor):
    """Top species by detection count over the trailing 24 hours."""

    _attr_translation_key = "daily_top_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_daily_top_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("daily_top_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("daily_top_species", [])}


class HaikuboxNotableSpeciesSensor(_HaikuboxSensor):
    """Most unusual species detected in the recent window.

    Rarity is measured against this box's own yearly baseline — a species
    ranked low (or absent) in the yearly top-75 scores close to 1.0.
    State persists after the detection window empties.
    """

    _attr_translation_key = "notable_species"
    _attr_icon = "mdi:bird-off"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_notable_species"

    def _top(self) -> dict | None:
        return self.coordinator.data.get("notable_detection")

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
        # rarity_score / yearly_rank are kept as scalars even though they
        # also live on detections[0] — they're this sensor's signature
        # metrics for the current top entry and convenient for templates.
        # All other per-record fields are reachable via detections[0].
        d = self._top()
        attrs: dict = {
            "detections": self.coordinator.data.get("notable_detections", []),
        }
        if d:
            attrs["rarity_score"] = d.get("rarity_score")
            attrs["yearly_rank"] = d.get("yearly_rank")
        return attrs


class HaikuboxNewSpeciesSensor(_HaikuboxSensor):
    """Tracks species never previously detected on this Haikubox.

    State: common name of the species with the most recent first
    detection. Derived from the persisted seen_species log, so the value
    is sticky across polls and survives HA restarts.
    """

    _attr_translation_key = "new_species"
    _attr_icon = "mdi:new-box"

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_new_species"

    def _latest(self) -> dict | None:
        return self.coordinator.data.get("new_detection")

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
        # `detections` is a sticky lifetime-history list: the N most
        # recently first-seen species, newest first. Capped at
        # NEW_SPECIES_HISTORY_LIMIT. Populated as soon as the box has any
        # species; head of the list is the sensor's sticky state.
        # lifetime_species_count is a sensor-level scalar (not a list
        # field); first_seen is the meaningful "discovered on" date for
        # the current top entry. Everything else lives on detections[0].
        d = self._latest()
        attrs: dict = {
            "detections": self.coordinator.data.get("new_detections", []),
            "lifetime_species_count": self.coordinator.data.get("lifetime_species_count", 0),
        }
        if d:
            attrs["first_seen"] = d.get("first_seen") or d.get("last_seen")
        return attrs


class HaikuboxYearlyTopSpeciesSensor(_HaikuboxSensor):
    """Top species by detection count this calendar year."""

    _attr_translation_key = "yearly_top_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_yearly_top_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("yearly_top_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("yearly_top_species", [])}


class HaikuboxRarestSpeciesSensor(_HaikuboxSensor):
    """Rarest species over the rolling 7-day window (highest rarity score)."""

    _attr_translation_key = "rarest_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HaikuboxCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_rarest_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("rarest_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("rarest_species", [])}
