"""The joins. Every check here relates two objects neither of which can see the other.

WHY A MODULE RATHER THAN A METHOD
---------------------------------
A binding is a relation between two things, so it cannot live inside either of them:
`IdentityAssertion` cannot see the claim it resolves, and `PredictionClaim` cannot see the
assurance context asserted about it. Putting these on one of the two types would mean
handing that type a reference to the other, which is how the dependency graph acquires a
cycle and how one of the pair quietly becomes the authority for both.

WHY IT IS NOT INSIDE `formation`
--------------------------------
It was, and that was the hole. `formation.release()` verified the bindings and
`import_envelope()` did not, so a wire payload could alter the recorded assurance basis
and the import boundary applied none of the guarantees that apply at live release. The
fix is not a second validator on the wire side -- two engines drift, and the day they
disagree is the day the portable form stops meaning what the in-memory form means. It is
one set of functions, called from both boundaries.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Nothing in this module decides whether a product may be delivered. These raise on
INCOHERENCE -- assurance about a different asset, a claim about a different model -- which
is a malformed input, not a business refusal. A claim the evidence cannot support is a
refusal, it is an assessment, and it belongs to the release path with a reason attached.
"""

from __future__ import annotations

from datetime import timedelta

from .bitemporal import EvidenceBundle
from .candidate import AssuranceContext, IntelligenceCandidate
from .contract import EvidenceSnapshot, PredictionClaim
from .decision import DecisionContext
from .predictor import (
    OutsideApplicability,
    input_fingerprint_for,
    model_artifact_digest,
    predict_degradation,
)


