"""Constants and pure helpers for the Nimbio integration.

This module deliberately has no Home Assistant imports so its logic
(latch classification, state mapping) is unit-testable standalone.
"""
from __future__ import annotations

DOMAIN = "nimbio"

# Config entry data keys.
CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"
CONF_ENVIRONMENT = "environment"
CONF_KEY_TYPE = "key_type"                # "account" | "community"
CONF_CAPABILITIES = "capabilities"
CONF_WEBHOOK_MODE = "webhook_mode"        # one of WEBHOOK_MODE_*
CONF_EXTERNAL_URL = "external_url"        # user-supplied public https base
CONF_HA_WEBHOOK_ID = "ha_webhook_id"      # HA-side receiver id
CONF_CLOUDHOOK_URL = "cloudhook_url"
CONF_NIMBIO_WEBHOOK_ID = "nimbio_webhook_id"  # server-side registration
CONF_NIMBIO_WEBHOOK_SECRET = "nimbio_webhook_secret"

# Options keys.
OPT_POLL_INTERVAL = "poll_interval"

WEBHOOK_MODE_CLOUDHOOK = "cloudhook"
WEBHOOK_MODE_EXTERNAL = "external"
WEBHOOK_MODE_POLLING = "polling"

# Polling cadence. In polling mode this is the live interval; in webhook mode
# a slow safety-net re-sync still runs. The gate-status / hold-opens / me reads
# are quota-exempt server-side, so neither burns the key's monthly quota.
DEFAULT_POLL_SECONDS = 60
WEBHOOK_SAFETY_POLL_SECONDS = 900

# Events the integration subscribes its webhook to.
WEBHOOK_EVENTS = [
    "sense_line.changed",
    "hold_open.changed",
    "device.online",
    "device.offline",
]

# Capability strings from GET /v1/me.
CAP_OPEN = "open"
CAP_GATE_STATUS = "gate_status"
CAP_HOLD_OPENS = "hold_opens"
CAP_WEBHOOKS = "webhooks"

SERVICE_HOLD_OPEN_FOR = "hold_open_for"

# ---------------------------------------------------------------------------
# Latch classification from the configured sense-line status vocabulary
# (`possible_statuses` on /v1/community/gate-status). The vocabulary is
# user-configured per latch, so entity choice follows it instead of a
# hardcoded per-device guess.
# ---------------------------------------------------------------------------

LATCH_CLASS_LOCK = "lock"
LATCH_CLASS_COVER = "cover"
LATCH_CLASS_BUTTON = "button"

_LOCK_VOCAB = {"locked", "unlocked"}
_COVER_VOCAB = {
    "open", "not open", "closed", "not closed",
    "fully open", "fully closed", "moving", "not moving",
}

# Sensed labels mapped to a binary open/closed reading. Anything else
# (Unknown / Failed to Get Status / Upgrading / Synchronizing / Malfunction)
# reads as unknown.
CLOSED_STATUSES = {"closed", "fully closed", "not open", "locked", "not moving"}
OPEN_STATUSES = {"open", "fully open", "not closed", "unlocked"}
MOVING_STATUSES = {"moving"}
PROBLEM_STATUSES = {"malfunction"}


def classify_latch(possible_statuses: list) -> str:
    """Pick the entity class for a latch from its configured vocabulary.

    `possible_statuses` entries are `{"status": str, "transient": bool}`
    dicts (or objects with those attributes). Locked/Unlocked vocab -> lock;
    any open/closed-family vocab -> cover; no sensing configured -> button.
    """
    labels = set()
    for entry in possible_statuses or []:
        status = entry.get("status") if isinstance(entry, dict) else getattr(entry, "status", None)
        if status:
            labels.add(str(status).strip().lower())
    if labels & _LOCK_VOCAB:
        return LATCH_CLASS_LOCK
    if labels & _COVER_VOCAB:
        return LATCH_CLASS_COVER
    return LATCH_CLASS_BUTTON


def status_is_closed(status: str | None) -> bool | None:
    """Map a sensed status label to closed (True) / open (False) / unknown (None)."""
    if not status:
        return None
    s = str(status).strip().lower()
    if s in CLOSED_STATUSES:
        return True
    if s in OPEN_STATUSES:
        return False
    return None


def status_is_moving(status: str | None) -> bool:
    return bool(status) and str(status).strip().lower() in MOVING_STATUSES


def status_is_problem(status: str | None) -> bool:
    return bool(status) and str(status).strip().lower() in PROBLEM_STATUSES
