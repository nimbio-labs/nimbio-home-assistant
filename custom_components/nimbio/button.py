"""Open buttons.

Two sources:
- Community keys: EVERY latch gets one — for sensing-less latches it is the
  primary (and only) control; for latches that also render as a cover/lock it
  is an always-pressable "Open", because the frontend disables a cover's open
  arrow while the state reads open and gate status can lag.
- Account (member) keys: one button per (key, latch) — the member surface has
  no status feed, so buttons are the whole experience.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LATCH_CLASS_BUTTON, classify_latch
from .coordinator import NimbioCoordinator
from .entity import NimbioLatchControlEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: NimbioCoordinator = runtime.coordinator
    if coordinator.data is None:
        return

    entities: list[ButtonEntity] = []
    if coordinator.key_type == "community":
        entities += [
            NimbioCommunityOpenButton(
                coordinator, latch_id,
                primary=classify_latch(latch.possible_statuses)
                == LATCH_CLASS_BUTTON)
            for latch_id, latch in coordinator.data.latches.items()
        ]
    else:
        for key in coordinator.data.account_keys:
            if key.disabled or key.pending or key.id is None:
                continue
            for latch in key.latches:
                if latch.id is not None:
                    entities.append(
                        NimbioAccountOpenButton(coordinator, key, latch))
    async_add_entities(entities)


class NimbioCommunityOpenButton(NimbioLatchControlEntity, ButtonEntity):
    """Open a community latch — always pressable regardless of gate state."""

    def __init__(self, coordinator, latch_id: str, primary: bool = True) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_open"
        if primary:
            # Sole control for this latch: carry the device name.
            self._attr_name = None
        else:
            # The latch also has a cover/lock entity carrying the device
            # name; this one is named "Open".
            self._attr_translation_key = "open_gate"

    async def async_press(self) -> None:
        await self.coordinator.client.community.open(self._latch_id)
        # Same refresh the cover/lock controls do — without it the gate
        # entity on this device keeps reporting its pre-open state until a
        # webhook lands or the poll interval elapses.
        await self.coordinator.async_request_refresh()


class NimbioAccountOpenButton(CoordinatorEntity[NimbioCoordinator], ButtonEntity):
    """Open one of the member's own latches through one of their keys."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: NimbioCoordinator, key, latch) -> None:
        super().__init__(coordinator)
        self._key_id = key.id
        self._latch_id = latch.id
        self._attr_unique_id = f"{key.id}_{latch.id}_open"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{key.id}_{latch.id}")},
            name=f"{latch.name or 'Latch'} ({key.name or 'Key'})",
            manufacturer="Nimbio",
        )

    async def async_press(self) -> None:
        await self.coordinator.client.account.open(self._key_id, self._latch_id)