def verify_bindings(
    candidate: IntelligenceCandidate,
    assurance: AssuranceContext,
    evidence: EvidenceSnapshot,
) -> None:
    """Every assertion must be ABOUT this candidate, or it is assurance for something else.

    These fields existed, travelled in the record, printed in the hero, and were read by
    anyone auditing the decision -- while binding to nothing. The assurance layer could
    resolve the identity of a different asset, declare a different model applicable, and
    assert point-in-time correctness for a different decision, and the product shipped
    with all three. The fixtures even disagreed on the first one: identity resolved
    `asset-4417` for a claim about `asset-4417/battery-pack`, and nothing noticed.

    Raised rather than abstained: an assurance context describing a different subject is
    not a business refusal, it is an incoherent input, and the same class of incoherence
    the candidate already raises on.
    """
    claim = candidate.prediction_claim
    context = candidate.context

    if assurance.identity_assertion.resolved_entity != claim.subject:
        raise ValueError(
            f"identity resolves {assurance.identity_assertion.resolved_entity!r} but the "
            f"claim is about {claim.subject!r}; this is assurance for a different asset"
        )
    if assurance.applicability_assertion.model_version != claim.model_version:
        raise ValueError(
            f"applicability is asserted for "
            f"{assurance.applicability_assertion.model_version!r} but the claim came from "
            f"{claim.model_version!r}; the envelope checked belongs to a model that did "
            f"not run"
        )
    # The subject type is now an assertion against something. Only a claim TO validity is
    # refused: asserting that a use outside the declared envelope is nonetheless
    # applicable is incoherent, while reporting that it is not applicable is the honest
    # verdict and must remain expressible -- it abstains, with a reason.
    #
    # THREE CHECKS, IN THIS ORDER, AND THE ORDER IS LOAD-BEARING.
    # An unknown subject type, an unsupported COMBINATION, and a part segment naming
    # something no assertion covers are three different faults with three different
    # remedies, and a test for the middle one is worthless if the first or last fires on
    # its fixture. The pair check sits above the part check for exactly that reason: a
    # claim about a battery pack asserted applicable as a hydraulic system trips both,
    # and the pair is the more fundamental fact about it.
    envelope = claim.declared_envelope
    asserted_type = assurance.applicability_assertion.subject_type
    if assurance.applicability_assertion.valid:
        if not envelope.admits_subject_type(asserted_type):
            raise ValueError(
                f"applicability asserts subject type {asserted_type!r} is valid, but the "
                f"model's declared envelope admits {envelope.supported_subject_types}; "
                f"the assertion invents an envelope of its own rather than checking the "
                f"one the claim carries"
            )
        # The cross-product, closed. `supported_metrics` and `supported_subject_types`
        # were independent sets, so a metric valid somewhere and a subject type valid
        # somewhere read as valid together -- and this model orients the sign of the trend
        # by metric, so a pressure series read off a battery pack is not a worse answer,
        # it is an answer to a question nobody asked.
        if not envelope.admits_pair(claim.metric, asserted_type):
            raise ValueError(
                f"the model declares no applicability for {claim.metric!r} on "
                f"{asserted_type!r}; it supports "
                f"{[(a.metric, a.subject_type) for a in envelope.supported_applicability]}"
                f", and a metric valid somewhere paired with a subject type valid "
                f"somewhere is not a combination anything was fitted for"
            )
    if (
        assurance.temporal_assertion.model_decision_time != context.model_decision_time
        or assurance.temporal_assertion.knowledge_cutoff != context.knowledge_cutoff
    ):
        raise ValueError(
            "the temporal assertion describes a different decision than the candidate's "
            "DecisionContext; the context is the single temporal authority and an "
            "assertion free to disagree with it is a second one"
        )
    # The part segment was a free variable. `subject_binding_mismatch` compares the
    # OBSERVED subject to the walk, never the claim's own, so everything after the first
    # `/` answered to nothing: a claim about `asset-4417/hydraulic-pump` released on
    # `battery_temp_c` readings while the walk named `battery-pack-1` at every step.
    #
    # The part is bound to the one field that asserts what kind of thing this is --
    # `ApplicabilityAssertion.subject_type`, which is itself already checked against the
    # model's declared envelope just above. Binding it here rather than inventing a parts
    # taxonomy keeps this a join between two things that already exist.
    # Guarded on `valid` for the same reason the envelope check above it is: reporting
    # that a use is NOT applicable is the honest verdict and must stay expressible -- it
    # abstains, with a reason. Only a claim TO applicability has to name the right part.
    observed = evidence.subject
    if (
        assurance.applicability_assertion.valid
        and observed
        and claim.subject.startswith(observed + "/")
    ):
        part = claim.subject[len(observed) + 1:]
        asserted = assurance.applicability_assertion.subject_type
        asserted_part = asserted.split("/", 1)[1] if "/" in asserted else asserted
        if part != asserted_part:
            raise ValueError(
                f"the claim is about the {part!r} of {observed!r}, but no assertion says "
                f"this claim is about a {part!r} -- applicability names "
                f"{asserted_part!r}; the part of the subject is asserted by nobody"
            )
    # Which rules produced the walk is one fact, and it was recorded twice with nothing
    # comparing the copies -- the shipped fixture itself carried `context-rules@0.7.0` on
    # the evidence and `context-rules@0.8.0` on the derivation, and the honest release path
    # emitted the disagreement. The model version and the two identity confidences are
    # bound here for exactly this reason; the rule version escaped.
    walk = candidate.business_consequence.derivation
    if (
        evidence.semantic_rule_version is not None
        and evidence.semantic_rule_version != walk.rule_version
    ):
        raise ValueError(
            f"the evidence names semantic rules {evidence.semantic_rule_version!r} but "
            f"the walk was performed under {walk.rule_version!r}; a reader asking which "
            f"rules produced the REASON path gets two answers out of one bundle"
        )
    if evidence.model_version is not None and evidence.model_version != claim.model_version:
        raise ValueError(
            f"evidence names model {evidence.model_version!r} but the claim came from "
            f"{claim.model_version!r}; the snapshot describes a different computation"
        )
    # Identity confidence was stored TWICE -- on the snapshot as a bare scalar, and on the
    # assertion that has a resolver, a version and evidence refs behind it -- and nothing
    # bound them. That is the two-authorities pattern on the dimension that decides whether
    # anyone knows what the claim is about, and it is what let a payload carry
    # `identity_confidence=0.02` beside a recorded `identity=RESOLVED`: the assessment was
    # projected from one copy and the policy consulted the other.
    #
    # The assertion is the authority -- a number with a resolver behind it can be
    # challenged, a bare float cannot -- so the snapshot must agree with it.
    if (
        evidence.identity_confidence is not None
        and evidence.identity_confidence != assurance.identity_assertion.confidence
    ):
        raise ValueError(
            f"the evidence snapshot records identity confidence "
            f"{evidence.identity_confidence} but {assurance.identity_assertion.resolver!r} "
            f"asserted {assurance.identity_assertion.confidence}; two numbers for one "
            f"question is how a record comes to be graded against one and reported "
            f"against the other"
        )


