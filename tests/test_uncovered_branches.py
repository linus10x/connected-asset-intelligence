"""Behaviour the source-derived mutation pass found nothing asserting.

WHERE THIS LIST CAME FROM
-------------------------
Every test here closes a mutation that SURVIVED a run of `mutation_generator.py` -- a
branch replaced with `pass`, a comparison inverted, a refusal reason replaced with a
different one -- while the whole suite stayed green.

Three shapes recur, and they are worth naming because they are the shapes a hand-written
corpus does not find.

FIRST: reasons nobody read. `binding.py` returns a REASON STRING rather than raising, so
the caller can decide whether it is a refusal or an assessment. Twelve of those strings
could be replaced with any other string and every test still passed, because the tests
asserted that a refusal happened and not which one. A refusal that cannot say what is
wrong sends a reader to re-read the bundle.

SECOND: the naming half of `missing_elements()`. Eight elements, eight branches, and the
suite exercised the count rather than the names -- so seven of the eight could stop being
reported and nothing noticed. The names are not decoration: they cross the wire in
`missing_evidence` and are compared at import.

THIRD: honest-path negatives. `late_relationships` is empty on a clean walk, and no test
said so, so a rule reporting EVERY window as late passed. Asserting the empty case is
what makes the populated case mean something.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

import test_formation as T
from cai.bitemporal import EvidenceBundle, Observation, ObservationLog
from cai.contract import EvidenceSnapshot
from cai.envelope import IntelligenceEnvelope, import_envelope, import_historical_envelope
from cai.product import Determination

TICK = timedelta(microseconds=1)


def wire(**over) -> dict:
    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


# ===========================================================================
# EVERY MISSING ELEMENT IS NAMED, AND THE NAME TRAVELS.
# ===========================================================================


ELEMENTS = {
    # `prediction_inputs` clears with it: bound inputs must be a subset of the cited
    # ids, so clearing the citation alone trips that rule first and never reaches
    # `missing_elements` at all.
    "observation_ids": {"observation_ids": (), "prediction_inputs": None},
    "subject": {"subject": ""},
    "model_version": {"model_version": None},
    "semantic_rule_version": {"semantic_rule_version": None},
    "identity_confidence": {"identity_confidence": None},
    "evidence_content_digest": {"evidence_content_digest": None},
    "prediction_inputs": {"prediction_inputs": None},
    "source_systems": {"source_systems": ()},
}


@pytest.mark.parametrize("element", sorted(ELEMENTS))
def test_each_absent_element_is_named_by_missing_elements(element):
    """`missing_elements()` is the ONLY thing that says what a record lacks.

    The suite exercised whether the list was empty. It never exercised what was in it, so
    seven of these eight branches could stop reporting and the completeness dimension
    would still say MISSING -- naming the wrong gap, or one fewer than there are.

    The names are not cosmetic: they cross the wire in `missing_evidence` and the import
    boundary compares them element by element.
    """
    snapshot = EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, **ELEMENTS[element]})

    assert element in snapshot.missing_elements()


def test_a_complete_snapshot_names_nothing_as_missing():
    """The twin. Without it, a `missing_elements` that returned every name always would
    satisfy all eight tests above."""
    assert T.evidence(T.claim()).missing_elements() == ()


def test_the_named_gaps_reach_the_recorded_assessment_in_order():
    """Two gaps at once, so the order and the count both matter. `EvidenceAssessment`
    refuses a MISSING that cannot say what is missing, and the importer compares the
    tuple exactly."""
    product = T.deliver(evidence=EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__,
        "model_version": None, "semantic_rule_version": None}))

    assessment = product.assurance.assessed.evidence_assessment
    assert assessment.missing_evidence == ("model_version", "semantic_rule_version")
    rebuilt = import_historical_envelope(wire(evidence=EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__,
        "model_version": None, "semantic_rule_version": None})))
    assert rebuilt.envelope.product.assurance.assessed.evidence_assessment \
        .missing_evidence == ("model_version", "semantic_rule_version")


# ===========================================================================
# INTEGRITY FINDINGS ARE NAMED, INDIVIDUALLY.
# ===========================================================================


def findings_for(snapshot, bundle=None, claim=None):
    from cai.binding import claim_is_replayable_here
    from cai.assessment import imported_integrity_findings

    claim = claim or T.claim()
    bundle = bundle if bundle is not None else EvidenceBundle(
        observations=T.observations())
    return imported_integrity_findings(
        evidence=snapshot, evidence_source=bundle, prediction_claim=claim,
    )


def test_an_absent_evidence_digest_is_reported_by_name():
    """`digest is None` is a different finding from `digest does not match`, and the two
    demand different responses: one is a producer that never computed it, the other is a
    record whose evidence moved."""
    findings = findings_for(EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "evidence_content_digest": None}))

    assert "evidence_content_digest is absent" in findings
    assert not any("is not the digest of" in f for f in findings)


def test_a_snapshot_that_says_nothing_about_its_subject_is_reported_by_name():
    """Distinct from a snapshot whose subject is WRONG. Absent and incorrect are not the
    same defect and do not go to the same person."""
    findings = findings_for(EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "subject": ""}))

    assert "the snapshot does not say what its readings are about" in findings


def test_an_honest_snapshot_produces_no_findings_at_all():
    """The twin for every finding in this section and in `test_portable_evidence`."""
    assert findings_for(T.evidence(T.claim())) == ()


def test_a_record_with_no_prediction_inputs_reports_both_bindings_it_cannot_make():
    """Two independent guards produce the same OUTCOME here -- integrity BROKEN -- so
    neither was attributable while only the outcome was asserted. The findings list is
    what tells them apart, and both have to be in it."""
    findings = findings_for(EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "prediction_inputs": None}))

    assert any("binds to no evidence" in f for f in findings)
    assert any("cannot be replayed" in f for f in findings)


# ===========================================================================
# THE BINDING FUNCTIONS SAY WHICH THING IS WRONG.
# ===========================================================================


def inputs_over(**over):
    from cai.contract import PredictionInput, PredictionInputs

    observations = T.observations()
    claim = T.claim()
    return PredictionInputs(**{
        "metric": claim.metric,
        "values": tuple(o.value for o in observations),
        "horizon_seconds": claim.horizon_seconds,
        "model_version": claim.model_version,
        "input_fingerprint": claim.input_fingerprint,
        "bound_inputs": tuple(
            PredictionInput(o.observation_id, o.content_digest(), o.value)
            for o in observations),
        **over,
    })


def snapshot_with(inputs):
    return EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "prediction_inputs": inputs})


def restamped(**over):
    """Inputs AND a claim that agree on a recomputed fingerprint.

    Restamping only the inputs does not reach the later checks: `input_fingerprint_mismatch`
    compares the recomputation to the CLAIM's fingerprint, so moving one and not the other
    fires the first arm every time. A forger moves both -- `input_fingerprint_for` is
    published so a verifier can re-derive it, which means an attacker can too -- and moving
    both is what makes the metric, horizon and model-version comparisons reachable at all.

    Returns (inputs, claim).
    """
    from cai.contract import PredictionClaim
    from cai.predictor import input_fingerprint_for

    inputs = inputs_over(**over)
    fingerprint = input_fingerprint_for(
        metric=inputs.metric, values=inputs.values,
        horizon_seconds=inputs.horizon_seconds, model_version=inputs.model_version,
        bound=tuple((b.observation_id, b.content_digest) for b in inputs.bound_inputs))
    return (
        inputs_over(**{**over, "input_fingerprint": fingerprint}),
        PredictionClaim(**{**T.claim().__dict__, "input_fingerprint": fingerprint}),
    )


def short_series():
    """Two readings, below the model's declared minimum, with the bound inputs to match.

    `PredictionInputs` refuses bound inputs that disagree with `values`, so a fixture that
    shortens one and not the other never reaches the predictor at all.
    """
    from cai.contract import PredictionClaim, PredictionInput
    from cai.predictor import input_fingerprint_for

    pair = T.observations()[:2]
    bound = tuple(PredictionInput(o.observation_id, o.content_digest(), o.value)
                  for o in pair)
    fingerprint = input_fingerprint_for(
        metric=T.claim().metric, values=tuple(o.value for o in pair),
        horizon_seconds=T.claim().horizon_seconds, model_version=T.claim().model_version,
        bound=tuple((b.observation_id, b.content_digest) for b in bound))
    return (
        inputs_over(values=tuple(o.value for o in pair), bound_inputs=bound,
                    input_fingerprint=fingerprint),
        PredictionClaim(**{**T.claim().__dict__, "input_fingerprint": fingerprint}),
    )


@pytest.mark.parametrize("name,build,fragment", [
    (
        "the stored fingerprint is not the claim's",
        lambda: (inputs_over(input_fingerprint="a" * 64), T.claim()),
        "carry a fingerprint the claim does not",
    ),
    (
        "the recomputation does not reproduce the claim's fingerprint",
        lambda: (inputs_over(metric="hydraulic_pressure_kpa"), T.claim()),
        "not the fingerprint of the inputs recorded",
    ),
    (
        "the inputs are about a different metric",
        lambda: restamped(metric="hydraulic_pressure_kpa"),
        "the inputs are",
    ),
    (
        "the inputs cover a different horizon",
        lambda: restamped(horizon_seconds=86400),
        "the inputs cover",
    ),
    (
        "the inputs were computed by a different model",
        lambda: restamped(model_version="degradation-baseline@9.9.9"),
        "the inputs were computed by",
    ),
])
def test_the_fingerprint_binding_says_which_field_disagrees(name, build, fragment):
    """Five distinct reasons, five distinct messages.

    Each was replaceable with any other string while every test passed, because the tests
    asserted a refusal happened rather than which one -- so a record whose horizon
    disagreed could report a metric mismatch and nothing would notice.
    """
    from cai.binding import input_fingerprint_mismatch

    inputs, claim = build()
    reason = input_fingerprint_mismatch(snapshot_with(inputs), claim)

    assert reason is not None and fragment in reason, reason


def test_honest_inputs_bind_to_their_claim():
    """The twin for all five."""
    from cai.binding import input_fingerprint_mismatch

    assert input_fingerprint_mismatch(snapshot_with(inputs_over()), T.claim()) is None


def test_the_stored_fingerprint_must_match_the_claims_own():
    """The copy in `prediction_inputs` is compared to the claim's, not only to the
    recomputed one -- a stored fingerprint disagreeing with both is a record whose two
    halves cite different readings."""
    from cai.binding import input_fingerprint_mismatch
    from cai.contract import PredictionClaim
    from cai.predictor import input_fingerprint_for

    inputs = inputs_over()
    other = input_fingerprint_for(
        metric=inputs.metric, values=inputs.values, horizon_seconds=inputs.horizon_seconds,
        model_version="degradation-baseline@9.9.9",
        bound=tuple((b.observation_id, b.content_digest) for b in inputs.bound_inputs))
    claim = PredictionClaim(**{**T.claim().__dict__, "input_fingerprint": other})

    # The claim's fingerprint is a real fingerprint of a DIFFERENT model version, so the
    # recomputation arm fires first and names it.
    reason = input_fingerprint_mismatch(snapshot_with(inputs), claim)
    assert reason is not None and "not the fingerprint of the inputs" in reason


@pytest.mark.parametrize("name,build,fragment", [
    (
        "no inputs at all",
        lambda: (None, T.claim()),
        "cannot be replayed",
    ),
    (
        "inputs outside the model's envelope",
        short_series,
        "fall outside the model's declared envelope",
    ),
])
def test_the_replay_says_why_it_could_not_reproduce_the_claim(name, build, fragment):
    from cai.binding import predictor_output_mismatch

    inputs, claim = build()
    reason = predictor_output_mismatch(snapshot_with(inputs), claim)

    assert reason is not None and fragment in reason, reason


def test_the_replay_names_the_fields_that_differ():
    """"the claim differs from what the recorded predictor produces on score" -- the field
    list is the whole diagnostic. Replaced with a fixed string, a forged score and a
    forged score_semantics become indistinguishable in the refusal."""
    from cai.binding import predictor_output_mismatch
    from cai.contract import PredictionClaim

    forged = PredictionClaim(**{**T.claim().__dict__, "score": 0.99})
    reason = predictor_output_mismatch(snapshot_with(inputs_over()), forged)

    assert reason is not None
    assert "score" in reason and "differs from what the recorded predictor produces" in reason


# ===========================================================================
# THE POINT-IN-TIME ELIGIBILITY RULE, AT ITS BOUNDARIES.
# ===========================================================================


def bundle_of(*observations):
    return EvidenceBundle(observations=observations)


def test_a_carried_reading_that_arrived_exactly_at_the_cutoff_is_eligible():
    """Inclusive at the cutoff, on the import side too -- the same boundary
    `point_in_time_view` uses, checked rather than arranged."""
    from cai.binding import point_in_time_eligibility_mismatch

    context = T.context()
    at_cutoff = Observation("a-0", "asset-4417", "battery_temp_c", 41.0,
                            T.t(12, 6), context.knowledge_cutoff, "source-a")
    after = Observation("a-1", "asset-4417", "battery_temp_c", 41.0,
                        T.t(12, 6), context.knowledge_cutoff + TICK, "source-a")

    assert point_in_time_eligibility_mismatch(bundle_of(at_cutoff), context) is None
    assert "after the knowledge cutoff" in point_in_time_eligibility_mismatch(
        bundle_of(after), context)


def test_a_carried_reading_valid_exactly_at_the_evaluation_time_is_eligible():
    from cai.binding import point_in_time_eligibility_mismatch

    context = T.context()
    at_evaluation = Observation("a-0", "asset-4417", "battery_temp_c", 41.0,
                                context.evaluation_time, context.knowledge_cutoff,
                                "source-a")

    assert point_in_time_eligibility_mismatch(bundle_of(at_evaluation), context) is None


def test_a_correction_that_arrived_after_the_cutoff_does_not_supersede_on_import():
    """The supersession filter is itself filtered by transaction time, at both
    boundaries. A correction the decision-maker had not received must not reach back and
    remove a reading the decision rested on."""
    from cai.binding import point_in_time_eligibility_mismatch

    context = T.context()
    original = Observation("a-0", "asset-4417", "battery_temp_c", 41.0,
                           T.t(12, 5), T.t(12, 5), "source-a")
    late_correction = Observation("a-1", "asset-4417", "battery_temp_c", 42.0,
                                  T.t(12, 6), context.knowledge_cutoff + TICK,
                                  "source-a", supersedes="a-0")
    early_correction = Observation("a-1", "asset-4417", "battery_temp_c", 42.0,
                                   T.t(12, 6), context.knowledge_cutoff, "source-a",
                                   supersedes="a-0")

    # The late correction is refused for its own arrival time, not for superseding.
    late = point_in_time_eligibility_mismatch(bundle_of(original, late_correction), context)
    assert "after the knowledge cutoff" in late
    assert "was corrected by" not in late
    # The early one had arrived, so carrying BOTH is a state release could not produce.
    early = point_in_time_eligibility_mismatch(
        bundle_of(original, early_correction), context)
    assert "was corrected by a later reading" in early


def test_a_reading_superseded_by_nothing_carried_is_eligible():
    """The twin: a bundle whose readings supersede nothing is clean, so the rule above is
    of a real correction rather than of the word `supersedes` appearing."""
    from cai.binding import point_in_time_eligibility_mismatch

    assert point_in_time_eligibility_mismatch(
        bundle_of(*T.observations()), T.context()) is None


# ===========================================================================
# THE RETROSPECTIVE VIEW'S SUPERSESSION FILTER.
# ===========================================================================


def test_a_correction_valid_after_the_moment_does_not_supersede_retrospectively():
    """`current_best_known_view` excludes what a correction replaced -- but only a
    correction that was itself effective by then. A correction dated next week does not
    retroactively remove this week's reading from what was believed."""
    log = ObservationLog()
    log.record(Observation("a-0", "asset-4417", "battery_temp_c", 41.0,
                           T.t(12, 5), T.t(12, 5), "source-a"))
    log.record(Observation("a-1", "asset-4417", "battery_temp_c", 42.0,
                           T.t(14), T.t(14), "source-a", supersedes="a-0"))

    at_12 = {o.observation_id for o in log.current_best_known_view(valid_time=T.t(13))}
    at_14 = {o.observation_id for o in log.current_best_known_view(valid_time=T.t(14))}

    assert at_12 == {"a-0"}, "the correction was not yet effective"
    assert at_14 == {"a-1"}, "at its own valid time it replaces what it corrects"


