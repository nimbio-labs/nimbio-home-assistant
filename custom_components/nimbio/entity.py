"""Shared entity base classes."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LatchState, NimbioCoordinator


class NimbioLatchEntity(CoordinatorEntity[NimbioCoordinator]):
    """Base for entities bound to one community latch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NimbioCoordinator, latch_id: str) -> None:
        super().__init__(coordinator)
        self._latch_id = latch_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, latch_id)},
            name=self.latch.name or "Nimbio Latch",
            manufacturer="Nimbio",
        )

    @property
    def latch(self) -> LatchState:
        return self.coordinator.data.latches[self._latch_id]

    @property
    def available(self) -> bool:
        return (super().available
                and self._latch_id in self.coordinator.data.latches
                and not self.latch.offline)
