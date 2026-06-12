from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HaikuboxCoordinator


class HaikuboxEntity(CoordinatorEntity[HaikuboxCoordinator]):
    """Base for every Haikubox entity (sensors + the binary sensor).

    Holds the single DeviceInfo so the platform files don't each repeat it.
    """

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
            # Shown on the owner's OWN device page (fine). This is not the same
            # as the diagnostics dump, where the serial is redacted because that
            # gets pasted into public bug reports.
            serial_number=self._serial,
            # One-click link to the box's public Haikubox page. Sharing is a
            # setup prerequisite, so this resolves for every configured box.
            configuration_url=f"https://birds.haikubox.com/listen/{self._serial}",
        )
