"""Config flow: paste an API key, discover what it can do, pick a push mode.

Keys come from two places (linked in the form description):
- Members: create an account key at https://api.nimbio.com/manage
- Community managers: create a community key in the admin portal
  (community.nimbio.com -> API Access)

The flow validates the key via GET /v1/me and branches on the key's
`capabilities` — a community key gets the webhook step (cloudhook / external
https URL / polling); an account key sets up open buttons only.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CAP_WEBHOOKS,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CAPABILITIES,
    CONF_EXTERNAL_URL,
    CONF_KEY_TYPE,
    CONF_WEBHOOK_MODE,
    DEFAULT_POLL_SECONDS,
    DOMAIN,
    OPT_POLL_INTERVAL,
    WEBHOOK_MODE_CLOUDHOOK,
    WEBHOOK_MODE_EXTERNAL,
    WEBHOOK_MODE_POLLING,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_key(hass: HomeAssistant, api_key: str,
                        base_url: str | None) -> dict[str, Any]:
    """Validate the key with /v1/me; returns key info or raises."""
    from nimbio_community_api import AsyncNimbioClient

    client = AsyncNimbioClient(api_key, base_url=base_url)
    try:
        me = await client.me()
    finally:
        await client.aclose()
    return {
        "api_key_id": me.key.api_key_id,
        "type": me.key.type or "account",
        "capabilities": list(me.key.capabilities),
        "mode": me.key.mode,
        "name": me.key.name,
        "prefix": me.key.prefix,
    }


def _cloud_available(hass: HomeAssistant) -> bool:
    try:
        from homeassistant.components import cloud
        return cloud.async_active_subscription(hass)
    except Exception:  # noqa: BLE001 — cloud not configured/loaded
        return False


class NimbioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Nimbio config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._key_info: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = (user_input.get(CONF_BASE_URL) or "").strip() or None
            try:
                info = await _validate_key(self.hass, api_key, base_url)
            except Exception as err:  # noqa: BLE001 — map to a form error
                _LOGGER.debug("Key validation failed: %s", err)
                errors["base"] = "invalid_auth" if "401" in str(err) or \
                    "Invalid API key" in str(err) else "cannot_connect"
            else:
                await self.async_set_unique_id(info["api_key_id"])
                self._abort_if_unique_id_configured()
                self._data = {
                    CONF_API_KEY: api_key,
                    CONF_BASE_URL: base_url,
                    CONF_KEY_TYPE: info["type"],
                    CONF_CAPABILITIES: info["capabilities"],
                }
                self._key_info = info
                if info["type"] == "community" and \
                        CAP_WEBHOOKS in info["capabilities"]:
                    return await self.async_step_webhook_mode()
                # Account key: polling only (no webhook feed for members yet).
                self._data[CONF_WEBHOOK_MODE] = WEBHOOK_MODE_POLLING
                return self._create()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_BASE_URL): str,
            }),
            errors=errors,
            description_placeholders={
                "manage_url": "https://api.nimbio.com/manage",
                "admin_url": "https://community.nimbio.com",
            },
        )

    async def async_step_webhook_mode(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        cloud_ok = _cloud_available(self.hass)
        options = []
        if cloud_ok:
            options.append(WEBHOOK_MODE_CLOUDHOOK)
        options += [WEBHOOK_MODE_EXTERNAL, WEBHOOK_MODE_POLLING]

        if user_input is not None:
            mode = user_input[CONF_WEBHOOK_MODE]
            external = (user_input.get(CONF_EXTERNAL_URL) or "").strip()
            if mode == WEBHOOK_MODE_EXTERNAL and not external.startswith("https://"):
                errors[CONF_EXTERNAL_URL] = "https_required"
            else:
                self._data[CONF_WEBHOOK_MODE] = mode
                if mode == WEBHOOK_MODE_EXTERNAL:
                    self._data[CONF_EXTERNAL_URL] = external.rstrip("/")
                return self._create()

        return self.async_show_form(
            step_id="webhook_mode",
            data_schema=vol.Schema({
                vol.Required(CONF_WEBHOOK_MODE,
                             default=options[0]): SelectSelector(
                    SelectSelectorConfig(options=options,
                                         mode=SelectSelectorMode.LIST,
                                         translation_key="webhook_mode")),
                vol.Optional(CONF_EXTERNAL_URL): str,
            }),
            errors=errors,
        )

    def _create(self):
        label = self._key_info.get("name") or self._key_info.get("prefix") or "Nimbio"
        suffix = " (test)" if self._key_info.get("mode") == "test" else ""
        return self.async_create_entry(title=f"{label}{suffix}", data=self._data)

    # -- reauth (revoked / rotated API key) --------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self,
                                        user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                info = await _validate_key(
                    self.hass, api_key, entry.data.get(CONF_BASE_URL))
            except Exception as err:  # noqa: BLE001 — map to a form error
                _LOGGER.debug("Reauth validation failed: %s", err)
                errors["base"] = "invalid_auth" if "401" in str(err) or \
                    "Invalid API key" in str(err) else "cannot_connect"
            else:
                # The replacement key must reach the same surface: same key
                # type (and for community keys, implicitly the same community
                # is enforced server-side by the new key itself).
                if info["type"] != entry.data.get(CONF_KEY_TYPE):
                    errors["base"] = "key_type_mismatch"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={**entry.data, CONF_API_KEY: api_key,
                              CONF_CAPABILITIES: info["capabilities"]},
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return NimbioOptionsFlow()


class NimbioOptionsFlow(config_entries.OptionsFlow):
    """Options: fallback poll interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get(
            OPT_POLL_INTERVAL, DEFAULT_POLL_SECONDS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(OPT_POLL_INTERVAL, default=current):
                    vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            }),
        )
