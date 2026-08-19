"""The aggregate root before assurance, and the assertions assurance consumes.

WHY A CANDIDATE EXISTS AT ALL
-----------------------------
Release used to receive a claim, a horizon, a confidence, a context and an action as
independent arguments, which meant nothing structurally required them to describe the same
decision. `IntelligenceCandidate` is the thing formed by CONNECT/PREDICT/REASON, and it is
either coherent or it does not exist.

Two questions, in order:

    PRODUCT FORMATION   can we form a meaningful intelligence product?
    PRODUCT ASSURANCE   may we responsibly deliver it?

Formation failing means there is nothing here to assess. That is categorically different
from a candidate whose evidence is incomplete, which is why context never became a seventh
assurance dimension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .action import ActionRecommendation
from .consequence import BusinessConsequence
from .contract import PredictionClaim
from .decision import DecisionContext
from .evidence import EvidenceAssessment


@dataclass(frozen=True)
class IdentityAssertion:
    """Who resolved this entity, how sure they were, and on what evidence.

    `identity_confidence` used to arrive as a bare float, which is another way of saying
    "the caller says 0.97". A number with no resolver behind it cannot be challenged.
    """

    resolved_entity: str
    resolver: str
    resolver_version: str
    confidence: float
    evidence_refs: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"identity confidence {self.confidence} outside [0, 1]")
        if not self.resolver:
            raise ValueError("an identity assertion with no resolver cannot be audited")
        # The six-decimal fix in `PredictionInputs` closed one call site of a class, not
        # the class. This number is written at six decimals and RENDERED on the delivered
        # card at two, so 0.8749999999 produced an honest DELIVERED product whose card
        # read 0.87, crossed the wire as "0.875000", and re-rendered as 0.88 -- refused by
        # this package's own importer, on the hero path, with an ordinary-looking value.
        if float(f"{self.confidence:.6f}") != self.confidence:
            raise ValueError(
                f"identity confidence {self.confidence!r} carries more precision than the "
                f"six-decimal wire form preserves, so this record would not survive its "
                f"own round trip; quantize it before it enters the assertion"
            )


@dataclass(frozen=True)
class ApplicabilityAssertion:
    """Whether THIS use satisfies the model's declared envelope.

    Distinct from the envelope itself, which belongs to the claim. The claim says what the
    predictor produced and what it declares itself valid for; this says whether the
    situation it was used in falls inside that. Model metadata versus assurance assertion --
    keeping them separate is what stops two authorities disagreeing about one question.

    For several revisions there was no envelope to satisfy: `subject_type` was compared
    against nothing, so this recorded a caller's preference and read as a verification.
    `binding.verify_bindings` now checks it against the envelope the claim carries.
    """

    model_version: str
    subject_type: str
    valid: bool
    basis: str

    def __post_init__(self) -> None:
        if not self.basis:
            raise ValueError("an applicability verdict with no basis is an opinion")
        if not self.subject_type:
            raise ValueError(
                "an applicability verdict naming no subject type asserts nothing about "
                "what the model was used on"
            )


@dataclass(frozen=True)
class TemporalAssertion:
    """Whether the features were point-in-time correct for this decision."""

    model_decision_time: datetime
    knowledge_cutoff: datetime
    feature_cutoff: datetime
    valid: bool
    basis: str = ""

    def __post_init__(self) -> None:
        for label, moment in (
            ("model_decision_time", self.model_decision_time),
            ("knowledge_cutoff", self.knowledge_cutoff),
            ("feature_cutoff", self.feature_cutoff),
        ):
            if moment.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware")
        if self.feature_cutoff > self.knowledge_cutoff and self.valid:
            raise ValueError(
                "features drawn past the knowledge cutoff cannot be point-in-time correct"
            )
        # A bare `valid=True` says point-in-time correctness was established and gives a
        # reader nothing to challenge -- the same defect `ApplicabilityAssertion.basis`
        # exists to prevent, left open on the assertion where it matters most.
        if not self.basis:
            raise ValueError(
                "a temporal verdict with no basis is a naked valid flag; say on what "
                "authority the features were judged point-in-time correct"
            )


@dataclass(frozen=True)
class EntitlementAssertion:
    """A rights determination scoped to the thing it authorises.

    Two booleans could not carry this. A commercial authorization depends on who, what
    data, what purpose, which recipient, which tenant, which time and which product -- and
    a generic `may_deliver=True` was reusable against a recipient nobody had cleared.

    This records a determination made by counsel or a policy engine. It does not make one.
    """

    recipient: str
    purpose: str
    subject: str
    tenant: str
    basis: str
    policy_id: str
    valid_from: datetime
    policy_version: str = ""
    """Which version of the naming policy made this determination.

    `policy_id` alone names the rule; it does not say which revision of it. Clearances are
    reissued when a contract is amended, and a reconstruction comparing a two-year-old
    determination against today's policy reaches a confident wrong answer about whether it
    should have been given -- the same reason `AssuranceDecision` carries a policy digest
    beside its version.
    """

    valid_to: datetime | None = None
    authorized_source_systems: tuple[str, ...] = ()
    """The feeds this clearance actually covers.

    `may_use_source_data` was a bare boolean -- permission to use *some* data, which is
    not a licence anyone signs. Empty means nothing is authorized, not everything: an
    unstated source scope is the case where nobody checked, and that must not release.
    """
    may_use_source_data: bool = False
    may_deliver_to_recipient: bool = False

    def __post_init__(self) -> None:
        if not self.basis or not self.policy_id:
            raise ValueError("an entitlement with no basis or policy id is unauditable")
        # `permits()` compares purpose and tenant with `!=`, so a blank on both sides
        # satisfied two of the six scope dimensions by comparing "" to "".
        #
        # RECIPIENT JOINED THEM, AND THE REASON IT WAS MISSING IS THE INTERESTING PART.
        # It was described as "required" on the strength of being a positional field with
        # no default -- which makes it required to PASS, not required to be anything. A
        # blank string satisfied it. So a clearance naming nobody could exist in memory,
        # be evaluated as unauthorized against a real recipient, and legitimately produce
        # an abstention -- while `schema/envelope-1.json` demanded a non-empty
        # `entitlement.recipient`. The supported producer could emit an honest record its
        # own portable form rejected, which is the governing asymmetry of this repository
        # pointing the other way.
        #
        # Closed on the producer side rather than by relaxing the schema, because a
        # clearance naming no recipient authorises no delivery and is not a useful typed
        # assertion. "No clearance exists" is representable already: an assertion with
        # `may_deliver_to_recipient=False`, or none of the six scope dimensions matching,
        # both abstain with a reason. An assertion with an empty identity is a different
        # thing -- a rights determination about nobody -- and it says nothing an auditor
        # could check.
        for label, value in (
            ("recipient", self.recipient),
            ("purpose", self.purpose),
            ("tenant", self.tenant),
        ):
            if not value:
                raise ValueError(
                    f"an entitlement with a blank {label} authorises nothing it can be "
                    f"checked against; the comparison succeeds by matching emptiness"
                )
        if not self.policy_version:
            raise ValueError(
                "an entitlement naming a policy but not its version cannot be compared "
                "against the rules that were actually in force"
            )
        for label, moment in (
            ("valid_from", self.valid_from), ("valid_to", self.valid_to)
        ):
            if moment is not None and moment.tzinfo is None:
                raise ValueError(f"entitlement {label} must be timezone-aware")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError(
                f"entitlement validity ends {self.valid_to.isoformat()} at or before it "
                f"begins {self.valid_from.isoformat()}; a clearance covering no time "
                f"authorises nothing and would read as an ordinary window"
            )

    def permits(
        self,
        *,
        recipient: str,
        purpose: str,
        subject: str,
        tenant: str,
        source_systems: tuple[str, ...],
        at: datetime,
    ) -> bool:
        """Scoped check against the ACTUAL delivery, never against the assertion itself.

        Every argument is required and keyword-only. `subject` and `tenant` sat on this
        class for several revisions without participating, so a clearance for the right
        recipient released a claim about the wrong asset, or the wrong customer's asset --
        the precise failure class this type was introduced to remove. An optional scope
        argument is one a caller omits, and an omitted comparison silently passes.
        """
        if recipient != self.recipient or purpose != self.purpose:
            return False
        if subject != self.subject or tenant != self.tenant:
            return False
        # Fail closed on the source licence: every feed the claim rests on must be named
        # by the clearance. A superset is a breach even when the extra feed is harmless.
        if not source_systems or not set(source_systems).issubset(
            self.authorized_source_systems
        ):
            return False
        if at < self.valid_from:
            return False
        if self.valid_to is not None and at >= self.valid_to:
            return False
        return self.may_use_source_data and self.may_deliver_to_recipient


@dataclass(frozen=True)
class AssuranceContext:
    """The four assertions assurance consults, gathered rather than passed loose.

    WHY THE EVIDENCE ASSESSMENT IS NOT HERE
    ---------------------------------------
    It was, and it was a design smell with a fixture to prove it: the release path
    discarded whatever the caller supplied and recomputed the assessment from the
    observations, yet every caller still had to hand one over -- and every fixture handed
    over `fully_satisfied()`, a verdict nobody had reached about evidence nobody had read.

    A field a caller must fill and the system then ignores teaches the caller that filling
    it means something. These four are inputs: determinations made by a resolver, by
    counsel, by a policy engine, gathered for the decision. The assessment is an OUTPUT,
    and it lives on `AssessedAssurance` beside the decision that consumed it.
    """

    identity_assertion: IdentityAssertion
    applicability_assertion: ApplicabilityAssertion
    temporal_assertion: TemporalAssertion
    entitlement_assertion: EntitlementAssertion

    def as_record(self) -> dict[str, Any]:
        return {
            "identity": {
                "resolved_entity": self.identity_assertion.resolved_entity,
                "resolver": self.identity_assertion.resolver,
                "resolver_version": self.identity_assertion.resolver_version,
                "confidence": f"{self.identity_assertion.confidence:.6f}",
                # What the resolution rests on. A confidence with no evidence behind it is
                # a number a reader cannot challenge, which is the reason this type
                # replaced a bare float in the first place -- and it was then dropped on
                # export, which put the bare float back on the wire.
                "evidence_refs": list(self.identity_assertion.evidence_refs),
                "conflicts": list(self.identity_assertion.conflicts),
            },
            "applicability": {
                "model_version": self.applicability_assertion.model_version,
                # The thing applicability is asserted ABOUT. Exported now because
                # `verify_bindings` checks it against the claim's declared envelope, and a
                # binding whose subject does not survive export cannot be re-checked.
                "subject_type": self.applicability_assertion.subject_type,
                "valid": self.applicability_assertion.valid,
                "basis": self.applicability_assertion.basis,
            },
            "temporal": {
                "model_decision_time": self.temporal_assertion.model_decision_time.isoformat(),
                "knowledge_cutoff": self.temporal_assertion.knowledge_cutoff.isoformat(),
                "feature_cutoff": self.temporal_assertion.feature_cutoff.isoformat(),
                "valid": self.temporal_assertion.valid,
                "basis": self.temporal_assertion.basis,
            },
            # The full scope, not a summary of it. This record carried recipient, purpose,
            # tenant, policy and basis while dropping subject, the validity window, the
            # licensed source systems and both permission booleans -- so an importer could
            # not re-run the authorization the bundle claims to preserve, and the scope
            # that decides delivery in memory simply vanished on export.
            "entitlement": {
                "recipient": self.entitlement_assertion.recipient,
                "purpose": self.entitlement_assertion.purpose,
                "subject": self.entitlement_assertion.subject,
                "tenant": self.entitlement_assertion.tenant,
                "policy_id": self.entitlement_assertion.policy_id,
                "policy_version": self.entitlement_assertion.policy_version,
                "basis": self.entitlement_assertion.basis,
                "valid_from": self.entitlement_assertion.valid_from.isoformat(),
                "valid_to": (
                    self.entitlement_assertion.valid_to.isoformat()
                    if self.entitlement_assertion.valid_to else None
                ),
                "authorized_source_systems": list(
                    self.entitlement_assertion.authorized_source_systems
                ),
                "may_use_source_data": self.entitlement_assertion.may_use_source_data,
                "may_deliver_to_recipient": (
                    self.entitlement_assertion.may_deliver_to_recipient
                ),
            },
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "AssuranceContext":
        """Rebuild the four assertions, running each type's own invariants.

        The importer used to keep this as a dict, so the assurance basis crossed the wire
        as data nobody validated: an entitlement window that ended before it began, a
        temporal verdict with no basis, a naive timestamp. Every one of those is refused in
        memory, and after this every one is refused on the way in, by the same code.
        """
        identity, applicability = r["identity"], r["applicability"]
        temporal, entitlement = r["temporal"], r["entitlement"]
        return cls(
            identity_assertion=IdentityAssertion(
                resolved_entity=identity["resolved_entity"],
                resolver=identity["resolver"],
                resolver_version=identity["resolver_version"],
                confidence=float(identity["confidence"]),
                evidence_refs=tuple(identity.get("evidence_refs") or ()),
                conflicts=tuple(identity.get("conflicts") or ()),
            ),
            applicability_assertion=ApplicabilityAssertion(
                model_version=applicability["model_version"],
                subject_type=applicability["subject_type"],
                valid=bool(applicability["valid"]),
                basis=applicability["basis"],
            ),
            temporal_assertion=TemporalAssertion(
                model_decision_time=datetime.fromisoformat(temporal["model_decision_time"]),
                knowledge_cutoff=datetime.fromisoformat(temporal["knowledge_cutoff"]),
                feature_cutoff=datetime.fromisoformat(temporal["feature_cutoff"]),
                valid=bool(temporal["valid"]),
                basis=temporal["basis"],
            ),
            entitlement_assertion=EntitlementAssertion(
                recipient=entitlement["recipient"],
                purpose=entitlement["purpose"],
                subject=entitlement["subject"],
                tenant=entitlement["tenant"],
                basis=entitlement["basis"],
                policy_id=entitlement["policy_id"],
                policy_version=entitlement["policy_version"],
                valid_from=datetime.fromisoformat(entitlement["valid_from"]),
                valid_to=(
                    datetime.fromisoformat(entitlement["valid_to"])
                    if entitlement.get("valid_to") else None
                ),
                authorized_source_systems=tuple(
                    entitlement.get("authorized_source_systems") or ()
                ),
                may_use_source_data=bool(entitlement["may_use_source_data"]),
                may_deliver_to_recipient=bool(entitlement["may_deliver_to_recipient"]),
            ),
        )


@dataclass(frozen=True)
class AssessedAssurance:
    """The four assertions AND the assessment computed from them. What decided.

    Separate from `AssuranceContext` because the two have different authors. The context
    is gathered; the assessment is computed by the release path from observations the
    caller cannot substitute. Holding them in one object after the fact is what lets a
    decision record carry its own basis, and lets an importer rebuild both and check that
    the verdict follows from them.
    """

    context: AssuranceContext
    evidence_assessment: EvidenceAssessment

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_assessment, EvidenceAssessment):
            raise TypeError(
                f"evidence_assessment must be an EvidenceAssessment, not "
                f"{type(self.evidence_assessment).__name__}; an assessment a caller "
                f"asserts is an assessment nobody performed"
            )
        if not isinstance(self.context, AssuranceContext):
            raise TypeError(
                f"context must be an AssuranceContext, not {type(self.context).__name__}"
            )

    def as_record(self) -> dict[str, Any]:
        return {**self.context.as_record(), "evidence": self.evidence_assessment.as_record()}

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "AssessedAssurance":
        return cls(
            context=AssuranceContext.from_record(r),
            evidence_assessment=EvidenceAssessment.from_record(r["evidence"]),
        )


@dataclass(frozen=True)
class IntelligenceCandidate:
    """One coherent decision, before anyone asks whether it may be delivered.

    Holding these together is the whole point. A candidate whose action is due after its
    consequence has landed, or whose prediction window does not overlap the exposure it
    claims to threaten, is incoherent -- and it is far better to discover that here than
    in a record somebody is reading eighteen months later.
    """

    candidate_id: str
    context: DecisionContext
    prediction_claim: PredictionClaim
    business_consequence: BusinessConsequence
    action: ActionRecommendation

    def __post_init__(self) -> None:
        # An annotation is documentation; a dataclass will seat a string here happily. The
        # structural guarantee §6 asks for -- that no API can accept arbitrary prediction
        # prose -- has to be a runtime refusal, or it is only a comment.
        if not isinstance(self.prediction_claim, PredictionClaim):
            raise TypeError(
                f"prediction_claim must be a PredictionClaim, not "
                f"{type(self.prediction_claim).__name__}; prose seated here is the "
                f"author-supplied claim this model exists to make impossible"
            )
        if not self.candidate_id:
            raise ValueError("a candidate with no id cannot be traced to its product")
        if not self.business_consequence.is_actionable():
            raise ValueError(
                f"{self.business_consequence.consequence_type} is not actionable; "
                f"there is no intelligence product to form"
            )
        if not self.context.prediction_window.overlaps(
            self.business_consequence.exposure_window
        ):
            raise ValueError(
                "the prediction window does not overlap the exposure it claims to "
                "threaten; the consequence belongs to a different decision"
            )
        # The horizon is DERIVED from the context in every fixture and was free to differ
        # in the type. A test showing the happy fixture agrees is a demonstration; it does
        # not prohibit disagreement. `DecisionContext` is the single temporal authority,
        # so a claim carrying its own horizon must be carrying the context's.
        derived_horizon = int(self.context.prediction_window.duration.total_seconds())
        if self.prediction_claim.horizon_seconds != derived_horizon:
            raise ValueError(
                f"the claim's horizon is {self.prediction_claim.horizon_seconds}s but the "
                f"decision's prediction window is {derived_horizon}s; two horizons that "
                f"can disagree are two temporal authorities, and the context is the only "
                f"one"
            )
        # The REASON stage answers to the same clock as the rest. A walk performed at a
        # later cutoff knows relationships the decision-maker did not, and a walk over a
        # different window describes a different exposure -- both produce a consequence
        # that looks derived and belongs to another decision.
        path = self.business_consequence.derivation
        if path.knowledge_cutoff != self.context.knowledge_cutoff:
            raise ValueError(
                f"the consequence was derived at cutoff "
                f"{path.knowledge_cutoff.isoformat()} but this decision's cutoff is "
                f"{self.context.knowledge_cutoff.isoformat()}; the walk knew a different "
                f"amount than the decision did"
            )
        if path.evaluated_window != self.context.prediction_window:
            raise ValueError(
                "the consequence was derived over a different window than the claim "
                "predicts; the context is the single temporal authority for REASON too"
            )
        # AN INSTRUCTION CANNOT BE DUE BEFORE THE DECISION THAT PRODUCED IT.
        #
        # A formation question rather than a release one: this candidate is incoherent
        # before anybody grades its evidence or checks anyone's rights. The model decided
        # at 07:00 and the thing it wants done was due at 06:00, so there is no history in
        # which this recommendation could have been carried out -- not a late delivery, an
        # impossible one.
        #
        # `ActionRecommendation` already refuses a deadline after its own operational
        # window closes, which bounds the action from above. Nothing bounded it from
        # below, and the lower bound is the one the decision's own clock supplies.
        #
        # Equality is permitted, and the consequence is stated rather than left implicit:
        # a candidate whose action is due at the exact moment the model decided can form
        # and can be honestly withheld, but can never be DELIVERED, because delivery is
        # strictly before the deadline and at or after the release decision, which is at
        # or after the model's. That is a coherent pair. Refusing it here instead would
        # mean formation rejecting a candidate for a reason that belongs to delivery.
        if self.action.due_by < self.context.model_decision_time:
            raise ValueError(
                f"the action is due {self.action.due_by.isoformat()} but the claim "
                f"recommending it was decided {self.context.model_decision_time.isoformat()}; "
                f"the instruction was already overdue when the model issued it, and no "
                f"delivery could have made it actionable"
            )
        # The action's window and the consequence's window were each checked against
        # something else and never against each other. An action scheduled around a window
        # that does not touch the exposure it claims to protect belongs to a different
        # operational event, whatever it is attached to.
        if not self.action.operational_window.overlaps(
            self.business_consequence.exposure_window
        ):
            raise ValueError(
                f"the action's operational window "
                f"[{self.action.operational_window.start.isoformat()}, "
                f"{self.action.operational_window.end.isoformat()}) does not overlap the "
                f"exposure it claims to protect; this action is for a different "
                f"operational event"
            )
        # The action's TARGET was read in exactly two places in this package: to render
        # the sentence an operator reads, and to write it to the wire. `rendered_text` is
        # re-derived and compared on import, so that check confirmed the record faithfully
        # reproduced the wrong instruction. A delivered card read `replace
        # asset-8899/hydraulic-pump` over evidence about asset-4417's battery pack.
        #
        # Wave 3 bound the claim's subject to the readings. This is the field an operator
        # physically acts on, and the same pass left it free.
        #
        # The target need not be the claim's subject -- the hero targets `battery-pack-1`,
        # the component the walk's HAS_COMPONENT step reached -- so what is required is
        # that the record names it SOMEWHERE.
        named = path.entities() | {self.prediction_claim.subject}
        if self.action.target not in named:
            raise ValueError(
                f"the action targets {self.action.target!r}, which is neither the claim's "
                f"subject nor anything the walk reached ({sorted(path.entities())}); the "
                f"instruction is about a different thing than the record is"
            )

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "IntelligenceCandidate":
        """Rebuild the aggregate root, which re-runs every coherence check it owns.

        Consequence-overlaps-the-window and the typed-claim refusal both fire here on the
        way in, so a schema-shaped payload describing an incoherent candidate is refused
        by the same code that refuses one built in process.
        """
        from .contract import PredictionClaim

        return cls(
            candidate_id=r["candidate_id"],
            context=DecisionContext.from_record(r["context"]),
            prediction_claim=PredictionClaim.from_record(r["prediction_claim"]),
            business_consequence=BusinessConsequence.from_record(
                r["business_consequence"]
            ),
            action=ActionRecommendation.from_record(r["action"]),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "context": self.context.as_record(),
            "prediction_claim": self.prediction_claim.as_record(),
            "business_consequence": self.business_consequence.as_record(),
            "action": self.action.as_record(),
        }
