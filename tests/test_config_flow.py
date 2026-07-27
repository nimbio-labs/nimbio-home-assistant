"""Config flow tests with the SDK validation stubbed."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nimbio.const import (
    CONF_API_KEY,
    CONF_KEY_TYPE,
    CONF_WEBHOOK_MODE,
    DOMAIN,
    WEBHOOK_MODE_POLLING,
)

COMMUNITY_INFO = {
    "api_key_id": "k-community", "type": "community",
    "capabilities": ["open", "gate_status", "hold_opens", "webhooks"],
    "mode": "test", "name": "HA key", "prefix": "nimbio_test_ab12cd34",
}
ACCOUNT_INFO = {
    "api_key_id": "k-account", "type": "account", "capabilities": ["open"],
    "mode": "live", "name": None, "prefix": "nimbio_live_ab12cd34",
}


@pytest.mark.asyncio
async def test_community_key_offers_webhook_step(hass: HomeAssistant):
    with patch("custom_components.nimbio.config_flow._validate_key",
               return_value=COMMUNITY_INFO):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "nimbio_test_x"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhook_mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WEBHOOK_MODE: WEBHOOK_MODE_POLLING})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA key (test)"
    assert result["data"][CONF_KEY_TYPE] == "community"
    assert result["data"][CONF_WEBHOOK_MODE] == WEBHOOK_MODE_POLLING


@pytest.mark.asyncio
async def test_account_key_skips_webhook_step(hass: HomeAssistant):
    with patch("custom_components.nimbio.config_flow._validate_key",
               return_value=ACCOUNT_INFO):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "nimbio_live_x"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY_TYPE] == "account"
    assert result["data"][CONF_WEBHOOK_MODE] == WEBHOOK_MODE_POLLING


@pytest.mark.asyncio
async def test_duplicate_key_aborts(hass: HomeAssistant):
    with patch("custom_components.nimbio.config_flow._validate_key",
               return_value=ACCOUNT_INFO):
        first = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER})
        first = await hass.config_entries.flow.async_configure(
            first["flow_id"], {CONF_API_KEY: "nimbio_live_x"})
        assert first["type"] is FlowResultType.CREATE_ENTRY

        second = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER})
        second = await hass.config_entries.flow.async_configure(
            second["flow_id"], {CONF_API_KEY: "nimbio_live_x"})
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_bad_key_shows_error(hass: HomeAssistant):
    with patch("custom_components.nimbio.config_flow._validate_key",
               side_effect=Exception("401 Invalid API key")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "nope"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
