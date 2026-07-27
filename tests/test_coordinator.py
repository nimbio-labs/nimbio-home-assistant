"""Coordinator webhook-patching behavior."""
import pytest
from homeassistant.core import HomeAssistant

from custom_components.nimbio.coordinator import (
    LatchState,
    NimbioCoordinator,
    NimbioData,
)


def _coordinator(hass: HomeAssistant) -> NimbioCoordinator:
    coord = NimbioCoordinator(
        hass, client=None, key_type="community",
        capabilities=["open", "gate_status", "hold_opens", "webhooks"],
        poll_seconds=900)
    data = NimbioData(hold_opens_available=True)
    data.latches["l1"] = LatchState(
        latch_id="l1", name="Front Gate", status="Closed",
        held_open=False, manual_hold_open=False)
    coord.async_set_updated_data(data)
    return coord


@pytest.mark.asyncio
async def test_sense_line_changed_patches_status(hass: HomeAssistant):
    coord = _coordinator(hass)
    coord.apply_webhook_event({
        "event": "sense_line.changed",
        "data": {"latch_id": "l1", "status_label": "Open", "transient": False},
    })
    assert coord.data.latches["l1"].status == "Open"


@pytest.mark.asyncio
async def test_hold_open_changed_patches_flags(hass: HomeAssistant):
    coord = _coordinator(hass)
    coord.apply_webhook_event({
        "event": "hold_open.changed",
        "data": {"latch_id": "l1", "held_open": True, "manual": True},
    })
    assert coord.data.latches["l1"].held_open is True
    assert coord.data.latches["l1"].manual_hold_open is True


@pytest.mark.asyncio
async def test_unknown_latch_is_ignored(hass: HomeAssistant):
    coord = _coordinator(hass)
    coord.apply_webhook_event({
        "event": "sense_line.changed",
        "data": {"latch_id": "does-not-exist", "status_label": "Open"},
    })
    assert coord.data.latches["l1"].status == "Closed"
