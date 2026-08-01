"""Locks — latches whose configured vocabulary is Locked/Unlocked."""
from __future__ import annotations

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LATCH_CLASS_LOCK, classify_latch
from .entity import NimbioLatchControlEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    if coordinator.data is None:
        return
    async_add_entities(
        NimbioLock(coordinator, latch_id)
        for latch_id, latch in coordinator.data.latches.items()
        if classify_latch(latch.possible_statuses) == LATCH_CLASS_LOCK
    )


class NimbioLock(NimbioLatchControlEntity, LockEntity):
    """A door with sensed Locked/Unlocked state. `open` fires the latch —
    there is no remote re-lock (doors relock themselves)."""

    _attr_supported_features = LockEntityFeature.OPEN
    _attr_name = None

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_lock"

    @property
    def is_locked(self) -> bool | None:
        # Offline = frozen feed; report unknown rather than a stale state.
        # The entity stays available so `open` still works (see
        # NimbioLatchControlEntity), but it must not claim a lock state it
        # can no longer observe.
        if self.latch.offline:
            return None
        status = (self.latch.status or "").strip().lower()
        if status == "locked":
            return True
        if status == "unlocked":
            return False
        return None

    @property
    def extra_state_attributes(self):
        return {"nimbio_status": self.latch.status,
                "latch_id": self._latch_id}

    async def async_open(self, **kwargs) -> None:
        await self.coordinator.client.community.open(self._latch_id)
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs) -> None:
        await self.async_open(**kwargs)

    async def async_lock(self, **kwargs) -> None:
        raise NotImplementedError("Nimbio latches relock themselves")