def test_clock_skew_exclusion_is_bounded_by_the_decision_and_the_subject():
    """`excluded_for_clock_skew` filters on transaction time AND subject, and both
    comparisons were only ever exercised with a log where they made no difference."""
    log = ObservationLog()
    log.record(Observation("skewed", "asset-4417", "battery_temp_c", 41.0,
                           T.t(12, 8), T.t(12, 7), "source-a"))
    log.record(Observation("skewed-late", "asset-4417", "battery_temp_c", 41.0,
                           T.t(13, 8), T.t(12, 7) + TICK, "source-a"))
    log.record(Observation("skewed-elsewhere", "asset-9999", "battery_temp_c", 41.0,
                           T.t(12, 8), T.t(12, 7), "source-a"))

    excluded = {o.observation_id for o in log.excluded_for_clock_skew(
        knowledge_cutoff=T.t(12, 7), subject="asset-4417")}

    assert excluded == {"skewed"}


# ===========================================================================
# THE WALK'S HONEST NEGATIVES.
# ===========================================================================


def test_a_clean_walk_reports_no_late_relationships_and_no_gaps():
    """The negative that makes every late-relationship test mean something. A rule that
    reported EVERY window as recorded-too-late passed the whole suite, because no test
    asserted the empty case."""
    impact = T.graph().derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=T.t(12, 7), horizon_end=T.t(15, 7),
        transaction_time_cutoff=T.t(12, 7))

    assert impact.derived
    assert impact.late_relationships == ()
    assert impact.missing_links == ()
    assert impact.ambiguities == ()


