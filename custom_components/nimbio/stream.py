"""SSE live event stream consumer — the default push mode.

Runs `client.community.stream_events()` (the SDK's auto-reconnecting SSE
consumer of `GET /v1/events/stream`) as a background task and patches the
coordinator with each event. The stream carries the exact webhook event
payloads, so the coordinator's `apply_webhook_event` handles both paths.

Works behind NAT — the connection is outbound, nothing is exposed. A
`stream.reset` message (server couldn't replay a reconnect gap) triggers a
full quota-exempt re-sync. The SDK reconnects through transport drops on its
own; HTTP-level errors here mean something real (revoked key, concurrent
stream cap), so they back off longer, and a 401 starts the reauth flow.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import STREAM_RETRY_SECONDS, WEBHOOK_EVENTS
from .coordinator import NimbioCoordinator

_LOGGER = logging.getLogger(__name__)


class NimbioEventStream:
    """Owns the background stream task for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client,
                 coordinator: NimbioCoordinator) -> None:
        self._hass = hass
        self._entry = entry
        self._client = client
        self._coordinator = coordinator
        self._task: asyncio.Task | None = None
        self.connected = False

    def start(self) -> None:
        if self._task is None:
            self._task = self._entry.async_create_background_task(
                self._hass, self._run(), name=f"nimbio-stream-{self._entry.entry_id}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.connected = False

    async def _run(self) -> None:
        from nimbio_community_api import AuthenticationError, NimbioError
        from nimbio_community_api.models import StreamReset

        while True:
            need_resync = False
            try:
                async for msg in self._client.community.stream_events(
                        events=WEBHOOK_EVENTS):
                    if not self.connected:
                        self.connected = True
                        _LOGGER.debug("event stream delivering")
                    if isinstance(msg, StreamReset):
                        # Gap not replayable — re-seed from the status reads
                        # (quota-exempt) instead of trusting stale state.
                        _LOGGER.debug("stream reset (%s); re-syncing", msg.reason)
                        await self._coordinator.async_request_refresh()
                    else:
                        # msg.data is the webhook envelope, verbatim.
                        self._coordinator.apply_webhook_event(msg.data)
            except asyncio.CancelledError:
                raise
            except AuthenticationError:
                _LOGGER.warning("event stream rejected the API key; starting reauth")
                self.connected = False
                self._entry.async_start_reauth(self._hass)
                return
            except NimbioError as err:
                _LOGGER.warning(
                    "event stream error (%s); retrying in %ss",
                    err, STREAM_RETRY_SECONDS)
                need_resync = True
            except Exception:  # noqa: BLE001 — must never kill the task loop
                _LOGGER.exception(
                    "unexpected event stream failure; retrying in %ss",
                    STREAM_RETRY_SECONDS)
                need_resync = True
            finally:
                self.connected = False

            await asyncio.sleep(STREAM_RETRY_SECONDS)
            if need_resync:
                # Events may have been missed while the stream was down.
                await self._coordinator.async_request_refresh()
