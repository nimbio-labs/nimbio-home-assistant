"""The Nimbio integration: gates, hold opens, and live status in HA.

Built entirely on the official `nimbio-community-api` SDK — no bespoke HTTP.
A community-manager API key gets live gate state (webhook push), opens, and
hold-open control; a member (account) key gets open buttons for their keys.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CAPABILITIES,
    CONF_KEY_TYPE,
    CONF_WEBHOOK_MODE,
    DEFAULT_POLL_SECONDS,
    DOMAIN,
    OPT_POLL_INTERVAL,
    SERVICE_HOLD_OPEN_FOR,
    WEBHOOK_MODE_POLLING,
    WEBHOOK_SAFETY_POLL_SECONDS,
)
from .coordinator import NimbioCoordinator
from .webhook import (
    async_ensure_webhook,
    async_remove_server_webhook,
    async_unregister_receiver,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class NimbioRuntime:
    """Per-entry runtime objects stored in hass.data[DOMAIN]."""

    client: object
    coordinator: NimbioCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from nimbio_community_api import AsyncNimbioClient
    from nimbio_community_api import AuthenticationError, NimbioError

    client = AsyncNimbioClient(
        entry.data[CONF_API_KEY], base_url=entry.data.get(CONF_BASE_URL))

    key_type = entry.data.get(CONF_KEY_TYPE, "account")
    capabilities = entry.data.get(CONF_CAPABILITIES, [])

    async def _cleanup() -> None:
        # A failed setup must leave nothing behind: the retry re-enters this
        # function, and a still-registered receiver would make it blow up
        # into a permanent 'failed to set up' state.
        async_unregister_receiver(hass, entry)
        await client.aclose()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    try:
        # Webhook registration first: it can demote the entry to polling
        # (e.g. test-mode key), and the coordinator's poll interval must
        # reflect the EFFECTIVE mode, not the configured one.
        mode = entry.data.get(CONF_WEBHOOK_MODE, WEBHOOK_MODE_POLLING)
        if key_type == "community" and mode != WEBHOOK_MODE_POLLING:
            mode = await async_ensure_webhook(hass, entry, client)

        if mode == WEBHOOK_MODE_POLLING:
            poll = entry.options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_SECONDS)
        else:
            poll = WEBHOOK_SAFETY_POLL_SECONDS

        coordinator = NimbioCoordinator(
            hass, client, key_type=key_type, capabilities=capabilities,
            poll_seconds=poll)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = NimbioRuntime(
            client=client, coordinator=coordinator)

        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, ConfigEntryAuthFailed):
        await _cleanup()
        raise
    except AuthenticationError as err:
        await _cleanup()
        raise ConfigEntryAuthFailed from err
    except NimbioError as err:
        await _cleanup()
        raise ConfigEntryNotReady(str(err)) from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        async_unregister_receiver(hass, entry)
        runtime: NimbioRuntime | None = hass.data.get(DOMAIN, {}).pop(
            entry.entry_id, None)
        if runtime is not None:
            await runtime.client.aclose()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the server-side webhook when the integration is removed."""
    from nimbio_community_api import AsyncNimbioClient

    if entry.data.get(CONF_KEY_TYPE) != "community":
        return
    client = AsyncNimbioClient(
        entry.data[CONF_API_KEY], base_url=entry.data.get(CONF_BASE_URL))
    try:
        await async_remove_server_webhook(hass, entry, client)
    finally:
        await client.aclose()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


# -- services -----------------------------------------------------------------

_HOLD_OPEN_FOR_SCHEMA = vol.Schema({
    vol.Required("latch_id"): cv.string,
    vol.Required("duration"): cv.positive_time_period,
    vol.Optional("entry_id"): cv.string,
})


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_HOLD_OPEN_FOR):
        return

    async def hold_open_for(call: ServiceCall) -> None:
        """Create a one-time hold-open window starting now."""
        latch_id: str = call.data["latch_id"]
        duration: datetime.timedelta = call.data["duration"]

        # Find the entry that owns this latch.
        runtime = None
        wanted = call.data.get("entry_id")
        for entry_id, rt in hass.data.get(DOMAIN, {}).items():
            if wanted and entry_id != wanted:
                continue
            if rt.coordinator.data and latch_id in rt.coordinator.data.latches:
                runtime = rt
                break
        if runtime is None:
            raise vol.Invalid(f"No Nimbio entry knows latch {latch_id}")

        # The API takes naive local time in the LATCH's own timezone — the
        # HA server's clock is not a safe substitute (a UTC-hosted HA with a
        # US latch would schedule the window hours in the future, holding
        # the gate open unattended later). If the timezone isn't known yet,
        # try one refresh to learn it; refuse rather than guess.
        state = runtime.coordinator.data.latches[latch_id]
        if not state.hold_open_timezone:
            await runtime.coordinator.async_refresh()
            state = runtime.coordinator.data.latches.get(latch_id)
        if state is None or not state.hold_open_timezone:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"Latch {latch_id} has no known timezone (hold-opens data "
                "unavailable); refusing to schedule a hold-open window that "
                "could land at the wrong time")

        from zoneinfo import ZoneInfo
        tz = ZoneInfo(state.hold_open_timezone)
        now = datetime.datetime.now(tz).replace(tzinfo=None, second=0,
                                                microsecond=0)
        end = now + duration
        fmt = "%Y-%m-%d %H:%M"
        await runtime.client.community.add_hold_open_event(
            latch_id, start=now.strftime(fmt), end=end.strftime(fmt))
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_HOLD_OPEN_FOR, hold_open_for,
        schema=_HOLD_OPEN_FOR_SCHEMA)