def test_a_component_not_fitted_at_the_horizon_start_says_exactly_that():
    """Two different "not fitted" messages exist -- one at horizon start, one at the
    window's opening -- and a fixture that trips both passes a test asserting either. The
    message has to name which."""
    from cai.context import Component

    graph = T.graph()
    graph.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=T.t(8, 1),
        source_system="asset-register", installed_from=T.t(14))
    impact = graph.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=T.t(12, 7), horizon_end=T.t(15, 7),
        transaction_time_cutoff=T.t(12, 7))

    assert any("not fitted to asset-4417 at horizon start" in m
               for m in impact.missing_links), impact.missing_links


def test_a_fact_recorded_exactly_at_the_cutoff_is_known_to_the_walk():
    """`known_at()` is the module function the window, shipment and commitment steps all
    use, and its boundary was only exercised through `Assignment.was_known_at`."""
    from cai.context import LoadingWindow, known_at

    window = LoadingWindow("win-9", "zone-3", T.t(13, 5), T.t(13, 11), "ship-22",
                           recorded_at=T.t(12, 7))

    assert known_at(window, T.t(12, 7))
    assert not known_at(window, T.t(12, 7) - TICK)


# ===========================================================================
# THE IMPORT BOUNDARY'S POLICY-DEPENDENT COMPARISONS.
# ===========================================================================


