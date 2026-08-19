"""The boundaries every temporal query is decided at, asserted one instant at a time.

WHY THIS FILE EXISTS
--------------------
The source-derived mutation pass found the same shape twenty times: change a `<=` to a
`<` in a bitemporal view or a graph-walk predicate, and the whole suite stays green.

That is not a cosmetic gap. Every one of these comparisons is the line between "the
decision-maker had this" and "they did not", and the module docstrings are emphatic that
the distinction is the entire point of keeping two clocks. A reading recorded AT the
cutoff was received; a reading recorded one microsecond after it was not. An assignment
that ends AT the moment a window opens did not cover that window -- the intervals are
half-open, and half-open is a decision, not an accident.

None of that was asserted anywhere. The suite exercised each view with data comfortably
inside or outside its bounds, so the bound itself answered to nothing and could be moved
either way without a single test noticing.

HOW EACH TEST IS BUILT
----------------------
One instant exactly ON the boundary, and one instant one microsecond past it. That pair
is what makes the test kill a mutation in EITHER direction: a rule that admitted too much
fails the second assertion, a rule that admitted too little fails the first. A test using
only a comfortably-inside value proves the query runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cai.bitemporal import Observation, ObservationLog
from cai.context import (
    Assignment,
    Component,
    ContextGraph,
    CustomerCommitment,
    LoadingWindow,
    Shipment,
)

TICK = timedelta(microseconds=1)


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def reading(oid: str, *, valid: datetime, arrived: datetime,
            subject: str = "asset-4417", value: float = 41.0,
            supersedes: str | None = None) -> Observation:
    return Observation(oid, subject, "battery_temp_c", value, valid, arrived,
                       "source-a", supersedes)


def log_of(*observations: Observation) -> ObservationLog:
    log = ObservationLog()
    for observation in observations:
        log.record(observation)
    return log


# ===========================================================================
# WHAT HAD ARRIVED. `transaction_time <= cutoff` -- inclusive, and it matters.
# ===========================================================================


def test_a_reading_that_arrived_exactly_at_the_cutoff_was_received():
    """Inclusive, and a rule that excluded it would refuse the hero: the reference
    scenario's decision moment IS its knowledge cutoff."""
    cutoff = t(12, 7)
    log = log_of(reading("a-0", valid=t(12, 6), arrived=cutoff))

    assert len(log.decision_time_view(transaction_time=cutoff)) == 1
    assert len(log.point_in_time_view(knowledge_cutoff=cutoff)) == 1


def test_a_reading_that_arrived_one_tick_after_the_cutoff_had_not_been_received():
    cutoff = t(12, 7)
    log = log_of(reading("a-0", valid=t(12, 6), arrived=cutoff + TICK))

    assert log.decision_time_view(transaction_time=cutoff) == ()
    assert log.point_in_time_view(knowledge_cutoff=cutoff) == ()


def test_a_reading_valid_exactly_at_the_evaluation_time_had_happened():
    """The second clock, on the same boundary. `point_in_time_view` requires BOTH: it had
    arrived, and the event it describes had occurred."""
    moment = t(12, 7)
    log = log_of(reading("a-0", valid=moment, arrived=moment))

    assert len(log.point_in_time_view(knowledge_cutoff=moment, evaluation_time=moment)) == 1


def test_a_reading_valid_one_tick_after_the_evaluation_time_had_not_happened():
    """The clock-skew hole `point_in_time_view` exists to close: a device stamps a reading
    in the future, delivers it before the decision, and lands inside a decision-time view
    describing an event that had not occurred."""
    moment = t(12, 7)
    log = log_of(reading("a-0", valid=moment + TICK, arrived=moment))

    assert len(log.decision_time_view(transaction_time=moment)) == 1, (
        "it genuinely had arrived -- the transaction-time view is right to include it"
    )
    assert log.point_in_time_view(knowledge_cutoff=moment, evaluation_time=moment) == ()


