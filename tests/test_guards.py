"""Every refusal guard, reached by an input that actually reaches it.

WHY THIS FILE EXISTS
--------------------
`guard_sweep.py` replaces each `raise` in `src/cai` with `pass` and runs the suite. A
guard whose removal leaves the suite green has no test holding it up: it reads as
protection, it is attributable to no assertion, and it would survive any audit that
counted checks instead of exercising them. Wave 1 found 73 of 137 removable; wave 4 found
61 of 170 still removable after three rounds of remediation.

Sixty-one guards is not sixty-one defects. Most were load-bearing rules that nothing had
got round to asserting, a few were genuinely unreachable, and telling those apart is the
whole exercise -- "coverage improved" is not an answer to it.

WHAT EACH TEST HERE HAS TO DO
-----------------------------
Reach the guard it names, and no other. That is harder than it sounds and it is where the
value is: a naive `delivery_time` on a DELIVERED product never reaches the timezone
check, because comparing an aware `release_decision_time` to a naive `delivery_time` is unequal and
the decision-time rule fires first. A test built the obvious way passes, kills nothing,
and reports coverage it does not have.

So every fixture below is otherwise valid, and several are shaped deliberately -- an
ABSTAINED product for the timestamp rule, an assertion built field-by-field so exactly one
field is wrong. Where a fixture cannot reach a guard, that guard is not tested here: it is
deleted, and the invariant that makes it unreachable is named where it used to be.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import test_formation as T
from cai.action import ActionRecommendation, ActionType, OutcomeObservation, OutcomeType
from cai.bitemporal import Observation
from cai.candidate import (
    ApplicabilityAssertion,
    AssessedAssurance,
    EntitlementAssertion,
    IdentityAssertion,
    IntelligenceCandidate,
    TemporalAssertion,
)
from cai.consequence import CustomerCommitmentConsequence, DowntimeConsequence
from cai.contract import EvidenceSnapshot, PredictionClaim
from cai.decision import DecisionContext, TimeInterval
from cai.delivery import AssuranceDecision, RenderedDelivery
from cai.derivation import (
    ConsequenceDerivation,
    DerivationRelationship,
    DerivationStep,
)
from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType
from cai.lifecycle import DispositionEvent, DispositionState
from cai.product import Determination, IntelligenceProduct

NAIVE = datetime(2026, 6, 13, 3, 0)
AWARE = datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)
R = DerivationRelationship


def window() -> TimeInterval:
    return TimeInterval(T.t(13, 5), T.t(13, 11))


def walk() -> ConsequenceDerivation:
    return ConsequenceDerivation(
        rule_version="context-rules@0.8.0", knowledge_cutoff=T.t(12, 7),
        evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)),
        steps=(DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9), "yard", T.t(8), None),),
    )


# ===========================================================================
# TIMEZONE AWARENESS. A naive timestamp hashes and orders differently depending
# on who reads it, which is the failure this record cannot afford anywhere.
# ===========================================================================


def test_an_action_deadline_must_be_timezone_aware():
    with pytest.raises(ValueError, match="due_by must be timezone-aware"):
        ActionRecommendation("act-1", ActionType.INSPECT, "battery-pack-1", "maintenance",
                             NAIVE, window(), "reason")


def test_an_outcome_observation_moment_must_be_timezone_aware():
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        OutcomeObservation("out-1", OutcomeType.NO_FAILURE_OBSERVED, "asset-4417",
                           TimeInterval(T.t(13, 2), T.t(13, 6)), NAIVE,
                           source="maintenance")


@pytest.mark.parametrize("field", ["model_decision_time", "knowledge_cutoff", "feature_cutoff"])
def test_every_temporal_assertion_clock_must_be_timezone_aware(field):
    """All three, because the guard loops over them and a test for one would leave the
    other two provable only by inspection."""
    stamps = {"model_decision_time": T.t(12, 7), "knowledge_cutoff": T.t(12, 7),
              "feature_cutoff": T.t(12, 7), field: NAIVE}
    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        TemporalAssertion(**stamps, valid=True, basis="point-in-time view at the cutoff")


@pytest.mark.parametrize("field", ["valid_from", "valid_to"])
def test_an_entitlement_validity_window_must_be_timezone_aware(field):
    with pytest.raises(ValueError, match=f"entitlement {field} must be timezone-aware"):
        T.entitlement(**{field: NAIVE, **({"valid_to": NAIVE} if field == "valid_to"
                                          else {})})


def test_an_evidence_capture_time_must_carry_a_timezone():
    with pytest.raises(ValueError, match="captured_at must carry a timezone"):
        EvidenceSnapshot(observation_ids=("a-0",), subject="asset-4417",
                         model_version=None, semantic_rule_version=None,
                         identity_confidence=None, captured_at=NAIVE)


@pytest.mark.parametrize("field", ["start", "end"])
def test_both_ends_of_an_interval_must_be_timezone_aware(field):
    ends = {"start": AWARE, "end": AWARE + timedelta(hours=1), field: NAIVE}
    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        TimeInterval(**ends)


@pytest.mark.parametrize("field", ["model_decision_time", "knowledge_cutoff", "evaluation_time"])
def test_every_decision_context_clock_must_be_timezone_aware(field):
    stamps = {"model_decision_time": T.t(12, 7), "knowledge_cutoff": T.t(12, 7),
              "evaluation_time": T.t(12, 7), field: NAIVE}
    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        DecisionContext(**stamps,
                        prediction_window=TimeInterval(T.t(12, 7), T.t(15, 7)))


def test_a_rendering_timestamp_must_be_timezone_aware():
    honest = T.deliver().rendered_delivery
    with pytest.raises(ValueError, match="rendered_at must be timezone-aware"):
        RenderedDelivery(**{**honest.__dict__, "rendered_at": NAIVE})


def test_a_decision_time_must_be_timezone_aware():
    honest = T.deliver().assurance
    with pytest.raises(ValueError, match="release_decision_time must be timezone-aware"):
        AssuranceDecision(**{**honest.__dict__, "release_decision_time": NAIVE})


@pytest.mark.parametrize("field", ["recorded_at", "valid_from", "valid_to"])
def test_every_derivation_step_clock_must_be_timezone_aware(field):
    stamps = {"recorded_at": T.t(9), "valid_from": T.t(8), "valid_to": T.t(20),
              field: NAIVE}
    with pytest.raises(ValueError, match=f"derivation step {field} must be timezone-aware"):
        DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", stamps["recorded_at"],
                       "yard-management", stamps["valid_from"], stamps["valid_to"])


def test_a_derivations_knowledge_cutoff_must_be_timezone_aware():
    with pytest.raises(ValueError, match="knowledge_cutoff must be timezone-aware"):
        ConsequenceDerivation(
            rule_version="context-rules@0.8.0", knowledge_cutoff=NAIVE,
            evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)),
            steps=(DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9), "yard", T.t(8), None),),
        )


def test_a_status_event_timestamp_must_be_timezone_aware():
    with pytest.raises(ValueError, match="status event's timestamp must be timezone-aware"):
        StatusEvent(StatusEventType.RETRACTED, NAIVE, "system", reason="withdrawn")


def test_a_disposition_event_timestamp_must_be_timezone_aware():
    with pytest.raises(ValueError, match="disposition event's timestamp must be"):
        DispositionEvent(DispositionState.DELIVERED, NAIVE, "system")


def test_a_products_validity_horizon_must_be_timezone_aware():
    """ABSTAINED deliberately.

    On a DELIVERED product a naive `delivery_time` never reaches this loop: comparing an
    aware `release_decision_time` to a naive `delivery_time` is unequal, so the decision-time rule
    fires first with a different message. An abstention carries no delivery time at all,
    so `valid_until` is the one timestamp left that can be naive here.
    """
    abstained = T.deliver(recipient="procurement@other-customer", purpose="benchmarking")
    assert abstained.determination is Determination.ABSTAINED
    with pytest.raises(ValueError, match="valid_until must be timezone-aware"):
        IntelligenceProduct(**{**abstained.__dict__, "valid_until": NAIVE})


@pytest.mark.parametrize("field", ["valid_time", "transaction_time"])
def test_both_observation_clocks_must_be_timezone_aware(field):
    """The rule that replaced the naive-datetime refusal inside `content_digest`.

    That one is deleted: it could not fire once the constructor refused a naive timestamp,
    and a guard no input can reach reads as protection while proving nothing. The rule
    moved one layer out, where it holds for every consumer of `valid_time` rather than
    only for the one that hashes it.
    """
    stamps = {"valid_time": T.t(8, 6), "transaction_time": T.t(8, 7), field: NAIVE}
    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        Observation("a-0", "asset-4417", "battery_temp_c", 41.0, stamps["valid_time"],
                    stamps["transaction_time"], "source-a")


def test_the_wire_refuses_a_timestamp_with_no_offset():
    """The public-boundary half of the whole family above.

    RFC 3339 requires an offset, so the published schema's `date-time` format refuses a
    naive timestamp before the domain sees it -- which is the right place for the wire to
    refuse it, and exactly why the in-memory tests above are not redundant with it.
    """
    import json

    from cai.envelope import SchemaViolation, import_envelope

    payload = json.loads(IntelligenceEnvelope(product=T.deliver()).canonical_json())
    payload["product"]["candidate"]["context"]["model_decision_time"] = "2026-06-12T07:00:00"
    with pytest.raises(SchemaViolation, match="model_decision_time"):
        import_envelope(payload)


# ===========================================================================
# IDENTIFIERS AND BASES. A record that cannot say who, what or on whose
# authority cannot be challenged by anybody.
# ===========================================================================


def test_an_action_with_no_id_cannot_be_joined_to_its_outcome():
    with pytest.raises(ValueError, match="an action with no id"):
        ActionRecommendation("", ActionType.INSPECT, "battery-pack-1", "maintenance",
                             T.t(13, 3), window(), "reason")


def test_an_outcome_with_no_id_cannot_be_cited():
    with pytest.raises(ValueError, match="an outcome with no id"):
        OutcomeObservation("", OutcomeType.NO_FAILURE_OBSERVED, "asset-4417",
                           TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4), source="m")


def test_an_outcome_with_no_subject_cannot_be_attached_to_anything():
    with pytest.raises(ValueError, match="an outcome with no subject"):
        OutcomeObservation("out-1", OutcomeType.NO_FAILURE_OBSERVED, "",
                           TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4), source="m")


def test_an_identity_assertion_with_no_resolver_cannot_be_audited():
    with pytest.raises(ValueError, match="no resolver cannot be audited"):
        IdentityAssertion("asset-4417/battery-pack", "", "1.0", 0.97)


def test_an_applicability_verdict_with_no_basis_is_an_opinion():
    with pytest.raises(ValueError, match="no basis is an opinion"):
        ApplicabilityAssertion("degradation-baseline@1.3.0", "forklift/battery-pack",
                               True, "")


def test_an_applicability_verdict_naming_no_subject_type_asserts_nothing():
    with pytest.raises(ValueError, match="naming no subject type"):
        ApplicabilityAssertion("degradation-baseline@1.3.0", "", True, "within envelope")


def test_a_temporal_verdict_with_no_basis_is_a_naked_valid_flag():
    with pytest.raises(ValueError, match="a naked valid flag"):
        TemporalAssertion(T.t(12, 7), T.t(12, 7), T.t(12, 7), True, basis="")


@pytest.mark.parametrize("field", ["basis", "policy_id"])
def test_an_entitlement_with_no_basis_or_policy_id_is_unauditable(field):
    with pytest.raises(ValueError, match="no basis or policy id is unauditable"):
        T.entitlement(**{field: ""})


def test_an_entitlement_naming_a_policy_but_not_its_version_is_uncomparable():
    with pytest.raises(ValueError, match="not its version cannot be compared"):
        T.entitlement(policy_version="")


@pytest.mark.parametrize("field", ["purpose", "tenant"])
def test_an_entitlement_with_a_blank_scope_field_authorises_nothing(field):
    with pytest.raises(ValueError, match="authorises nothing it can be checked against"):
        T.entitlement(**{field: ""})


def test_an_entitlement_covering_no_time_authorises_nothing():
    with pytest.raises(ValueError, match="at or before it begins"):
        T.entitlement(valid_from=T.t(10), valid_to=T.t(10))


def test_a_candidate_with_no_id_cannot_be_traced_to_its_product():
    with pytest.raises(ValueError, match="a candidate with no id"):
        T.candidate(candidate_id="")


def test_a_commitment_consequence_must_name_the_commitment():
    with pytest.raises(ValueError, match="must name the commitment"):
        CustomerCommitmentConsequence("CUSTOMER_COMMITMENT", window(), walk(),
                                      commitment_id="", commitment_description="d")


@pytest.mark.parametrize("field", ["subject", "object"])
def test_a_derivation_step_must_name_both_ends(field):
    ends = {"subject": "asset-4417", "object": "zone-3", field: ""}
    with pytest.raises(ValueError, match="must name a relationship and both ends"):
        DerivationStep(R.ASSIGNED_TO, ends["subject"], ends["object"], T.t(9), "yard")


def test_a_derivation_step_must_name_its_source_system():
    with pytest.raises(ValueError, match="names no source system"):
        DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9), "")


def test_a_derivation_that_cannot_say_which_rules_produced_it_is_refused():
    with pytest.raises(ValueError, match="cannot say which rules produced it"):
        ConsequenceDerivation(
            rule_version="", knowledge_cutoff=T.t(12, 7),
            evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)),
            steps=(DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9), "yard", T.t(8), None),),
        )


def test_a_derivation_with_no_steps_is_a_conclusion_with_no_path():
    with pytest.raises(ValueError, match="a conclusion with no path"):
        ConsequenceDerivation(
            rule_version="context-rules@0.8.0", knowledge_cutoff=T.t(12, 7),
            evaluated_window=TimeInterval(T.t(12, 7), T.t(15, 7)), steps=(),
        )


def test_a_status_event_with_no_actor_records_a_withdrawal_and_not_who_made_it():
    with pytest.raises(ValueError, match="a status event with no actor"):
        StatusEvent(StatusEventType.RETRACTED, T.t(13, 6), "", reason="withdrawn")


def test_a_retraction_with_no_reason_is_unauditable():
    with pytest.raises(ValueError, match="retraction with no reason"):
        StatusEvent(StatusEventType.RETRACTED, T.t(13, 6), "system", reason="")


def test_a_supersession_must_name_what_replaced_it():
    with pytest.raises(ValueError, match="must name what replaced it"):
        StatusEvent(StatusEventType.SUPERSEDED, T.t(13, 6), "system")


def test_a_disposition_with_no_actor_records_the_half_a_dispute_does_not_need():
    with pytest.raises(ValueError, match="a disposition with no actor"):
        DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "")


@pytest.mark.parametrize("field", ["product_id", "claim_series_id"])
def test_a_product_must_carry_its_own_identifiers(field):
    honest = T.deliver()
    expected = ("a product with no id" if field == "product_id"
                else "no series id cannot be recognised")
    with pytest.raises(ValueError, match=expected):
        IntelligenceProduct(**{**honest.__dict__, field: ""})


@pytest.mark.parametrize("field", ["observation_id", "subject", "metric", "source_system"])
def test_a_reading_must_say_what_it_is_and_where_it_came_from(field):
    """Four new guards, and `source_system` is the load-bearing one: it is the value the
    entitlement union is computed over, so an unnamed feed is a product licensed against
    nothing."""
    parts = {"observation_id": "a-0", "subject": "asset-4417",
             "metric": "battery_temp_c", "source_system": "source-a", field: ""}
    with pytest.raises(ValueError):
        Observation(parts["observation_id"], parts["subject"], parts["metric"], 41.0,
                    T.t(8, 6), T.t(8, 7), parts["source_system"])


# ===========================================================================
# TYPES. An annotation is documentation; a dataclass will seat a string happily.
# ===========================================================================


def test_the_assessed_assurance_refuses_an_untyped_context():
    from cai.evidence import fully_satisfied

    with pytest.raises(TypeError, match="context must be an AssuranceContext"):
        AssessedAssurance(context={"identity": "asset-4417"},
                          evidence_assessment=fully_satisfied())


def test_a_decision_carrying_an_untyped_basis_records_an_underivable_verdict():
    honest = T.deliver().assurance
    with pytest.raises(TypeError, match="assessed must be an AssessedAssurance"):
        AssuranceDecision(**{**honest.__dict__, "assessed": {"evidence": "fine"}})


def test_the_claim_refuses_an_envelope_that_is_not_one():
    honest = T.claim()
    with pytest.raises(ValueError, match="declared_envelope must be a ModelEnvelope"):
        PredictionClaim(**{**honest.__dict__, "declared_envelope": "anything goes"})


def test_the_envelope_refuses_a_trail_of_loose_dictionaries():
    with pytest.raises(TypeError, match="must be typed DispositionEvents"):
        IntelligenceEnvelope(product=T.deliver(),
                             lifecycle_events=({"state": "DELIVERED"},))


def test_the_envelope_refuses_an_untyped_outcome():
    with pytest.raises(TypeError, match="outcome must be an OutcomeObservation"):
        IntelligenceEnvelope(product=T.deliver(), outcome={"outcome_type": "NO_FAILURE"})


def test_the_envelope_refuses_untyped_status_events():
    with pytest.raises(TypeError, match="must be typed StatusEvents"):
        IntelligenceEnvelope(product=T.deliver(),
                             status_events=({"event_type": "RETRACTED"},))


def test_the_release_evidence_must_be_a_bundle():
    honest = T.deliver()
    with pytest.raises(TypeError, match="release_evidence must be an EvidenceBundle"):
        IntelligenceProduct(**{**honest.__dict__,
                               "release_evidence": honest.release_evidence.observations})


# ===========================================================================
# RANGES AND FINITENESS. A number outside its own stated domain is not a value
# with a problem, it is a different quantity wearing the field's name.
# ===========================================================================


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_an_identity_confidence_outside_the_unit_interval_is_refused(confidence):
    with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
        IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", confidence)


@pytest.mark.parametrize("confidence", [-0.5, 2.0])
def test_a_snapshot_identity_confidence_outside_the_unit_interval_is_refused(confidence):
    with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
        EvidenceSnapshot(observation_ids=("a-0",), subject="asset-4417",
                         model_version=None, semantic_rule_version=None,
                         identity_confidence=confidence, captured_at=T.t(12, 7))


def test_a_non_finite_score_is_not_a_score():
    honest = T.claim()
    with pytest.raises(ValueError, match="is not finite"):
        PredictionClaim(**{**honest.__dict__, "score": float("nan")})


def test_a_non_positive_horizon_describes_no_period():
    honest = T.claim()
    with pytest.raises(ValueError, match="must be positive"):
        PredictionClaim(**{**honest.__dict__, "horizon_seconds": 0})


@pytest.mark.parametrize("strength", [-0.1, 1.5])
def test_an_evidence_strength_outside_the_unit_interval_is_refused(strength):
    honest = T.claim()
    with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
        PredictionClaim(**{**honest.__dict__, "evidence_strength": strength})


def test_negative_downtime_is_not_downtime():
    with pytest.raises(ValueError, match="cannot be negative"):
        DowntimeConsequence("DOWNTIME", window(), walk(), asset_id="asset-4417",
                            expected_hours_lost=-1.0, affected_operation="loading")


def test_non_finite_telemetry_is_outside_the_models_envelope():
    from cai.predictor import OutsideApplicability, predict_degradation

    with pytest.raises(OutsideApplicability, match="non-finite value"):
        predict_degradation(metric="battery_temp_c",
                            values=(41.0, float("inf"), 45.0),
                            horizon=timedelta(days=1))


def test_a_non_finite_reading_cannot_enter_the_log():
    with pytest.raises(ValueError, match="has value"):
        Observation("a-0", "asset-4417", "battery_temp_c", float("nan"),
                    T.t(8, 6), T.t(8, 7), "source-a")


@pytest.mark.parametrize("bound", ["min_observations", "max_horizon_seconds"])
def test_an_envelopes_bounds_must_be_positive_to_bound_anything(bound):
    from cai.predictor import MetricApplicability, ModelEnvelope

    bounds = {"min_observations": 3, "max_horizon_seconds": 604800, bound: 0}
    with pytest.raises(ValueError, match="must be positive to bound anything"):
        ModelEnvelope(model_version="m@1", model_artifact_digest="0" * 64,
                      supported_applicability=(
                          MetricApplicability("battery_temp_c", "forklift/battery-pack"),
                      ), **bounds)


def test_an_envelope_declaring_no_combination_bounds_nothing():
    from cai.predictor import ModelEnvelope

    with pytest.raises(ValueError, match="places no bound on use"):
        ModelEnvelope(model_version="m@1", model_artifact_digest="0" * 64,
                      supported_applicability=(), min_observations=3,
                      max_horizon_seconds=604800)


def test_an_envelope_declaring_one_combination_twice_says_nothing_twice():
    from cai.predictor import MetricApplicability, ModelEnvelope

    pair = MetricApplicability("battery_temp_c", "forklift/battery-pack")
    with pytest.raises(ValueError, match="the same combination twice"):
        ModelEnvelope(model_version="m@1", model_artifact_digest="0" * 64,
                      supported_applicability=(pair, pair), min_observations=3,
                      max_horizon_seconds=604800)


def test_an_applicability_pair_with_an_empty_half_bounds_nothing():
    from cai.predictor import MetricApplicability

    with pytest.raises(ValueError, match="bounds nothing"):
        MetricApplicability("battery_temp_c", "")


def test_a_relationship_valid_over_no_interval_was_never_true():
    with pytest.raises(ValueError, match="valid over no interval"):
        DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9), "yard-management",
                       T.t(10), T.t(10))


# ===========================================================================
# CLOSED VOCABULARIES AND CANONICAL FORM.
# ===========================================================================


def test_a_type_with_no_canonical_json_form_is_refused_rather_than_guessed():
    from cai.canonical import NotCanonicalizable, canonicalize

    with pytest.raises(NotCanonicalizable, match="has no canonical JSON form"):
        canonicalize({"when": datetime(2026, 6, 13, tzinfo=timezone.utc)})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_non_finite_float_has_no_canonical_json_form(value):
    from cai.canonical import NotCanonicalizable, canonicalize

    with pytest.raises(NotCanonicalizable, match="has no canonical JSON form"):
        canonicalize({"score": value})


def test_a_non_integer_float_is_refused_rather_than_formatted():
    from cai.canonical import NotCanonicalizable, canonicalize

    with pytest.raises(NotCanonicalizable, match="cannot be canonicalised portably"):
        canonicalize({"score": 0.4942})


def test_an_unknown_consequence_type_is_refused_rather_than_degraded():
    from cai.consequence import BusinessConsequence

    record = T.commitment().as_record()
    record["consequence_type"] = "SAFETY"
    with pytest.raises(ValueError, match="not a consequence type this system implements"):
        BusinessConsequence.from_record(record)


def test_a_silent_abstention_is_indistinguishable_from_a_crash():
    """The refusal must say why. Reached through `AssuranceDecision`, which owns the
    rule; `IntelligenceProduct` re-checks it and cannot be constructed to reach its own
    copy, because a decision with no reasons cannot exist to be seated there."""
    honest = T.deliver().assurance
    with pytest.raises(ValueError, match="no stated reason"):
        AssuranceDecision(**{**honest.__dict__, "permitted": False,
                             "blocking_reasons": ()})


def test_a_permitted_decision_cannot_carry_blocking_reasons():
    honest = T.deliver().assurance
    with pytest.raises(ValueError, match="cannot carry blocking reasons"):
        AssuranceDecision(**{**honest.__dict__, "blocking_reasons": ("entitlement",)})


def test_a_product_cannot_supersede_itself():
    honest = T.deliver()
    with pytest.raises(ValueError, match="supersedes itself"):
        IntelligenceProduct(**{**honest.__dict__,
                               "supersedes_product_id": honest.product_id})


def test_an_outcome_description_contradicting_its_own_fields_is_refused():
    """Derived on the way out, re-derived and COMPARED on the way in. Reading it back
    would make the exported sentence an input; discarding a contradictory one silently
    would import the bundle as something other than the bytes it arrived as."""
    record = OutcomeObservation(
        "out-1", OutcomeType.NO_FAILURE_OBSERVED, "asset-4417",
        TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4), source="m",
    ).as_record()
    record["description"] = "everything went fine"
    with pytest.raises(ValueError, match="the sentence its own fields render"):
        OutcomeObservation.from_record(record)


def test_a_candidate_refuses_prose_in_place_of_a_typed_claim():
    with pytest.raises(TypeError, match="prediction_claim must be a PredictionClaim"):
        IntelligenceCandidate("cand-1", T.context(),
                              "94% probability of pack failure within 72h",
                              T.commitment(), T.action())


# ===========================================================================
# THE NON-TRIVIALITY SWEEP. Every guard above refuses something; this proves
# none of them refuses everything.
# ===========================================================================


def test_the_honest_constructions_all_still_succeed():
    """One test, deliberately broad.

    A file of sixty refusals passes perfectly against types that refuse every input, and
    that failure mode is invisible from inside the refusals themselves. These are the same
    objects the refusals above vary by exactly one field.
    """
    assert ActionRecommendation("act-1", ActionType.INSPECT, "battery-pack-1",
                                "maintenance", T.t(13, 3), window(), "reason").action_id
    assert OutcomeObservation("out-1", OutcomeType.NO_FAILURE_OBSERVED, "asset-4417",
                              TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4),
                              source="m").outcome_id
    assert TemporalAssertion(T.t(12, 7), T.t(12, 7), T.t(12, 7), True,
                             basis="point-in-time view at the cutoff").valid
    assert T.entitlement().basis
    assert EvidenceSnapshot(observation_ids=("a-0",), subject="asset-4417",
                            model_version=None, semantic_rule_version=None,
                            identity_confidence=0.97, captured_at=T.t(12, 7)).subject
    assert TimeInterval(AWARE, AWARE + timedelta(hours=1)).duration
    assert DecisionContext(T.t(12, 7), T.t(12, 7), T.t(12, 7),
                           TimeInterval(T.t(12, 7), T.t(15, 7))).horizon
    assert DerivationStep(R.ASSIGNED_TO, "asset-4417", "zone-3", T.t(9),
                          "yard-management").label()
    assert walk().root_entity == "asset-4417"
    assert StatusEvent(StatusEventType.RETRACTED, T.t(13, 6), "system",
                       reason="withdrawn").actor
    assert DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system").actor
    assert Observation("a-0", "asset-4417", "battery_temp_c", 41.0, T.t(8, 6),
                       T.t(8, 7), "source-a").content_digest()
    assert IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", 0.97)
    assert ApplicabilityAssertion("degradation-baseline@1.3.0", "forklift/battery-pack",
                                  True, "within envelope").valid
    assert DowntimeConsequence("DOWNTIME", window(), walk(), asset_id="asset-4417",
                               expected_hours_lost=6.0,
                               affected_operation="loading").is_actionable()
    assert T.deliver().determination is Determination.DELIVERED


# ===========================================================================
# THE RELEASE-AUTHORITY AND IMPORT-BOUNDARY GUARDS.
#
# `guard_sweep.py` reported every one of these removable with the suite green,
# and each needed a fixture shaped so that no EARLIER check fires on it. Two
# recurring tricks: name a policy this package does not ship, so the policy
# re-run cannot reach the record first; and keep the recorded assessment
# internally consistent, so `EvidenceAssessment.from_record` admits it.
# ===========================================================================


def payload(**over) -> dict:
    import json

    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


def restamp_assessment(p) -> None:
    """Recompute the assessment's DERIVED values after its dimensions have been edited.

    `EvidenceAssessment.from_record` re-derives `release` and `blocking_reasons` from the
    six dimensions and refuses a record whose stated conclusion does not follow from them.
    So a forgery that flips one dimension and leaves the conclusion alone is refused for
    THAT -- one check earlier than the one it was written to reach.

    A real forger recomputes, because the derivation is published. Doing the same here is
    what makes these fixtures reach the arms they name rather than the arm that catches
    lazy forgeries.
    """
    from cai.evidence import (
        Completeness,
        EntitlementState,
        EvidenceAssessment,
        Identity,
        Integrity,
        Support,
        TemporalEligibility,
    )

    dimensions = p["product"]["assurance"]["assurance_context"]["evidence"]
    rebuilt = EvidenceAssessment(
        support=Support(dimensions["support"]),
        completeness=Completeness(dimensions["completeness"]),
        integrity=Integrity(dimensions["integrity"]),
        temporal_eligibility=TemporalEligibility(dimensions["temporal_eligibility"]),
        identity=Identity(dimensions["identity"]),
        entitlement=EntitlementState(dimensions["entitlement"]),
        missing_evidence=tuple(dimensions["missing_evidence"]),
        conflicts=tuple(dimensions["conflicts"]),
    )
    dimensions["release"] = rebuilt.release_decision().value
    dimensions["blocking_reasons"] = list(rebuilt.blocking_reasons())


def foreign_policy(p) -> None:
    """A policy this package does not ship, so the verdict cannot be recomputed.

    Used below to reach checks that live ABOVE the policy branch. Without it the policy
    re-run refuses the record first, and a test for the earlier check passes on the later
    one -- which is how several of these came to be removable in the first place.
    """
    p["product"]["assurance"]["policy_id"] = "acme.house-rules"


def test_a_permitted_decision_over_an_assessment_that_withholds_is_refused():
    """The single most important refusal in the product: the system contradicting itself
    about the only question that matters.

    The foreign policy is load-bearing in the FIXTURE. Under the shipped policy the
    re-run produces permitted=False and refuses the record on that ground instead, so
    this guard was removable while a test claimed to cover it. Under a policy nobody can
    reproduce, this is the only thing standing between the record and acceptance -- which
    is exactly when it matters.
    """
    from cai.envelope import import_historical_envelope

    def rewrite(p):
        foreign_policy(p)
        p["product"]["assurance"]["assurance_context"]["evidence"].update({
            "identity": "AMBIGUOUS",
            "release": "WITHHOLD",
            "blocking_reasons": ["identity=AMBIGUOUS"],
        })

    forged = payload()
    rewrite(forged)
    with pytest.raises(ValueError, match="permitted release while its own evidence"):
        import_historical_envelope(forged)


def test_a_verdict_the_named_policy_does_not_reproduce_is_refused():
    """The shipped policy, re-run over the recorded basis. No foreign policy here -- this
    is the check the foreign policy switches OFF, so it needs the opposite fixture."""
    from cai.envelope import import_envelope

    forged = payload()
    forged["product"]["assurance"]["assurance_context"]["identity"]["confidence"] = (
        "0.500000")
    forged["product"]["evidence"]["identity_confidence"] = "0.500000"
    with pytest.raises(ValueError, match="over the recorded assurance basis produces"):
        import_envelope(forged)


def test_a_record_naming_the_wrong_missing_evidence_is_refused():
    """Completeness AGREES -- both say MISSING -- and the named list does not. A fixture
    where completeness itself disagreed would be refused one line earlier."""
    from cai.envelope import import_envelope

    forged = payload(evidence=EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "semantic_rule_version": None}))
    assert forged["product"]["determination"] == "ABSTAINED"
    dimensions = forged["product"]["assurance"]["assurance_context"]["evidence"]
    assert dimensions["completeness"] == "MISSING"
    dimensions["missing_evidence"] = ["model_version"]
    dimensions["blocking_reasons"] = ["completeness=MISSING(model_version)"]
    reasons = [r for r in forged["product"]["assurance"]["blocking_reasons"]
               if "completeness" not in r] + ["completeness=MISSING(model_version)"]
    forged["product"]["assurance"]["blocking_reasons"] = reasons
    forged["product"]["abstention_reason"] = "; ".join(reasons)
    with pytest.raises(ValueError, match="as missing but its evidence is missing"):
        import_envelope(forged)


def test_a_record_asserting_resolved_identity_over_no_confidence_is_refused():
    """The half of the identity dimension that holds under ANY policy floor: an
    unrecorded confidence is not a resolved identity, whatever the line was drawn at.

    Foreign policy, so the exact identity comparison is switched off and this narrower
    rule is the one that has to fire.
    """
    from cai.envelope import import_historical_envelope

    forged = payload(evidence=EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "identity_confidence": None}))
    foreign_policy(forged)
    forged["product"]["assurance"]["assurance_context"]["evidence"]["identity"] = (
        "RESOLVED")
    restamp_assessment(forged)
    with pytest.raises(ValueError, match="identity=RESOLVED over evidence carrying no"):
        import_historical_envelope(forged)


def test_a_record_asserting_support_over_an_inapplicable_model_is_refused():
    """The other threshold-free half: a model its own assertion says was not valid here
    supports nothing, at any minimum evidence strength."""
    from cai.envelope import import_historical_envelope

    forged = payload(assurance=T.assurance(applicability=ApplicabilityAssertion(
        "degradation-baseline@1.3.0", "forklift/battery-pack", False,
        "this series came off a different kind of thing")))
    foreign_policy(forged)
    forged["product"]["assurance"]["assurance_context"]["evidence"]["support"] = (
        "SUPPORTED")
    restamp_assessment(forged)
    with pytest.raises(ValueError, match="support=SUPPORTED over a model its own"):
        import_historical_envelope(forged)


def test_a_record_whose_temporal_dimension_contradicts_its_own_assertion_is_refused():
    """The dimension loop, reached through `temporal_eligibility` rather than
    `completeness`, so the loop is exercised on more than one member."""
    from cai.envelope import import_historical_envelope

    forged = payload(assurance=T.assurance(temporal=TemporalAssertion(
        T.t(12, 7), T.t(12, 7), T.t(12, 7), False,
        basis="the feature view was rebuilt after the decision")))
    foreign_policy(forged)
    forged["product"]["assurance"]["assurance_context"]["evidence"][
        "temporal_eligibility"] = "ELIGIBLE_AS_OF_DECISION"
    restamp_assessment(forged)
    with pytest.raises(ValueError, match="temporal_eligibility=ELIGIBLE_AS_OF_DECISION"):
        import_historical_envelope(forged)


def test_the_strict_reconstruction_api_refuses_an_unverifiable_record_directly():
    """`IntelligenceProduct.from_record` is a public entry point with no internal caller
    -- the envelope path uses `from_record_with_findings` -- so nothing exercised its
    refusal. A strict API nobody tests is a strict API nobody can rely on."""
    from cai.product import UnverifiableBasis

    forged = payload()
    claim = forged["product"]["candidate"]["prediction_claim"]
    claim["model_artifact_digest"] = "e" * 64
    claim["declared_envelope"]["model_artifact_digest"] = "e" * 64
    with pytest.raises(UnverifiableBasis, match="strict import cannot verify"):
        IntelligenceProduct.from_record(forged["product"])


def test_the_same_record_reconstructs_when_it_can_be_verified():
    """Non-triviality twin for the entry point above."""
    rebuilt = IntelligenceProduct.from_record(payload()["product"])
    assert rebuilt.determination is Determination.DELIVERED


@pytest.mark.parametrize("field", ["recipient", "purpose", "tenant"])
def test_a_product_with_a_blank_delivery_scope_cannot_exist(field):
    """The three fields the entitlement is re-checked against. `permits()` compares
    purpose and tenant with `!=`, so a blank on both sides satisfies two of the six scope
    dimensions by matching emptiness."""
    honest = T.deliver()
    with pytest.raises(ValueError, match=f"a product with a blank {field}"):
        IntelligenceProduct(**{**honest.__dict__, field: ""})


def test_a_delivered_claim_must_record_when_it_was_delivered():
    honest = T.deliver()
    with pytest.raises(ValueError, match="must record when it was delivered"):
        IntelligenceProduct(**{**honest.__dict__, "delivery_time": None})


def test_a_delivered_claim_must_preserve_what_the_recipient_saw():
    honest = T.deliver()
    with pytest.raises(ValueError, match="what the recipient actually saw"):
        IntelligenceProduct(**{**honest.__dict__, "rendered_delivery": None})


def test_an_outcome_with_no_trail_that_reached_it_is_refused():
    honest = T.deliver()
    outcome = OutcomeObservation(
        "out-1", OutcomeType.NO_FAILURE_OBSERVED,
        honest.candidate.prediction_claim.subject,
        TimeInterval(T.t(13, 2), T.t(13, 6)), T.t(13, 4), source="m",
        related_action_id=honest.candidate.action.action_id)
    with pytest.raises(ValueError, match="the trail never reached OUTCOME_OBSERVED"):
        IntelligenceEnvelope(product=honest, outcome=outcome)


def test_a_trail_that_reached_outcome_observed_with_no_outcome_is_refused():
    honest = T.deliver()
    trail = (
        DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
        DispositionEvent(DispositionState.IGNORED, T.t(12, 9), "ops"),
        DispositionEvent(DispositionState.OUTCOME_OBSERVED, T.t(13, 4), "system"),
    )
    with pytest.raises(ValueError, match="no outcome is recorded"):
        IntelligenceEnvelope(product=honest, lifecycle_events=trail)


def test_a_historical_import_result_refuses_an_untyped_envelope():
    from cai.envelope import HistoricalEnvelopeImport, import_historical_envelope

    honest = import_historical_envelope(payload())
    with pytest.raises(TypeError, match="envelope must be an IntelligenceEnvelope"):
        HistoricalEnvelopeImport(envelope={"product": "trust me"},
                                 verification_report=honest.verification_report)


def test_a_historical_import_result_refuses_an_untyped_report():
    """A report that is a loose dict is the boolean this type replaced, wearing a
    different shape."""
    from cai.envelope import HistoricalEnvelopeImport, import_historical_envelope

    honest = import_historical_envelope(payload())
    with pytest.raises(TypeError, match="verification_report must be a"):
        HistoricalEnvelopeImport(envelope=honest.envelope,
                                 verification_report={"claim_replay": "VERIFIED"})


def test_an_unfamiliar_canonicalization_is_refused_before_the_schema_sees_it():
    """The guard `guard_sweep.py` found unreachable: the schema declares
    `canonicalization` as a const, so it refused an unfamiliar algorithm first and this
    check could never fire. Moved above the schema, it fires with its own message.

    Which algorithm produced the canonical bytes decides whether a reader can recompute
    the digest AT ALL, and burying that in a list of schema errors buries the one fact
    that makes the rest of the bundle uncheckable.
    """
    from cai.envelope import import_envelope

    forged = payload()
    forged["canonicalization"] = "whatever/1"
    with pytest.raises(ValueError, match="canonical bytes are only reproducible"):
        import_envelope(forged)


def test_the_verification_report_lookup_needs_no_hand_written_guard():
    """`__getitem__` used to end in a `raise KeyError` that could not fire, because the
    constructor guarantees every dimension is present. Indexing a total mapping raises
    for a caller who asks for something that is not a dimension, and needs no guard."""
    from cai.envelope import import_historical_envelope
    from cai.verification import VerificationDimension

    report = import_historical_envelope(payload()).verification_report
    assert report[VerificationDimension.LIFECYCLE].dimension is (
        VerificationDimension.LIFECYCLE)
    with pytest.raises(KeyError):
        report["not-a-dimension"]
