"""The comparisons that decide, asserted at the instant they decide at.

WHERE THIS LIST CAME FROM
-------------------------
`mutation_generator.py` derives its candidates from the AST of `src/cai` and knows
nothing about the tests, which is the whole reason it can find behaviour nothing asserts.
Everything below is a mutation that SURVIVED the first honest run: a `<` swapped for a
`<=`, a branch replaced with `pass`, a refusal reason replaced with a different one, and
the whole suite stayed green.

Most are boundaries. A policy floor is `confidence < floor`, not `<=`, so a confidence
exactly AT the floor releases -- that is what declaring a floor means, and nothing said
so. An entitlement is valid from `valid_from` inclusive and to `valid_to` exclusive, and
nothing exercised either end. A claim may be stamped valid until the exact close of the
window it describes and not one microsecond past it.

The rest are branches nothing walked: the DOWNTIME arm of the consequence dispatch, the
paths that carry a non-empty `prerequisites`, `ambiguities` or `note` across the wire, the
UNKNOWN entitlement state, the conflict list reaching `blocking_reasons`.

Each test pairs the instant ON the boundary with one microsecond past it, because a test
that only asserts one side kills a mutation in only one direction.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

import test_formation as T
from cai.decision import TimeInterval
from cai.envelope import IntelligenceEnvelope, import_envelope, parse_envelope
from cai.policy import ReleasePolicy
from cai.product import Determination, ProductStatus

TICK = timedelta(microseconds=1)


def wire(**over) -> dict:
    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


# ===========================================================================
# POLICY THRESHOLDS. A floor is a floor: at it, you are above it.
# ===========================================================================


def test_a_confidence_exactly_at_the_identity_floor_releases():
    """`confidence < floor`, not `<=`. A policy that refused AT its own floor would be
    a policy whose stated number is not the number it applies."""
    at_floor = ReleasePolicy().identity_floor

    assert T.deliver(assurance=T.assurance(
        identity=T.IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0",
                                     at_floor))).determination is Determination.DELIVERED


def test_a_confidence_one_step_below_the_identity_floor_withholds():
    at_floor = ReleasePolicy().identity_floor
    product = T.deliver(assurance=T.assurance(
        identity=T.IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0",
                                     at_floor - 0.000001)))

    assert product.determination is Determination.ABSTAINED
    assert any("identity" in r for r in product.assurance.blocking_reasons)


def test_an_evidence_strength_exactly_at_the_deliverable_minimum_releases():
    """The support dimension's boundary, moved from the CLAIM side to the POLICY side.

    Substituting `evidence_strength` on the claim does not work and the reason is worth
    recording: the replay binds it, so a hand-set strength makes the claim differ from
    what the recorded predictor produces and the record abstains for integrity instead --
    passing a test that claims to exercise the floor. The confidence heuristic is
    `0.45 + 0.06n`, which cannot land on 0.60 for any admissible n either.

    Moving the policy to meet the claim exercises the same comparison honestly, and
    exercises the policy seam while it is there.
    """
    strength = T.claim().evidence_strength

    at_minimum = T.deliver(policy=ReleasePolicy(min_evidence_strength=strength))
    just_above = T.deliver(policy=ReleasePolicy(min_evidence_strength=strength + 0.000001))

    assert at_minimum.determination is Determination.DELIVERED
    assert just_above.determination is Determination.ABSTAINED
    assert any("evidence strength" in r for r in just_above.assurance.blocking_reasons)


def test_an_unresolved_identity_conflict_is_reported_by_the_policy():
    """The `identity.conflicts` branch of `ReleasePolicy.evaluate`, which nothing walked
    at the release path -- only at the import boundary."""
    product = T.deliver(assurance=T.assurance(
        identity=T.IdentityAssertion(
            "asset-4417/battery-pack", "resolver-a", "1.0", 0.97,
            conflicts=("fleet-register says asset-4417, telematics says asset-9001",))))

    assert product.determination is Determination.ABSTAINED
    assert any("unresolved conflicts" in r for r in product.assurance.blocking_reasons)


def test_a_temporal_assertion_that_is_not_valid_is_reported_by_the_policy():
    product = T.deliver(assurance=T.assurance(temporal=T.TemporalAssertion(
        T.t(12, 7), T.t(12, 7), T.t(12, 7), False,
        basis="the feature view was rebuilt after the decision")))

    assert product.determination is Determination.ABSTAINED
    assert any("point-in-time" in r for r in product.assurance.blocking_reasons)


def test_the_conflicts_a_bundle_carries_reach_the_blocking_reasons():
    """`EvidenceAssessment.blocking_reasons` appends `unresolved_conflicts=...`, and the
    integrity dimension already blocks -- so the branch adds nothing to the OUTCOME and
    everything to what a reader is told. It sends an engineer to the two systems that
    disagree instead of to a hash."""
    from cai.bitemporal import Observation, ObservationLog

    log = ObservationLog()
    for observation in T.observations():
        log.record(observation)
    first = T.observations()[0]
    log.record(Observation(first.observation_id, first.subject, first.metric, 999.9,
                           first.valid_time, first.transaction_time, "source-b"))

    product = T.deliver(observation_log=log)
    assert any("unresolved_conflicts=" in r for r in product.assurance.blocking_reasons)


def test_an_entitlement_with_no_basis_is_UNKNOWN_and_never_permission():
    """`EntitlementState.UNKNOWN` -- "an unrecorded right is not a right". The enum member
    existed and the branch that produces it was never walked from the release path.

    `EntitlementAssertion` refuses a blank basis, so the assertion is real and the basis
    is emptied afterwards -- which is the only way this state is reachable at all, and
    worth knowing.
    """
    from cai.candidate import EntitlementAssertion
    from cai.evidence import EntitlementState

    honest = T.entitlement()
    unstated = EntitlementAssertion.__new__(EntitlementAssertion)
    object.__setattr__(unstated, "__dict__", {**honest.__dict__, "basis": ""})

    product = T.deliver(assurance=T.assurance(entitlement=unstated))
    assert product.determination is Determination.ABSTAINED
    assert product.assurance.assessed.evidence_assessment.entitlement is (
        EntitlementState.UNKNOWN)


# ===========================================================================
# ENTITLEMENT VALIDITY, WHICH IS A HALF-OPEN WINDOW LIKE EVERY OTHER.
# ===========================================================================


def test_a_clearance_permits_at_the_instant_it_becomes_valid():
    delivery = T.t(12, 7)

    assert T.deliver(assurance=T.assurance(
        entitlement=T.entitlement(valid_from=delivery))
    ).determination is Determination.DELIVERED
    withheld = T.deliver(assurance=T.assurance(
        entitlement=T.entitlement(valid_from=delivery + TICK)))
    assert withheld.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in withheld.assurance.blocking_reasons)


def test_a_clearance_has_expired_at_the_instant_it_becomes_invalid():
    """Exclusive at the far end. A clearance that ran out at 07:00 did not authorise a
    07:00 delivery."""
    delivery = T.t(12, 7)

    expired = T.deliver(assurance=T.assurance(
        entitlement=T.entitlement(valid_to=delivery)))
    assert expired.determination is Determination.ABSTAINED
    assert T.deliver(assurance=T.assurance(
        entitlement=T.entitlement(valid_to=delivery + TICK))
    ).determination is Determination.DELIVERED


@pytest.mark.parametrize("flag", ["may_use_source_data", "may_deliver_to_recipient"])
def test_both_permission_flags_are_required_not_either(flag):
    """`may_use_source_data and may_deliver_to_recipient`. Swapped to `or`, a clearance
    covering the data but not the recipient -- or the reverse -- authorises delivery."""
    product = T.deliver(assurance=T.assurance(entitlement=T.entitlement(**{flag: False})))

    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


# ===========================================================================
# PERISHABILITY AND LINEAGE, AT THE INSTANT.
# ===========================================================================


def test_a_claim_may_be_valid_until_the_exact_close_of_its_window():
    """The WINDOW bound, isolated from the deadline bound that now sits inside it.

    `valid_until` answers to two upper bounds -- the end of the window the claim
    predicts, and the deadline of the action it recommends -- and with the default
    fixture the deadline is by far the tighter one, so this test could no longer reach
    the rule it names. The action below is deliberately given a late deadline, which
    makes the window the binding bound again. Moving `valid_until` instead would have
    left the window rule asserted by nothing.
    """
    window_end = T.context().prediction_window.end
    late = T.ActionRecommendation(
        "act-001", T.ActionType.INSPECT, "battery-pack-1", "maintenance",
        window_end,
        TimeInterval(T.t(13, 5), window_end + timedelta(hours=1)),
        "degradation signal", T.Priority.ROUTINE,
    )
    unhurried = T.candidate(action=late)

    assert T.deliver(
        candidate=unhurried, valid_until=window_end
    ).determination is Determination.DELIVERED
    with pytest.raises(ValueError, match="cannot outlive the window"):
        T.deliver(candidate=unhurried, valid_until=window_end + TICK)


def test_a_product_expires_at_its_validity_horizon_not_after_it():
    """`moment >= valid_until` -- EXPIRED at the instant, not one tick later. A claim
    stamped valid until 03:00 is not actionable at 03:00."""
    horizon = T.action().due_by
    product = T.deliver(valid_until=horizon)

    assert product.status_at(horizon - TICK) is ProductStatus.ACTIVE
    assert product.status_at(horizon) is ProductStatus.EXPIRED


def test_a_status_event_applies_from_the_instant_it_happened():
    """`e.at <= moment`. An event applies at its own moment, not from the tick after --
    and events that have not yet occurred do not apply at all, which is what stops a
    retraction rewriting what an earlier reader was entitled to believe."""
    from cai.envelope import StatusEvent, StatusEventType

    at = T.t(13, 6)
    envelope = IntelligenceEnvelope(
        product=T.deliver(),
        status_events=(StatusEvent(StatusEventType.RETRACTED, at, "system",
                                   reason="pack replaced"),))

    assert envelope.status_at(at - TICK) is not ProductStatus.RETRACTED
    assert envelope.status_at(at) is ProductStatus.RETRACTED


def test_a_status_event_at_the_delivery_instant_is_permitted():
    """`event.at < delivery` refuses. An event AT delivery is simultaneous, not before
    it, and a rule that refused it would refuse a same-instant correction."""
    from cai.envelope import StatusEvent, StatusEventType

    delivery = T.t(12, 7)
    IntelligenceEnvelope(
        product=T.deliver(),
        status_events=(StatusEvent(StatusEventType.RETRACTED, delivery, "system",
                                   reason="issued in error"),))
    with pytest.raises(ValueError, match="predates delivery"):
        IntelligenceEnvelope(
            product=T.deliver(),
            status_events=(StatusEvent(StatusEventType.RETRACTED, delivery - TICK,
                                       "system", reason="issued in error"),))


def test_an_outcome_window_may_open_at_the_delivery_instant():
    """`observation_window.start < delivery` refuses. Opening AT delivery is the earliest
    honest window -- the recipient had the recommendation at that instant."""
    from cai.action import OutcomeObservation, OutcomeType
    from cai.lifecycle import DispositionEvent, DispositionState

    product = T.deliver()
    delivery = product.delivery_time

    def envelope_with(window_start):
        return IntelligenceEnvelope(
            product=product,
            lifecycle_events=(
                DispositionEvent(DispositionState.DELIVERED, delivery, "system"),
                DispositionEvent(DispositionState.IGNORED, T.t(12, 9), "ops"),
                DispositionEvent(DispositionState.OUTCOME_OBSERVED, T.t(13, 4), "ops"),
            ),
            outcome=OutcomeObservation(
                "out-1", OutcomeType.NO_FAILURE_OBSERVED,
                product.candidate.prediction_claim.subject,
                TimeInterval(window_start, T.t(13, 6)), T.t(13, 4), source="m",
                related_action_id=product.candidate.action.action_id),
        )

    assert envelope_with(delivery).outcome is not None
    with pytest.raises(ValueError, match="before the recommendation was delivered"):
        envelope_with(delivery - TICK)


def test_a_lifecycle_may_record_two_events_at_the_same_instant():
    """`later.at < earlier.at` refuses. Equal timestamps are not out of order, and a rule
    that refused them would refuse a trail written by a system with second resolution."""
    from cai.lifecycle import DispositionState, IllegalTransition, ProductLifecycle

    lifecycle = ProductLifecycle("asset-4417/battery-pack", product_id="ip-001")
    lifecycle.advance(DispositionState.DELIVERED, at=T.t(12, 7), actor="system")
    lifecycle.advance(DispositionState.ACKNOWLEDGED, at=T.t(12, 7), actor="ops")

    assert len(lifecycle.events) == 2
    with pytest.raises(IllegalTransition, match="precedes the previous event"):
        lifecycle.advance(DispositionState.ACCEPTED, at=T.t(12, 7) - TICK, actor="ops")


def test_an_imported_trail_may_carry_two_events_at_the_same_instant():
    """The same rule at the wire boundary, which has its own copy in `check_trail`."""
    from cai.lifecycle import DispositionEvent, DispositionState, IllegalTransition, check_trail

    same = (
        DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
        DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 7), "ops"),
    )
    check_trail(same)
    with pytest.raises(IllegalTransition, match="precedes the previous event"):
        check_trail((
            DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
            DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 7) - TICK, "ops"),
        ))


def test_an_action_may_fall_due_exactly_as_its_window_closes():
    """`due_by > window.end` refuses. Due AT the close is the last moment it could still
    change the outcome, and refusing it would refuse a legitimate instruction."""
    from cai.action import ActionRecommendation, ActionType

    window = TimeInterval(T.t(13, 5), T.t(13, 11))
    ActionRecommendation("act-1", ActionType.INSPECT, "battery-pack-1", "maintenance",
                         T.t(13, 11), window, "reason")
    with pytest.raises(ValueError, match="falls after the operational window closes"):
        ActionRecommendation("act-1", ActionType.INSPECT, "battery-pack-1", "maintenance",
                             T.t(13, 11) + TICK, window, "reason")


def test_two_intervals_touching_at_a_point_do_not_overlap():
    """`start < other.end and end > other.start`, both strict. Two intervals meeting at
    an instant share no duration, and a prediction window that ends as an exposure begins
    does not threaten it."""
    first = TimeInterval(T.t(12), T.t(13))
    touching_after = TimeInterval(T.t(13), T.t(14))
    overlapping = TimeInterval(T.t(13) - TICK, T.t(14))

    assert not first.overlaps(touching_after)
    assert not touching_after.overlaps(first)
    assert first.overlaps(overlapping)
    assert overlapping.overlaps(first)


def test_a_derivation_step_recorded_exactly_at_the_cutoff_is_admitted():
    """`recorded_at > cutoff` refuses. A fact recorded AT the cutoff was on record, which
    is the same inclusive boundary the observation layer uses."""
    from cai.derivation import ConsequenceDerivation, DerivationRelationship, DerivationStep

    cutoff = T.t(12, 7)

    def walk_recorded_at(moment):
        return ConsequenceDerivation(
            rule_version="context-rules@0.8.0", knowledge_cutoff=cutoff,
            evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)),
            steps=(DerivationStep(DerivationRelationship.ASSIGNED_TO, "asset-4417",
                                  "zone-3", moment, "yard-management", T.t(8), None),),
        )

    assert walk_recorded_at(cutoff).steps
    with pytest.raises(ValueError, match="recorded after the cutoff"):
        walk_recorded_at(cutoff + TICK)


# ===========================================================================
# BRANCHES NOTHING WALKED.
# ===========================================================================


def test_a_downtime_consequence_survives_the_wire():
    """The DOWNTIME arm of `BusinessConsequence.from_record`. The second consequence type
    exists to prove the abstraction is not shaped around the hero, and nothing had ever
    round-tripped one -- so the dispatch branch that rebuilds it was dead on the wire."""
    from cai.consequence import BusinessConsequence, DowntimeConsequence

    consequence = DowntimeConsequence(
        "DOWNTIME", TimeInterval(T.t(13, 5), T.t(13, 11)), T.derivation(),
        asset_id="asset-4417", expected_hours_lost=6.5, affected_operation="loading")

    rebuilt = BusinessConsequence.from_record(consequence.as_record())

    assert isinstance(rebuilt, DowntimeConsequence)
    assert rebuilt.asset_id == "asset-4417"
    assert rebuilt.expected_hours_lost == 6.5
    assert rebuilt.as_record() == consequence.as_record()


def test_downtime_below_a_shift_is_not_actionable_and_at_a_shift_is():
    """`expected_hours_lost >= 1.0`. Below a shift's worth this is noise an operator
    should not be interrupted for; AT a shift it is not."""
    from cai.consequence import DowntimeConsequence

    def downtime(hours):
        return DowntimeConsequence(
            "DOWNTIME", TimeInterval(T.t(13, 5), T.t(13, 11)), T.derivation(),
            asset_id="asset-4417", expected_hours_lost=hours,
            affected_operation="loading")

    assert downtime(1.0).is_actionable()
    assert not downtime(0.99).is_actionable()
    assert downtime(0.0).expected_hours_lost == 0.0, "zero is not negative"


def test_a_sixty_four_character_non_hex_digest_is_still_not_a_digest():
    """`len(digest) != 64 or any(not hex)`. Swapped to `and`, a 64-character string of
    'g's passes both the evidence snapshot and the assurance decision -- and sixty-four
    characters that look exactly like a SHA-256 is the shape this check exists for."""
    from cai.contract import EvidenceSnapshot
    from cai.delivery import AssuranceDecision

    with pytest.raises(ValueError, match="cannot be a content digest"):
        EvidenceSnapshot(observation_ids=("a-0",), subject="asset-4417",
                         model_version=None, semantic_rule_version=None,
                         identity_confidence=None, evidence_content_digest="g" * 64,
                         captured_at=T.t(12, 7))
    honest = T.deliver().assurance
    with pytest.raises(ValueError, match="cannot be a policy digest"):
        AssuranceDecision(**{**honest.__dict__, "policy_digest": "g" * 64})


def test_an_integral_float_canonicalises_to_an_integer_rather_than_being_refused():
    """`value != int(value)` -- only NON-integer floats have no portable canonical form.
    Refusing `259200.0` would refuse a horizon every producer can legitimately emit."""
    from cai.canonical import canonicalize

    assert canonicalize({"horizon_seconds": 259200.0}) == '{"horizon_seconds":259200}'
    assert canonicalize({"horizon_seconds": 259200}) == '{"horizon_seconds":259200}'


@pytest.mark.parametrize("name,build,check", [
    (
        "action prerequisites",
        lambda: T.deliver(candidate=T.candidate(action=T.ActionRecommendation(
            "act-001", T.ActionType.INSPECT, "battery-pack-1", "maintenance", T.t(13, 3),
            TimeInterval(T.t(13, 5), T.t(13, 11)),
            "degradation signal over the commitment horizon", T.Priority.BEFORE_NEXT_USE,
            prerequisites=("isolate the pack", "lock out the charger")))),
        lambda e: e.product.candidate.action.prerequisites == (
            "isolate the pack", "lock out the charger"),
    ),
])
def test_a_non_empty_optional_collection_survives_the_wire(name, build, check):
    """`r.get("prerequisites") or ()` reads as a default and is a real branch: swapped to
    `and ()`, a populated list becomes empty on import and the operator loses the
    instructions that had to happen first.

    Nothing carried a non-empty one across the wire, so the drop was invisible.
    """
    envelope = IntelligenceEnvelope(product=build())
    text = envelope.canonical_json()

    rebuilt = parse_envelope(text)

    assert check(rebuilt)
    assert rebuilt.canonical_json() == text


def test_a_disposition_note_survives_the_wire():
    """`r.get("note") or ""`. The note is where an override records WHY, which is the
    most informative row in the whole disposition trail."""
    from cai.action import OutcomeObservation, OutcomeType
    from cai.lifecycle import DispositionEvent, DispositionState

    product = T.deliver()
    envelope = IntelligenceEnvelope(
        product=product,
        lifecycle_events=(
            DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
            DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 9), "ops"),
            DispositionEvent(DispositionState.OVERRIDDEN, T.t(12, 14), "ops",
                             note="unit already scheduled for service on the 13th"),
            DispositionEvent(DispositionState.OUTCOME_OBSERVED, T.t(13, 4), "ops",
                             note="no failure observed"),
        ),
        outcome=OutcomeObservation(
            "out-1", OutcomeType.NO_FAILURE_OBSERVED,
            product.candidate.prediction_claim.subject,
            TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4), source="m",
            related_action_id=product.candidate.action.action_id),
    )
    text = envelope.canonical_json()

    rebuilt = parse_envelope(text)

    assert [e.note for e in rebuilt.lifecycle_events][2] == (
        "unit already scheduled for service on the 13th")
    assert rebuilt.canonical_json() == text


def test_the_walks_unverifiable_annotations_do_not_travel():
    """`ambiguities` and `late_relationships` are the producer's account of what it
    found, and a reader holding the envelope has nothing to check them against -- the
    graph is not in it.

    They used to cross the wire. A strict portable record that carries an assertion
    nobody can verify overstates what it has verified: a forger could empty the late
    list, or invent an ambiguity, and every check still passed. They stay on the
    in-memory type, where the walk that produced them is the authority.
    """
    from cai.consequence import BusinessConsequence
    from cai.derivation import ConsequenceDerivation

    walk = ConsequenceDerivation(
        rule_version=T.derivation().rule_version,
        knowledge_cutoff=T.derivation().knowledge_cutoff,
        evaluated_window=T.derivation().evaluated_window,
        steps=T.derivation().steps,
        ambiguities=("two candidate zones were on record",),
        late_relationships=("SUPPORTS(zone-3,win-11) recorded after cutoff",),
    )
    assert walk.ambiguities and walk.late_relationships, "in memory they are kept"

    record = T.commitment(derivation=walk).as_record()
    assert "ambiguities" not in record["derivation"]
    assert "late_relationships" not in record["derivation"]

    rebuilt = BusinessConsequence.from_record(record)
    assert rebuilt.derivation.ambiguities == ()
    assert rebuilt.derivation.late_relationships == ()


def test_named_missing_evidence_survives_the_wire():
    """`r.get("missing_evidence") or ()` on the assessment. An abstention that cannot say
    what was missing is the uninformative verdict the six dimensions replaced."""
    from cai.contract import EvidenceSnapshot

    product = T.deliver(evidence=EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "semantic_rule_version": None}))
    assert product.determination is Determination.ABSTAINED
    text = IntelligenceEnvelope(product=product).canonical_json()

    rebuilt = parse_envelope(text)

    assert rebuilt.product.assurance.assessed.evidence_assessment.missing_evidence == (
        "semantic_rule_version",)
    assert rebuilt.canonical_json() == text


def test_an_honest_abstention_with_no_prediction_inputs_is_readable_as_history():
    """The defect this pair of checks had, pointing the other way.

    `assess_evidence` records completeness=MISSING(prediction_inputs) and
    integrity=BROKEN, and the product abstains saying exactly that. Import then RAISED --
    in both modes -- so the release path emitted a bundle its own importer could not read
    at all, on the honest case rather than a forged one.

    The fix is not to accept it strictly. A record with no inputs genuinely cannot be
    replayed, so `claim_replay` is UNVERIFIABLE and strict import refuses, which is what
    strict means. What changed is that the record is now READABLE, with the gap named,
    instead of being rejected outright by both doors.
    """
    from cai.contract import EvidenceSnapshot
    from cai.envelope import import_historical_envelope
    from cai.product import UnverifiableBasis
    from cai.verification import VerificationDimension, VerificationState

    inputless = EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "prediction_inputs": None})
    assert T.deliver(evidence=inputless).determination is Determination.ABSTAINED
    payload = wire(evidence=inputless)

    with pytest.raises(UnverifiableBasis, match="nothing to replay against"):
        import_envelope(payload)

    read = import_historical_envelope(payload)
    assert read.verification_report.state_of(VerificationDimension.CLAIM_REPLAY) is (
        VerificationState.UNVERIFIABLE)
    assert json.loads(read.envelope.canonical_json()) == payload
    assert read.envelope.product.assurance.assessed.evidence_assessment.missing_evidence \
        == ("prediction_inputs",)


def test_a_delivered_record_still_has_to_bind_and_replay():
    """The twin, and the reason the rule above is not an escape hatch.

    A DELIVERED product requires permitted=True, which requires the assessment to
    RELEASE, which requires integrity=VALID -- so a delivered record always claims to
    bind, and always has to.
    """
    forged = wire()
    forged["product"]["evidence"]["prediction_inputs"]["input_fingerprint"] = "a" * 64
    with pytest.raises(ValueError, match="does not bind to its evidence"):
        import_envelope(forged)

    replayed = wire()
    replayed["product"]["candidate"]["prediction_claim"]["score"] = "0.990000"
    with pytest.raises(ValueError, match="replays differently"):
        import_envelope(replayed)


def test_the_verification_report_describes_a_verified_dimension_in_words():
    """`describe()` renders both states. The VERIFIED arm is what a reader logging a
    historical import actually prints, and nothing asserted it."""
    from cai.envelope import import_historical_envelope
    from cai.verification import VerificationDimension

    report = import_historical_envelope(wire()).verification_report

    assert report[VerificationDimension.LIFECYCLE].describe() == "lifecycle: VERIFIED"
    assert report.fully_verified() is True, "a bool, not merely something truthy"
    assert "VERIFIED" in report.describe()