def test_the_shipped_policy_compares_identity_and_support_exactly():
    """`thresholds_known` gates the EXACT comparison of the two policy-dependent
    dimensions. Under the shipped policy the floor is known, so a recorded identity that
    the confidence does not imply is refused by name -- and this is the last guard
    `guard_sweep.py` reported removable.
    """
    forged = wire()
    dimensions = forged["product"]["assurance"]["assurance_context"]["evidence"]
    dimensions["identity"] = "AMBIGUOUS"
    dimensions["release"] = "WITHHOLD"
    dimensions["blocking_reasons"] = ["identity=AMBIGUOUS"]
    forged["product"]["assurance"]["permitted"] = False
    forged["product"]["assurance"]["blocking_reasons"] = ["identity=AMBIGUOUS"]
    forged["product"]["determination"] = "ABSTAINED"
    forged["product"]["delivery_time"] = None
    forged["product"]["valid_until"] = None
    forged["product"]["rendered_delivery"] = None
    forged["product"]["abstention_reason"] = "identity=AMBIGUOUS"

    with pytest.raises(ValueError, match="says identity=AMBIGUOUS but re-running"):
        import_envelope(forged)


def test_a_foreign_policy_does_not_get_the_exact_comparison():
    """The twin, and the reason the gate exists: the thresholds of a policy this package
    does not ship are not on the wire, so where the line was drawn is unknowable and the
    exact comparison would be a guess presented as a verdict."""
    forged = wire()
    dimensions = forged["product"]["assurance"]["assurance_context"]["evidence"]
    dimensions["identity"] = "AMBIGUOUS"
    dimensions["release"] = "WITHHOLD"
    dimensions["blocking_reasons"] = ["identity=AMBIGUOUS"]
    forged["product"]["assurance"]["policy_id"] = "acme.house-rules"
    forged["product"]["assurance"]["permitted"] = False
    forged["product"]["assurance"]["blocking_reasons"] = ["identity=AMBIGUOUS"]
    forged["product"]["determination"] = "ABSTAINED"
    forged["product"]["delivery_time"] = None
    forged["product"]["valid_until"] = None
    forged["product"]["rendered_delivery"] = None
    forged["product"]["abstention_reason"] = "identity=AMBIGUOUS"

    read = import_historical_envelope(forged)
    assert read.envelope.product.determination is Determination.ABSTAINED


