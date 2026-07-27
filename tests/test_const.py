"""Pure unit tests for latch classification and status mapping (no HA needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.nimbio.const import (  # noqa: E402
    LATCH_CLASS_BUTTON,
    LATCH_CLASS_COVER,
    LATCH_CLASS_LOCK,
    classify_latch,
    status_is_closed,
    status_is_moving,
    status_is_problem,
)


def _p(*labels):
    return [{"status": s, "transient": False} for s in labels]


def test_lock_vocabulary_wins():
    assert classify_latch(_p("Locked", "Unlocked")) == LATCH_CLASS_LOCK
    # Mixed vocab with lock labels still reads as a lock.
    assert classify_latch(_p("Locked", "Open")) == LATCH_CLASS_LOCK


def test_cover_vocabulary():
    assert classify_latch(_p("Open", "Closed")) == LATCH_CLASS_COVER
    assert classify_latch(_p("Fully Open", "Fully Closed", "Moving")) == LATCH_CLASS_COVER
    assert classify_latch(_p("Not Open", "Not Closed")) == LATCH_CLASS_COVER


def test_no_sensing_is_a_button():
    assert classify_latch([]) == LATCH_CLASS_BUTTON
    assert classify_latch(None) == LATCH_CLASS_BUTTON
    # Only status labels that don't imply position (e.g. malfunction pair).
    assert classify_latch(_p("Malfunction", "No Malfunction")) == LATCH_CLASS_BUTTON


def test_status_binary_mapping():
    assert status_is_closed("Closed") is True
    assert status_is_closed("Fully Closed") is True
    assert status_is_closed("Not Open") is True
    assert status_is_closed("Locked") is True
    assert status_is_closed("Open") is False
    assert status_is_closed("Fully Open") is False
    assert status_is_closed("Not Closed") is False
    # Transitional / diagnostic labels are unknown, never a phantom position.
    assert status_is_closed("Unknown") is None
    assert status_is_closed("Failed to Get Status") is None
    assert status_is_closed("Upgrading") is None
    assert status_is_closed(None) is None


def test_moving_and_problem():
    assert status_is_moving("Moving") is True
    assert status_is_moving("Not Moving") is False
    assert status_is_problem("Malfunction") is True
    assert status_is_problem("No Malfunction") is False