def subject_binding_mismatch(
    candidate: IntelligenceCandidate, observed_subjects: frozenset[str]
) -> str | None:
    """Is the claim about the thing the readings are about?

    THE DEFECT THIS CLOSES
    ----------------------
    `claim.subject` was a free variable. Every check that consumed a subject read it FROM
    THE CLAIM -- the entitlement scope, the identity assertion, the rendered card, the
    replay's own comparison claim -- so relabelling the asset consistently across all of
    them produced a DELIVERED product about `asset-9999/battery-pack` computed entirely
    from `asset-4417`'s telemetry. Nothing anywhere compared the claim's subject to
    `Observation.subject`, at the release path or at the import boundary.

    The record even contradicted itself in plain text: the derivation walk carried inside
    the same bundle names `asset-4417` at every step. Nobody looked.

    THE CONVENTION, STATED RATHER THAN INFERRED
    -------------------------------------------
    A claim's subject is either the observed subject itself, or a part of it written
    `<observed>/<part>`. That is the identifier scheme this reference implementation
    already uses -- observations about `asset-4417`, a claim about
    `asset-4417/battery-pack` -- and it was a convention nothing enforced. Enforcing it is
    a narrow, checkable rule; inferring an entity-resolution ontology from the strings
    would be the platform this project declines to build.

    A claim resting on readings from more than one subject is refused outright: the
    evidence would be about several things and the claim about one, and nothing in the
    record would say how they combine.
    """
    claim = candidate.prediction_claim
    if not observed_subjects:
        return "the claim rests on no observations at all"
    if len(observed_subjects) > 1:
        return (
            f"the readings are about {sorted(observed_subjects)} but the claim is about "
            f"one thing; a claim over several subjects needs a rule for combining them "
            f"that this record does not carry"
        )
    observed = next(iter(observed_subjects))
    if claim.subject != observed and not claim.subject.startswith(observed + "/"):
        return (
            f"the claim is about {claim.subject!r} but every reading it rests on is about "
            f"{observed!r}; a claim is either about the observed subject or about a part "
            f"of it written '<subject>/<part>'"
        )
    # And the walk that produced the consequence has to be about it too. The derivation is
    # the one place the record states, in its own words, which asset this decision is for.
    #
    # THE ROOT, not merely a mention. `entities()` is a flat set, so this check was
    # satisfied by an asset appearing anywhere in the walk -- including as the OBJECT of a
    # step that arrived at it from something else. The walk is rooted at the thing it is
    # about, and a derivation that reaches the observed asset from elsewhere is a walk
    # about a different subject that happens to pass through this one.
    walk = candidate.business_consequence.derivation
    if walk.root_entity != observed:
        if observed not in walk.entities():
            return (
                f"the readings are about {observed!r}, which the derivation "
                f"{walk.explain()} never mentions; the evidence and the reasoning "
                f"describe different things"
            )
        return (
            f"the readings are about {observed!r} but the derivation is rooted at "
            f"{walk.root_entity!r} and only passes through it; a walk about one asset "
            f"that mentions another does not make the other its subject"
        )
    return None


def point_in_time_eligibility_mismatch(
    bundle: EvidenceBundle, context: DecisionContext
) -> str | None:
    """Could this decision have rested on exactly these readings, on its own clock?

    WHY THIS IS A FUNCTION AND NOT A LINE INSIDE THE IMPORTER
    ---------------------------------------------------------
    The release path gets this property by construction: it asks `ObservationLog
    .evidence_for` for the point-in-time view, and the view is defined by these rules. The
    import boundary cannot -- the readings arrive from outside, attached to a decision
    context that also arrives from outside, and nothing about the pair is arranged.

    Written once and named, so the property release ARRANGES and the property import
    CHECKS are the same property, stated in one place. `point_in_time_view` is the other
    half of that pair; if either moves, this is the function that has to move with it.

    THE ONE RULE THAT IS ONLY PARTLY RECONSTRUCTABLE, STATED
    -------------------------------------------------------
    Supersession is checked against the carried readings only. At release, a correction
    that had arrived by the cutoff removes what it corrects even when the correction
    itself falls outside the view (a future valid time, say), and a reader holding only
    the bundle cannot see a correction the bundle does not carry. What IS checkable is
    that no carried reading is superseded by another carried reading that had arrived --
    which is the forgery worth closing, because it is the one a producer can construct.
    """
    reasons: list[str] = []
    superseded_by_then = {
        o.supersedes
        for o in bundle.observations
        if o.supersedes and o.transaction_time <= context.knowledge_cutoff
    }
    for observation in bundle.observations:
        if observation.transaction_time > context.knowledge_cutoff:
            reasons.append(
                f"{observation.observation_id} reached this system "
                f"{observation.transaction_time.isoformat()}, after the knowledge cutoff "
                f"{context.knowledge_cutoff.isoformat()}"
            )
        if observation.valid_time > context.evaluation_time:
            reasons.append(
                f"{observation.observation_id} describes an event at "
                f"{observation.valid_time.isoformat()}, after the evaluation time "
                f"{context.evaluation_time.isoformat()}"
            )
        if observation.has_implausible_clock():
            reasons.append(
                f"{observation.observation_id} claims an event that had not happened when "
                f"it arrived"
            )
        if observation.observation_id in superseded_by_then:
            reasons.append(
                f"{observation.observation_id} was corrected by a later reading the "
                f"decision-maker already had"
            )
    if not reasons:
        return None
    return (
        "the carried evidence is not the point-in-time view this decision could have "
        "rested on: " + "; ".join(sorted(reasons))
    )