def test_a_verdict_whose_reasons_differ_is_refused_even_when_permitted_agrees():
    """`permitted != recorded or blocking_reasons != recorded` -- swapped to `and`, a
    record whose verdict matches while its REASONS do not sails through. The reasons are
    what an operator acts on."""
    forged = wire(recipient="procurement@other-customer", purpose="benchmarking")
    assert forged["product"]["determination"] == "ABSTAINED"
    # An EXTRA reason the policy does not produce. `permitted` still matches, so only
    # the reasons diverge -- which is the half an `and` would miss.
    reasons = ["entitlement=UNAUTHORIZED", "identity: unresolved conflicts []"]
    forged["product"]["assurance"]["blocking_reasons"] = reasons
    forged["product"]["abstention_reason"] = "; ".join(reasons)

    with pytest.raises(ValueError, match="over the recorded assurance basis produces"):
        import_envelope(forged)


def test_an_abstention_reason_is_the_joined_blocking_reasons():
    """Derived, and the derivation is what `_verify_derived_wire_values` compares. A
    fixed string in its place agrees with itself on both sides of the wire."""
    product = T.deliver(recipient="procurement@other-customer", purpose="benchmarking")

    assert product.determination is Determination.ABSTAINED
    assert product.abstention_reason() == "; ".join(product.assurance.blocking_reasons)
    assert "entitlement" in product.abstention_reason()
    assert T.deliver().abstention_reason() is None