def test_a_lag_of_exactly_zero_is_not_an_implausible_clock():
    """Boundary on `arrival_lag() < 0`. A reading delivered in the same instant it
    describes is a fast feed, not a paradox, and treating it as one would silently drop
    every punctual reading from a well-behaved source."""
    moment = t(12, 7)

    assert not reading("a-0", valid=moment, arrived=moment).has_implausible_clock()
    assert reading("a-1", valid=moment + TICK, arrived=moment).has_implausible_clock()


def test_lateness_is_measured_strictly_against_its_threshold():
    """`is_late` is `lag > threshold`, not `>=`. A reading exactly at the threshold is
    within tolerance -- that is what declaring a tolerance means."""
    at_threshold = reading("a-0", valid=t(12, 6), arrived=t(12, 6) + timedelta(hours=2))

    assert not at_threshold.is_late(timedelta(hours=2))
    assert at_threshold.is_late(timedelta(hours=2) - TICK)


def test_the_retrospective_view_includes_a_reading_valid_exactly_at_the_moment():
    moment = t(12, 7)
    log = log_of(reading("a-0", valid=moment, arrived=moment + timedelta(days=8)))

    assert len(log.current_best_known_view(valid_time=moment)) == 1
    assert log.current_best_known_view(valid_time=moment - TICK) == ()


def test_the_two_views_disagree_on_exactly_the_late_arrival():
    """The property the whole module exists for, asserted rather than described: the
    decision-time view and the retrospective view differ by the readings that arrived
    after the decision, and by nothing else."""
    decision = t(12, 7)
    log = log_of(
        reading("a-0", valid=t(12, 6), arrived=t(12, 6, ) + timedelta(minutes=4)),
        reading("a-1", valid=t(12, 6), arrived=t(20)),
    )

    known = {o.observation_id for o in log.decision_time_view(transaction_time=decision)}
    believed = {o.observation_id
                for o in log.current_best_known_view(valid_time=decision)}

    assert known == {"a-0"}
    assert believed == {"a-0", "a-1"}
    assert believed - known == {"a-1"}


def test_the_knowledge_gap_is_bounded_at_both_ends():
    """Learned about the pre-decision period only after the decision. Both comparisons are
    load-bearing: a reading valid AT the decision counts, one valid after it does not; a
    reading that arrived AT the decision does not count, one that arrived after it does.
    """
    decision = t(12, 7)
    log = log_of(
        reading("in", valid=decision, arrived=decision + TICK),
        reading("arrived-at-decision", valid=decision, arrived=decision),
        reading("valid-after", valid=decision + TICK, arrived=decision + timedelta(days=1)),
    )

    gap = {o.observation_id
           for o in log.knowledge_gap(knowledge_cutoff=decision, subject="asset-4417")}
    assert gap == {"in"}


def test_late_arrivals_are_bounded_by_the_window_and_the_threshold():
    """`since <= valid_time <= until` and `transaction_time > until`. Three comparisons,
    each moved one tick, each observed."""
    since, until = t(10), t(12)
    log = log_of(
        reading("inside", valid=t(11), arrived=until + TICK),
        reading("arrived-at-close", valid=t(11), arrived=until),
        reading("valid-before-window", valid=since - TICK, arrived=until + TICK),
        reading("valid-at-window-close", valid=until, arrived=until + timedelta(days=2)),
    )

    late = {o.observation_id
            for o in log.late_arrivals(since=since, until=until,
                                       threshold=timedelta(0))}
    assert late == {"inside", "valid-at-window-close"}


def test_a_view_filtered_by_subject_returns_only_that_subject():
    """The `o.subject == subject` comparison in every view. A swap to `!=` inverts the
    filter, and every view that takes a subject was exercised only with a log containing
    one asset -- where the two answers are the same set."""
    log = log_of(
        reading("a-0", valid=t(12, 6), arrived=t(12, 6)),
        reading("z-0", valid=t(12, 6), arrived=t(12, 6), subject="asset-9999"),
    )
    moment = t(12, 7)

    for view in (
        {o.observation_id for o in log.decision_time_view(
            transaction_time=moment, subject="asset-4417")},
        {o.observation_id for o in log.current_best_known_view(
            valid_time=moment, subject="asset-4417")},
        {o.observation_id for o in log.point_in_time_view(
            knowledge_cutoff=moment, subject="asset-4417")},
        {o.observation_id for o in log.excluded_for_clock_skew(
            knowledge_cutoff=moment, subject="asset-4417")} | {"a-0"},
    ):
        assert view == {"a-0"}, view


