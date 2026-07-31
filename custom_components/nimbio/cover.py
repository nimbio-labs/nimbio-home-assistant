"""Gate covers — latches whose configured vocabulary is the open/closed family."""
from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    LATCH_CLASS_COVER,
    classify_latch,
    status_is_closed,
    status_is_moving,
)
from .entity import NimbioLatchEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    if coordinator.data is None:
        return
    entities = [
        NimbioGateCover(coordinator, latch_id)
        for latch_id, latch in coordinator.data.latches.items()
        if classify_latch(latch.possible_statuses) == LATCH_CLASS_COVER
    ]
    async_add_entities(entities)


class NimbioGateCover(NimbioLatchEntity, CoverEntity):
    """A gate with sensed open/closed state. Opening fires a latch open."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_name = None  # entity carries the device name
    # Never grey out the open control: the frontend disables a cover's open
    # button once the state reads open, but gate status arrives with sensing/
    # webhook lag and gates auto-close on their own — a member must always be
    # able to fire an open.
    _attr_assumed_state = True

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_gate"

    @property
    def is_closed(self) -> bool | None:
        return status_is_closed(self.latch.status)

    @property
    def is_opening(self) -> bool:
        # The sense line reports a single Moving state without direction.
        return status_is_moving(self.latch.status)

    @property
    def extra_state_attributes(self):
        return {"nimbio_status": self.latch.status,
                "latch_id": self._latch_id}

    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.client.community.open(self._latch_id)
        await self.coordinator.async_request_refresh()