def test_status_events_survive_the_wire():
    """`payload.get("status_events") or ()` reads as a default and is a real branch:
    swapped, a supersession is dropped on import and a reader following the lineage
    forward finds nothing."""
    from cai.envelope import StatusEvent, StatusEventType

    envelope = IntelligenceEnvelope(
        product=T.deliver(),
        status_events=(StatusEvent(StatusEventType.SUPERSEDED, T.t(13, 6), "system",
                                   replacement_product_id="ip-002"),))
    text = envelope.canonical_json()

    rebuilt = import_envelope(json.loads(text))

    assert len(rebuilt.status_events) == 1
    assert rebuilt.status_events[0].replacement_product_id == "ip-002"
    assert rebuilt.canonical_json() == text


def test_a_lifecycle_is_closed_only_at_the_outcome():
    """`is_closed()` returns a bool, and a truthy non-bool passes an `assert` just as
    well -- so the assertion has to be `is True` and `is False`."""
    from cai.lifecycle import DispositionState, ProductLifecycle

    lifecycle = ProductLifecycle("asset-4417/battery-pack", product_id="ip-001")
    lifecycle.advance(DispositionState.DELIVERED, at=T.t(12, 7), actor="system")
    assert lifecycle.is_closed() is False

    lifecycle.advance(DispositionState.IGNORED, at=T.t(12, 9), actor="ops")
    assert lifecycle.is_closed() is False

    lifecycle.advance(DispositionState.OUTCOME_OBSERVED, at=T.t(13, 4), actor="ops")
    assert lifecycle.is_closed() is True


def test_an_inapplicable_model_records_support_as_UNSUPPORTED():
    """The six dimensions are the record's own statement about itself, and this one was
    masked.

    `ReleasePolicy.evaluate` adds its own "applicability" reason from the assertion, so a
    product with an inapplicable model abstains either way -- and every test asserted the
    ABSTENTION rather than the DIMENSION. With the support arm removed, the record still
    refused while recording `support=SUPPORTED` beside `applicability: not valid`, which
    is a bundle saying the evidence backed a claim the model had no business making.

    A model used outside its declared envelope supports nothing, whatever number it
    returned.
    """
    from cai.candidate import ApplicabilityAssertion
    from cai.evidence import Support

    inapplicable = T.deliver(assurance=T.assurance(applicability=ApplicabilityAssertion(
        "degradation-baseline@1.3.0", "forklift/battery-pack", False,
        "this series came off a different kind of thing")))

    assert inapplicable.determination is Determination.ABSTAINED
    assert inapplicable.assurance.assessed.evidence_assessment.support is (
        Support.UNSUPPORTED)
    # The twin, on the same dimension: an applicable model over strong evidence SUPPORTS.
    assert T.deliver().assurance.assessed.evidence_assessment.support is Support.SUPPORTED


