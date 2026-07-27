"""Diagnostic sensors: API usage counters from /v1/me."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NimbioCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: NimbioCoordinator = runtime.coordinator
    async_add_entities([
        NimbioUsageSensor(coordinator, entry, "month_count", "quota_used"),
        NimbioUsageSensor(coordinator, entry, "month_limit", "quota_limit"),
    ])


class NimbioUsageSensor(CoordinatorEntity[NimbioCoordinator], SensorEntity):
    """One usage counter from the key's /v1/me payload."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "calls"

    def __init__(self, coordinator: NimbioCoordinator, entry: ConfigEntry,
                 field: str, translation_key: str) -> None:
        super().__init__(coordinator)
        self._field = field
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{field}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Nimbio API ({entry.title})",
            manufacturer="Nimbio",
        )

    @property
    def native_value(self):
        return (self.coordinator.data.usage or {}).get(self._field)
