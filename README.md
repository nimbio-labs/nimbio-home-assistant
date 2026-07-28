# Nimbio for Home Assistant

Open your Nimbio gates, see live gate status, and control hold opens from
[Home Assistant](https://www.home-assistant.io/). Built on the official
[`nimbio-community-api`](https://pypi.org/project/nimbio-community-api/) SDK.

## What you get

| Your key | Experience |
|---|---|
| **Member key** (create at [api.nimbio.com/manage](https://api.nimbio.com/manage)) | An **open button** for every latch on every key you hold. |
| **Community manager key** (admin portal → API Access) | Live **gate entities** (cover or lock, following each latch's configured status vocabulary), **manual hold-open switches**, a **held-open sensor**, box **connectivity/malfunction** diagnostics, a `nimbio.hold_open_for` service for timed hold opens, and API-usage sensors. |

Gate status arrives **push-first** over Nimbio community webhooks — signed
deliveries, verified in HA — via either:

- **Nabu Casa cloudhook** (recommended; nothing to expose), or
- your own **public https URL**, if your HA is already reachable, or
- **polling** as a fallback (status reads are quota-exempt on Nimbio's side,
  so polling doesn't consume your key's monthly quota).

A `nimbio_test_...` key exercises the full pipeline without ever moving a
gate — ideal for trying the integration out.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → *Custom repositories* → add
   `https://github.com/nimbio-labs/nimbio-home-assistant` (type: Integration).
2. Install **Nimbio**, restart Home Assistant.
3. Settings → Devices & Services → *Add Integration* → **Nimbio**.

### Manual

Copy `custom_components/nimbio/` into your `config/custom_components/` and
restart.

## Configuration

1. Paste your API key (`nimbio_test_...` or `nimbio_live_...`). The
   integration discovers what the key can do via `/v1/me`.
2. Community keys: pick how updates arrive (cloudhook / external URL /
   polling). With a push mode the integration **registers its own webhook**
   through your API key and stores the signing secret — no admin-portal step.
3. Done. Entities appear per latch.

### Timed hold opens

```yaml
service: nimbio.hold_open_for
data:
  latch_id: "1c9f4c2e-..."   # `latch_id` attribute on the gate entity
  duration: "01:00:00"
```

The **manual hold open** switch reflects only the manual toggle; the
**Held open** sensor is the combined truth (manual OR an active one-time /
recurring window). Turning the switch off never cancels a scheduled window.

## Notes

- Webhook deliveries are authenticated with a Stripe-style HMAC
  (`X-Nimbio-Signature` over `"{timestamp}.{body}"`) and a replay-tolerance
  window before any state is touched.
- Removing the integration deletes its server-side webhook (and cloudhook).
- Rate limits: opens and other writes count against your key's quota as
  usual; the status reads this integration polls are quota-exempt.

## Development

```bash
pip install -e ../nimbio-python-community-api  # or nimbio-community-api from PyPI
pip install pytest pytest-homeassistant-custom-component
pytest
```

Issues and PRs welcome at
[nimbio-labs/nimbio-home-assistant](https://github.com/nimbio-labs/nimbio-home-assistant).

---

**About Nimbio** — [Nimbio](https://nimbio.com) is cellular gate and door access for gated
communities, apartment buildings, and commercial properties. Developer docs and integration guides:
[nimbio.com/developers](https://nimbio.com/developers/).
