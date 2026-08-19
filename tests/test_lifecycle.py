"""Tests for the disposition/outcome lifecycle.

The one that matters most is `test_no_code_path_can_claim_the_intervention_worked`.
Everything else is supporting structure.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
from cai.lifecycle import (
    AttributedEffect, DispositionState, IllegalTransition, ProductLifecycle,
)

def t(h: int) -> datetime:
    """Hours from a fixed origin, allowed to exceed 24 so tests can span days."""
    return datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(hours=h)

def fresh() -> ProductLifecycle:
    lc = ProductLifecycle(product_subject="asset-4417/battery-pack")
    lc.advance(DispositionState.DELIVERED, at=t(7), actor="system")
    return lc

def test_full_happy_path_reaches_a_closed_outcome():
    lc = fresh()
    lc.advance(DispositionState.ACKNOWLEDGED, at=t(8), actor="ops")
    lc.advance(DispositionState.ACCEPTED, at=t(9), actor="ops")
    lc.advance(DispositionState.ACTION_COMPLETED, at=t(14), actor="technician")
    lc.advance(DispositionState.OUTCOME_OBSERVED, at=t(20), actor="system",
               note="no failure observed during horizon")
    assert lc.is_closed()
    # `observed_outcome` is GONE, not empty. The lifecycle records state transitions; the
    # typed OutcomeObservation on the envelope records what was observed. A prose outcome
    # here was a second authority that could not be grouped, counted, or joined to the
    # recommendation it was about.
    assert not hasattr(lc, "observed_outcome")
    assert lc.events[-1].note == "no failure observed during horizon"

def test_no_code_path_can_claim_the_intervention_worked():
    """The causal boundary. A followed recommendation plus no failure is NOT proof.

    AttributedEffect has exactly one member, so there is no value to assign even by
    mistake. This test exists to fail loudly if someone later adds one.
    """
    lc = fresh()
    lc.advance(DispositionState.ACKNOWLEDGED, at=t(8), actor="ops")
    lc.advance(DispositionState.ACCEPTED, at=t(9), actor="ops")
    lc.advance(DispositionState.ACTION_COMPLETED, at=t(14), actor="technician")
    lc.advance(DispositionState.OUTCOME_OBSERVED, at=t(20), actor="system",
               note="no failure observed during horizon")
    assert lc.attributed_effect is AttributedEffect.NOT_ESTABLISHED
    assert len(list(AttributedEffect)) == 1, (
        "a second AttributedEffect value was added -- causation cannot be established "
        "from outcome capture alone"
    )
    assert lc.as_record()["attributed_effect"] == "NOT_ESTABLISHED"

def test_override_is_a_first_class_outcome_not_a_failure():
    """An override is a recorded decision, not a defect report.

    Overrides cluster for many reasons -- the signal is wrong, or it arrives too late to
    act on, or the recipient cannot act, or the crew already knew. Reading the cluster as
    a verdict on the model is how a team spends a quarter retuning one that was right.
    """
    lc = fresh()
    lc.advance(DispositionState.ACKNOWLEDGED, at=t(8), actor="ops")
    lc.advance(DispositionState.OVERRIDDEN, at=t(9), actor="ops",
               note="unit already scheduled for service")
    lc.advance(DispositionState.OUTCOME_OBSERVED, at=t(30), actor="system",
               note="failure occurred")
    assert lc.is_closed()
    assert any(e.state is DispositionState.OVERRIDDEN for e in lc.events)

def test_ignored_recommendations_still_reach_an_outcome():
    """A naturally observed non-adoption case, and the most valuable data in the loop.

    Not a control arm. Nothing was randomised and the recipient chose, so the cases that
    go unadopted are exactly the ones somebody judged safe to leave alone -- which is the
    definition of a confounded comparison. The vocabulary matters because "control arm"
    invites a causal reading of the difference, and this design earns no such thing.
    """
    lc = fresh()
    lc.advance(DispositionState.IGNORED, at=t(23), actor="system")
    lc.advance(DispositionState.OUTCOME_OBSERVED, at=t(30), actor="system",
               note="failure occurred")
    assert lc.is_closed()

@pytest.mark.parametrize("bad_target", [
    DispositionState.ACTION_COMPLETED, DispositionState.ACCEPTED,
    DispositionState.OUTCOME_OBSERVED,
])
def test_illegal_transitions_are_refused_with_a_reason(bad_target):
    """Skipping acknowledgement must fail -- a lifecycle that accepts anything
    records history without describing it."""
    lc = fresh()
    with pytest.raises(IllegalTransition, match="not a permitted transition"):
        lc.advance(bad_target, at=t(8), actor="ops")

def test_the_legal_path_is_actually_permitted():
    """Anti-conservatism: refusing everything would pass the test above."""
    lc = fresh()
    lc.advance(DispositionState.ACKNOWLEDGED, at=t(8), actor="ops")
    assert lc.state is DispositionState.ACKNOWLEDGED

def test_trail_preserves_who_did_what_and_when():
    lc = fresh()
    lc.advance(DispositionState.ACKNOWLEDGED, at=t(8), actor="ops-lead")
    rec = lc.as_record()
    assert rec["trail"][-1]["actor"] == "ops-lead"
    assert rec["trail"][-1]["state"] == "ACKNOWLEDGED"
    assert "T08:00" in rec["trail"][-1]["at"]


# ---------------------------------------------------------------------------
# TRAIL INTEGRITY. Added after an audit found a lifecycle could be acknowledged
# without ever having been delivered.
# ---------------------------------------------------------------------------


def test_a_lifecycle_cannot_open_at_acknowledged():
    """The empty trail is an absence, not a delivery.

    `state` reported DELIVERED for a lifecycle with no events, so a caller could build a
    fresh one and advance straight to ACKNOWLEDGED -- recording that a customer
    acknowledged a product that had never been sent.
    """
    trail = ProductLifecycle(product_subject="asset-4417/battery-pack")
    assert trail.state is None
    with pytest.raises(IllegalTransition):
        trail.advance(
            DispositionState.ACKNOWLEDGED,
            at=datetime(2026, 6, 12, tzinfo=timezone.utc),
            actor="operations@customer",
        )


def test_a_lifecycle_opens_at_delivered():
    """Non-triviality twin: the legal opening must still work."""
    trail = ProductLifecycle(product_subject="asset-4417/battery-pack")
    trail.advance(
        DispositionState.DELIVERED,
        at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        actor="system",
    )
    assert trail.state is DispositionState.DELIVERED


def test_events_cannot_go_backwards_in_time():
    """A trail that can be written out of order cannot be replayed."""
    trail = ProductLifecycle(product_subject="asset-4417/battery-pack")
    trail.advance(
        DispositionState.DELIVERED,
        at=datetime(2026, 6, 12, 9, tzinfo=timezone.utc),
        actor="system",
    )
    with pytest.raises(IllegalTransition):
        trail.advance(
            DispositionState.ACKNOWLEDGED,
            at=datetime(2026, 6, 12, 8, tzinfo=timezone.utc),  # an hour earlier
            actor="operations@customer",
        )


def test_a_trail_binds_to_a_product_not_merely_an_asset():
    """One asset carries many claims; an outcome must not attach to the wrong one."""
    first = ProductLifecycle(
        product_subject="asset-4417/battery-pack", product_id="ip-2026-06-12-001"
    )
    second = ProductLifecycle(
        product_subject="asset-4417/battery-pack", product_id="ip-2026-06-19-004"
    )
    assert first.product_id != second.product_id
    assert first.as_record()["product_id"] == "ip-2026-06-12-001"
