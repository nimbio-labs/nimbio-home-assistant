"""Data coordinator: merges webhook pushes with polled re-syncs.

State flow: one full fetch seeds state at setup; webhook events patch it live
(instant, quota-free); a slow polled re-sync (fast in polling mode) is the
safety net for missed deliveries. The status reads used here are quota-exempt
server-side, so polling never burns the key's monthly quota.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CAP_GATE_STATUS,
    CAP_HOLD_OPENS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class LatchState:
    """Merged live state for one community latch."""

    latch_id: str
    name: str | None = None
    status: str | None = None
    offline: bool = False
    possible_statuses: list = field(default_factory=list)
    held_open: bool = False
    manual_hold_open: bool = False
    hold_open_timezone: str | None = None


@dataclass
class NimbioData:
    """Everything the entities render."""

    # Community surface.
    latches: dict[str, LatchState] = field(default_factory=dict)
    hold_opens_available: bool = False
    # Account surface: list of AccountKey models (SDK objects).
    account_keys: list = field(default_factory=list)
    # Diagnostics from /v1/me.
    usage: dict[str, Any] = field(default_factory=dict)


class NimbioCoordinator(DataUpdateCoordinator[NimbioData]):
    """Polls the Nimbio API and applies webhook pushes in between."""

    def __init__(self, hass: HomeAssistant, client, *, key_type: str,
                 capabilities: list[str], poll_seconds: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_seconds),
        )
        self.client = client
        self.key_type = key_type
        self.capabilities = capabilities

    # -- polling ------------------------------------------------------------

    async def _async_update_data(self) -> NimbioData:
        try:
            if self.key_type == "community":
                return await self._fetch_community()
            return await self._fetch_account()
        except UpdateFailed:
            raise
        except Exception as err:  # noqa: BLE001 — surface as UpdateFailed
            raise UpdateFailed(f"Nimbio API error: {err}") from err

    async def _fetch_community(self) -> NimbioData:
        tasks = [self.client.community.gate_status(), self.client.me()]
        fetch_holds = CAP_HOLD_OPENS in self.capabilities
        if fetch_holds:
            tasks.append(self.client.community.hold_opens())
        results = await asyncio.gather(*tasks, return_exceptions=True)

        gate, me = results[0], results[1]
        holds = results[2] if fetch_holds else None
        if isinstance(gate, Exception):
            raise UpdateFailed(f"gate-status failed: {gate}")

        data = NimbioData()
        if not isinstance(me, Exception) and me is not None:
            data.usage = {
                "minute_count": me.key.minute_count,
                "minute_limit": me.key.minute_limit,
                "month_count": me.key.month_count,
                "month_limit": me.key.month_limit,
            }

        for latch in gate.latches:
            if latch.latch_id is None:
                continue
            data.latches[latch.latch_id] = LatchState(
                latch_id=latch.latch_id,
                name=latch.latch_name,
                status=latch.status,
                offline=latch.offline,
                possible_statuses=[
                    {"status": p.status, "transient": p.transient}
                    for p in latch.possible_statuses
                ],
            )

        # A community with Hold Opens disabled fails this read with
        # `hold_opens_disabled` — treat it as "feature off", not an error.
        if holds is not None and not isinstance(holds, Exception):
            data.hold_opens_available = True
            for latch_id, entry in holds.latches.items():
                state = data.latches.get(latch_id)
                if state is None:
                    state = data.latches[latch_id] = LatchState(
                        latch_id=latch_id, name=entry.latch_name)
                state.held_open = entry.held_open
                state.manual_hold_open = entry.manual
                state.hold_open_timezone = entry.timezone
        elif isinstance(holds, Exception):
            _LOGGER.debug("hold-opens read unavailable: %s", holds)

        return data

    async def _fetch_account(self) -> NimbioData:
        keys, me = await asyncio.gather(
            self.client.account.keys(), self.client.me(),
            return_exceptions=True)
        if isinstance(keys, Exception):
            raise UpdateFailed(f"account keys failed: {keys}")
        data = NimbioData(account_keys=list(keys))
        if not isinstance(me, Exception) and me is not None:
            data.usage = {
                "minute_count": me.key.minute_count,
                "minute_limit": me.key.minute_limit,
                "month_count": me.key.month_count,
                "month_limit": me.key.month_limit,
            }
        return data

    # -- webhook pushes -------------------------------------------------------

    def apply_webhook_event(self, event: dict[str, Any]) -> None:
        """Patch coordinator data from a verified webhook envelope."""
        if self.data is None:
            return
        event_type = event.get("event")
        payload = event.get("data") or {}
        latch_id = payload.get("latch_id")

        if event_type == "sense_line.changed" and latch_id:
            state = self.data.latches.get(str(latch_id))
            if state is not None and not payload.get("transient"):
                state.status = payload.get("status_label") or state.status
                self.async_set_updated_data(self.data)
            elif state is not None:
                # Transient states (e.g. Moving) still render live.
                state.status = payload.get("status_label") or state.status
                self.async_set_updated_data(self.data)
        elif event_type == "hold_open.changed" and latch_id:
            state = self.data.latches.get(str(latch_id))
            if state is not None:
                if payload.get("held_open") is not None:
                    state.held_open = bool(payload["held_open"])
                if payload.get("manual") is not None:
                    state.manual_hold_open = bool(payload["manual"])
                self.async_set_updated_data(self.data)
        elif event_type in ("device.online", "device.offline"):
            # The payload names the box; latch linkage isn't included, so fall
            # back to a re-sync (cheap + quota-exempt).
            self.hass.async_create_task(self.async_request_refresh())