def claim_is_replayable_here(claim: PredictionClaim) -> bool:
    """Whether the running implementation is the one that produced this claim.

    A claim from a different build cannot be replayed by this one, and pretending
    otherwise would compare two models and blame the record for the difference. Stated as
    a question so the two boundaries can answer it differently: at release the answer must
    be yes, because the claim was produced moments ago by this process.
    """
    return claim.model_artifact_digest == model_artifact_digest()


def input_fingerprint_mismatch(
    evidence: EvidenceSnapshot, claim: PredictionClaim
) -> str | None:
    """Does the claim's fingerprint belong to the inputs recorded beside it?

    Recomputed rather than compared to the copy in `prediction_inputs`, which would only
    prove the record agrees with itself. The fingerprint is a pure function of metric,
    values, horizon, model version and the bound observations, so this check needs no
    predictor implementation and holds for a record produced by a build we do not have.
    """
    pi = evidence.prediction_inputs
    if pi is None:
        return "the record carries no prediction inputs, so the claim binds to no evidence"
    expected = input_fingerprint_for(
        metric=pi.metric,
        values=pi.values,
        horizon_seconds=pi.horizon_seconds,
        model_version=pi.model_version,
        bound=tuple((b.observation_id, b.content_digest) for b in pi.bound_inputs),
    )
    if expected != claim.input_fingerprint:
        return (
            "the claim's input fingerprint is not the fingerprint of the inputs recorded "
            "beside it; the record cites one set of readings and carries another"
        )
    if pi.input_fingerprint != claim.input_fingerprint:
        return "the prediction inputs carry a fingerprint the claim does not"
    if pi.metric != claim.metric:
        return f"the inputs are {pi.metric!r} but the claim is about {claim.metric!r}"
    if pi.horizon_seconds != claim.horizon_seconds:
        return (
            f"the inputs cover {pi.horizon_seconds}s but the claim asserts "
            f"{claim.horizon_seconds}s"
        )
    if pi.model_version != claim.model_version:
        return (
            f"the inputs were computed by {pi.model_version!r} and the claim came from "
            f"{claim.model_version!r}"
        )
    return None


def predictor_output_mismatch(
    evidence: EvidenceSnapshot, claim: PredictionClaim
) -> str | None:
    """Replay the recorded predictor and compare EVERY field it determined.

    THE DEFECT THIS CLOSES
    ----------------------
    The release path bound the claim to its input fingerprint, its metric and its horizon.
    It bound none of the values the predictor actually produced. A caller could keep a
    perfectly legitimate fingerprint over genuine observations, substitute a different
    score -- or, worse, leave the score alone and change what the score is said to MEAN --
    and reach DELIVERED with every other signal green.

    That is the whole product thesis. A record that proves the inputs reproduce a number,
    while leaving the stored number and its stated meaning free, has proved the least
    interesting half of the claim.

    THE COMPARISON IS WHOLE-RECORD ON PURPOSE
    -----------------------------------------
    Rebuilding the claim the predictor WOULD produce and comparing the portable forms
    means no field can be forgotten, now or when a field is added. A hand-listed set of
    comparisons is a list somebody maintains, and the defect being fixed is precisely that
    three fields were on such a list and four were not.

    Returns a reason rather than raising: a claim its evidence cannot support is a
    withholding, not a malformed input.
    """
    pi = evidence.prediction_inputs
    if pi is None:
        return "the record carries no prediction inputs, so the claim cannot be replayed"
    try:
        replayed = predict_degradation(
            metric=pi.metric,
            values=pi.values,
            horizon=timedelta(seconds=pi.horizon_seconds),
            bound=tuple((b.observation_id, b.content_digest) for b in pi.bound_inputs),
        )
    except OutsideApplicability as exc:
        return f"the recorded inputs fall outside the model's declared envelope: {exc}"

    produced = PredictionClaim.from_prediction(replayed, subject=claim.subject).as_record()
    recorded = claim.as_record()
    differing = sorted(k for k in produced if produced[k] != recorded.get(k))
    if differing:
        return (
            "the claim differs from what the recorded predictor produces on "
            + ",".join(differing)
            + "; the record asserts something this evidence did not compute"
        )
    return None
