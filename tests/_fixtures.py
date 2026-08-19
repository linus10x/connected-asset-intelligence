"""Shared builders for the test suite.

Here rather than duplicated per file because several suites need a *derived*
`BusinessImpact`, and a hand-rolled one per file would drift. The release path now
refuses a product whose business context was not derived, so "a valid impact" is a
precondition for most tests that are not about context at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cai.context import (
    Assignment,
    Component,
    BusinessImpact,
    ContextGraph,
    CustomerCommitment,
    LoadingWindow,
    Shipment,
)
from cai.bitemporal import Observation, digest_observations
from cai.contract import EvidenceSnapshot, PredictionInputs

# An arbitrary fixed origin. Fixed rather than `now()` so a failure is reproducible
# years later, which is the same property the contract claims for itself.
ORIGIN = datetime(2026, 6, 12, tzinfo=timezone.utc)


def ts(hours: float = 0) -> datetime:
    return ORIGIN + timedelta(hours=hours)


def complete_evidence() -> EvidenceSnapshot:
    """Every element present, including the evidence content digest.

    The digest is a literal here rather than computed from observations: these suites
    test the contract's treatment of a complete snapshot, not the digest function.
    `test_portability` and `test_bitemporal` cover the computation itself.
    """
    return EvidenceSnapshot(
        observation_ids=("obs-1", "obs-2"),
        subject="asset-4417",
        evidence_content_digest="d" * 64,
        prediction_inputs=PredictionInputs(
            metric="battery_temp_c",
            values=(41.0, 45.6),
            horizon_seconds=259200,
            model_version="degradation-baseline@1.3.0",
            input_fingerprint="f" * 64,
        ),
        model_version="degradation-baseline@1.3.0",
        semantic_rule_version="context-rules@0.6.0",
        identity_confidence=0.97,
        source_systems=("source-a", "source-c"),
    )


def context_graph(*, zone_id: str = "zone-3", recorded_at: datetime | None = None) -> ContextGraph:
    """A graph that walks all five relationships to a customer commitment."""
    graph = ContextGraph()
    graph.components["battery-pack-1"] = Component(
        component_id="battery-pack-1", asset_id="asset-4417", kind="battery-pack",
        recorded_at=ts(-95), source_system="asset-register",
    )
    graph.assignments.append(
        Assignment(
            asset_id="asset-4417",
            zone_id=zone_id,
            valid_from=ts(-96),
            recorded_at=recorded_at if recorded_at is not None else ts(-95),
            source_system="yard-management",
        )
    )
    graph.windows.append(
        LoadingWindow(
            window_id="win-9",
            zone_id="zone-3",
            opens=ts(22),
            closes=ts(28),
            shipment_id="ship-22",
            recorded_at=ts(-90),
            source_system="dock-scheduler",
        )
    )
    graph.shipments["ship-22"] = Shipment(
        "ship-22", "commit-7", recorded_at=ts(-90),
        source_system="transport-management")
    graph.commitments["commit-7"] = CustomerCommitment(
        "commit-7", "next-day delivery window, customer A", recorded_at=ts(-90),
        source_system="order-management",
    )
    return graph


def derived_impact() -> BusinessImpact:
    """A business impact that genuinely walked the graph. `derived` is True."""
    impact = context_graph().derive_impact(
        asset_id="asset-4417",
        component_id="battery-pack-1",
        horizon_start=ts(0),
        horizon_end=ts(72),
        transaction_time_cutoff=ts(0),
    )
    assert impact.derived, "fixture is meant to derive; the graph or rules changed"
    return impact


def underived_impact() -> BusinessImpact:
    """A business impact that reached no commitment. `derived` is False.

    Built by pointing the asset at a zone with no loading window, so the failure is
    produced by the real derivation rather than by constructing the dataclass directly.
    A hand-built False would test nothing about the walk.
    """
    impact = context_graph(zone_id="zone-11").derive_impact(
        asset_id="asset-4417",
        horizon_start=ts(0),
        horizon_end=ts(72),
        transaction_time_cutoff=ts(0),
    )
    assert not impact.derived, "fixture is meant to fail derivation"
    return impact


def sample_observations() -> tuple[Observation, ...]:
    """The readings `complete_evidence()` cites. Release verifies against these."""
    return tuple(
        Observation(
            observation_id=oid,
            subject="asset-4417",
            metric="battery_temp_c",
            value=value,
            valid_time=ts(-24),
            transaction_time=ts(-23),
            source_system="source-a",
        )
        for oid, value in (("obs-1", 41.0), ("obs-2", 45.6))
    )


def verified_evidence() -> EvidenceSnapshot:
    """`complete_evidence()` with a digest that actually matches the observations.

    The generic fixture carries a placeholder digest, which is right for tests about
    structural completeness and wrong for anything that reaches the release path -- where
    an unverifiable digest is now correctly BROKEN.
    """
    base = complete_evidence()
    return EvidenceSnapshot(
        **{**base.__dict__,
           "evidence_content_digest": digest_observations(sample_observations())}
    )
