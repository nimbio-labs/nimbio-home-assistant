"""Locks are the other control that carries sensed state, so they share the
cover's hazard: the status feed can freeze while the entity stays usable."""
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.nimbio.const import DOMAIN
from custom_components.nimbio.coordinator import (
    LatchState,
    NimbioCoordinator,
    NimbioData,
)
from custom_components.nimbio.lock import NimbioLock, async_setup_entry


def _coordinator(hass: HomeAssistant) -> NimbioCoordinator:
    coord = NimbioCoordinator(
        hass, client=None, key_type="community",
        capabilities=["open", "gate_status"], poll_seconds=900)
    data = NimbioData()
    data.latches["door"] = LatchState(
        latch_id="door", name="Side Door", status="Locked",
        possible_statuses=[{"status": "Locked", "transient": False},
                           {"status": "Unlocked", "transient": False}])
    data.latches["gate"] = LatchState(
        latch_id="gate", name="Main Gate", status="Open",
        possible_statuses=[{"status": "Open", "transient": False},
                           {"status": "Closed", "transient": False}])
    coord.async_set_updated_data(data)
    return coord


async def _locks(hass: HomeAssistant, coord):
    entry = SimpleNamespace(entry_id="test-entry")
    hass.data.setdefault(DOMAIN, {})["test-entry"] = SimpleNamespace(
        coordinator=coord)
    added = []
    await async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    return added


@pytest.mark.asyncio
async def test_only_lock_vocabulary_latches_become_locks(hass: HomeAssistant):
    # Entity class follows the configured vocabulary — an Open/Closed gate
    # must not also surface as a lock.
    locks = await _locks(hass, _coordinator(hass))
    assert {lock._latch_id for lock in locks} == {"door"}


@pytest.mark.asyncio
async def test_is_locked_reads_the_configured_vocabulary(hass: HomeAssistant):
    coord = _coordinator(hass)
    lock = NimbioLock(coord, "door")
    assert lock.is_locked is True
    coord.data.latches["door"].status = "Unlocked"
    assert lock.is_locked is False
    # Anything outside the vocabulary is unknown, not a guess.
    coord.data.latches["door"].status = "Malfunction"
    assert lock.is_locked is None


@pytest.mark.asyncio
async def test_offline_reports_unknown_but_stays_available(hass: HomeAssistant):
    # Same contract as the cover: the control must keep working (the server
    # decides whether an open succeeds), but it must not keep asserting a
    # lock state read off a frozen feed.
    coord = _coordinator(hass)
    coord.data.latches["door"].offline = True
    lock = NimbioLock(coord, "door")
    assert lock.available is True
    assert lock.is_locked is None


@pytest.mark.asyncio
async def test_lock_is_not_remotely_lockable(hass: HomeAssistant):
    # Doors relock themselves; claiming otherwise would let an automation
    # believe it had secured a door it had not.
    lock = NimbioLock(_coordinator(hass), "door")
    with pytest.raises(NotImplementedError):
        await lock.async_lock()
