"""Webhook receiver + server-side registration lifecycle.

Deliveries are authenticated with the SDK's Stripe-style HMAC verifier
(X-Nimbio-Signature over "{timestamp}.{body}") before touching state.
Registration is done through the same API key the entry uses, so the config
flow never needs a human in the admin portal; the signing secret is stored in
the config entry (returned exactly once at create/rotate time).
"""
from __future__ import annotations

import logging
import secrets as _secrets
from http import HTTPStatus
from typing import Any

from aiohttp.web import Request, Response

from homeassistant.components import webhook as ha_webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLOUDHOOK_URL,
    CONF_EXTERNAL_URL,
    CONF_HA_WEBHOOK_ID,
    CONF_NIMBIO_WEBHOOK_ID,
    CONF_NIMBIO_WEBHOOK_SECRET,
    CONF_WEBHOOK_MODE,
    DOMAIN,
    WEBHOOK_EVENTS,
    WEBHOOK_MODE_CLOUDHOOK,
    WEBHOOK_MODE_EXTERNAL,
    WEBHOOK_MODE_POLLING,
)

_LOGGER = logging.getLogger(__name__)


def _register_receiver(hass: HomeAssistant, entry: ConfigEntry,
                       ha_webhook_id: str) -> None:
    """Register the HA-side receiver, tolerating a leftover registration
    from a failed setup attempt (ConfigEntryNotReady retries re-enter here,
    and ha_webhook.async_register raises on a duplicate id)."""
    try:
        ha_webhook.async_register(
            hass, DOMAIN, f"Nimbio ({entry.title})", ha_webhook_id,
            _make_handler(entry),
        )
    except ValueError:
        # Already registered (setup retry): re-point it at a fresh handler
        # bound to the current entry object.
        ha_webhook.async_unregister(hass, ha_webhook_id)
        ha_webhook.async_register(
            hass, DOMAIN, f"Nimbio ({entry.title})", ha_webhook_id,
            _make_handler(entry),
        )


async def async_ensure_webhook(hass: HomeAssistant, entry: ConfigEntry,
                               client) -> str:
    """Register the HA receiver and (once) the server-side webhook.

    Returns the EFFECTIVE update mode: normally the configured one, but
    demoted to polling (persisted on the entry) when the server-side
    registration cannot produce a secret — e.g. a test-mode key, whose
    writes are simulated and return none.
    """
    mode = entry.data.get(CONF_WEBHOOK_MODE, WEBHOOK_MODE_POLLING)
    if mode == WEBHOOK_MODE_POLLING:
        return mode

    updates: dict[str, Any] = {}
    ha_webhook_id = entry.data.get(CONF_HA_WEBHOOK_ID)
    if not ha_webhook_id:
        ha_webhook_id = _secrets.token_hex(16)
        updates[CONF_HA_WEBHOOK_ID] = ha_webhook_id

    _register_receiver(hass, entry, ha_webhook_id)

    # Public URL for the receiver.
    if mode == WEBHOOK_MODE_CLOUDHOOK:
        url = entry.data.get(CONF_CLOUDHOOK_URL)
        if not url:
            from homeassistant.components import cloud
            url = await cloud.async_create_cloudhook(hass, ha_webhook_id)
            updates[CONF_CLOUDHOOK_URL] = url
    else:  # WEBHOOK_MODE_EXTERNAL
        base = entry.data[CONF_EXTERNAL_URL]
        url = f"{base}{ha_webhook.async_generate_path(ha_webhook_id)}"

    # Server-side registration (once; survives reloads via the entry data).
    if not entry.data.get(CONF_NIMBIO_WEBHOOK_ID):
        created = await client.community.create_webhook(
            url, WEBHOOK_EVENTS, description=f"Home Assistant ({entry.title})")
        if created.webhook is None or not created.webhook.secret:
            # Really fall back: persist polling mode so the coordinator uses
            # the fast poll interval and deliveries can't dangle unverified.
            _LOGGER.warning(
                "Nimbio webhook registration returned no secret (test-mode "
                "key?); switching this entry to polling mode")
            ha_webhook.async_unregister(hass, ha_webhook_id)
            updates[CONF_WEBHOOK_MODE] = WEBHOOK_MODE_POLLING
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **updates})
            return WEBHOOK_MODE_POLLING
        updates[CONF_NIMBIO_WEBHOOK_ID] = created.webhook.webhook_id
        updates[CONF_NIMBIO_WEBHOOK_SECRET] = created.webhook.secret

    if updates:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **updates})
    return mode


def async_unregister_receiver(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ha_webhook_id = entry.data.get(CONF_HA_WEBHOOK_ID)
    if ha_webhook_id:
        ha_webhook.async_unregister(hass, ha_webhook_id)


async def async_remove_server_webhook(hass: HomeAssistant, entry: ConfigEntry,
                                      client) -> None:
    """Delete the server-side webhook (entry removal). Best-effort."""
    webhook_id = entry.data.get(CONF_NIMBIO_WEBHOOK_ID)
    if webhook_id:
        try:
            await client.community.delete_webhook(webhook_id)
        except Exception as err:  # noqa: BLE001 — never block removal
            _LOGGER.warning("Could not delete Nimbio webhook %s: %s",
                            webhook_id, err)
    if entry.data.get(CONF_CLOUDHOOK_URL):
        try:
            from homeassistant.components import cloud
            await cloud.async_delete_cloudhook(
                hass, entry.data[CONF_HA_WEBHOOK_ID])
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Cloudhook cleanup failed: %s", err)


def _make_handler(entry: ConfigEntry):
    """Build the aiohttp handler bound to this entry's secret + coordinator."""

    async def handle_webhook(hass: HomeAssistant, webhook_id: str,
                             request: Request) -> Response:
        from nimbio_community_api.webhooks import verify_signature

        secret = entry.data.get(CONF_NIMBIO_WEBHOOK_SECRET)
        if not secret:
            return Response(status=HTTPStatus.NOT_FOUND)

        body = await request.read()
        signature = request.headers.get("X-Nimbio-Signature")
        timestamp = request.headers.get("X-Nimbio-Timestamp")
        if not verify_signature(secret, timestamp, body, signature or ""):
            _LOGGER.warning("Rejected Nimbio webhook delivery with a bad "
                            "signature (webhook_id=%s)", webhook_id)
            return Response(status=HTTPStatus.UNAUTHORIZED)

        import json
        try:
            event = json.loads(body.decode("utf-8"))
        except ValueError:
            return Response(status=HTTPStatus.BAD_REQUEST)

        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if runtime is not None:
            runtime.coordinator.apply_webhook_event(event)
        return Response(status=HTTPStatus.OK)

    return handle_webhook