def test_a_correction_that_had_arrived_supersedes_and_one_that_had_not_does_not():
    """Supersession is itself filtered by transaction time. A correction that arrived
    after the decision must NOT reach back and rewrite it -- which is the difference
    between reconstructing a decision and improving it."""
    decision = t(12, 7)
    early = log_of(
        reading("a-0", valid=t(12, 5), arrived=t(12, 5)),
        reading("a-1", valid=t(12, 6), arrived=decision, supersedes="a-0"),
    )
    late = log_of(
        reading("a-0", valid=t(12, 5), arrived=t(12, 5)),
        reading("a-1", valid=t(12, 6), arrived=decision + TICK, supersedes="a-0"),
    )

    assert {o.observation_id
            for o in early.point_in_time_view(knowledge_cutoff=decision)} == {"a-1"}
    assert {o.observation_id
            for o in late.point_in_time_view(knowledge_cutoff=decision)} == {"a-0"}


def test_a_conflict_pairing_two_different_readings_is_not_a_conflict():
    """An integrity conflict is ONE id whose payload two sources disagree about. A pair
    naming two different ids describes no contradiction at all, and would withhold a
    product for a disagreement that does not exist."""
    from cai.bitemporal import EvidenceBundle

    first = reading("a-0", valid=t(12, 5), arrived=t(12, 5))
    other = reading("a-1", valid=t(12, 6), arrived=t(12, 6), value=99.9)
    with pytest.raises(ValueError, match="not two different readings"):
        EvidenceBundle(observations=(first, other),
                       integrity_conflicts=((first, other),))


# ===========================================================================
# THE GRAPH WALK. Its predicates are half-open intervals too, and its failure
# paths are the ones that tell a data gap from a reporting lag.
# ===========================================================================


