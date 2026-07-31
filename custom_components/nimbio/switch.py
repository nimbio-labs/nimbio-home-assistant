"""Manual (indefinite) hold-open switches.

The switch mirrors the *indefinite* hold-open state — server-side this is the
CM portal's "Hold Open Now → Indefinite" window, so a hold started here shows
on the portal's Hold Opens page (endable there with "End Hold Open") and vice
versa. `held_open` (any source — indefinite, one-time window, recurring
schedule) is a separate binary sensor, so turning this switch off never
silently fights an active scheduled window.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import NimbioLatchControlEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    if coordinator.data is None or not coordinator.data.hold_opens_available:
        return
    # Only latches the hold-opens payload actually covers: the backend skips
    # latches without a timezone, and a switch for one of those would accept
    # toggles that never physically act.
    async_add_entities(
        NimbioManualHoldOpenSwitch(coordinator, latch_id)
        for latch_id, latch in coordinator.data.latches.items()
        if latch.hold_open_capable
    )


class NimbioManualHoldOpenSwitch(NimbioLatchControlEntity, SwitchEntity):
    """On = the manual hold open is active for this latch."""

    _attr_translation_key = "manual_hold_open"

    def __init__(self, coordinator, latch_id: str) -> None:
        super().__init__(coordinator, latch_id)
        self._attr_unique_id = f"{latch_id}_manual_hold_open"

    @property
    def is_on(self) -> bool:
        return self.latch.manual_hold_open

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.community.set_hold_open(
            self._latch_id, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.community.set_hold_open(
            self._latch_id, False)
        await self.coordinator.async_request_refresh()
