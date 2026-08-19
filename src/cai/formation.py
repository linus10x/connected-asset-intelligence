"""PRODUCT FORMATION -> PRODUCT ASSURANCE -> RELEASE.

Two questions, in order, and the order is the architecture:

    FORMATION   can we form a meaningful intelligence product?
    ASSURANCE   may we responsibly deliver it?

Formation failing means there is nothing here to assess. A prediction with no reachable,
actionable consequence is a maintenance alert, and shipping it as sold intelligence is the
category error the whole project argues against. That is why context never became a seventh
assurance dimension: it is not a property of a candidate's evidence, it is the question of
whether a candidate exists.

The signature is the control. There is no parameter here through which a caller can supply
prose, a horizon, a confidence, or an action independent of the typed candidate -- those
escape hatches are what every recurring defect came out of, and closing them structurally
is worth more than any test asserting they should not be used.
"""

from __future__ import annotations

from datetime import datetime

from .binding import subject_binding_mismatch, verify_bindings
from .bitemporal import ObservationLog
from .candidate import AssessedAssurance, AssuranceContext, IntelligenceCandidate
from .contract import EvidenceSnapshot
from .delivery import RenderedDelivery, trust_line
from .policy import ReleasePolicy
from .assessment import assess_release_evidence
from .product import Determination, IntelligenceProduct


class FormationRefused(Exception):
    """Raised when no coherent intelligence product can be formed at all.

    Distinct from an abstention. An abstention is a product that exists and was withheld,
    and it is a recordable outcome. This is the absence of a product, which is not.
    """


