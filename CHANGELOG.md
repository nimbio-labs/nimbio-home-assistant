# Changelog

All notable changes to the Nimbio Home Assistant integration are documented
here. This project adheres to [Semantic Versioning](https://semver.org/).

HACS installs from git tags, so every version below is a release to real
installations.

## [Unreleased]

### Security
- The push-event debug log no longer dumps the raw event payload. It logs
  named fields (`status_label`, `transient`, `held_open`, `manual`) plus the
  list of keys present, so the diagnostic value is unchanged while the values
  of any field the API adds later stay out of the log. `data` is
  server-controlled, and Home Assistant users routinely paste debug logs into
  public issue reports — an unbounded passthrough is the wrong default there,
  even though nothing sensitive is carried today.

## [0.2.2] - 2026-08-01

### Fixed
- The `nimbio_status` attribute on gate covers and locks is now blank while
  the box is offline. 0.2.1 stopped the *state* from asserting a frozen
  reading, but the attribute kept exposing it, so a template using
  `state_attr(..., 'nimbio_status')` still saw a stale "Closed"/"Locked" —
  the exact value 0.2.1 set out to stop reporting.
- Read-only entities no longer raise from `available` if the coordinator has
  no data yet. The control base already guarded this; the read-only base did
  not, and an entity that raises from `available` breaks the state write for
  more than itself. Not reachable from the shipped setup path — platforms
  build no entities before the first refresh — so this is a latent fix.

### Changed
- `apply_webhook_event` no longer branches on a sense-line event's
  `transient` flag: both branches were identical, so the test decided
  nothing. Transient states (e.g. Moving) are applied like any other, which
  is what was already happening. Behavior is unchanged; the dead branch and
  the ambiguity about which path was intended are gone.

## [0.2.1] - 2026-08-01

### Fixed
- A gate that reads offline now reports **unknown** state instead of its last
  known reading. The cover's `is_closed` / `is_opening` and the lock's
  `is_locked` return unknown while the box is offline — the status feed is
  frozen, and an automation acting on a stale "closed" is worse than one
  seeing unknown. The entities stay *available* so the open control keeps
  working; the "Box online" binary sensor remains the honest connectivity
  signal.

### Changed
- Every applied push event is now debug-logged (event type, latch, status
  label, payload), so a "why didn't my gate update" report can be diagnosed
  from a debug log alone.

## [0.2.0] - 2026-07-31

### Added
- **Live event stream, on by default.** Gate status now arrives over Nimbio's
  SSE event stream (`community.stream_events()` in the SDK): Home Assistant
  opens one outbound connection to the API, so push updates work behind NAT
  with nothing exposed, no Nabu Casa subscription, and no webhook
  registration step. The stream carries the exact webhook event payloads, so
  both push paths share one code path and one event vocabulary. A stream
  reset (a reconnect gap the server can't replay) triggers a full re-sync
  rather than trusting stale state, and a rejected key starts the reauth
  flow.

### Changed
- Cloudhook, external-URL webhooks, and polling remain available and
  unchanged — they are now alternatives to the stream rather than the only
  options. Requires `nimbio-community-api >= 0.3.0`.

## [0.1.4] - 2026-07-30

### Fixed
- All latch controls (open button, gate cover, lock, hold-open switch) now
  share one availability rule instead of each defining its own, so a gate
  can't be openable from one entity and greyed out on another.
- The open button refreshes state after a press, so the UI reflects the
  result without waiting for the next update.

## [0.1.3] - 2026-07-30

### Fixed
- The open button stays available when the latch reads offline. The offline
  flag rides the same delayed status feed as gate state, so a stale reading
  used to disable every way to open the gate at exactly the moment it was
  needed — and an unavailable entity is invisible to automations and scripts,
  not merely greyed out. The server still rejects an open for a genuinely
  unreachable box.

## [0.1.2] - 2026-07-30

### Added
- A dedicated **Open button for every gate**, alongside the cover/lock entity.

### Changed
- The gate cover is now `assumed_state`, so it stays pressable even while the
  reported state says the gate is already open. Gate status can lag; the
  button never does.

## [0.1.1] - 2026-07-28

### Added
- Nimbio icon and logo ship inside the integration (`brand/`), using Home
  Assistant 2026.3+ local brand images — the integration is branded in the UI
  without waiting on a `home-assistant/brands` pull request.

## [0.1.0] - 2026-07-28

First release. A HACS custom integration (domain `nimbio`) built entirely on
the official [`nimbio-community-api`](https://pypi.org/project/nimbio-community-api/)
Python SDK.

### Added
- **Member (account) keys:** an open button for every latch on every key you
  hold.
- **Community manager keys:** live gate entities — a `cover` or a `lock`
  chosen from each latch's *configured* status vocabulary rather than a
  hardcoded guess — plus manual hold-open switches, a held-open sensor, box
  connectivity and malfunction diagnostics, and API-usage sensors.
- `nimbio.hold_open_for` service for timed hold opens. Windows are scheduled
  in the **latch's own timezone**, never the Home Assistant server clock, and
  the service refuses rather than guessing when the timezone isn't known — a
  UTC-hosted HA with a US gate would otherwise hold it open unattended hours
  later.
- The manual hold-open switch mirrors the CM portal's *indefinite* hold open,
  in both directions; turning it off never cancels a scheduled window, and the
  "Held open" sensor is the combined truth.
- Push updates via Nabu Casa cloudhook or your own public https URL, with
  polling as a fallback. The integration registers its own server-side
  webhook through your API key, so there is no admin-portal step, and it
  deletes that webhook when the integration is removed.
- Webhook deliveries are verified with a Stripe-style HMAC
  (`X-Nimbio-Signature` over `"{timestamp}.{body}"`) and a replay-tolerance
  window before any state is touched.
- Config flow with reauthentication, an options flow for the poll interval,
  and `nimbio_test_...` key support that exercises the whole pipeline without
  ever moving a gate.
- CI: pytest, Home Assistant **hassfest**, and **HACS** validation.

### Notes
- Status reads (gate status, hold opens, `/v1/me`) are quota-exempt
  server-side, so polling and re-syncs never consume the key's monthly quota.
  Opens and other writes count as usual.
- A test-mode key can't be issued a webhook signing secret, so an entry
  configured for webhooks is transparently demoted to polling.
