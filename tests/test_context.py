"""Tests for business-context derivation."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
from cai.context import (
    Assignment, ContextGraph, CustomerCommitment, LoadingWindow, RULE_VERSION, Shipment,
)

def t(h: int) -> datetime:
    return datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(hours=h)

def graph(assignment_to: int | None = None) -> ContextGraph:
    g = ContextGraph()
    g.assignments.append(Assignment("asset-4417", "zone-3", t(0), t(0),
                                    source_system="yard-management",
                                    valid_to=t(assignment_to) if assignment_to else None))
    g.windows.append(LoadingWindow("win-9", "zone-3", t(70), t(78), "ship-22",
                                   recorded_at=t(0), source_system="dock-scheduler"))
    g.shipments["ship-22"] = Shipment("ship-22", "commit-7", recorded_at=t(0),
                                      source_system="transport-management")
    g.commitments["commit-7"] = CustomerCommitment(
        "commit-7", "next-day delivery, customer A", recorded_at=t(0),
        source_system="order-management")
    return g

def test_business_impact_is_derived_from_temporally_valid_relationships():
    """The named requirement: a full walk of all five relationships."""
    impact = graph().derive_impact(asset_id="asset-4417", horizon_start=t(60),
                                   horizon_end=t(132), transaction_time_cutoff=t(60))
    assert impact.derived
    assert impact.commitment.description == "next-day delivery, customer A"
    assert impact.rule_version == RULE_VERSION
    # Every relationship traversed must be named.
    joined = " ".join(impact.source_facts)
    for rel in ("ASSIGNED_TO", "SUPPORTS", "LOADS", "FULFILLS"):
        assert rel in joined
    assert impact.missing_links == ()

def test_missing_or_late_relationship_prevents_business_impact_claim():
    """The polarity twin. A stale assignment must not produce an impact.

    The asset left zone-3 at hour 24; the horizon starts at hour 60. Joining without
    asking *when* the assignment was true would happily report a disruption to a bay
    the asset had left days earlier.
    """
    impact = graph(assignment_to=24).derive_impact(
        asset_id="asset-4417", horizon_start=t(60), horizon_end=t(132),
        transaction_time_cutoff=t(60))
    assert not impact.derived
    assert impact.commitment is None
    assert any("no zone assignment" in m for m in impact.missing_links)

def test_ambiguous_assignment_refuses_rather_than_picking_one():
    g = graph()
    g.assignments.append(Assignment("asset-4417", "zone-9", t(0), t(0),
                                    source_system="yard-management"))
    impact = g.derive_impact(asset_id="asset-4417", horizon_start=t(60),
                             horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("multiple zones" in a for a in impact.ambiguities)

@pytest.mark.parametrize("drop, expected", [
    ("shipments", "no shipment record"),
    ("commitments", "no commitment record"),
])
def test_each_broken_link_is_named_not_silently_dropped(drop, expected):
    g = graph(); getattr(g, drop).clear()
    impact = g.derive_impact(asset_id="asset-4417", horizon_start=t(60),
                             horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any(expected in m for m in impact.missing_links)

def test_non_overlapping_horizon_produces_no_impact():
    """Anti-conservatism: not every prediction threatens a commitment."""
    impact = graph().derive_impact(asset_id="asset-4417", horizon_start=t(200),
                                   horizon_end=t(210), transaction_time_cutoff=t(200))
    assert not impact.derived
    assert any("no loading window" in m for m in impact.missing_links)

def test_record_carries_the_knowledge_boundary():
    """A conclusion drawn under a different cutoff is a different conclusion."""
    rec = graph().derive_impact(asset_id="asset-4417", horizon_start=t(60),
                                horizon_end=t(132), transaction_time_cutoff=t(60)).as_record()
    assert rec["transaction_time_cutoff"].startswith("2026-06-14")
    assert rec["rule_version"] == RULE_VERSION
    assert len(rec["horizon"]) == 2


# ---------------------------------------------------------------------------
# RESTORED from test_integration_chain.py during the claim-centric refactor.
#
# The migration ledger claimed these were "module-level and still covered here".
# The mutation harness disproved that: four mutants survived because their guarding
# tests had gone with the retired suite. They are module-level invariants and they
# belong in this file -- but they were not in it, and the claim that they were is the
# exact kind of thing a ledger exists to prevent.
# ---------------------------------------------------------------------------

from cai.context import Component  # noqa: E402


def _graph_with_component(recorded_at=None, component_recorded=None, window_recorded=None):
    g = graph()
    g.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack",
        recorded_at=component_recorded or t(0), source_system="asset-register",
    )
    if recorded_at is not None:
        g.assignments[0] = Assignment("asset-4417", "zone-3", t(0), recorded_at,
                                      source_system="yard-management")
    if window_recorded is not None:
        g.windows[0] = LoadingWindow("win-9", "zone-3", t(70), t(78), "ship-22",
                                     recorded_at=window_recorded,
                                     source_system="dock-scheduler")
    return g


def test_an_assignment_recorded_after_the_cutoff_is_not_used():
    """A relationship entered late was not available, however true it later proved.

    Asserting only `not derived` passes for the wrong reason: the window recheck added
    later ALSO refuses this graph, so the knowledge-time filter could be removed entirely
    and the test would stay green. Mutation caught exactly that. The assertion is on the
    specific message the knowledge-time filter emits, which nothing else produces.
    """
    impact = _graph_with_component(recorded_at=t(90)).derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("recorded later" in m for m in impact.missing_links), (
        f"refused, but not by the knowledge-time filter: {impact.missing_links}"
    )
    assert impact.late_relationships


def test_a_context_fact_recorded_after_the_cutoff_is_not_used():
    """Only ASSIGNED_TO was filtered once; the commercial half used whatever it knew."""
    impact = _graph_with_component(window_recorded=t(90)).derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert impact.late_relationships


def test_the_same_facts_recorded_in_time_do_derive():
    """Non-triviality twin for both of the above."""
    assert _graph_with_component().derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60)).derived


def test_a_component_on_another_asset_is_refused():
    """A claim must bind to a part of the machine it is about."""
    g = _graph_with_component()
    g.components["battery-pack-9"] = Component(
        "battery-pack-9", "asset-9999", "battery-pack", recorded_at=t(0),
        source_system="asset-register")
    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-9",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("belongs to" in a for a in impact.ambiguities)


def test_two_overlapping_windows_refuse_rather_than_taking_the_first():
    """`overlapping[0]` let list order decide the economic consequence."""
    g = _graph_with_component()
    g.windows.append(LoadingWindow("win-12", "zone-3", t(71), t(79), "ship-99",
                                   recorded_at=t(0), source_system="dock-scheduler"))
    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("loading windows" in a for a in impact.ambiguities)


def test_an_asset_reassigned_before_the_window_is_not_a_risk_to_it():
    """The consequence happens at the window, not when the claim was issued."""
    g = _graph_with_component()
    g.assignments[0] = Assignment("asset-4417", "zone-3", t(0), t(0),
                                  source_system="yard-management", valid_to=t(65))
    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived


def test_the_full_walk_traverses_all_five_relationships_including_has_component():
    """`test_business_impact_is_derived_from_temporally_valid_relationships` calls itself
    a full walk of all five and traverses four: it never passes `component_id`, so the
    HAS_COMPONENT step could be deleted with the suite green.

    That step is what binds a claim to the part that degrades rather than to the machine,
    and since the derivation now travels in the portable record it is also the first link
    a reader follows.
    """
    impact = _graph_with_component().derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert impact.derived
    assert [s.relationship for s in impact.steps] == [
        "HAS_COMPONENT", "ASSIGNED_TO", "SUPPORTS", "LOADS", "FULFILLS",
    ]
    first = impact.steps[0]
    assert (first.subject, first.object) == ("asset-4417", "battery-pack-1")
    assert first.source_system == "asset-register"


def test_a_component_swapped_in_after_the_horizon_starts_is_refused():
    """`fitted_at` guards two joins and neither was exercised. A pack fitted after the
    decision was not the pack that produced the readings."""
    g = _graph_with_component()
    g.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(0),
        source_system="asset-register", installed_from=t(80))
    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("not fitted" in m for m in impact.missing_links)


def test_a_component_removed_before_the_window_opens_is_refused():
    """The second `fitted_at` join: a pack removed before the window cannot be what fails
    during it. Distinct from the one above, and separately unguarded."""
    g = _graph_with_component()
    g.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(0),
        source_system="asset-register", removed_at=t(65))
    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=t(60), horizon_end=t(132), transaction_time_cutoff=t(60))
    assert not impact.derived
    assert any("not fitted when" in m for m in impact.missing_links)
