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
                and self.coordinator.data is not None
                and self._latch_id in self.coordinator.data.latches
                and not self.latch.offline)


class NimbioLatchControlEntity(NimbioLatchEntity):
    """Base for entities that ACT on a latch (open, hold open).

    Controls deliberately drop the `offline` gate that read-only entities
    keep. The offline flag rides the same delayed status feed as gate
    state, so a stale reading would disable every way to open the gate at
    exactly the moment the user needs it — and an unavailable entity is
    dead to automations and scripts too, not merely greyed out. Sensors
    still go unavailable (their data genuinely is stale) and the "Box
    online" binary sensor remains the honest connectivity signal; the
    server rejects an open for a truly unreachable box.

    Controls that ALSO carry sensed state (cover, lock) must not exploit
    this to keep reporting that state: staying available is about the
    control remaining usable, not about the reading still being true. Those
    classes return None (unknown) for their state while offline, and blank
    the raw status they expose as an attribute — gating one without the
    other leaves the stale value reachable from a template.
    """

    @property
    def available(self) -> bool:
        return (self.coordinator.last_update_success
                and self.coordinator.data is not None
                and self._latch_id in self.coordinator.data.latches)
