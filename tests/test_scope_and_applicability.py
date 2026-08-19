"""Three questions the record could answer wrongly while every other signal stayed green.

    Was the operator entitled to ALL the data that forms this product?
    Was the model fitted for THIS metric on THIS kind of thing?
    Does the REASON path actually reason, or is it merely connected?

Each had the same shape: a check existed, ran, and was weaker than the sentence describing
it. The entitlement covered the telemetry and not the business systems the delivered claim
is derived from. The model envelope declared metrics and subject types as independent
sets, which is a cross-product. The derivation required connectivity, which a relabelled
walk satisfies.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

import test_formation as T
from cai.candidate import ApplicabilityAssertion
from cai.consequence import DowntimeConsequence
from cai.decision import TimeInterval
from cai.derivation import ConsequenceDerivation, DerivationRelationship, DerivationStep
from cai.envelope import IntelligenceEnvelope, import_envelope, import_historical_envelope
from cai.predictor import MetricApplicability, declared_envelope
from cai.product import Determination


def wire(**over) -> dict:
    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


def forged(mutate) -> dict:
    payload = wire()
    mutate(payload)
    return payload


def blocked_for(product, dimension: str) -> bool:
    return any(dimension in reason for reason in product.assurance.blocking_reasons)


# ===========================================================================
# ENTITLEMENT MUST COVER EVERY MATERIAL INPUT SOURCE.
# ===========================================================================


def test_a_clearance_covering_every_consumed_source_delivers():
    """The twin every refusal below depends on.

    Without it a rule that refused every clearance would pass the whole section, and the
    honest fixture -- the one that licenses all six systems -- is what proves the union is
    satisfiable rather than merely strict.
    """
    product = T.deliver()

    assert product.determination is Determination.DELIVERED
    assert set(T.CONSUMED_SOURCES) == set(
        T.entitlement().authorized_source_systems
    )


def test_a_product_using_an_unlicensed_telemetry_source_is_refused():
    """The half that already worked, kept as evidence that widening did not weaken it."""
    unlicensed = tuple(s for s in T.CONSUMED_SOURCES if s != "source-a")
    product = T.deliver(
        assurance=T.assurance(
            entitlement=T.entitlement(authorized_source_systems=unlicensed))
    )

    assert product.determination is Determination.ABSTAINED
    assert blocked_for(product, "entitlement")


@pytest.mark.parametrize("unlicensed_system", [
    "asset-register",
    "yard-management",
    "dock-scheduler",
    "transport-management",
    "order-management",
])
def test_a_product_using_an_unlicensed_reason_source_is_refused(unlicensed_system):
    """The half that did not.

    The entitlement checked the telemetry feeds and stopped there. But the thing being
    sold is not the temperature -- it is "your next-day delivery commitment to customer A
    is at risk", and that sentence is derived by joining an asset register, a yard, a dock
    schedule, a transport plan and an order book. Five business systems whose data forms
    the delivered product, none of them licensed, on a record whose entire premise is that
    a commercial intelligence product carries an implied entitlement to the data
    underneath it.

    All five are parametrized rather than one representative, because the union is over a
    set and a check that happened to look at only the first step would pass a single case.
    """
    covered = tuple(s for s in T.CONSUMED_SOURCES if s != unlicensed_system)
    product = T.deliver(
        assurance=T.assurance(
            entitlement=T.entitlement(authorized_source_systems=covered))
    )

    assert product.determination is Determination.ABSTAINED, unlicensed_system
    assert blocked_for(product, "entitlement")


def test_a_source_the_product_does_not_consume_need_not_be_licensed():
    """The boundary, stated from the permissive side.

    "Every system the record mentions" would be a different and wrong rule: it would
    refuse a delivery because some unrelated feed exists in the same log, and an operator
    could not act on that. The union is over data MATERIALLY USED -- the readings the
    assessment ran over, and the derivation steps the consequence was built from.

    Here the log carries a reading from a feed nobody licensed, about another asset, so it
    never enters the point-in-time view and never forms any part of this product.
    """
    from cai.bitemporal import Observation

    stranger = Observation("q-1", "asset-0000", "battery_temp_c", 12.0,
                           T.t(9, 6), T.t(9, 7), "unlicensed-side-channel")
    product = T.deliver(observation_log=T.log_of(T.observations() + (stranger,)))

    assert product.determination is Determination.DELIVERED
    assert "unlicensed-side-channel" not in T.entitlement().authorized_source_systems


def test_the_union_rule_is_the_one_both_boundaries_use():
    """One implementation, named, rather than the same set assembled twice.

    Two copies of a union rule is the two-authorities pattern this package spends its time
    removing, and the day they disagree is the day the wire stops meaning what the memory
    means.
    """
    from cai.assessment import material_source_systems

    product = T.deliver()
    assert material_source_systems(
        evidence_source=product.release_evidence,
        derivation=product.candidate.business_consequence.derivation,
    ) == tuple(sorted(T.CONSUMED_SOURCES))


def test_historical_import_re_runs_the_same_entitlement_source_union():
    """Rights are re-checked over the same union on the way in, and not waived by a policy
    this package does not ship.

    The forgery relabels a derivation step's source system to one the clearance does not
    cover, then names a foreign policy -- the branch that used to skip the authorization
    entirely.
    """
    def mutate(p):
        steps = p["product"]["candidate"]["business_consequence"]["derivation"]["steps"]
        steps[0]["source_system"] = "unlicensed-registry"
        p["product"]["assurance"]["policy_id"] = "acme.house-rules"

    with pytest.raises(ValueError, match="does not authorise the delivery"):
        import_historical_envelope(forged(mutate))
    with pytest.raises(ValueError, match="does not authorise the delivery"):
        import_envelope(forged(mutate))


def test_the_untouched_record_still_imports_under_the_union():
    """Non-triviality twin for the import half."""
    assert import_envelope(wire()).product.determination is Determination.DELIVERED


# ===========================================================================
# METRIC x SUBJECT-TYPE APPLICABILITY.
# ===========================================================================


def test_the_reference_model_declares_pairs_not_two_independent_sets():
    """STRUCTURAL. Two sets are a cross-product; this model is fitted for two of the four
    combinations the old declaration admitted."""
    envelope = declared_envelope()

    assert envelope.supported_applicability == (
        MetricApplicability("battery_temp_c", "forklift/battery-pack"),
        MetricApplicability("hydraulic_pressure_kpa", "forklift/hydraulic-system"),
    )
    # The flat views survive as DERIVED projections, so the refusal paths that read them
    # cannot drift from the declaration.
    assert envelope.supported_metrics == (
        "battery_temp_c", "hydraulic_pressure_kpa")
    assert envelope.supported_subject_types == (
        "forklift/battery-pack", "forklift/hydraulic-system")
    assert "supported_metrics" not in envelope.as_record()
    assert "supported_subject_types" not in envelope.as_record()


def test_a_supported_pair_delivers():
    """battery_temp_c on a forklift battery pack. The hero, and the twin for the
    refusals below."""
    assert T.deliver().determination is Determination.DELIVERED


def test_the_cross_product_is_not_the_declaration():
    """The arithmetic, stated so the gap is not merely asserted in a docstring."""
    envelope = declared_envelope()
    cross_product = len(envelope.supported_metrics) * len(
        envelope.supported_subject_types)

    assert cross_product == 4
    assert len(envelope.supported_applicability) == 2
    assert not envelope.admits_pair("battery_temp_c", "forklift/hydraulic-system")
    assert not envelope.admits_pair("hydraulic_pressure_kpa", "forklift/battery-pack")


def test_an_individually_valid_metric_and_subject_type_can_still_be_an_invalid_pair():
    """THE defect. Both halves are in the envelope; the combination never was.

    `battery_temp_c` is a supported metric. `forklift/hydraulic-system` is a supported
    subject type. `admits_metric(m) and admits_subject_type(s)` was true, so the assurance
    layer recorded a verified applicability for a temperature series read off a hydraulic
    system -- and `predict_degradation` orients the sign of the trend BY METRIC, so that
    is not a worse answer, it is an answer to a question nobody asked.

    The refusal must be the PAIR refusal, not the part-segment refusal that also fires on
    this fixture. `verify_bindings` orders the pair check above the part check for exactly
    that reason, and the message assertion is what holds the ordering in place.
    """
    with pytest.raises(ValueError, match="declares no applicability for"):
        T.deliver(assurance=T.assurance(applicability=ApplicabilityAssertion(
            "degradation-baseline@1.3.0", "forklift/hydraulic-system", True,
            "metric within declared envelope")))


def test_an_unknown_subject_type_refuses_on_the_envelope_not_on_the_pair():
    """Two different faults with two different remedies. A subject type the model has
    never heard of is not the same as a combination it was not fitted for, and a suite
    that cannot tell them apart cannot show either check is reachable."""
    with pytest.raises(ValueError, match="the model's declared envelope admits"):
        T.deliver(assurance=T.assurance(applicability=ApplicabilityAssertion(
            "degradation-baseline@1.3.0", "wind-turbine/gearbox", True,
            "metric within declared envelope")))


def test_an_unknown_metric_cannot_reach_a_claim_at_all():
    """Refused one layer earlier than the pair, by the claim's own invariant.

    `PredictionClaim.__post_init__` checks the metric against the envelope it carries, so
    an unknown metric never gets as far as an applicability assertion about it.
    """
    from cai.contract import PredictionClaim

    honest = T.claim()
    with pytest.raises(ValueError, match="outside the claim's own declared envelope"):
        PredictionClaim(**{**honest.__dict__, "metric": "coolant_temp_c"})


def test_the_predictor_itself_refuses_an_unknown_metric():
    """The other half of the same rule, at the model rather than at the claim."""
    from datetime import timedelta

    from cai.predictor import OutsideApplicability, predict_degradation

    with pytest.raises(OutsideApplicability, match="not in declared envelope"):
        predict_degradation(metric="coolant_temp_c", values=(1.0, 2.0, 3.0),
                            horizon=timedelta(days=1))


def test_import_enforces_the_same_pair_semantics():
    """The wire half. `verify_bindings` runs at both boundaries, so this is the same
    check reached from the other side rather than a wire-side restatement of it."""
    def mutate(p):
        p["product"]["assurance"]["assurance_context"]["applicability"][
            "subject_type"] = "forklift/hydraulic-system"

    with pytest.raises(ValueError, match="declares no applicability for"):
        import_envelope(forged(mutate))
    with pytest.raises(ValueError, match="declares no applicability for"):
        import_historical_envelope(forged(mutate))


def test_an_applicability_verdict_of_NOT_valid_stays_expressible():
    """Reporting that a use is outside the envelope is the honest verdict and must remain
    sayable -- it abstains, with a reason. Only a claim TO validity is incoherent.

    Without this, the pair check would be a rule that refuses the truthful answer.
    """
    product = T.deliver(assurance=T.assurance(applicability=ApplicabilityAssertion(
        "degradation-baseline@1.3.0", "forklift/hydraulic-system", False,
        "this series came off a battery pack, not a hydraulic system")))

    assert product.determination is Determination.ABSTAINED
    assert blocked_for(product, "applicability")


# ===========================================================================
# THE REASON PATH. Connected is not the same as coherent.
# ===========================================================================


R = DerivationRelationship


_SCOPE_BY_RELATION = {
    # What the graph actually stamps on each relation, so a fixture exercising TOPOLOGY
    # is not simultaneously asserting a temporal shape the producing system cannot hold.
    # Before the relation-specific joins existed these were all None, which meant every
    # topology fixture in this file described a walk the graph could not have emitted --
    # they passed because nothing was reading the field.
    R.HAS_COMPONENT: (T.t(1), None),
    R.ASSIGNED_TO: (T.t(8), None),
    R.SUPPORTS: (T.t(13, 5), T.t(13, 11)),
    R.LOADS: (None, None),
    R.FULFILLS: (None, None),
}


def step(relationship, subject, obj, hour=1) -> DerivationStep:
    # Looked up leniently: an unknown relation must still reach `DerivationStep`, which
    # is what refuses it by name. Coercing here would swallow that refusal.
    valid_from, valid_to = _SCOPE_BY_RELATION.get(relationship, (None, None))
    return DerivationStep(
        relationship, subject, obj, T.t(9, hour), "some-system", valid_from, valid_to
    )


def walk(*steps) -> ConsequenceDerivation:
    return ConsequenceDerivation(
        rule_version="context-rules@0.8.0",
        knowledge_cutoff=T.t(12, 7),
        evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)),
        steps=steps,
    )


REFERENCE = (
    (R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
    (R.ASSIGNED_TO, "asset-4417", "zone-3"),
    (R.SUPPORTS, "zone-3", "win-9"),
    (R.LOADS, "win-9", "ship-22"),
    (R.FULFILLS, "ship-22", "commit-7"),
)


def test_the_real_five_relation_path_forms():
    """The twin. A topology rule that refused the reference walk would refuse everything,
    and every refusal below would pass against it."""
    real = walk(*(step(*s) for s in REFERENCE))

    assert real.root_entity == "asset-4417"
    assert real.terminal_entity == "commit-7"
    assert real.explain() == (
        "HAS_COMPONENT(asset-4417,battery-pack-1) -> ASSIGNED_TO(asset-4417,zone-3) -> "
        "SUPPORTS(zone-3,win-9) -> LOADS(win-9,ship-22) -> FULFILLS(ship-22,commit-7)"
    )


# ---------------------------------------------------------------------------
# CARDINALITY. Topology and temporal validity were both closed, and the walk
# could still be a shape the graph refuses to emit.
# ---------------------------------------------------------------------------


def scoped(relationship, subject, obj, valid_from=None, valid_to=None):
    """A step with an explicitly chosen interval, for building a second branch."""
    return DerivationStep(
        relationship, subject, obj, T.t(9, 1), "some-system", valid_from, valid_to
    )


def two_branch_walk() -> tuple[DerivationStep, ...]:
    """Two complete, individually valid commercial branches from one zone.

    Nothing here is temporally wrong, which is the point. Both loading windows overlap
    the evaluated window. The assignment and the component hold at BOTH window openings,
    so the relation-specific joins the previous wave added all pass. Each branch is a
    correct chain of correct relations over real entities.

    The walk is impossible for one reason only: the graph selects a single loading
    window and refuses outright when two overlap the horizon, because two windows is a
    data defect rather than a richer answer. So this is a derivation the producer cannot
    emit, presented to an importer that had no rule about how many of anything a walk may
    contain.
    """
    return (
        scoped(R.HAS_COMPONENT, "asset-4417", "battery-pack-1", T.t(1), None),
        scoped(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(8), None),
        scoped(R.SUPPORTS, "zone-3", "win-9", T.t(13, 5), T.t(13, 11)),
        scoped(R.LOADS, "win-9", "ship-22"),
        scoped(R.FULFILLS, "ship-22", "commit-7"),
        scoped(R.SUPPORTS, "zone-3", "win-10", T.t(13, 6), T.t(13, 12)),
        scoped(R.LOADS, "win-10", "ship-23"),
        scoped(R.FULFILLS, "ship-23", "commit-7"),
    )


def test_the_graph_refuses_two_overlapping_loading_windows():
    """THE PRODUCER HALF. Establish that this state is one the graph will not emit.

    Without this, the refusal below could be a rule invented for the wire that the live
    system does not actually have -- which is the same defect as the missing rule,
    pointing the other way.
    """
    from cai.context import LoadingWindow, Shipment

    g = T.graph()
    g.windows.append(LoadingWindow(
        "win-10", "zone-3", T.t(13, 6), T.t(13, 12), "ship-23", recorded_at=T.t(9),
        source_system="dock-scheduler"))
    g.shipments["ship-23"] = Shipment(
        "ship-23", "commit-7", recorded_at=T.t(9), source_system="transport-management")

    impact = g.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=T.t(12, 7), horizon_end=T.t(15, 7),
        transaction_time_cutoff=T.t(12, 7),
    )

    assert not impact.derived
    assert any("loading windows" in a and "overlap" in a for a in impact.ambiguities)


def test_a_walk_carrying_two_complete_commercial_branches_is_refused():
    """THE ATTACK. Strict import must not accept what the graph just refused."""
    with pytest.raises(ValueError, match="SUPPORTS"):
        walk(*two_branch_walk())


def test_a_commitment_consequence_requires_the_whole_commercial_chain():
    """One of each, not merely at most one of each.

    A walk stopping at the zone is a legitimate DOWNTIME path and is not a commitment
    path: without SUPPORTS/LOADS/FULFILLS nothing establishes which promise is exposed.
    `terminal_entity == commitment_id` alone did not catch it -- a two-step walk whose
    last object happens to be the commitment satisfies that comparison.
    """
    from cai.consequence import CustomerCommitmentConsequence

    truncated = walk(
        step(R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
        step(R.ASSIGNED_TO, "asset-4417", "commit-7"),
    )
    with pytest.raises(ValueError, match="SUPPORTS|LOADS|FULFILLS|commercial"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(T.t(13, 5), T.t(13, 11)), truncated,
            commitment_id="commit-7",
            commitment_description="next-day delivery window",
            counterparty="customer A",
        )


def test_a_commitment_consequence_forms_without_a_component_step():
    """HAS_COMPONENT IS OPTIONAL, and the reference API is why.

    `ContextGraph.derive_impact` takes `component_id: str | None = None` and emits the
    HAS_COMPONENT step only when one was supplied. Requiring it on the wire would refuse
    a walk the producer emits whenever the claim is about the whole machine rather than
    a part of it -- inventing a constraint the live system does not have, which is the
    mirror image of the defect above.
    """
    from cai.consequence import CustomerCommitmentConsequence

    componentless = walk(
        step(R.ASSIGNED_TO, "asset-4417", "zone-3"),
        step(R.SUPPORTS, "zone-3", "win-9"),
        step(R.LOADS, "win-9", "ship-22"),
        step(R.FULFILLS, "ship-22", "commit-7"),
    )
    consequence = CustomerCommitmentConsequence(
        "CUSTOMER_COMMITMENT", TimeInterval(T.t(13, 5), T.t(13, 11)), componentless,
        commitment_id="commit-7",
        commitment_description="next-day delivery window",
        counterparty="customer A",
    )
    assert consequence.derivation.terminal_entity == "commit-7"


def test_the_downtime_path_is_bounded_on_its_own_terms():
    """DOWNTIME is a rooted PREFIX, not a commitment chain with pieces missing.

    Forcing the commercial cardinality onto it would refuse the two-step walk the graph
    emits for an asset whose zone supports no window -- which is precisely the case this
    second consequence type exists to carry. It still may not carry two of anything.
    """
    from cai.consequence import DowntimeConsequence

    complete = DowntimeConsequence(
        "DOWNTIME", TimeInterval(T.t(13, 5), T.t(13, 11)),
        walk(
            step(R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
            step(R.ASSIGNED_TO, "asset-4417", "zone-3"),
        ),
        asset_id="asset-4417", expected_hours_lost=6.0, affected_operation="loading",
    )
    assert complete.derivation.root_entity == "asset-4417"

    # ...and the at-most-one rule still applies to it, from one scope up.
    with pytest.raises(ValueError, match="at most one ASSIGNED_TO"):
        walk(
            step(R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
            step(R.ASSIGNED_TO, "asset-4417", "zone-3"),
            scoped(R.ASSIGNED_TO, "asset-4417", "zone-4", T.t(8), None),
        )


def test_strict_import_refuses_the_two_branch_walk():
    """The same attack, arriving on the wire rather than built in process.

    THE SECOND BRANCH REUSES THE REAL WALK'S SOURCE SYSTEMS, and that detail decides
    whether this test proves anything. Built with a made-up `source_system`, the record
    is refused -- but by the entitlement check, because the clearance does not licence a
    feed called "some-system". The attack would have been reported as defeated by a rule
    that never looked at the walk's shape at all.
    """
    payload = IntelligenceEnvelope(product=T.deliver()).as_record()
    derivation = payload["product"]["candidate"]["business_consequence"]["derivation"]
    honest = derivation["steps"]
    by_relation = {s["relationship"]: s for s in honest}
    second_branch = [
        {**by_relation["SUPPORTS"], "object": "win-10",
         "valid_from": T.t(13, 6).isoformat(), "valid_to": T.t(13, 12).isoformat()},
        {**by_relation["LOADS"], "subject": "win-10", "object": "ship-23"},
        {**by_relation["FULFILLS"], "subject": "ship-23"},
    ]
    derivation["steps"] = honest + second_branch

    with pytest.raises((ValueError, TypeError), match="at most one SUPPORTS"):
        import_envelope(payload)


def test_the_relationship_vocabulary_is_closed():
    """It was `str`. A forger could keep the real entities, keep the walk connected, and
    relabel the relations -- producing a well-formed, fully connected, entirely
    nonsensical derivation that every structural check passed."""
    assert [r.value for r in R] == [
        "HAS_COMPONENT", "ASSIGNED_TO", "SUPPORTS", "LOADS", "FULFILLS"]
    with pytest.raises(ValueError, match="not a relationship this system walks"):
        step("CAUSES", "asset-4417", "commit-7")


def test_a_relabelled_but_connected_walk_is_refused():
    """The forgery reachability alone accepts.

    Every step joins to the one before it, every entity is real, and the sequence means
    nothing: an asset does not LOAD a zone, and a zone does not HAVE a loading window as a
    component. Connectivity is a property of the entities; this is a property of the
    relations, and only the second one makes a derivation an argument.
    """
    with pytest.raises(ValueError, match="may only continue from"):
        walk(
            step(R.LOADS, "asset-4417", "zone-3"),
            step(R.HAS_COMPONENT, "zone-3", "win-9"),
        )


@pytest.mark.parametrize("name,steps,pattern", [
    (
        "HAS_COMPONENT must leave the root",
        (
            (R.ASSIGNED_TO, "asset-4417", "zone-3"),
            (R.HAS_COMPONENT, "zone-3", "battery-pack-1"),
        ),
        "may only continue from the walk's root",
    ),
    (
        "ASSIGNED_TO must leave the root",
        (
            (R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
            (R.ASSIGNED_TO, "battery-pack-1", "zone-3"),
        ),
        "may only continue from the walk's root",
    ),
    (
        "SUPPORTS continues from the assigned zone",
        (
            (R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
            (R.SUPPORTS, "battery-pack-1", "win-9"),
        ),
        "may only continue from ASSIGNED_TO",
    ),
    (
        "LOADS continues from the loading window",
        (
            (R.ASSIGNED_TO, "asset-4417", "zone-3"),
            (R.LOADS, "zone-3", "ship-22"),
        ),
        "may only continue from SUPPORTS",
    ),
    (
        "FULFILLS continues from the shipment",
        (
            (R.ASSIGNED_TO, "asset-4417", "zone-3"),
            (R.SUPPORTS, "zone-3", "win-9"),
            (R.FULFILLS, "win-9", "commit-7"),
        ),
        "may only continue from LOADS",
    ),
])
def test_each_relation_may_only_continue_from_where_it_belongs(name, steps, pattern):
    """Five entries in a table, five tests. Each fixture is CONNECTED -- every step starts
    somewhere an earlier step reached -- so none of them passes on the reachability rule,
    and each names the relation whose predecessor it violated."""
    with pytest.raises(ValueError, match=pattern):
        walk(*(step(*s) for s in steps))


def test_a_walk_with_a_hole_in_it_is_still_refused():
    """The reachability rule the predecessor table did not replace."""
    with pytest.raises(ValueError, match="which nothing earlier in the walk reached"):
        walk(
            step(R.ASSIGNED_TO, "asset-4417", "zone-3"),
            step(R.FULFILLS, "ship-22", "commit-7"),
        )


def test_a_commitment_consequence_terminates_at_its_own_commitment():
    """The path must arrive at this conclusion, not merely mention it."""
    from cai.consequence import CustomerCommitmentConsequence

    # `ship-22` rather than an entity the walk never touches. An absent commitment is
    # refused one check earlier, by "the derivation never reaches it", so a fixture naming
    # `commit-999` would pass this test while the terminal rule was deleted. Naming an
    # INTERMEDIATE entity satisfies the reachability half and isolates the terminal one.
    with pytest.raises(ValueError, match="the path does not arrive at this conclusion"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(T.t(13, 5), T.t(13, 11)),
            walk(*(step(*s) for s in REFERENCE)),
            commitment_id="ship-22", commitment_description="a shipment, not a promise",
            counterparty="customer B",
        )


def test_a_commitment_consequence_the_walk_never_reaches_is_refused_earlier():
    """The other half, so neither check is proved only by the other."""
    from cai.consequence import CustomerCommitmentConsequence

    with pytest.raises(ValueError, match="never reaches"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(T.t(13, 5), T.t(13, 11)),
            walk(*(step(*s) for s in REFERENCE)),
            commitment_id="commit-999", commitment_description="somebody else's promise",
            counterparty="customer B",
        )


def test_a_downtime_consequence_must_be_rooted_at_its_own_asset():
    """Downtime has no terminus to require -- the walk may legitimately stop at the zone --
    so the base "the asset is somewhere in the entity set" check was all that held it, and
    a flat set is satisfied by an asset the walk merely passes through.

    The rooted equivalent says where the path BEGINS instead of where it ends, which is
    the honest difference between the two consequence types.
    """
    rooted_elsewhere = walk(
        step(R.HAS_COMPONENT, "asset-9999", "battery-pack-1"),
        step(R.ASSIGNED_TO, "asset-9999", "zone-3"),
    )
    with pytest.raises(ValueError, match="rooted at 'asset-9999' but this downtime"):
        DowntimeConsequence(
            "DOWNTIME", TimeInterval(T.t(13, 5), T.t(13, 11)), rooted_elsewhere,
            asset_id="battery-pack-1", expected_hours_lost=6.0,
            affected_operation="loading",
        )


def test_the_downtime_consequence_its_own_walk_supports_still_forms():
    """Twin for the rule above, and the reason the second consequence type exists: it must
    NOT need to reach a commitment."""
    consequence = DowntimeConsequence(
        "DOWNTIME", TimeInterval(T.t(13, 5), T.t(13, 11)),
        walk(
            step(R.HAS_COMPONENT, "asset-4417", "battery-pack-1"),
            step(R.ASSIGNED_TO, "asset-4417", "zone-3"),
        ),
        asset_id="asset-4417", expected_hours_lost=6.0, affected_operation="loading",
    )

    assert consequence.is_actionable()
    assert consequence.derivation.terminal_entity == "zone-3"


def test_the_walk_must_be_rooted_at_the_observed_asset_not_merely_mention_it():
    """`entities()` is a flat set, so "the observed asset appears in the walk" was
    satisfied by an asset appearing anywhere -- including as the OBJECT of a step that
    arrived at it from something else entirely.

    Here the walk is a real, connected, vocabulary-valid path rooted at another machine
    that happens to pass through the observed one. Every earlier check is satisfied.
    """
    from cai.binding import subject_binding_mismatch

    passing_through = walk(
        step(R.HAS_COMPONENT, "asset-0001", "asset-4417"),
        step(R.ASSIGNED_TO, "asset-0001", "zone-3"),
        step(R.SUPPORTS, "zone-3", "win-9"),
        step(R.LOADS, "win-9", "ship-22"),
        step(R.FULFILLS, "ship-22", "commit-7"),
    )
    # A SECOND HAS_COMPONENT step used to sit above, naming the component the action
    # targets so the candidate's action-target rule would not fire before this test
    # reached the binding it is named for. Two steps of one relation is now refused one
    # scope up, so the action is re-pointed at the asset the walk does reach instead.
    # Same purpose, achieved without a shape the graph cannot emit.
    targets_the_asset = T.ActionRecommendation(
        "act-001", T.ActionType.INSPECT, "asset-4417", "maintenance", T.t(13, 3),
        TimeInterval(T.t(13, 5), T.t(13, 11)),
        "degradation signal", T.Priority.BEFORE_NEXT_USE,
    )
    candidate = T.candidate(
        consequence=T.commitment(derivation=passing_through), action=targets_the_asset
    )

    reason = subject_binding_mismatch(candidate, frozenset({"asset-4417"}))
    assert reason is not None
    assert "only passes through it" in reason


def test_the_semantic_rule_version_must_be_the_versions_the_walk_ran_under():
    """One fact recorded twice, with nothing comparing the copies -- the shipped fixture
    itself once carried 0.7.0 on the evidence and 0.8.0 on the derivation."""
    from cai.contract import EvidenceSnapshot

    c = T.candidate()
    drifted = EvidenceSnapshot(**{
        **T.evidence(c.prediction_claim).__dict__,
        "semantic_rule_version": "context-rules@0.7.0",
    })
    with pytest.raises(ValueError, match="two answers out of one bundle"):
        T.deliver(candidate=c, evidence=drifted)


def test_the_wire_refuses_a_relationship_outside_the_vocabulary():
    """The schema closes the vocabulary; the domain closes which relation may follow
    which. Both are needed: an enum alone permits any ordering."""
    from cai.envelope import SchemaViolation

    def mutate(p):
        steps = p["product"]["candidate"]["business_consequence"]["derivation"]["steps"]
        steps[0]["relationship"] = "CAUSES"

    with pytest.raises(SchemaViolation, match="relationship"):
        import_envelope(forged(mutate))


def test_the_wire_refuses_a_relabelled_but_connected_walk():
    """The domain half, on the wire. Every relation here is in the vocabulary, so the
    schema passes it and the topology rule is what refuses it."""
    def mutate(p):
        steps = p["product"]["candidate"]["business_consequence"]["derivation"]["steps"]
        # LOADS and FULFILLS SWAP LABELS, rather than SUPPORTS becoming a second LOADS.
        # The old mutation produced two LOADS steps, which the cardinality rule now
        # refuses one check earlier -- so this test would have reported the topology rule
        # working while never reaching it. Swapping keeps every relation appearing once.
        #
        # FULFILLS(win-9,ship-22) then LOADS(ship-22,commit-7): in the vocabulary,
        # connected end to end, both relations unscoped exactly as the graph emits them,
        # and FULFILLS may not continue from SUPPORTS.
        swap = {"LOADS": "FULFILLS", "FULFILLS": "LOADS"}
        for s in steps:
            if s["relationship"] in swap:
                s["relationship"] = swap[s["relationship"]]

    with pytest.raises(ValueError, match="may only continue from"):
        import_envelope(forged(mutate))


def test_the_reference_walk_survives_the_wire_unchanged():
    """Twin for both wire refusals."""
    rebuilt = import_envelope(wire()).product.candidate.business_consequence.derivation

    assert [s.relationship for s in rebuilt.steps] == [
        R.HAS_COMPONENT, R.ASSIGNED_TO, R.SUPPORTS, R.LOADS, R.FULFILLS]
    assert rebuilt.root_entity == "asset-4417"
    assert rebuilt.terminal_entity == "commit-7"


# ===========================================================================
# THE RELATION-SPECIFIC TEMPORAL JOINS.
#
# The first attempt at this rule required a step's validity interval merely to
# OVERLAP the evaluated window. Control Tower produced the counterexample that
# breaks it, and it is worth stating in full because the shape recurs:
#
#     evaluated window   12 Jun 07:00 -> 15 Jun 07:00
#     ASSIGNED_TO        12 Jun 07:00 -> 13 Jun 04:00
#     loading window     opens 13 Jun 05:00
#
# The assignment overlaps the evaluated window, so the generic rule passed it.
# The graph refuses the consequence outright -- it rechecks `covers(window.opens)`,
# and the forklift left that zone an hour before the truck arrived. Strict import
# admitted a derivation the release path could not have emitted.
#
# The loading-window opening is not a fact the reader lacks. The SUPPORTS step
# carries it as `valid_from`. So the checks below are local, and each one names
# the graph line it mirrors.
# ===========================================================================


TICK_ = timedelta(microseconds=1)

OPENS_ = T.t(13, 5)
"""When win-9 opens, in the reference graph. The second moment every join is checked at."""
CLOSES_ = T.t(13, 11)
HORIZON_ = T.t(12, 7)


def joined_walk(
    *,
    assigned_from=T.t(8),
    assigned_to=None,
    installed_from=T.t(1),
    removed_at=None,
    opens=OPENS_,
    closes=CLOSES_,
):
    """The reference five-relation walk with its two time-scoped joins configurable.

    Built by hand rather than from the graph BECAUSE the graph would refuse most of
    these -- which is the point. These are the forgeries an attacker hands to strict
    import, and the question is whether import refuses what the graph refuses.
    """
    return ConsequenceDerivation(
        rule_version="context-rules@0.8.0",
        knowledge_cutoff=HORIZON_,
        evaluated_window=TimeInterval(HORIZON_, T.t(15, 7)),
        steps=(
            DerivationStep(R.HAS_COMPONENT, "asset-4417", "battery-pack-1", T.t(8, 1),
                           "asset-register", installed_from, removed_at),
            DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(8, 1),
                           "yard-management", assigned_from, assigned_to),
            DerivationStep(R.SUPPORTS, "zone-3", "win-9", T.t(9),
                           "dock-scheduler", opens, closes),
            DerivationStep(R.LOADS, "win-9", "ship-22", T.t(9),
                           "transport-management"),
            DerivationStep(R.FULFILLS, "ship-22", "commit-7", T.t(9),
                           "order-management"),
        ),
    )


def test_the_reference_walk_with_both_joins_scoped_still_forms():
    """The twin. Every refusal below is worthless if the honest walk fails too."""
    honest = joined_walk()

    assert honest.terminal_entity == "commit-7"
    assert [s.valid_from for s in honest.steps][3:] == [None, None]


# --- ASSIGNED_TO, at the loading-window opening -----------------------------


def test_an_assignment_ending_a_microsecond_before_the_window_opens_is_refused():
    """CT's counterexample, to the microsecond. The assignment overlaps the evaluated
    window and the asset is somewhere else by the time the truck arrives."""
    with pytest.raises(ValueError, match="not in force when the loading window opens"):
        joined_walk(assigned_to=OPENS_ - TICK_)


def test_an_assignment_ending_exactly_when_the_window_opens_is_refused():
    """Half-open, like every interval in this package: `valid_to` is exclusive, so an
    assignment ending at 05:00 was already over at 05:00. `Assignment.covers` agrees,
    and now it agrees because both call the same function."""
    with pytest.raises(ValueError, match="not in force when the loading window opens"):
        joined_walk(assigned_to=OPENS_)


def test_an_assignment_lasting_a_microsecond_past_the_window_opening_is_admitted():
    """The other side of the same line. Without this the two tests above would pass
    against a rule that refused every bounded assignment."""
    assert joined_walk(assigned_to=OPENS_ + TICK_).steps


def test_an_assignment_beginning_after_the_horizon_opens_is_refused():
    """The graph's FIRST check -- `a.covers(horizon_start)` -- which the overlap rule
    also missed in the other direction: an assignment starting mid-window overlaps it."""
    with pytest.raises(ValueError, match="not in force when the evaluated window opens"):
        joined_walk(assigned_from=HORIZON_ + TICK_)


def test_an_assignment_beginning_exactly_at_the_horizon_opening_is_admitted():
    """`valid_from` is inclusive. The twin for the test above."""
    assert joined_walk(assigned_from=HORIZON_).steps


def test_an_assignment_with_no_start_is_refused():
    """`Assignment.valid_from` is a required field on the graph's own record, so a walk
    that omits it describes a row the producing system cannot hold."""
    with pytest.raises(ValueError, match="does not say when the assignment began"):
        joined_walk(assigned_from=None)


# --- HAS_COMPONENT, at the same two moments --------------------------------


def test_a_component_removed_before_the_window_opens_is_refused():
    """`part.fitted_at(window.opens)` in the graph. A pack pulled for service the night
    before cannot be what fails during the loading window."""
    with pytest.raises(ValueError, match="not in force when the loading window opens"):
        joined_walk(removed_at=OPENS_ - TICK_)


def test_a_component_removed_exactly_when_the_window_opens_is_refused():
    with pytest.raises(ValueError, match="not in force when the loading window opens"):
        joined_walk(removed_at=OPENS_)


def test_a_component_still_fitted_through_the_window_opening_is_admitted():
    assert joined_walk(removed_at=OPENS_ + TICK_).steps


def test_a_component_fitted_after_the_horizon_opens_is_refused():
    """`component.fitted_at(horizon_start)`. A pack fitted after the decision was not
    the pack that produced the readings."""
    with pytest.raises(ValueError, match="not in force when the evaluated window opens"):
        joined_walk(installed_from=HORIZON_ + TICK_)


def test_a_component_with_neither_end_scoped_is_admitted():
    """`fitted_at` treats both ends open as always-fitted, and so must this. A rule that
    demanded an interval would refuse a component record the graph emits unscoped."""
    assert joined_walk(installed_from=None, removed_at=None).steps


# --- SUPPORTS, whose interval IS the loading window ------------------------


def test_a_loading_window_with_an_open_end_is_refused():
    """The graph copies `opens` and `closes` straight off the window record, so a
    half-scoped SUPPORTS is not a weaker claim -- it leaves the moment every other join
    is checked against undefined, which is the check silently not running."""
    for missing in ({"opens": None}, {"closes": None}):
        with pytest.raises(ValueError, match="loading window with an open end"):
            joined_walk(**missing)


def test_a_loading_window_starting_when_the_evaluated_window_closes_is_refused():
    """`w.overlaps(horizon_start, horizon_end)` is how the graph selects windows at all."""
    end = T.t(15, 7)
    assert joined_walk(opens=end - TICK_, closes=end + TICK_).steps
    with pytest.raises(ValueError, match="does not overlap the window"):
        joined_walk(opens=end, closes=end + TICK_)


def test_a_loading_window_ending_when_the_evaluated_window_opens_is_refused():
    assert joined_walk(opens=HORIZON_ - TICK_, closes=HORIZON_ + TICK_).steps
    with pytest.raises(ValueError, match="does not overlap the window"):
        joined_walk(opens=HORIZON_ - TICK_, closes=HORIZON_)


# --- LOADS and FULFILLS carry no interval, because no source has one -------


def test_a_time_scoped_shipment_relation_is_refused():
    """`Shipment` and `CustomerCommitment` have no validity field. A scoped LOADS is not
    a stricter claim; it is a temporal fact no system in this scenario could supply."""
    honest = joined_walk()
    for index, relation in ((3, "LOADS"), (4, "FULFILLS")):
        steps = list(honest.steps)
        original = steps[index]
        steps[index] = DerivationStep(
            original.relationship, original.subject, original.object,
            original.recorded_at, original.source_system, T.t(1), None,
        )
        with pytest.raises(ValueError, match=f"{relation} is not a time-scoped relation"):
            ConsequenceDerivation(
                rule_version=honest.rule_version,
                knowledge_cutoff=honest.knowledge_cutoff,
                evaluated_window=honest.evaluated_window,
                steps=tuple(steps),
            )


# --- AND THE POINT OF ALL OF IT: the two paths admit the same universe -----


def _graph_with(**over):
    """The reference graph with the assignment and component overridden."""
    from cai.context import Assignment, Component

    g = T.graph()
    g.assignments.clear()
    g.assignments.append(Assignment(
        "asset-4417", "zone-3",
        over.get("assigned_from", T.t(8)), T.t(8, 1),
        source_system="yard-management",
        valid_to=over.get("assigned_to"),
    ))
    g.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=T.t(8, 1),
        source_system="asset-register",
        installed_from=over.get("installed_from", T.t(1)),
        removed_at=over.get("removed_at"),
    )
    return g


def _graph_derives(**over) -> bool:
    ctx = T.context()
    return _graph_with(**over).derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=ctx.prediction_window.start,
        horizon_end=ctx.prediction_window.end,
        transaction_time_cutoff=ctx.knowledge_cutoff,
    ).derived


def _import_admits(**over) -> bool:
    try:
        joined_walk(**over)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("name,over", [
    ("honest", {}),
    ("assignment ends a microsecond before the window opens", {"assigned_to": OPENS_ - TICK_}),
    ("assignment ends exactly when the window opens", {"assigned_to": OPENS_}),
    ("assignment lasts a microsecond past the opening", {"assigned_to": OPENS_ + TICK_}),
    ("assignment begins after the horizon opens", {"assigned_from": HORIZON_ + TICK_}),
    ("component removed before the window opens", {"removed_at": OPENS_ - TICK_}),
    ("component removed exactly when the window opens", {"removed_at": OPENS_}),
    ("component still fitted past the opening", {"removed_at": OPENS_ + TICK_}),
    ("component fitted after the horizon opens", {"installed_from": HORIZON_ + TICK_}),
])
def test_the_import_boundary_and_the_live_graph_admit_the_same_states(name, over):
    """THE GOVERNING RULE, TESTED DIRECTLY RATHER THAN ARGUED.

    Nine operational states, each fed to both paths. The graph either derives or refuses;
    strict import either admits the corresponding walk or refuses it. If the two ever
    disagree, a record exists that the import boundary accepts and the release path could
    not have produced -- which is the one question this repository is built to answer.

    Written as a table on purpose. The previous rule passed six of these nine.
    """
    assert _import_admits(**over) is _graph_derives(**over), name


def test_an_impact_that_derived_without_reaching_a_commitment_says_so():
    """`not derived or commitment is None`, and the `or` is load-bearing.

    `BusinessImpact` is a plain record with no invariant tying `derived` to `commitment`,
    so the inconsistent pair is constructible -- and with `and` in its place, an impact
    claiming to have derived while reaching no commitment would render a commitment
    sentence with nothing behind it.
    """
    from cai.context import BusinessImpact

    inconsistent = BusinessImpact(
        derived=True, commitment=None, steps=T.derivation().steps,
        rule_version="context-rules@0.8.0",
        prediction_horizon=(T.t(12, 7), T.t(15, 7)),
        transaction_time_cutoff=T.t(12, 7),
    )

    assert inconsistent.economic_consequence_text() == (
        "no customer commitment reached by derivation")
