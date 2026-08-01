# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nimbio-home-assistant** is the official open-source [Home Assistant](https://www.home-assistant.io/) integration for Nimbio — gates, hold opens, and live gate status inside HA. It ships as a HACS custom component under the HA domain **`nimbio`** (`custom_components/nimbio/`).

It is a **public repo** (`nimbio-labs/nimbio-home-assistant`) read by end users and by HA reviewers. Everything in it is customer-visible: README, strings, log messages, changelog.

It talks to `api.nimbio.com` **only through the official Python SDK** (`nimbio-community-api`, repo `nimbio-python-community-api`) — no bespoke HTTP, no WAMP, no database. If the integration needs an endpoint the SDK doesn't expose, add it to the SDK first.

## Two key types, two products

The config flow calls `/v1/me` and branches on `key.type`. This split runs through every platform file — check it before assuming an entity exists.

| Key type | Source | What the integration builds |
|---|---|---|
| `account` (member key) | api.nimbio.com/manage | One open **button** per latch on every key the member holds. No status, no hold opens. |
| `community` (CM key) | admin portal → API Access | Gate **cover**/**lock** entities, an always-pressable open **button** per gate, hold-open **switch**, held-open + connectivity + malfunction **binary sensors**, API-usage **sensors**, and the `nimbio.hold_open_for` service. |

Feature availability within a community key is driven by the `capabilities` array from `/v1/me` (`CAP_OPEN`, `CAP_GATE_STATUS`, `CAP_HOLD_OPENS`, `CAP_WEBHOOKS` in `const.py`), not by trial and error.

## Architecture

| File | Responsibility |
|---|---|
| `__init__.py` | Entry setup/teardown, the `NimbioRuntime` dataclass in `hass.data[DOMAIN]`, and the `nimbio.hold_open_for` service. |
| `config_flow.py` | User + reauth flows and the options flow. Unique id is the API key id, so the same key can't be added twice. |
| `coordinator.py` | `NimbioCoordinator` (a `DataUpdateCoordinator`) plus `NimbioData` / `LatchState`. Owns the merge of polled fetches and pushed events (`apply_webhook_event`). |
| `stream.py` | `NimbioEventStream` — the default push path. Background task over the SDK's `community.stream_events()` (SSE). |
| `webhook.py` | The alternative push path: HA-side receiver, HMAC verification, and the server-side webhook registration lifecycle. |
| `entity.py` | `NimbioLatchEntity` (read-only) and `NimbioLatchControlEntity` (acts on a latch) — the two availability rules. |
| `const.py` | Constants **and pure helpers** (`classify_latch`, `status_is_*`). Deliberately has **no Home Assistant imports** so the logic is unit-testable standalone — keep it that way. |
| `binary_sensor.py`, `button.py`, `cover.py`, `lock.py`, `sensor.py`, `switch.py` | The six platforms in `PLATFORMS`. |
| `brand` (directory) | Icon/logo shipped in-repo (HA 2026.3+ local brand images), so the integration is branded without a home-assistant/brands PR. |

### Invariants worth knowing before you change things

- **Entity class follows the latch's configured status vocabulary**, not a hardcoded device guess. `classify_latch(possible_statuses)` returns lock / cover / button; Locked|Unlocked → lock, any open/closed-family vocab → cover, nothing sensed → button. A latch therefore appears on exactly one of `lock.py` / `cover.py` / `button.py`.
- **Controls never go unavailable on `offline`.** `NimbioLatchControlEntity` deliberately drops the offline gate that `NimbioLatchEntity` keeps: the offline flag rides the same delayed status feed as gate state, and an unavailable entity is dead to automations too. Controls that also carry sensed state (cover, lock) return `None` for that state while offline — staying available is about the control being usable, not the reading being true. The gate cover is `assumed_state = True` for the same reason.
- **Update modes** (`const.py` `WEBHOOK_MODE_*`): `stream` is the default and needs no registration (outbound SSE, works behind NAT); `cloudhook` and `external` register a real server-side webhook through the user's own API key; `polling` is the fallback. `async_ensure_webhook` returns the **effective** mode — a test-mode key can't get a signing secret, so it is demoted to polling and that demotion is persisted on the entry. The coordinator's poll interval must always reflect the effective mode.
- **The stream carries verbatim webhook envelopes**, so `apply_webhook_event` serves both push paths. One event vocabulary (`WEBHOOK_EVENTS`) for both.
- **Status reads are quota-exempt server-side** (gate-status, hold-opens, `/v1/me`), so polling and re-syncs never burn the key's monthly quota. Opens and other writes do count.
- **`hold_open_for` uses the latch's own timezone**, never the HA server clock — a UTC-hosted HA with a US latch would otherwise hold a gate open unattended hours later. If the timezone is unknown it refreshes once, then refuses rather than guessing.
- **A failed setup must leave nothing behind.** `_cleanup()` unregisters the HA receiver before re-raising; a dangling registration turns the `ConfigEntryNotReady` retry into a permanent failure.
- **A 401 anywhere** (coordinator, stream) must surface as `ConfigEntryAuthFailed` / `async_start_reauth`, not a retried `UpdateFailed`.
- **Hold-opens read failures degrade, they don't reset.** A transient failure of only that read carries the previous hold-open state forward; `hold_opens_disabled` means the feature is off, not an error; a failure on the *first* refresh fails setup rather than building entities from half a picture.

## Commands

```bash
source .venv/bin/activate
pip install -e ../nimbio-python-community-api   # or nimbio-community-api from PyPI
pip install pytest pytest-homeassistant-custom-component
pytest                                          # testpaths=tests, asyncio_mode=auto
```

CI (`.github/workflows/`) runs pytest, **hassfest**, and **HACS validation** — hassfest is strict about `manifest.json` key order and about URLs living in `strings.json` description placeholders rather than in the flow code. Run the workflows' checks mentally before pushing manifest or strings changes; they are the usual source of red CI here.

## Releasing

1. Bump `"version"` in `custom_components/nimbio/manifest.json` (HACS reads it from there — this repo has no `pyproject.toml`).
2. Add a dated section to `CHANGELOG.md`.
3. Update the customer-facing changelogs in nimbioCore: `nimbioCore/changelogs/home-assistant.md` and `nimbioCore/marketing-changelogs/home-assistant.md`.
4. Tag `vX.Y.Z` and push the tag. HACS serves users from tags, so a tag is a release to real installs.
5. If the release needs a newer SDK, bump the floor in `manifest.json` `requirements` — HA installs it at runtime, so an unbumped floor silently ships a broken integration.

## Related

- `nimbio-python-community-api` — the SDK this integration is built on. Any new API surface lands there first.
- `nimbio-public-api` — the REST service behind the SDK (auth, scopes, quota, webhook + SSE contracts).
- `nimbioCore/docs/home-assistant-integration-design-brief.md` — the original design brief.
- `nimbioCore/docs/home-assistant-install-runbook.md` — the install/verify runbook.
- `CHANGELOG.md` (this repo) — technical changelog for GitHub releases.
