"""Coordinator webhook-patching + refresh-resilience behavior."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

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


def _fake_gate(latch_id="l1", name="Front Gate", status="Closed"):
    p = SimpleNamespace(status="Open", transient=False)
    latch = SimpleNamespace(latch_id=latch_id, latch_name=name, status=status,
                            offline=False, possible_statuses=[p])
    return SimpleNamespace(latches=[latch])


def _fake_me():
    key = SimpleNamespace(minute_count=1, minute_limit=60,
                          month_count=2, month_limit=1000)
    return SimpleNamespace(key=key)


@pytest.mark.asyncio
async def test_transient_hold_opens_failure_keeps_previous_state(hass: HomeAssistant):
    # A blip on ONLY the hold-opens read must not reset held_open/manual to
    # False against physical reality.
    coord = _coordinator(hass)
    coord.data.latches["l1"].held_open = True
    coord.data.latches["l1"].manual_hold_open = True
    coord.data.latches["l1"].hold_open_timezone = "America/Los_Angeles"
    coord.data.latches["l1"].hold_open_capable = True

    coord.client = SimpleNamespace(
        community=SimpleNamespace(
            gate_status=AsyncMock(return_value=_fake_gate()),
            hold_opens=AsyncMock(side_effect=Exception("502 blip")),
        ),
        me=AsyncMock(return_value=_fake_me()),
    )
    data = await coord._fetch_community()
    assert data.hold_opens_available is True
    assert data.latches["l1"].held_open is True
    assert data.latches["l1"].manual_hold_open is True
    assert data.latches["l1"].hold_open_timezone == "America/Los_Angeles"
    assert data.latches["l1"].hold_open_capable is True


@pytest.mark.asyncio
async def test_hold_opens_disabled_is_feature_off(hass: HomeAssistant):
    coord = _coordinator(hass)
    err = Exception("Hold opens are disabled")
    err.code = "hold_opens_disabled"
    coord.client = SimpleNamespace(
        community=SimpleNamespace(
            gate_status=AsyncMock(return_value=_fake_gate()),
            hold_opens=AsyncMock(side_effect=err),
        ),
        me=AsyncMock(return_value=_fake_me()),
    )
    data = await coord._fetch_community()
    assert data.hold_opens_available is False


@pytest.mark.asyncio
async def test_auth_error_raises_config_entry_auth_failed(hass: HomeAssistant):
    from nimbio_community_api import AuthenticationError
    coord = _coordinator(hass)
    coord.client = SimpleNamespace(
        community=SimpleNamespace(
            gate_status=AsyncMock(side_effect=AuthenticationError(
                "Invalid API key", status_code=401)),
            hold_opens=AsyncMock(return_value=SimpleNamespace(latches={})),
        ),
        me=AsyncMock(return_value=_fake_me()),
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._fetch_community()
