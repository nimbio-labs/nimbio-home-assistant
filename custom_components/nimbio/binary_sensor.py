"""Binary sensors: held-open (any source), box connectivity, malfunction."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, status_is_problem
from .entity import NimbioLatchEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    if coordinator.data is None or coordinator.key_type != "community":
        return
    entities: list[BinarySensorEntity] = []
    for latch_id, latch in coordinator.data.latches.items():
        entities.append(NimbioConnectivitySensor(coordinator, latch_id))
        entities.append(NimbioProblemSensor(coordinator, latch_id))
        # Held-open only where the hold-opens payload covers the latch
        # (the backend skips latches without a timezone).
        if coordinator.data.hold_opens_available and latch.hold_open_capable:
            entities.append(NimbioHeldOpenSensor(coordinator, latch_id))
    async_add_entities(entities)


class NimbioHeldOpenSensor(NimbioLatchEntity, BinarySensorEntity):
    """On when ANY hold-open source (manual/event/recurring) is active."""

    _attr_translation_key = "held_open"

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_held_open"

    @property
    def is_on(self) -> bool:
        return self.latch.held_open


class NimbioConnectivitySensor(NimbioLatchEntity, BinarySensorEntity):
    """On when the latch's box is reachable."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "box_online"

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_online"

    @property
    def available(self) -> bool:
        # Deliberately not gated on latch.offline — this sensor IS the
        # offline indicator.
        return (self.coordinator.last_update_success
                and self._latch_id in self.coordinator.data.latches)

    @property
    def is_on(self) -> bool:
        return not self.latch.offline


class NimbioProblemSensor(NimbioLatchEntity, BinarySensorEntity):
    """On when the sensed status reports a malfunction."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "malfunction"

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_malfunction"

    @property
    def is_on(self) -> bool:
        return status_is_problem(self.latch.status)