# ===========================================================================
# THE PACKAGE SURFACE THAT HAD NO CALLERS.
#
# Six importable names were deleted this increment as dead code, and Control Tower
# rejected that: §12(D) authorised deleting dead GUARDS, not importable types and
# methods, and zero call sites INSIDE this repository does not establish that a name
# is outside the package contract. There is no `__init__.py` declaring a surface, so
# every module-level name is importable by anyone, and `NOT_RECONSTRUCTABLE` is named
# in a frozen artifact.
#
# They were untested, not dead. Restored, and tested here.
# ===========================================================================


def test_the_evidence_status_vocabulary_is_two_valued_and_says_reconstructable():
    """Both members are meaningful answers. The names matter: they were PROVEN and
    NOT_PROVABLE, and that was an overclaim -- nothing here establishes that a claim is
    true, only that the record can be reassembled and examined."""
    from cai.contract import EvidenceStatus

    assert [s.value for s in EvidenceStatus] == [
        "RECONSTRUCTABLE", "NOT_RECONSTRUCTABLE"]
    assert "PROVEN" not in [s.value for s in EvidenceStatus], (
        "a reader who sees PROVEN beside a claim reasonably concludes it was verified"
    )


def test_a_reconstruction_reports_its_status_and_survives_export():
    from cai.contract import EvidenceStatus, Reconstruction

    good = Reconstruction(EvidenceStatus.RECONSTRUCTABLE, (), "asset-4417")
    bad = Reconstruction(EvidenceStatus.NOT_RECONSTRUCTABLE,
                         ("observation_ids", "captured_at"), "asset-4417")

    assert good.is_reconstructable() is True
    assert bad.is_reconstructable() is False
    assert bad.as_record() == {
        "subject": "asset-4417",
        "status": "NOT_RECONSTRUCTABLE",
        "missing_evidence": ["observation_ids", "captured_at"],
    }


def test_a_snapshot_knows_whether_it_is_complete():
    """`is_complete()` is the boolean form of `missing_elements()`. Both must agree, and
    a mutation that made one constant would leave them disagreeing."""
    complete = T.evidence(T.claim())
    incomplete = EvidenceSnapshot(**{
        **complete.__dict__, "semantic_rule_version": None})

    assert complete.is_complete() is True
    assert incomplete.is_complete() is False
    assert bool(incomplete.missing_elements()) is not incomplete.is_complete()


def test_the_business_impact_renders_its_walk_and_its_failure():
    """`business_context_text()` renders from `source_facts`, so the prose and the
    derivation cannot drift -- there is only one place the words can come from. The
    undived case must say WHY, or a thin conclusion is indistinguishable from a correct
    finding of no impact."""
    from tests._fixtures import derived_impact, underived_impact

    derived, undived = derived_impact(), underived_impact()

    assert derived.business_context_text().startswith("derived via ")
    assert "HAS_COMPONENT(asset-4417,battery-pack-1)" in derived.business_context_text()
    assert undived.business_context_text().startswith("no business context derived (")
    assert undived.blocking_reasons(), "a refusal with no reason is a silent gap"
    for reason in undived.blocking_reasons():
        assert reason in undived.business_context_text()


def test_the_business_impact_renders_the_commitment_it_actually_reached():
    from tests._fixtures import derived_impact, underived_impact

    assert derived_impact().economic_consequence_text() == (
        "at risk: next-day delivery window, customer A")
    assert underived_impact().economic_consequence_text() == (
        "no customer commitment reached by derivation")


def test_a_prediction_is_actionable_at_its_floor_and_not_below():
    """`confidence >= floor`, inclusive. A predictor that refused AT its own stated floor
    would be applying a different number than the one it declares."""
    from datetime import timedelta

    from cai.predictor import predict_degradation

    prediction = predict_degradation(
        metric="battery_temp_c", values=tuple(o.value for o in T.observations()),
        horizon=timedelta(days=3),
        bound=tuple((o.observation_id, o.content_digest()) for o in T.observations()))

    assert prediction.is_actionable(prediction.confidence) is True
    assert prediction.is_actionable(prediction.confidence - 0.000001) is True
    assert prediction.is_actionable(prediction.confidence + 0.000001) is False