def graph(**over) -> ContextGraph:
    """The reference graph, one fact at a time overridable."""
    g = ContextGraph()
    g.components["battery-pack-1"] = over.get("component", Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register", installed_from=t(1)))
    g.assignments.append(over.get("assignment", Assignment(
        "asset-4417", "zone-3", t(8), t(8, 1), source_system="yard-management")))
    g.windows.append(over.get("window", LoadingWindow(
        "win-9", "zone-3", t(13, 5), t(13, 11), "ship-22", recorded_at=t(9),
        source_system="dock-scheduler")))
    g.shipments["ship-22"] = over.get("shipment", Shipment(
        "ship-22", "commit-7", recorded_at=t(9), source_system="transport-management"))
    g.commitments["commit-7"] = over.get("commitment", CustomerCommitment(
        "commit-7", "next-day delivery window", recorded_at=t(9),
        source_system="order-management"))
    return g


def derive(g: ContextGraph, *, cutoff: datetime = t(12, 7), component="battery-pack-1"):
    return g.derive_impact(
        asset_id="asset-4417", component_id=component,
        horizon_start=t(12, 7), horizon_end=t(15, 7), transaction_time_cutoff=cutoff,
    )


def test_the_reference_graph_derives():
    """The twin for everything below."""
    impact = derive(graph())

    assert impact.derived
    assert impact.commitment.commitment_id == "commit-7"
    assert impact.blocking_reasons() == ()


def test_an_assignment_is_covered_at_its_own_start_and_not_at_its_end():
    """Half-open: `valid_from <= moment < valid_to`. An asset reassigned away exactly as
    the horizon opens is not in that zone, and one assigned exactly then is."""
    at_start = Assignment("asset-4417", "zone-3", t(12, 7), t(8), source_system="yard")
    ends_at_start = Assignment("asset-4417", "zone-3", t(8), t(8), source_system="yard",
                               valid_to=t(12, 7))

    assert at_start.covers(t(12, 7))
    assert not at_start.covers(t(12, 7) - TICK)
    assert not ends_at_start.covers(t(12, 7))
    assert ends_at_start.covers(t(12, 7) - TICK)


def test_a_fact_recorded_exactly_at_the_cutoff_was_known():
    """`recorded_at <= cutoff`, the relationship layer's version of the rule the
    observation layer got right from the start."""
    assignment = Assignment("asset-4417", "zone-3", t(8), t(12, 7), source_system="yard")

    assert assignment.was_known_at(t(12, 7))
    assert not assignment.was_known_at(t(12, 7) - TICK)


def test_a_component_is_fitted_at_its_installation_and_not_at_its_removal():
    part = Component("battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(1),
                     installed_from=t(12, 7), removed_at=t(13, 7))

    assert part.fitted_at(t(12, 7))
    assert not part.fitted_at(t(12, 7) - TICK)
    assert not part.fitted_at(t(13, 7))
    assert part.fitted_at(t(13, 7) - TICK)


def test_a_loading_window_overlaps_strictly():
    """`start < closes and end > opens`. A horizon that ends exactly as a window opens
    does not overlap it -- two intervals touching at a point share no duration."""
    window = LoadingWindow("win-9", "zone-3", t(13, 5), t(13, 11), "ship-22",
                           recorded_at=t(9))

    assert window.overlaps(t(13, 5), t(13, 11))
    assert not window.overlaps(t(13, 11), t(13, 20)), "starts as the window closes"
    assert not window.overlaps(t(13), t(13, 5)), "ends as the window opens"
    assert window.overlaps(t(13, 11) - TICK, t(13, 20))


@pytest.mark.parametrize("name,over,missing_fragment,late_fragment", [
    (
        "the component was recorded after the cutoff",
        {"component": Component("battery-pack-1", "asset-4417", "battery-pack",
                                recorded_at=t(12, 7) + TICK,
                                source_system="asset-register", installed_from=t(1))},
        "component battery-pack-1 not known at cutoff",
        "HAS_COMPONENT",
    ),
    (
        "the shipment was recorded after the cutoff",
        {"shipment": Shipment("ship-22", "commit-7", recorded_at=t(12, 7) + TICK,
                              source_system="transport-management")},
        "shipment ship-22 not known at cutoff",
        "LOADS",
    ),
    (
        "the commitment was recorded after the cutoff",
        {"commitment": CustomerCommitment("commit-7", "next-day delivery window",
                                          recorded_at=t(12, 7) + TICK,
                                          source_system="order-management")},
        "commitment commit-7 not known at cutoff",
        "FULFILLS",
    ),
])
def test_a_fact_recorded_too_late_is_reported_rather_than_used(
    name, over, missing_fragment, late_fragment
):
    """Reported, not silently dropped, and that distinction is the module's stated point.

    A walk that never names a late relationship is indistinguishable from one that ignores
    transaction time entirely. A reader looking at a thin conclusion deserves to know that
    the fact existed and arrived too late -- which is a reporting lag somebody can shorten
    -- rather than that it never existed, which is a data gap.
    """
    impact = derive(graph(**over))

    assert not impact.derived
    assert any(missing_fragment in m for m in impact.missing_links), impact.missing_links
    assert any(late_fragment in link for link in impact.late_relationships), (
        impact.late_relationships
    )


def test_a_missing_component_record_is_a_gap_not_a_lag():
    """The other arm of the same branch: no record at all reports a missing link and NO
    late relationship. A walk that conflated the two would send somebody to chase a
    reporting delay that does not exist."""
    g = graph()
    g.components.clear()
    impact = derive(g)

    assert not impact.derived
    assert impact.late_relationships == ()
    assert any("no component record" in m for m in impact.missing_links)


def test_a_component_not_yet_fitted_at_the_horizon_start_derives_nothing():
    impact = derive(graph(component=Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register", installed_from=t(14))))

    assert not impact.derived
    assert any("not fitted" in m for m in impact.missing_links)


def test_a_component_belonging_to_another_asset_is_an_ambiguity():
    impact = derive(graph(component=Component(
        "battery-pack-1", "asset-0001", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register", installed_from=t(1))))

    assert not impact.derived
    assert any("belongs to asset-0001" in a for a in impact.ambiguities)


def test_an_assignment_recorded_too_late_reads_differently_from_none_at_all():
    """The pair the module says demands opposite responses, asserted as a pair."""
    late = graph(assignment=Assignment("asset-4417", "zone-3", t(8),
                                       t(12, 7) + TICK, source_system="yard-management"))
    absent = ContextGraph()
    absent.components["battery-pack-1"] = graph().components["battery-pack-1"]

    lagging = derive(late)
    missing = derive(absent)

    assert any("recorded later" in m for m in lagging.missing_links), lagging.missing_links
    assert lagging.late_relationships, "a lag must name the relationship that lagged"
    assert any("valid at horizon start" in m for m in missing.missing_links)
    assert missing.late_relationships == (), "a gap has nothing to report as late"


def test_a_loading_window_recorded_too_late_reads_differently_from_none_at_all():
    lagging = derive(graph(window=LoadingWindow(
        "win-9", "zone-3", t(13, 5), t(13, 11), "ship-22",
        recorded_at=t(12, 7) + TICK, source_system="dock-scheduler")))
    none_at_all = graph()
    none_at_all.windows.clear()
    missing = derive(none_at_all)

    assert any("known at cutoff" in m for m in lagging.missing_links)
    assert any("SUPPORTS" in link for link in lagging.late_relationships)
    assert any("overlapping the horizon" in m for m in missing.missing_links)
    assert missing.late_relationships == ()


def test_two_zones_at_once_is_a_defect_not_a_richer_answer():
    g = graph()
    g.assignments.append(Assignment("asset-4417", "zone-9", t(8), t(8, 1),
                                    source_system="yard-management"))
    impact = derive(g)

    assert not impact.derived
    assert any("multiple zones" in a for a in impact.ambiguities)


def test_two_overlapping_windows_are_an_ambiguity_not_an_insertion_order():
    """Previously resolved by list order, which made the economic consequence depend on
    which row happened to be read first."""
    g = graph()
    g.windows.append(LoadingWindow("win-10", "zone-3", t(13, 6), t(13, 12), "ship-23",
                                   recorded_at=t(9), source_system="dock-scheduler"))
    impact = derive(g)

    assert not impact.derived
    assert any("loading windows" in a for a in impact.ambiguities)


def test_an_asset_reassigned_before_the_window_opens_is_not_a_risk_to_it():
    """The re-check across the interval that actually matters. An asset assigned at
    horizon start and moved before the window opens is not a risk to that window, and
    saying otherwise is the same hindsight error in the other direction."""
    impact = derive(graph(assignment=Assignment(
        "asset-4417", "zone-3", t(8), t(8, 1), source_system="yard-management",
        valid_to=t(13, 5))))

    assert not impact.derived
    assert any("is not assigned to zone-3 when win-9 opens" in m
               for m in impact.missing_links)


def test_a_component_removed_before_the_window_opens_derives_nothing():
    impact = derive(graph(component=Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register", installed_from=t(1), removed_at=t(13, 5))))

    assert not impact.derived
    assert any("not fitted when win-9 opens" in m for m in impact.missing_links)


def test_a_missing_shipment_or_commitment_record_is_named():
    without_shipment = graph()
    without_shipment.shipments.clear()
    without_commitment = graph()
    without_commitment.commitments.clear()

    assert any("no shipment record" in m
               for m in derive(without_shipment).missing_links)
    assert any("no commitment record" in m
               for m in derive(without_commitment).missing_links)


def test_a_walk_without_a_component_still_derives():
    """`component_id=None` skips HAS_COMPONENT entirely, which is the DowntimeConsequence
    shape. A rule that required the component step would refuse the second consequence
    type the abstraction exists to prove."""
    impact = derive(graph(), component=None)

    assert impact.derived
    assert impact.source_facts[0].startswith("ASSIGNED_TO")


# ===========================================================================
# THREE MOMENTS, AND WHICH QUESTION EACH ONE ANSWERS.
#
# `DecisionContext.decision_time` said "when the claim was issued" and called itself
# the single temporal authority. `AssuranceDecision.decided_at` sat beside it, bound
# to `delivery_time` by an invariant and to the context by nothing. Two names that
# read as synonyms, describing two different decisions.
#
# They are now `model_decision_time` and `release_decision_time`, and the rule between
# them is an ORDER rather than an equality. Equality would have read the reference
# scenario's timing -- inference and gating in one process call -- as a domain rule.
# ===========================================================================


def _delivered_with(**over):
    import test_formation as T

    return T.deliver(**over)


def test_the_reference_release_stamps_all_three_moments_at_one_instant():
    """The twin, and the reason the ambiguity survived: in a single-process release the
    model decides, the gate decides and the delivery happens at the same instant, so
    nothing ever exercised the difference."""
    product = _delivered_with()

    assert (
        product.candidate.context.model_decision_time
        == product.assurance.release_decision_time
        == product.delivery_time
    )


def test_a_gate_decision_after_the_model_decision_is_admitted():
    """The case equality would have wrongly refused.

    A deployment where the release gate runs after the model -- which is every real
    deployment -- must not be refused for it. If this test cannot be made to pass, the
    rule is encoding the demo's timing.
    """
    import test_formation as T

    later = T.context().model_decision_time + timedelta(minutes=20)
    product = _delivered_with(release_decision_time=later)

    assert product.candidate.context.model_decision_time < product.delivery_time
    assert product.assurance.release_decision_time == later


def test_a_claim_issued_after_the_gate_authorised_it_is_refused():
    """The state the missing invariant admitted: released before it was made."""
    import test_formation as T
    from cai.candidate import TemporalAssertion
    from cai.decision import DecisionContext

    base = T.context()
    issued_later = base.model_decision_time + timedelta(hours=1)
    ahead = DecisionContext(
        model_decision_time=issued_later,
        knowledge_cutoff=base.knowledge_cutoff,
        evaluation_time=base.evaluation_time,
        prediction_window=base.prediction_window,
    )
    # The temporal assertion is bound to the context and refuses first if left behind,
    # which would have made this test pass on a check it does not name.
    matched = T.assurance(temporal=TemporalAssertion(
        issued_later, base.knowledge_cutoff, base.knowledge_cutoff, True,
        basis="features drawn from the point-in-time view at the knowledge cutoff"))

    # "ruled on" rather than "permitted": the check moved out of the DELIVERED branch and
    # now applies to abstentions too, where nothing was permitted and the gate still ruled.
    with pytest.raises(ValueError, match="ruled on a claim that had not been made"):
        _delivered_with(candidate=T.candidate(context=ahead), assurance=matched)


def test_the_gate_and_the_delivery_remain_one_moment():
    """Unchanged, and re-asserted here so the ordering rule above cannot be read as
    having loosened the equality below it."""
    import test_formation as T

    product = _delivered_with()
    with pytest.raises(ValueError, match="authorised by a decision taken at another time"):
        import dataclasses

        dataclasses.replace(
            product, delivery_time=product.delivery_time + timedelta(seconds=1)
        )


def test_each_clock_is_read_by_the_question_it_answers():
    """STRUCTURAL, and the point of the rename.

    The model's clock bounds the evidence. The gate's clock selects the rules. If one
    function read both for one purpose the distinction would be decorative, so this
    fixes which is consumed where.
    """
    import inspect

    import cai.assessment as assessment_module
    from cai.binding import point_in_time_eligibility_mismatch

    gate = inspect.signature(assessment_module._assess_evidence).parameters
    assert "release_decision_time" in gate, (
        "the entitlement window is judged against the gate's clock"
    )
    assert "model_decision_time" not in gate

    # The evidence side reads the CONTEXT's clocks -- the cutoff and the evaluation
    # moment -- and never the gate's. That is the separation the rename makes legible:
    # one function cannot silently start judging evidence by when somebody pressed send.
    evidence_clock = inspect.getsource(point_in_time_eligibility_mismatch)
    assert "context.knowledge_cutoff" in evidence_clock
    assert "release_decision_time" not in evidence_clock
