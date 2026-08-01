"""Every community latch gets an always-pressable Open button — including
latches that already render as a cover/lock (the frontend disables a cover's
open arrow while the state reads open, and gate status can lag)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.nimbio.button import async_setup_entry
from custom_components.nimbio.const import DOMAIN
from custom_components.nimbio.coordinator import (
    LatchState,
    NimbioCoordinator,
    NimbioData,
)
from custom_components.nimbio.cover import NimbioGateCover


def _coordinator(hass: HomeAssistant) -> NimbioCoordinator:
    coord = NimbioCoordinator(
        hass, client=None, key_type="community",
        capabilities=["open", "gate_status"], poll_seconds=900)
    data = NimbioData()
    data.latches["sensed"] = LatchState(
        latch_id="sensed", name="Main Gate", status="Open",
        possible_statuses=[{"status": "Open", "transient": False},
                           {"status": "Closed", "transient": False}])
    data.latches["blind"] = LatchState(latch_id="blind", name="E2E Latch")
    coord.async_set_updated_data(data)
    return coord


async def _buttons(hass: HomeAssistant, coord):
    entry = SimpleNamespace(entry_id="test-entry")
    hass.data.setdefault(DOMAIN, {})["test-entry"] = SimpleNamespace(
        coordinator=coord)
    added = []
    await async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    return added


@pytest.mark.asyncio
async def test_every_latch_gets_an_open_button(hass: HomeAssistant):
    buttons = await _buttons(hass, _coordinator(hass))
    assert {b._latch_id for b in buttons} == {"sensed", "blind"}


@pytest.mark.asyncio
async def test_button_naming_primary_vs_secondary(hass: HomeAssistant):
    buttons = {b._latch_id: b for b in await _buttons(hass, _coordinator(hass))}
    # Sensing-less latch: the button is the sole control and carries the
    # device name.
    assert buttons["blind"]._attr_name is None
    # Sensed latch: the cover carries the device name, so the button must
    # NOT also be device-named — HA's Entity._name_internal returns
    # _attr_name whenever it is set and ignores translation_key, so a
    # reinstated `_attr_name = None` would ship two entities called
    # "Main Gate" on one device.
    sensed = buttons["sensed"]
    assert getattr(sensed, "_attr_name", "unset") == "unset"
    assert sensed._attr_translation_key == "open_gate"


@pytest.mark.asyncio
async def test_controls_stay_available_when_latch_reads_offline(hass: HomeAssistant):
    # The offline flag rides the same laggy status feed the controls exist
    # to distrust — a stale offline reading must not disable them, and all
    # controls on a device must agree (a cover that goes unavailable is
    # dead to automations even though the button still works).
    coord = _coordinator(hass)
    coord.data.latches["sensed"].offline = True
    buttons = {b._latch_id: b for b in await _buttons(hass, coord)}
    assert buttons["sensed"].available is True
    cover = NimbioGateCover(coord, "sensed")
    assert cover.available is True
    # ...but a control that also carries sensed state must report unknown
    # rather than the frozen last reading.
    assert cover.is_closed is None
    assert cover.is_opening is False


@pytest.mark.asyncio
async def test_press_refreshes_coordinator(hass: HomeAssistant):
    # Without the refresh the cover on the same device keeps reporting its
    # pre-open state until a webhook lands or the poll interval elapses.
    coord = _coordinator(hass)
    coord.client = SimpleNamespace(
        community=SimpleNamespace(open=AsyncMock()))
    coord.async_request_refresh = AsyncMock()
    buttons = {b._latch_id: b for b in await _buttons(hass, coord)}
    await buttons["sensed"].async_press()
    coord.client.community.open.assert_awaited_once_with("sensed")
    coord.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_cover_open_control_is_never_disabled(hass: HomeAssistant):
    # assumed_state keeps the frontend from greying out the open arrow while
    # the (possibly lagging) state reads open.
    cover = NimbioGateCover(_coordinator(hass), "sensed")
    assert cover.assumed_state is True
