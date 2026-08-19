"""The release decision: may this claim be delivered to this recipient, now?

The ordering below is deliberate. Entitlement is checked before evidence because a
claim the operator has no right to deliver should be refused on those grounds, and
saying so plainly is more useful to the reader than a generic refusal.

The five questions, in order:

  1. Identity and context -- do we know what this claim is about?
  2. Model applicability  -- is the predictor valid here, on point-in-time data?
  3. Entitlement          -- may we use this data and deliver to this recipient?
  4. Evidence sufficiency -- could we defend this claim afterwards?
  5. Release authority    -- is the claim certain enough to act on?

A note on question 5, because the wording used to overreach. It was described as
"release authority scaled to consequence", which promised that a costlier consequence
would face a higher bar. It does not: the check is a single global confidence floor, and
`economic_consequence` never enters the decision. Consequence-scaled authority is a
reasonable thing to build and this is not it, so the description now matches the code.

Each returns a named reason on refusal. "Blocked" without a reason is the same
failure as a silent gap.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .bitemporal import EvidenceBundle, digest_observations
from .contract import EvidenceSnapshot, PredictionClaim
from .evidence import (
    Completeness,
    EntitlementState,
    EvidenceAssessment,
    Identity,
    Integrity,
    Release,
    Support,
    TemporalEligibility,
)

if TYPE_CHECKING:  # policy imports candidate, which must not depend on this module
    from .candidate import EntitlementAssertion
    from .derivation import ConsequenceDerivation
    from .policy import ReleasePolicy

# `IDENTITY_CONFIDENCE_FLOOR` and `MIN_DELIVERABLE_CONFIDENCE` used to be defined HERE as
# well as in `policy.py`, with identical values and near-identical comments. Two
# authorities for one threshold, and the worse half of the pair: `ReleasePolicy.digest()`
# hashes only the policy's own copies, while the identity and support DIMENSIONS were
# decided by these -- so the digest that exists "so a threshold edited without a version
# bump is still detectable" could not detect an edit to the number that actually decided,
# and moved when a number that did not decide was changed. The thresholds now arrive from
# the policy, so there is one authority and the digest covers it.
#
# `POLICY_VERSION = "release-policy@1.0.0"` also sat here and was stamped onto nothing.
# Deleted with the legacy release representation it belonged to, along with the
# `dataclass`, `timezone` and `BusinessImpact` imports that only `evaluate_release` used.


def material_source_systems(
    *, evidence_source: EvidenceBundle, derivation: "ConsequenceDerivation"
) -> tuple[str, ...]:
    """Every source system materially used to form the delivered product.

    THE BOUNDARY, DEFINED EXPLICITLY
    --------------------------------
        1. the source systems of the observations the assessment ran over
        2. the source systems of the derivation steps the consequence was built from

    and nothing else. A system merely NAMED somewhere in the record -- in a late-
    relationship string, in an ambiguity note, in prose -- was not consumed and does not
    need licensing. Authorization is about the data that forms the product, not about
    every party the record mentions.

    WHY THE SECOND HALF WAS MISSING
    -------------------------------
    The entitlement checked the telemetry feeds and stopped there. But the thing being
    sold is not the prediction: it is "your next-day delivery commitment to customer A is
    at risk", and that sentence is derived from an asset register, a yard-management
    system, a dock scheduler, a transport-management system and an order-management
    system. Five business systems whose data forms the delivered product, none of them
    licensed, on a record whose whole premise is that a commercial intelligence product
    carries an implied entitlement to the data underneath it.

    The reference fixture licensed telemetry only, and the honest fix is to widen the
    fixture rather than to narrow the model to whatever the fixture already covered.
    """
    return tuple(sorted(
        {o.source_system for o in evidence_source.observations}
        | set(derivation.source_systems())
    ))


def _integrity_findings(
    *,
    evidence: EvidenceSnapshot,
    evidence_source: EvidenceBundle,
    prediction_claim: PredictionClaim,
    replay_claim: bool,
) -> tuple[str, ...]:
    """Every way this record and the readings beside it fail to agree. Empty means VALID.

    WHY THIS IS A LIST AND NOT A BOOLEAN
    ------------------------------------
    The integrity dimension answers eight independent questions and used to collapse all
    of them into the word BROKEN. In memory that was survivable, because the release path
    is the only thing that reads it and it abstains either way.

    It stopped being survivable when the import boundary began recomputing this dimension
    over carried evidence. "integrity=VALID but the evidence produces BROKEN" is true of a
    substituted subject, an altered value, a rewritten source system, a fabricated bound
    input and four other things, and a refusal that cannot say which sends a reader to
    read the whole bundle. Worse for this repository's own purposes: a suite whose
    integrity tests all assert the same generic string cannot tell whether each test
    reaches the arm it claims to.

    These strings are diagnostics and are deliberately NOT on the wire. A record carrying
    its own list of what is wrong with it would be a second authority, re-derived and
    compared like every other derived value -- and there is nothing here a reader needs
    that recomputing does not give them.
    """
    from .binding import input_fingerprint_mismatch, predictor_output_mismatch

    findings: list[str] = []

    # Can the record be trusted as a record, independent of what it says?
    #
    # This checked only that the digest LOOKED like a SHA-256, which meant sixty-four "a"
    # characters passed the integrity dimension while having nothing to do with the cited
    # readings. A syntactic check on a hash is not an integrity check; it is a typo check
    # wearing one's clothes. When the observations are supplied the digest is recomputed
    # and compared, which is the only version of this that means anything.
    # NARROWED, not deleted. The malformed-string half moved to
    # `EvidenceSnapshot.__post_init__`, where the shape is knowable without the readings
    # and where it fires at both boundaries -- import used to accept a digest that was not
    # even hex. `None` is still reachable here, because a snapshot may legitimately carry
    # no digest at all (`missing_elements` counts that as missing evidence), so this arm
    # stays. Deleting it outright would have been the "unreachable guard" mistake in
    # reverse: removing a check that can still fire.
    digest = evidence.evidence_content_digest
    if digest is None:
        findings.append("evidence_content_digest is absent")
    elif digest_observations(evidence_source.observations) != digest:
        findings.append(
            "evidence_content_digest is not the digest of the readings carried with it"
        )

    # The claim itself must be the one these inputs produce. Without this the record can
    # assert "peer-benchmarked degradation percentile" over evidence from a model that
    # computes no percentile, and every other check still passes.
    #
    # Two questions, and for several revisions only the first was asked. Does the claim
    # bind to the inputs recorded beside it -- and is the claim what those inputs actually
    # PRODUCE? Binding the fingerprint, the metric and the horizon leaves score,
    # score_semantics, evidence_strength and the artifact digest free, so a caller could
    # keep genuine evidence and substitute the number being sold, or its meaning.
    #
    # BOTH calls, and the wave-1 reasoning for calling only one was wrong. It argued the
    # replay subsumes the fingerprint check. It does not: the replay recomputes a
    # fingerprint from the inputs and compares it to the CLAIM's, and never looks at the
    # copy stored in `prediction_inputs.input_fingerprint`. So a stored fingerprint could
    # disagree with both, release would deliver, and the importer -- which does run this
    # check -- would refuse the record this path had just produced. A release path that
    # emits bundles its own boundary rejects is the same asymmetry in the other direction.
    reason = input_fingerprint_mismatch(evidence, prediction_claim)
    if reason is not None:
        findings.append(f"input fingerprint: {reason}")
    # The replay, and the one arm of this dimension that is build-dependent. See
    # `_assess_evidence`'s `replay_claim`: skipped only when the record names a model
    # artifact this process does not have, never at a caller's preference.
    if replay_claim:
        reason = predictor_output_mismatch(evidence, prediction_claim)
        if reason is not None:
            findings.append(f"replay: {reason}")

    # The snapshot's observation_ids are the pointers a later reader follows. They were
    # checked only for non-emptiness, so a record could cite readings that do not exist
    # while the aggregate digest and the bound inputs both verified against a different
    # set entirely -- and this fired on the LIVE release path, not merely on import.
    cited = sorted(evidence.observation_ids)
    verified = sorted(o.observation_id for o in evidence_source.observations)
    if cited != verified:
        findings.append(
            f"the snapshot cites {cited} but the evidence carried is {verified}"
        )

    # And the snapshot must say what those readings are ABOUT, correctly. Without this the
    # subject the claim is sold under answers to nothing: a claim about `asset-9999`
    # computed from `asset-4417`'s telemetry passed every other check, because every check
    # that consumed a subject read it from the claim itself.
    observed = frozenset(o.subject for o in evidence_source.observations)
    if not evidence.subject:
        findings.append("the snapshot does not say what its readings are about")
    elif frozenset({evidence.subject}) != observed:
        findings.append(
            f"the snapshot says its readings are about {evidence.subject!r} but they are "
            f"about {sorted(observed)}"
        )

    # And it must say what those readings CAME FROM, correctly. `source_systems` is the
    # tuple handed to `permits()` to test against the licence, and it was the snapshot's
    # own claim about itself -- while `Observation.source_system` sits in the bundle and
    # inside every content digest, compared to nothing.
    #
    # The asymmetry was the whole defect: `authorized_source_systems` is fail-closed on
    # empty, so the honest producer declaring both of its feeds was refused, and the one
    # understating its feed list delivered on an unlicensed feed with the card reading
    # "rights permitted". A rights check is worth what its inputs are worth.
    declared = frozenset(evidence.source_systems)
    actual = frozenset(o.source_system for o in evidence_source.observations)
    if declared != actual:
        findings.append(
            f"the snapshot declares feeds {sorted(declared)} but its readings came from "
            f"{sorted(actual)}"
        )

    # Bound predictor inputs must come from the evidence that was just verified.
    # Checking bound_inputs against `values` only proves the record agrees with itself:
    # a producer could cite genuine observations, carry their correct aggregate digest,
    # and bind fabricated-but-internally-consistent inputs beside them.
    # Same narrowing as `EvidenceSnapshot.__post_init__`: an empty `bound_inputs` is
    # no longer constructible, so this guard's second half could not fire.
    pi = evidence.prediction_inputs
    if pi is not None:
        by_id = {o.observation_id: o for o in evidence_source.observations}
        for b in pi.bound_inputs:
            source = by_id.get(b.observation_id)
            if source is None:
                findings.append(
                    f"bound input {b.observation_id!r} is not among the readings carried"
                )
                continue
            if source.content_digest() != b.content_digest:
                findings.append(
                    f"bound input {b.observation_id!r} carries a content digest that is "
                    f"not that reading's"
                )
            if source.value != b.value_used:
                findings.append(
                    f"bound input {b.observation_id!r} replays {b.value_used!r} but that "
                    f"reading holds {source.value!r}"
                )

    # Two sources asserting different payloads under one id is an unresolved contradiction
    # in the evidence, not a footnote. The log already detects these; until wave 4 nothing
    # carried them into the decision, and until this increment nothing carried them out of
    # it either.
    findings.extend(evidence_source.conflict_descriptions())
    return tuple(findings)


def _assess_evidence(
    *,
    evidence: EvidenceSnapshot,
    entitlement_assertion: "EntitlementAssertion",
    delivering_to: str,
    for_purpose: str,
    about_subject: str,
    for_tenant: str,
    release_decision_time: datetime,
    confidence: float,
    model_applicable: bool,
    point_in_time_correct: bool,
    evidence_source: EvidenceBundle,
    prediction_claim: PredictionClaim,
    derivation: "ConsequenceDerivation",
    policy: "ReleasePolicy",
    replay_claim: bool,
) -> EvidenceAssessment:
    """Project the release inputs onto the six dimensions.

    WHY `replay_claim` IS REQUIRED AND NOT DEFAULTED
    -----------------------------------------------
    Exactly one of the eight things the integrity dimension checks needs the predictor
    implementation that produced the claim: the replay, which re-runs the recorded model
    over the recorded inputs and compares every field it determined. The other seven are
    pure functions of the record and the readings.

    That asymmetry did not matter while the observations lived only in memory. It matters
    now that the import boundary recomputes this assessment: a record from a build this
    process does not have cannot be replayed here, and running the arm anyway would
    compare two different models and blame the record for the difference.

    So the caller states whether the replay applies, and the parameter has no default,
    because an optional verification argument is one a caller forgets -- which is the
    defect this whole module was reshaped around. `formation.release` passes True
    unconditionally: the claim was produced moments earlier by this process, so a claim
    carrying another build's digest is incoherent there and must fail the replay rather
    than skip it. `IntelligenceProduct.from_record` passes `claim_is_replayable_here`,
    a pure function of the record, and reports the unreplayable case as an explicit
    UNVERIFIABLE dimension rather than as a verification.

    WHY THIS FUNCTION HAD TO EXIST
    ------------------------------
    For several revisions this repository had two release systems. `evidence.py` defined
    the six-dimension assessment and enumerated its whole state space in tests; the
    presentation told readers that all 432 states were verified and exactly one releases.
    Meanwhile `evaluate_release` ran a completely separate sequence of `if` statements,
    and nothing imported `EvidenceAssessment` outside its own tests.

    Both statements were true in isolation and the pair was misleading: the enumerated
    algebra was not the thing deciding anything. This function is the join, so the
    enumeration now describes the running product rather than a parallel demonstration.

    Each mapping below is a judgement, and each is stated rather than assumed.
    """
    # IDENTITY -- an unrecorded confidence is not a resolved identity. CONFLICTED is
    # reachable in the algebra but not derivable from a single scalar, so this projection
    # never emits it; resolving that needs multi-source identity evidence this contract
    # consumes rather than computes.
    if evidence.identity_confidence is None:
        identity = Identity.AMBIGUOUS
    elif evidence.identity_confidence < policy.identity_floor:
        identity = Identity.AMBIGUOUS
    else:
        identity = Identity.RESOLVED

    # COMPLETENESS -- straight from the snapshot, which already names its own gaps.
    missing = evidence.missing_elements()
    completeness = Completeness.MISSING if missing else Completeness.COMPLETE

    # INTEGRITY -- computed by `integrity_findings`, which names every disagreement it
    # finds. One implementation, called from here and quoted by the import boundary when
    # its recomputed answer differs from the recorded one.
    findings = _integrity_findings(
        evidence=evidence,
        evidence_source=evidence_source,
        prediction_claim=prediction_claim,
        replay_claim=replay_claim,
    )
    integrity = Integrity.BROKEN if findings else Integrity.VALID
    conflicts = evidence_source.conflict_descriptions()

    # ENTITLEMENT -- projected from the scoped assertion, which is the single source of
    # truth. The assertion knows recipient, purpose, tenant and validity window; this
    # dimension is its verdict expressed in the algebra's vocabulary, never a second
    # opinion. An unstated basis is UNKNOWN, and UNKNOWN is never permission.
    if not entitlement_assertion.basis:
        entitlement_state = EntitlementState.UNKNOWN
    elif entitlement_assertion.permits(
        # The ACTUAL scope of this delivery, not the assertion's own fields. Checking an
        # assertion against itself is always true and makes the scoping decorative -- the
        # entire point is that a clearance obtained for one recipient, one asset, one
        # tenant or one data licence must not authorise anything else. Subject comes from
        # the claim, tenant from the delivery, source systems from the evidence actually
        # relied on: each is the real value, none is echoed back from the clearance.
        recipient=delivering_to,
        purpose=for_purpose,
        subject=about_subject,
        tenant=for_tenant,
        # THE UNION, not the telemetry alone. `evidence.source_systems` covers the
        # readings the prediction was computed from; the REASON path separately consumed
        # an asset register, a yard-management system, a dock scheduler, a
        # transport-management system and an order-management system to turn that
        # prediction into the commercial claim actually being delivered. Licensing half
        # the inputs to a product and calling it authorised is the defect a scoped
        # entitlement type exists to prevent, one layer up from where it was fixed.
        source_systems=material_source_systems(
            evidence_source=evidence_source, derivation=derivation
        ),
        at=release_decision_time,
    ):
        entitlement_state = EntitlementState.AUTHORIZED
    else:
        entitlement_state = EntitlementState.UNAUTHORIZED

    # TEMPORAL ELIGIBILITY -- features not point-in-time correct means the claim was
    # computed from evidence the decision did not have.
    temporal = (
        TemporalEligibility.ELIGIBLE_AS_OF_DECISION
        if point_in_time_correct
        else TemporalEligibility.LATE
    )

    # SUPPORT -- whether the evidence backs the claim at all. A model used outside its
    # declared envelope supports nothing, whatever number it returned.
    #
    # `or confidence is None` used to sit on this condition and could not fire:
    # `confidence` is `PredictionClaim.evidence_strength`, a `float` whose own
    # `__post_init__` requires it inside [0, 1]. Both callers pass exactly that. The
    # disjunct read as defence and was unreachable, so the parameter is typed `float` and
    # the arm is gone -- a signature that cannot express the state beats a branch that
    # checks for it.
    if not model_applicable:
        support = Support.UNSUPPORTED
    elif confidence < policy.min_evidence_strength:
        support = Support.UNSUPPORTED
    else:
        support = Support.SUPPORTED

    return EvidenceAssessment(
        support=support,
        completeness=completeness,
        integrity=integrity,
        temporal_eligibility=temporal,
        identity=identity,
        entitlement=entitlement_state,
        missing_evidence=missing,
        # Named, not merely counted. "integrity=BROKEN" sends an engineer to look at a
        # hash; "obs a-0: source-a and source-b disagree about the payload" sends them to
        # the two systems that actually need reconciling.
        conflicts=conflicts,
    )



# ===========================================================================
# THE TWO SUPPORTED WAYS TO ASSESS EVIDENCE. NEITHER TAKES A REPLAY ARGUMENT.
#
# `_assess_evidence` and `_integrity_findings` above are correct and they were
# PUBLIC, with `replay_claim: bool` on the signature. The two real boundaries
# already chose it honestly -- release passed a literal True, import derived it
# from the record -- but this package declares no surface, so every module-level
# name is importable, and the project had already accepted that reasoning once,
# when six deleted names had to be restored on exactly that argument. Using the
# opposite standard here would have been an argument rather than a rule.
#
# So the replay decision is made BY CONSTRUCTION, in two functions named for the
# boundary they serve. There is no supported call through which a caller can ask
# for the claim not to be replayed, and the underscore says which functions are
# the implementation rather than the contract.
#
# Two wrappers, not a verification-policy object. A policy API would put the seam
# back with more ceremony around it.
# ===========================================================================


def _refuse_replay_argument(kwargs: dict[str, Any], entry: str) -> None:
    """A caller may not smuggle the replay decision through a wrapper's `**kwargs`.

    Without this the seam survives the rename: `assess_release_evidence(...,
    replay_claim=False)` reaches `_assess_evidence` with two values for the argument and
    fails -- but it fails as a `TypeError` from a function the caller did not name, which
    is an accident rather than a rule. The rule is that these entry points decide replay
    by construction, so state it where it is decided.
    """
    if "replay_claim" in kwargs:
        raise TypeError(
            f"{entry} does not accept replay_claim; whether the claim is replayed is "
            f"derived from the boundary and the record, never chosen by a caller"
        )


def assess_release_evidence(**kwargs: Any) -> EvidenceAssessment:
    """Assess evidence at live release, where the replay is not optional.

    The claim was produced moments ago by this process, so a claim carrying another
    build's artifact digest is incoherent here -- it must FAIL the replay, never skip it.
    """
    _refuse_replay_argument(kwargs, "assess_release_evidence")
    return _assess_evidence(**kwargs, replay_claim=True)


def assess_imported_evidence(**kwargs: Any) -> EvidenceAssessment:
    """Assess evidence carried in from the wire, replaying only what this build can.

    Replayability is derived from the record and the running implementation --
    `claim_is_replayable_here` compares the claim's model artifact digest against this
    build's -- and never from a caller's preference. The unreplayable case is not a pass:
    `IntelligenceProduct.from_record` reports it as an explicitly UNVERIFIABLE dimension.
    """
    from .binding import claim_is_replayable_here

    _refuse_replay_argument(kwargs, "assess_imported_evidence")
    return _assess_evidence(
        **kwargs, replay_claim=claim_is_replayable_here(kwargs["prediction_claim"])
    )


def imported_integrity_findings(**kwargs: Any) -> tuple[str, ...]:
    """The named reasons behind an imported record's integrity dimension.

    Diagnostics for a refusal that has already been decided, so it must reach its answer
    the same way -- same function, same replay decision -- or the refusal would quote
    reasons that did not decide it.
    """
    from .binding import claim_is_replayable_here

    _refuse_replay_argument(kwargs, "imported_integrity_findings")
    return _integrity_findings(
        **kwargs, replay_claim=claim_is_replayable_here(kwargs["prediction_claim"])
    )
