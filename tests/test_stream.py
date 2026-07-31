"""NimbioEventStream behavior: apply events, re-sync on reset/outage,
reauth on a rejected key, clean cancellation."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from nimbio_community_api import AuthenticationError, RateLimitError
from nimbio_community_api.models import StreamEvent, StreamReset

from custom_components.nimbio import stream as stream_mod
from custom_components.nimbio.const import DOMAIN
from custom_components.nimbio.stream import NimbioEventStream


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry


def _coordinator() -> MagicMock:
    coord = MagicMock()
    coord.apply_webhook_event = MagicMock()
    coord.async_request_refresh = AsyncMock()
    return coord


def _client(gen_factory) -> MagicMock:
    client = MagicMock()
    client.community.stream_events = gen_factory
    return client


def _event(i: int, etype: str = "sense_line.changed") -> StreamEvent:
    return StreamEvent(id=f"e{i}", type=etype, data={
        "event": etype, "id": f"e{i}", "community_id": 5,
        "occurred_at": "2026-07-31T12:00:00+00:00",
        "data": {"latch_id": "l1", "status_label": "Open"},
    })


async def _wait_for(condition, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_events_are_applied_to_coordinator(hass: HomeAssistant):
    delivered = asyncio.Event()

    def gen_factory(**kwargs):
        async def gen():
            yield _event(1)
            yield _event(2, "hold_open.changed")
            delivered.set()
            await asyncio.Event().wait()  # hold the stream open
        return gen()

    coord = _coordinator()
    s = NimbioEventStream(hass, _entry(hass), _client(gen_factory), coord)
    s.start()
    await asyncio.wait_for(delivered.wait(), timeout=2)
    await _wait_for(lambda: coord.apply_webhook_event.call_count >= 2)

    assert s.connected is True
    first = coord.apply_webhook_event.call_args_list[0].args[0]
    assert first["event"] == "sense_line.changed"
    assert first["data"]["latch_id"] == "l1"

    await s.stop()
    assert s.connected is False


@pytest.mark.asyncio
async def test_reset_triggers_resync(hass: HomeAssistant):
    def gen_factory(**kwargs):
        async def gen():
            yield StreamReset(reason="replay_unavailable")
            await asyncio.Event().wait()
        return gen()

    coord = _coordinator()
    s = NimbioEventStream(hass, _entry(hass), _client(gen_factory), coord)
    s.start()
    await _wait_for(lambda: coord.async_request_refresh.await_count >= 1)
    coord.apply_webhook_event.assert_not_called()
    await s.stop()


@pytest.mark.asyncio
async def test_auth_error_starts_reauth_and_stops(hass: HomeAssistant):
    def gen_factory(**kwargs):
        async def gen():
            raise AuthenticationError("rejected", status_code=401, code=None,
                                      request_id=None, response=None,
                                      headers=None)
            yield  # pragma: no cover — makes this an async generator
        return gen()

    entry = _entry(hass)
    coord = _coordinator()
    s = NimbioEventStream(hass, entry, _client(gen_factory), coord)
    s.start()
    await _wait_for(lambda: s._task is not None and s._task.done())
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == "reauth" for f in flows)
    assert s.connected is False


@pytest.mark.asyncio
async def test_http_error_retries_and_resyncs(hass: HomeAssistant, monkeypatch):
    monkeypatch.setattr(stream_mod, "STREAM_RETRY_SECONDS", 0)
    calls = {"n": 0}

    def gen_factory(**kwargs):
        calls["n"] += 1
        async def gen():
            if calls["n"] == 1:
                raise RateLimitError("cap", status_code=429, code="stream_limit",
                                     request_id=None, response=None,
                                     headers=None, retry_after=None)
            yield _event(9)
            await asyncio.Event().wait()
        return gen()

    coord = _coordinator()
    s = NimbioEventStream(hass, _entry(hass), _client(gen_factory), coord)
    s.start()
    await _wait_for(lambda: coord.apply_webhook_event.call_count >= 1)

    # The outage triggered a catch-up re-sync before the second connection.
    assert coord.async_request_refresh.await_count >= 1
    assert calls["n"] == 2
    await s.stop()