def release(
    *,
    candidate: IntelligenceCandidate,
    assurance: AssuranceContext,
    evidence: EvidenceSnapshot,
    observation_log: ObservationLog,
    recipient: str,
    purpose: str,
    tenant: str,
    product_id: str,
    claim_series_id: str,
    release_decision_time: datetime,
    valid_until: datetime | None = None,
    supersedes_product_id: str | None = None,
    policy: ReleasePolicy | None = None,
) -> IntelligenceProduct:
    """Assess a formed candidate and return a delivered product or a reasoned abstention.

    THE EVIDENCE IS ISSUED HERE, NOT SUPPLIED
    -----------------------------------------
    This path used to take an `EvidenceBundle`, and the docstring said there was no
    arrangement of arguments in which it saw the readings and not the contradictions found
    in them. That read like a proof and it was false, through two audits.

    `EvidenceBundle` is a frozen dataclass with a public constructor and
    `integrity_conflicts` defaulting to `()`. A caller who built one by hand handed this
    path the readings and no contradictions, and nothing here could recompute them:
    `ObservationLog.record` keeps the first reading and rejects the second, so the rogue
    was never in `bundle.observations` to be found. The TYPE was enforced; what the type
    CONTAINED was a convention, and those are different guarantees.

    So the parameter is gone. This path takes the LOG and asks it, so the authority that
    detects a same-id/different-payload conflict is the authority that issues the evidence
    the assessment runs over. There is no argument left through which a caller can assert
    that a bundle came from a log.

    WHAT THE CALLER STILL CHOOSES, AND WHY THAT IS SAFE
    ---------------------------------------------------
    The point-in-time query needs a clock and a subject. Both come from objects that are
    already bound to this decision rather than from free parameters: the clock from
    `candidate.context`, which `DecisionContext` makes the single temporal authority and
    `verify_bindings` checks the temporal assertion against; the subject from
    `evidence.subject`, which `assess_evidence` then re-checks against the subjects of the
    readings the log actually returned. A caller who names a different subject gets a
    bundle about that subject and an integrity dimension that says so.

    THE INPUT CLOCK IS A RELEASE DECISION, AND IT USED TO BE CALLED `delivery_time`
    ------------------------------------------------------------------------------
    Whatever the caller passed went straight into `assess_release_evidence` and
    `policy.evaluate` as `release_decision_time`, because that is what it is: the moment
    the system decides whether the intelligence may go out. Only afterwards, and only if
    the decision permits, does anything get delivered.

    So on the abstained path the parameter was named after an event that does not happen.
    `product.delivery_time` is None there -- correctly, nothing was delivered -- while the
    argument the caller had to pass to reach that outcome was called `delivery_time`. A
    reader reconciling the package's own three-clock model against this signature found the
    public API contradicting it at the entry point.

    The rename does not introduce a fourth clock or a delivery-delay abstraction. This
    reference implementation delivers immediately when it decides to, so on the delivered
    path `delivery_time` and `rendered_at` are both this same instant. The declared rule is
    unchanged:

        model_decision_time <= release_decision_time

    and, only when delivered:

        release_decision_time == delivery_time

    A system that queued or batched deliveries would need a genuinely separate clock. This
    one does not, and inventing the parameter before the behaviour would be an abstraction
    with no implementation behind it.
    """
    policy = policy or ReleasePolicy()

    # An `EvidenceBundle` seated here would duck-type far enough to be confusing and not
    # far enough to work, so it is refused by name. This is the guard that makes "a
    # hand-built bundle cannot be substituted into the supported release path" a runtime
    # fact rather than a claim about a type annotation.
    if not isinstance(observation_log, ObservationLog):
        raise TypeError(
            f"observation_log must be an ObservationLog, not "
            f"{type(observation_log).__name__}; release obtains its evidence from the log "
            f"that detected the conflicts in it, and evidence a caller assembles is "
            f"evidence nobody reconciled"
        )

    # Before anything is assessed: is this assurance context even about this candidate?
    # Grading the evidence of a claim whose assertions describe a different asset is a
    # confident answer to the wrong question.
    verify_bindings(candidate, assurance, evidence)

    # THE POINT-IN-TIME VIEW, TAKEN RATHER THAN TRUSTED.
    # `point_in_time_view` requires transaction_time <= model_decision_time and valid_time <=
    # evaluation_time, drops readings whose two clocks contradict each other, and drops
    # anything a correction that had arrived by then supersedes. Because release now
    # performs that query itself, every one of those properties holds of `evidence_source`
    # by construction.
    #
    # This is what replaced an explicit `transaction_time > knowledge_cutoff` refusal that
    # used to sit a few lines below. That check existed because the bundle arrived from
    # outside and might not have come from this query; it cannot fire now, and a guard no
    # input can reach reads as protection while proving nothing. The same rule is enforced
    # -- by `binding.point_in_time_eligibility_mismatch` -- at the import boundary, where
    # the readings DO arrive from outside and the property has to be checked rather than
    # arranged.
    evidence_source = observation_log.evidence_for(
        knowledge_cutoff=candidate.context.knowledge_cutoff,
        evaluation_time=candidate.context.evaluation_time,
        subject=evidence.subject or None,
    )
    # The claim, the readings and the walk must all be about the same thing. Raised rather
    # than abstained: a claim about a different asset than its own evidence is not a
    # business refusal, it is an incoherent input.
    reason = subject_binding_mismatch(
        candidate, frozenset(o.subject for o in evidence_source.observations)
    )
    if reason is not None:
        raise ValueError(f"the claim does not describe its own evidence: {reason}")

    # The evidence assessment is COMPUTED here, never accepted from the caller. Taking it
    # as an input is the same defect this path was built to close: a verification that a
    # caller asserts is a verification nobody performed. `evidence_source` exists to be
    # used, and `AssuranceContext` no longer has a field through which a caller could
    # offer an assessment at all.
    computed = assess_release_evidence(
        evidence=evidence,
        entitlement_assertion=assurance.entitlement_assertion,
        delivering_to=recipient,
        for_purpose=purpose,
        # Subject from the claim itself, not from the clearance and not from a caller
        # argument: the entitlement must bind to the asset the claim is actually about.
        about_subject=candidate.prediction_claim.subject,
        for_tenant=tenant,
        release_decision_time=release_decision_time,
        confidence=candidate.prediction_claim.evidence_strength,
        model_applicable=assurance.applicability_assertion.valid,
        point_in_time_correct=assurance.temporal_assertion.valid,
        evidence_source=evidence_source,
        prediction_claim=candidate.prediction_claim,
        derivation=candidate.business_consequence.derivation,
        # One authority for the thresholds. The dimensions and the policy used to read
        # from two separate sets of constants that happened to agree.
        policy=policy,
        # Unconditionally. The claim was produced moments ago by this process, so one
        # carrying another build's artifact digest is incoherent here and has to FAIL the
        # replay rather than be excused from it. The import boundary is the only place
        # where "this build cannot check that" is a real answer.
    )
    # The caller supplied the four assertions; the assessment is the one thing here they
    # could not. Joining them now is what makes the decision carry its own basis.
    assessed = AssessedAssurance(context=assurance, evidence_assessment=computed)
    decision = policy.evaluate(
        candidate, assessed, release_decision_time=release_decision_time
    )

    if not decision.permitted:
        return IntelligenceProduct(
            product_id=product_id,
            candidate=candidate,
            assurance=decision,
            evidence=evidence,
            # The evidence the assessment actually ran over, carried out with the product.
            # An abstention needs it as much as a delivery does: the recorded refusal is
            # only checkable by a reader who can recompute the assessment that produced it.
            release_evidence=evidence_source,
            determination=Determination.ABSTAINED,
            recipient=recipient,
            purpose=purpose,
            tenant=tenant,
            claim_series_id=claim_series_id,
            supersedes_product_id=supersedes_product_id,
        )

    # Rendered only on delivery, and only from the candidate. There is no path by which a
    # caller hands us the sentence the customer reads.
    # Immediate delivery: the decision instant IS the delivery instant and the render
    # instant. Three names for one moment, because this implementation does not queue.
    rendered = RenderedDelivery.render(candidate, rendered_at=release_decision_time)
    # `with_trust_line` restamps the digest. Rebuilding the dataclass here by hand is what
    # carried the pre-trust-line digest onto every delivered product.
    rendered = rendered.with_trust_line(
        trust_line(identity_confidence=assurance.identity_assertion.confidence)
    )

    return IntelligenceProduct(
        product_id=product_id,
        candidate=candidate,
        assurance=decision,
        evidence=evidence,
        release_evidence=evidence_source,
        determination=Determination.DELIVERED,
        recipient=recipient,
        purpose=purpose,
        tenant=tenant,
        claim_series_id=claim_series_id,
        delivery_time=release_decision_time,
        valid_until=valid_until,
        supersedes_product_id=supersedes_product_id,
        rendered_delivery=rendered,
    )
