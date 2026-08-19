"""The delivered intelligence product, and the lineage that makes it perishable.

ONE REPRESENTATION
------------------
The old `IntelligenceProduct` carried `claim`, `prediction_horizon`, `recommended_action`
and `confidence` as independent scalars beside the typed objects that also described them.
Two authorities for one fact is the drift surface every recurring defect came out of, so
this shape has exactly one:

    IntelligenceProduct = candidate + assurance decision + delivery metadata

Everything a reader used to get from a scalar is reachable through the candidate, and the
literal text the customer saw is preserved by `RenderedDelivery` -- a derived artifact from
a versioned renderer, never a place anybody authors prose.

PERISHABILITY WITHOUT MUTATION
------------------------------
Connected-asset intelligence goes stale fast. The 07:00 claim can be void by 11:00 because
the asset moved, the pack was replaced, or the shipment changed.

`claim_series_id`, `supersedes_product_id` and `valid_until` are set once, at construction.
Retraction is NOT a field mutated onto this record later -- that would rewrite history, and
the entire argument for decision-time evidence depends on the record standing still. A
retraction is a subsequent event in the envelope, and the current status of a claim is
DERIVED from lineage plus events plus time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .bitemporal import EvidenceBundle
from .candidate import IntelligenceCandidate
from .contract import EvidenceSnapshot
from .delivery import RENDERER_VERSION, AssuranceDecision, RenderedDelivery, trust_line
from .verification import (
    DimensionVerification,
    VerificationDimension,
    unverifiable,
    verified,
)


class UnverifiableBasis(ValueError):
    """Strict import refusing a record it cannot fully check.

    A `ValueError` because every other refusal at this boundary is one, and a caller
    wrapping the import in `except ValueError` must not let this through while catching
    everything else. Named so the historical path can be recommended by exception type
    rather than by reading a message.
    """


class Determination(str, Enum):
    DELIVERED = "DELIVERED"
    ABSTAINED = "ABSTAINED"


class ProductStatus(str, Enum):
    """Derived, never stored. See `status_at`."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"
    WITHHELD = "WITHHELD"
    """The candidate was never delivered.

    The other four answers are all about a claim somebody received: it is still good, it
    has gone off, something replaced it, it was withdrawn. An abstention is none of
    those, and until this member existed it reported ACTIVE -- because `status_at`
    checked only whether `valid_until` had passed, and an abstention has no `valid_until`
    to pass.

    So the one determination that was deliberately withheld answered the question "is
    this still actionable?" with the value that means "yes, act on it". A caller asking
    for the status of every record in a series got a withheld candidate back looking like
    a live recommendation.

    Added as a member rather than raising on the question, because a reader iterating a
    claim series legitimately wants the status of every record in it, and an exception
    for the ordinary case would push every such caller into a try/except that
    reintroduces the same mistake at a different level.
    """


@dataclass(frozen=True)
class IntelligenceProduct:
    """A delivered -- or deliberately withheld -- piece of intelligence."""

    product_id: str
    candidate: IntelligenceCandidate
    assurance: AssuranceDecision
    evidence: EvidenceSnapshot
    release_evidence: EvidenceBundle
    """The readings the assessment actually ran over, and the contradictions found in them.

    `evidence` is a CITATION -- ids, an aggregate digest, a list of source systems, the
    bound predictor inputs. Everything a reader could do with it was check that the record
    agreed with itself: the digest could not be re-derived without the readings, the bound
    inputs could not be confirmed to be the readings they named, and a contradiction the
    producer chose not to mention left no trace at all.

    So the portable representation was strictly weaker than the in-memory one, on an
    artifact whose entire proposition is that the decision survives the platform that
    produced it. This field is the evidence itself, carried out with the product, so an
    importer can re-run `assess_evidence` -- the same function release runs -- and refuse a
    record whose recorded verdict its own evidence does not produce.
    """

    determination: Determination
    recipient: str
    claim_series_id: str
    purpose: str = ""
    """What this delivery was FOR, as opposed to what the clearance covers.

    The entitlement assertion carries a purpose too, and for several revisions that was
    the only copy -- so the record described a clearance and never the delivery it
    authorised. `permits()` checked the actual purpose against the assertion at release
    time and the actual purpose then vanished, which meant an importer re-running the
    authorization could only compare the assertion against itself. That check is always
    true, and it made the export's claim to preserve the authorization false.
    """

    tenant: str = ""
    """The tenant this was delivered under. Here for the same reason as `purpose`, and it
    is the dimension that leaks across customers when nobody can re-check it."""

    delivery_time: datetime | None = None
    valid_until: datetime | None = None
    supersedes_product_id: str | None = None
    rendered_delivery: RenderedDelivery | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.release_evidence, EvidenceBundle):
            raise TypeError(
                f"release_evidence must be an EvidenceBundle, not "
                f"{type(self.release_evidence).__name__}; a product that cannot show the "
                f"readings its assessment ran over records a verdict nobody can re-derive"
            )
        if not self.product_id:
            raise ValueError("a product with no id cannot be superseded or retracted")
        # RECIPIENT, PURPOSE AND TENANT, for delivered and abstained alike.
        #
        # These three are the scope the entitlement is re-checked against, and
        # `EntitlementAssertion.permits` compares purpose and tenant with `!=` -- so a
        # blank on both sides satisfied two of the six scope dimensions by matching
        # emptiness. `EntitlementAssertion` closed its own half of that; the delivery's
        # copy was the half left open, and it was open on abstentions too, where the
        # recipient check was gated behind DELIVERED.
        #
        # Unconditional here rather than DELIVERED-only. That is what makes the
        # DELIVERED-only recipient guard removable rather than merely untested: a stronger
        # invariant one scope up makes it unreachable.
        for label, value in (
            ("recipient", self.recipient),
            ("purpose", self.purpose),
            ("tenant", self.tenant),
        ):
            if not value:
                raise ValueError(
                    f"a product with a blank {label} records a delivery whose scope "
                    f"cannot be checked against the clearance that authorised it; the "
                    f"comparison would succeed by matching emptiness"
                )
        if not self.claim_series_id:
            raise ValueError(
                "a product with no series id cannot be recognised as a later view of "
                "the same underlying claim"
            )
        # A product supersedes something OTHER than itself. The identical cycle expressed
        # as a status event was already refused -- "a reader walking the lineage arrives
        # back where they started" -- and expressed as lineage it was accepted, because
        # the test guarding it only ever exercised the status-event arm.
        if self.supersedes_product_id == self.product_id:
            raise ValueError(
                f"{self.product_id} supersedes itself; a reader walking the lineage "
                f"arrives back where they started"
            )
        # THE MODEL DECIDES, THEN THE GATE DECIDES. FOR EVERY DETERMINATION.
        #
        # This sat inside the DELIVERED branch below, which is the one branch where the
        # ordering is implied anyway: a delivered product pins `release_decision_time`
        # equal to `delivery_time`, so the comparison there is doing half the work it
        # looks like it is doing. An ABSTAINED product pins neither -- and so the case
        # where the rule is the only thing holding the two clocks together was the case
        # that skipped it. A withheld record could claim its release gate refused a claim
        # an hour before the model issued it.
        #
        # The ordering is a property of the DECISION, not of a successful delivery. A
        # candidate is scored and then gated whether or not anything is sent.
        if self.candidate.context.model_decision_time > \
                self.assurance.release_decision_time:
            raise ValueError(
                f"the claim was issued "
                f"{self.candidate.context.model_decision_time.isoformat()} but "
                f"release was decided "
                f"{self.assurance.release_decision_time.isoformat()}; a gate cannot "
                f"have ruled on a claim that had not been made"
            )
        if self.determination is Determination.DELIVERED:
            if self.delivery_time is None:
                raise ValueError("a delivered claim must record when it was delivered")
            # Perishability answers to something. Wave 3 closed "stamped valid until
            # 2099" and left the ABSENT case open, so a 72-hour claim read ACTIVE in 2099
            # and release emitted it by default -- absence upgraded into permission, on
            # the one question perishability exists to answer.
            if self.valid_until is None:
                raise ValueError(
                    "a delivered claim with no validity horizon never expires; "
                    "perishability cannot be expressed by leaving it out"
                )
            if self.rendered_delivery is None:
                raise ValueError(
                    "a delivered claim must preserve what the recipient actually saw"
                )
            # `if not self.recipient` sat here and is gone rather than kept as
            # belt-and-braces. Every product now refuses a blank recipient, above, so this
            # arm could not fire -- and a DELIVERED-only version of a rule that should
            # always hold is how an abstention came to be recordable with no recipient at
            # all, on the field the entitlement scope is checked against.
            if not self.assurance.permitted:
                raise ValueError(
                    "DELIVERED contradicts an assurance decision that refused release"
                )
            # THREE MOMENTS, TWO QUESTIONS, ONE ORDER.
            #
            # The release decision and the delivery happen together. Release always stamps
            # them equal; import accepted any value at all, so a record could be decided
            # in 2099 and delivered in 2026 and read as coherent -- and
            # `release_decision_time` is what the policy re-evaluation is replayed
            # against, so a free value there is a free hand over which rules were in
            # force.
            if self.assurance.release_decision_time != self.delivery_time:
                raise ValueError(
                    f"the release decision was taken "
                    f"{self.assurance.release_decision_time.isoformat()} but the product "
                    f"was delivered {self.delivery_time.isoformat()}; a delivery cannot "
                    f"be authorised by a decision taken at another time"
                )
            # The model-before-gate ordering is enforced one scope up, unconditionally,
            # and is deliberately NOT restated here. ORDERING RATHER THAN EQUALITY is the
            # ruling that made hoisting necessary: the two clocks answer different
            # questions -- `model_decision_time` is what the evidence cutoff and
            # point-in-time correctness are judged against, `release_decision_time` is
            # what the entitlement window and the policy thresholds are judged against --
            # so binding them equal would read the reference scenario's single-process
            # timing as a domain rule and refuse any deployment whose gate runs 200ms
            # after its model.
            #
            # Permitting the gap is what created the rule below.
            #
            # A DELAYED GATE MUST NOT DELIVER AN ALREADY-STALE INSTRUCTION.
            #
            # Once the gate may lag the model, this becomes reachable: the model decides
            # at 07:00, the action is due at 08:00, the gate clears it at 09:00, and the
            # operator is handed a card telling them to do something an hour ago. Every
            # field is individually valid. The card is impossible on arrival.
            #
            # STRICTLY BEFORE, and the exclusivity is the same convention as everywhere
            # else here: `TimeInterval.contains` is half-open, `valid_until` expires AT
            # its moment, an observation window closes half-open. A card handed over at
            # the instant the work was due leaves no interval in which the work could be
            # done.
            due_by = self.candidate.action.due_by
            if self.delivery_time >= due_by:
                raise ValueError(
                    f"the product was delivered {self.delivery_time.isoformat()} but the "
                    f"action it asks for was due {due_by.isoformat()}; the recipient is "
                    f"being instructed to have already done something, and a "
                    f"recommendation that cannot be acted on is not a delivery"
                )
            # `captured is not None` used to guard this and could not be false:
            # `EvidenceSnapshot.__post_init__` refuses a snapshot with no capture time.
            captured = self.evidence.captured_at
            if captured > self.delivery_time:
                raise ValueError(
                    f"evidence captured {captured.isoformat()} postdates delivery at "
                    f"{self.delivery_time.isoformat()}; a claim cannot rest on evidence "
                    f"that did not yet exist when it was made"
                )
            if self.valid_until is not None and self.valid_until <= self.delivery_time:
                raise ValueError(
                    "a claim that expires at or before delivery was never actionable"
                )
            # And it cannot outlive the window it describes. The only check used to be
            # "after delivery", so `valid_until` answered to nothing at the far end: a
            # product about the next 72 hours could be stamped valid until 2099 and read
            # ACTIVE forever, on the very question -- is this still actionable? -- that
            # perishability exists to answer.
            window_end = self.candidate.context.prediction_window.end
            if self.valid_until is not None and self.valid_until > window_end:
                raise ValueError(
                    f"the claim is stamped valid until "
                    f"{self.valid_until.isoformat()} but predicts only to "
                    f"{window_end.isoformat()}; intelligence cannot outlive the window it "
                    f"describes"
                )
            # NOR OUTLIVE THE DEADLINE OF THE ACTION IT IS ASKING FOR.
            #
            # A SECOND bound rather than a replacement for the one above, because the two
            # answer different questions and either can be the binding one. The window is
            # how far the claim reaches; the deadline is how long the instruction can
            # still be carried out. `valid_until` is the field this package uses to answer
            # "is this still actionable?", and a product reporting ACTIVE after the
            # deadline of its own action answers that question wrongly while looking
            # entirely well-formed.
            #
            # Inclusive here where delivery was exclusive, and the asymmetry is the point:
            # `valid_until` is an exclusive end -- `status_at` returns EXPIRED AT that
            # moment -- so `valid_until == due_by` means the product goes stale exactly
            # when the deadline lands. That is the longest honest horizon, and it makes
            # "no product is ACTIVE at or after its own deadline" hold at the boundary
            # rather than one tick inside it.
            if self.valid_until is not None and self.valid_until > due_by:
                raise ValueError(
                    f"the claim is stamped valid until "
                    f"{self.valid_until.isoformat()} but the action it recommends was due "
                    f"{due_by.isoformat()}; it would still read as actionable after the "
                    f"deadline of the only thing it asks anyone to do"
                )
            if self.rendered_delivery.rendered_at != self.delivery_time:
                raise ValueError(
                    f"the artifact was rendered "
                    f"{self.rendered_delivery.rendered_at.isoformat()} but the product "
                    f"was delivered {self.delivery_time.isoformat()}; the record would "
                    f"attest a rendering the recipient did not receive at delivery"
                )
        else:
            if self.assurance.permitted:
                raise ValueError(
                    "ABSTAINED contradicts an assurance decision that permitted release"
                )
            # Prose belongs to a delivery. Every rendering check returned early for
            # anything not DELIVERED, so "nobody can author prose here because nobody
            # authors it at all" was false for precisely the products nobody rendered:
            # an abstained record travelled carrying a card reading "94% probability of
            # pack failure within 72h", and the envelope's lifecycle check skipped itself
            # on the same condition.
            if self.rendered_delivery is not None or self.delivery_time is not None:
                raise ValueError(
                    f"a {self.determination.value} product carries a delivery nobody "
                    f"delivered; the artifact and the time belong to a delivery that did "
                    f"not happen"
                )
            # `if not self.assurance.blocking_reasons: raise` sat here and is deleted.
            #
            # This branch is the `not permitted` case, and `AssuranceDecision.__post_init__`
            # already refuses a decision that is not permitted and states no reason -- so
            # no decision that could reach this line can have an empty reason list. The
            # guard could not fire, which `guard_sweep.py` reported and no test could
            # contradict.
            #
            # The RULE is not gone: it is enforced one type up, where the decision is made,
            # by `test_guards.test_a_silent_abstention_is_indistinguishable_from_a_crash`.
            # A duplicate of a rule at a scope that cannot reach it reads as defence in
            # depth and is decoration.
        # Every timestamp on a load-bearing type, not only the ones a particular check
        # happened to compare. A naive timestamp hashes and orders differently depending
        # on who reads it, which is the failure this record cannot afford anywhere.
        for label, moment in (
            ("delivery_time", self.delivery_time), ("valid_until", self.valid_until)
        ):
            if moment is not None and moment.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware")

    # ---- derived views. Nothing below is stored, so nothing below can go stale.

    def abstention_reason(self) -> str | None:
        if self.determination is Determination.DELIVERED:
            return None
        return "; ".join(self.assurance.blocking_reasons)

    def status_at(self, moment: datetime) -> ProductStatus:
        """This record's own status: what it says about itself, plus time.

        WHAT WAS WRONG WITH THE OLD SIGNATURE
        -------------------------------------
        It took `retracted: bool` and `superseded_by: str` FROM THE CALLER. So the answer
        to "is this still actionable" was whatever the caller already believed, on the one
        question this architecture exists to have a single authority for. The docstring
        said status was derived from lineage plus events plus time while the events were a
        parameter -- and a test asserted the parameters worked, which is how it survived a
        suite that looked thorough.

        Retraction and supersession are facts recorded BESIDE this record, in the
        envelope, and `IntelligenceEnvelope.status_at` is the single authority that
        combines them with this. A product on its own can only say whether it has expired,
        which is a property of its own immutable `valid_until`.

        AND WHETHER IT WAS EVER DELIVERED AT ALL
        ----------------------------------------
        That question comes first and was not asked. The body was the expiry comparison
        alone, so a product with no `valid_until` fell through to ACTIVE -- and an
        abstention has no `valid_until` by construction. The record that exists to say
        "this was withheld" reported the status that means "delivered, still good".
        """
        if self.determination is not Determination.DELIVERED:
            return ProductStatus.WITHHELD
        # Non-None for a DELIVERED product: `__post_init__` refuses one with no validity
        # horizon, on the grounds that perishability cannot be expressed by leaving it
        # out. The `is not None` test that used to guard this comparison could therefore
        # never be false once the withheld case was routed above it.
        assert self.valid_until is not None
        if moment >= self.valid_until:
            return ProductStatus.EXPIRED
        return ProductStatus.ACTIVE

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "IntelligenceProduct":
        """Strict reconstruction: every check this implementation can run, or refuse.

        No waiver. `accept_unverifiable_basis` used to sit here and on `import_envelope`,
        and it returned an object indistinguishable from a fully verified one -- absence
        of a verification silently upgraded into presence, which is the defect this
        package refuses everywhere else, wearing a keyword argument.

        A reader who wants to READ a record this build cannot fully check calls
        `from_record_with_findings` (or `envelope.import_historical_envelope`) and gets
        the findings alongside, so the gap stays visible instead of being laundered.
        """
        from .verification import VerificationState

        product, findings = cls.from_record_with_findings(r)
        blocked = [f for f in findings if f.state is VerificationState.UNVERIFIABLE]
        if blocked:
            raise UnverifiableBasis(
                "strict import cannot verify this record: "
                + "; ".join(f.describe() for f in blocked)
                + ". Read it with import_historical_envelope(), which returns the "
                "verification report beside the envelope; absence of a verification is "
                "not a verification"
            )
        return product

    @classmethod
    def from_record_with_findings(
        cls, r: dict[str, Any]
    ) -> tuple["IntelligenceProduct", tuple["DimensionVerification", ...]]:
        """Rebuild the product, which re-runs every guarantee live release runs.

        DELIVERED-requires-permitted-assurance, a delivery time, a rendered artifact, a
        named recipient, evidence that does not postdate delivery, and a `valid_until`
        after delivery all fire in `__post_init__`. What did NOT fire, until this
        revision, was everything BETWEEN the reconstructed objects: the assurance basis
        came back as an untouched dictionary, so a payload could resolve a different
        identity, name a different model, assert a different decision's temporal
        correctness, alter the entitlement scope or rewrite the six dimensions under a
        `permitted=true` verdict, and the import boundary applied none of the checks that
        apply at live release.

        The functions called below are the SAME ones `formation.release` calls. A
        hand-written wire validator restating their rules would be a second semantics
        engine, and the two would disagree on the day it mattered.

        `abstention_reason` and `release_policy_version` are still not read back as
        inputs -- they are derived on the way out and VERIFIED on the way in by
        `_verify_derived_wire_values`, which is the difference between refusing a second
        authority and silently normalising a contradictory one.

        WHAT THE FINDINGS ARE, AND WHAT THEY ARE NOT
        --------------------------------------------
        Three of this record's dimensions can be genuinely uncheckable HERE rather than
        wrong: the claim's replay needs the predictor build that produced it, the policy
        replay needs thresholds that are not on the wire, and re-rendering the card needs
        the renderer version that produced it. Each is reported, with a reason, so a
        reader can decide.

        Everything else either passes or raises. In particular the entitlement scope is
        not among the findings, because both halves of that comparison travel in full:
        there is no threshold to be missing and no build to be absent, so "we could not
        check the rights question" is never an honest answer.
        """
        from .binding import (
            claim_is_replayable_here,
            input_fingerprint_mismatch,
            point_in_time_eligibility_mismatch,
            predictor_output_mismatch,
            subject_binding_mismatch,
            verify_bindings,
        )

        delivery_time = r.get("delivery_time")
        valid_until = r.get("valid_until")
        rendered = r.get("rendered_delivery")
        product = cls(
            product_id=r["product_id"],
            candidate=IntelligenceCandidate.from_record(r["candidate"]),
            assurance=AssuranceDecision.from_record(r["assurance"]),
            evidence=EvidenceSnapshot.from_record(r["evidence"]),
            release_evidence=EvidenceBundle.from_record(r["release_evidence"]),
            determination=Determination(r["determination"]),
            recipient=r["recipient"],
            purpose=r["purpose"],
            tenant=r["tenant"],
            claim_series_id=r["claim_series_id"],
            delivery_time=(
                datetime.fromisoformat(delivery_time) if delivery_time else None
            ),
            valid_until=datetime.fromisoformat(valid_until) if valid_until else None,
            supersedes_product_id=r.get("supersedes_product_id"),
            rendered_delivery=(
                RenderedDelivery.from_record(rendered) if rendered else None
            ),
        )

        assessed = product.assurance.assessed
        verify_bindings(product.candidate, assessed.context, product.evidence)

        # The same binding the release path runs, over the subjects of the readings the
        # bundle actually carries. It used to run over `frozenset({evidence.subject})` --
        # the snapshot's own claim about itself -- because the observations were not on the
        # wire. They are now, so this is the same comparison release makes, against the
        # same input, rather than a weaker stand-in for it.
        reason = subject_binding_mismatch(
            product.candidate,
            frozenset(o.subject for o in product.release_evidence.observations),
        )
        if reason is not None:
            raise ValueError(f"the imported claim does not describe its own evidence: {reason}")

        # And the decision-maker has to have HAD the readings. On the release path this
        # holds by construction, because release takes the point-in-time view from the log
        # itself; here the readings and the clock both arrive from outside, so the property
        # is checked rather than arranged. One function states it for both boundaries.
        reason = point_in_time_eligibility_mismatch(
            product.release_evidence, product.candidate.context
        )
        if reason is not None:
            raise ValueError(reason)

        claim = product.candidate.prediction_claim
        # A RECORD WITH NO PREDICTION INPUTS AT ALL IS A DIFFERENT CASE FROM A WRONG ONE.
        #
        # Both binding functions return a reason when `prediction_inputs` is None, and
        # both refusals used to raise -- so an honest abstention was unreadable in EITHER
        # mode. `assess_evidence` records completeness=MISSING(prediction_inputs) and
        # integrity=BROKEN, the product abstains saying exactly that, and the importer
        # then rejected the bundle the release path had just produced. That is the
        # asymmetry this package names as a defect class, pointing the other way.
        #
        # Absent inputs are not a forgery, they are an absence the record already
        # declares. There is nothing to bind to and nothing to replay against, so the
        # honest answer is the one §3 defines: the check could not be run, which is
        # UNVERIFIABLE with a reason. Strict import still refuses -- a record that cannot
        # be replayed is not fully verified, and strict means strict -- and
        # `import_historical_envelope` reads it with the gap named, which is the whole
        # point of having two modes.
        #
        # A record that HAS inputs and does not bind to them is untouched by this: that is
        # a wrong answer rather than a missing one, and it still raises by name.
        inputs_absent = product.evidence.prediction_inputs is None
        # Build-independent, so it holds for a record this process could not replay: the
        # fingerprint is a pure function of the recorded inputs.
        reason = input_fingerprint_mismatch(product.evidence, claim)
        if reason is not None and not inputs_absent:
            raise ValueError(f"the imported claim does not bind to its evidence: {reason}")
        # The full replay is only meaningful against the build that produced the claim.
        #
        # WHY THIS FAILS CLOSED
        # ---------------------
        # It did not, and that re-opened the exact attack the replay exists to stop. The
        # artifact digest is supplied BY THE RECORD and is only cross-checked against the
        # claim's own declared envelope, so a forger could set a digest naming no build we
        # have, skip the only check binding score, score_semantics and evidence_strength,
        # and import as DELIVERED carrying "94% probability of failure" over evidence that
        # computes an ordering. The record chose whether the strongest check ran.
        #
        # A record from another build genuinely cannot be replayed here -- that part was
        # true. What was wrong was treating "cannot verify" as "verified". Reporting the
        # gap by name puts the decision where it belongs: with the reader, stated, rather
        # than with the payload, silently.
        findings: list[DimensionVerification] = []
        if inputs_absent:
            findings.append(unverifiable(
                VerificationDimension.CLAIM_REPLAY,
                "the record carries no prediction inputs, so there is nothing to replay "
                "against; its own evidence assessment records this as missing evidence",
            ))
        elif claim_is_replayable_here(claim):
            reason = predictor_output_mismatch(product.evidence, claim)
            if reason is not None:
                raise ValueError(f"the imported claim replays differently: {reason}")
            findings.append(verified(VerificationDimension.CLAIM_REPLAY))
        else:
            findings.append(unverifiable(
                VerificationDimension.CLAIM_REPLAY,
                f"the claim names model artifact "
                f"{claim.model_artifact_digest[:12]}..., which is not the build running "
                f"here, so its score, score semantics and evidence strength cannot be "
                f"re-derived from the recorded inputs",
            ))

        findings.append(product._verify_recorded_decision_follows_from_its_basis())
        product._verify_the_assessment_follows_from_the_evidence()
        findings.append(verified(VerificationDimension.EVIDENCE_RECONSTRUCTION))
        findings.append(verified(VerificationDimension.ENTITLEMENT_SCOPE))
        findings.append(
            product._verify_the_delivered_artifact_is_what_the_candidate_renders()
        )
        product._verify_derived_wire_values(r)
        return product, tuple(findings)

    def _verify_the_assessment_follows_from_the_evidence(self) -> None:
        """Re-run the release path's own assessment over the carried evidence.

        WHAT THIS USED TO BE, AND WHY IT WAS NOT ENOUGH
        -----------------------------------------------
        It re-derived two of the six dimensions -- completeness from
        `EvidenceSnapshot.missing_elements()`, identity from the snapshot's confidence
        against the policy floor -- and said plainly that the other four were not
        re-derivable here: integrity needed the observations, entitlement needed the
        delivery scope, support needed the applicability verdict, temporal eligibility
        needed the feature view.

        Three of those four were only unavailable because the observations were not on the
        wire. They are now, so this calls `assess_evidence` -- the SAME function
        `formation.release` calls, with the same arguments drawn from the record -- and
        compares its answer to the recorded one. That is what makes the two boundaries
        describe one semantic universe rather than two that happen to agree: there is no
        second wire-side implementation of evidence semantics to drift from the first.

        WHAT REMAINS POLICY-DEPENDENT, STATED RATHER THAN GLOSSED
        ---------------------------------------------------------
        Two dimensions consult thresholds. `identity` compares the confidence to a floor
        and `support` compares evidence strength to a minimum, and the thresholds of a
        policy this package does not ship are not on the wire. For a foreign policy those
        two are therefore compared only where the answer does not depend on where the line
        was drawn: an unrecorded confidence is not a resolved identity under ANY floor, and
        a model asserted to be inapplicable supports nothing at ANY minimum.

        The other four dimensions, plus the named missing evidence and the named conflicts,
        are compared exactly, whatever policy the record names.
        """
        from .binding import claim_is_replayable_here
        from .evidence import Identity, Support
        from .policy import POLICY_ID, POLICY_VERSION, ReleasePolicy
        from .assessment import assess_imported_evidence, imported_integrity_findings

        assessed = self.assurance.assessed
        recorded = assessed.evidence_assessment
        thresholds_known = (
            self.assurance.policy_id == POLICY_ID
            and self.assurance.policy_version == POLICY_VERSION
        )
        recomputed = assess_imported_evidence(
            evidence=self.evidence,
            entitlement_assertion=assessed.context.entitlement_assertion,
            delivering_to=self.recipient,
            for_purpose=self.purpose,
            about_subject=self.candidate.prediction_claim.subject,
            for_tenant=self.tenant,
            release_decision_time=self.assurance.release_decision_time,
            confidence=self.candidate.prediction_claim.evidence_strength,
            model_applicable=assessed.context.applicability_assertion.valid,
            point_in_time_correct=assessed.context.temporal_assertion.valid,
            evidence_source=self.release_evidence,
            prediction_claim=self.candidate.prediction_claim,
            derivation=self.candidate.business_consequence.derivation,
            policy=ReleasePolicy(),
        )

        # CONFLICTS BEFORE INTEGRITY, and the order is load-bearing rather than tidy.
        # A dropped contradiction moves integrity from BROKEN to VALID, so comparing the
        # dimension first refuses with "integrity disagrees" and an empty findings list --
        # the recomputed evidence is clean, so there is nothing for it to name. The
        # conflicts comparison is the one that can say what was deleted.
        if tuple(recorded.conflicts) != tuple(recomputed.conflicts):
            raise ValueError(
                f"the record names conflicts {list(recorded.conflicts)} but the evidence "
                f"it carries produces {list(recomputed.conflicts)}; a contradiction "
                f"dropped on the way out is a withholding that never happened"
            )
        if recorded.integrity is not recomputed.integrity:
            # NAMED, not merely counted. Eight independent invariants project onto this one
            # dimension, and a refusal that says only "integrity" sends a reader to re-read
            # the whole bundle -- and lets a test claiming to exercise one arm pass on
            # another. `integrity_findings` is the same function `assess_evidence` used to
            # reach its answer, so the reasons quoted here are the reasons that decided.
            detail = "; ".join(
                imported_integrity_findings(
                    evidence=self.evidence,
                    evidence_source=self.release_evidence,
                    prediction_claim=self.candidate.prediction_claim,
                )
            ) or "the record carries evidence its recorded assessment does not describe"
            raise ValueError(
                f"the record's assessment says integrity={recorded.integrity.value} but "
                f"the evidence it carries produces {recomputed.integrity.value}: {detail}"
            )
        for dimension in ("completeness", "temporal_eligibility", "entitlement"):
            if getattr(recorded, dimension) is not getattr(recomputed, dimension):
                raise ValueError(
                    f"the record's assessment says {dimension}="
                    f"{getattr(recorded, dimension).value} but the evidence it carries "
                    f"produces {getattr(recomputed, dimension).value}; the recorded "
                    f"verdict does not follow from the record's own evidence"
                )
        if tuple(recorded.missing_evidence) != tuple(recomputed.missing_evidence):
            raise ValueError(
                f"the record names {list(recorded.missing_evidence)} as missing but its "
                f"evidence is missing {list(recomputed.missing_evidence)}"
            )
        if thresholds_known:
            for dimension in ("support", "identity"):
                if getattr(recorded, dimension) is not getattr(recomputed, dimension):
                    raise ValueError(
                        f"the record's assessment says {dimension}="
                        f"{getattr(recorded, dimension).value} but re-running "
                        f"{POLICY_VERSION} over the evidence it carries produces "
                        f"{getattr(recomputed, dimension).value}"
                    )
            return
        if self.evidence.identity_confidence is None and (
            recorded.identity is Identity.RESOLVED
        ):
            raise ValueError(
                "the record asserts identity=RESOLVED over evidence carrying no identity "
                "confidence at all"
            )
        if not assessed.context.applicability_assertion.valid and (
            recorded.support is Support.SUPPORTED
        ):
            raise ValueError(
                "the record asserts support=SUPPORTED over a model its own applicability "
                "assertion says was not valid here; a model used outside its declared "
                "envelope supports nothing, whatever number it returned"
            )

    def _verify_the_delivered_artifact_is_what_the_candidate_renders(
        self,
    ) -> "DimensionVerification":
        """Re-render the card and compare. This is the text a human was actually shown.

        Every other derived string on the wire is re-derived and compared -- the action's
        sentence, the consequence's description, the abstention reason, the outcome's
        description. The delivered artifact, which is the one thing in the bundle that a
        customer literally read, was the one left out: `RenderedDelivery.__post_init__`
        checks the blob against its own digest, and nothing checked the blob against the
        claim.

        That made the module docstring's promise false across the wire. Nobody can author
        prose here IN MEMORY because nobody authors it at all; off the wire, a payload
        could restamp the digest over "94% probability of failure within 72h" while the
        typed claim beside it still said "relative degradation signal, ordering only".

        WHY A FOREIGN RENDERER IS UNVERIFIABLE RATHER THAN REFUSED
        ----------------------------------------------------------
        `RenderedDelivery.render` always stamps THIS build's `RENDERER_VERSION`, so a card
        produced by another renderer could never reproduce here -- and the check refused
        it, which reads as "this record is forged" when the honest reading is "this record
        was rendered by software I do not have". That is the same mistake the claim replay
        made before it was separated into a reported dimension, on a different field.

        An ABSTAINED product reports VERIFIED, not UNVERIFIABLE: it has no rendered
        artifact, `__post_init__` refuses one, and that absence is a checked fact rather
        than a gap in what this reader could see.
        """
        if self.determination is not Determination.DELIVERED:
            return verified(VerificationDimension.RENDERED_ARTIFACT)
        rendered = self.rendered_delivery
        assert rendered is not None  # guaranteed by __post_init__ for DELIVERED
        if rendered.renderer_version != RENDERER_VERSION:
            return unverifiable(
                VerificationDimension.RENDERED_ARTIFACT,
                f"the card was produced by {rendered.renderer_version}, not the "
                f"{RENDERER_VERSION} running here, so it cannot be re-rendered and "
                f"compared",
            )
        expected = RenderedDelivery.render(
            self.candidate, rendered_at=rendered.rendered_at, locale=rendered.locale
        ).with_trust_line(self._trust_line())
        if rendered.content_digest != expected.content_digest:
            raise ValueError(
                "the delivered artifact is not what this candidate renders; the record "
                "attests a sentence the typed claim beside it does not say"
            )
        return verified(VerificationDimension.RENDERED_ARTIFACT)

    def _trust_line(self) -> str:
        """The assurance line appended at delivery, from the ONE implementation.

        Writing it out again here would mean an honest bundle failing to reproduce the
        moment either copy was edited -- the drift this whole file argues against.
        """
        return trust_line(
            identity_confidence=(
                self.assurance.assessed.context.identity_assertion.confidence
            )
        )

    def _verify_recorded_decision_follows_from_its_basis(
        self,
    ) -> "DimensionVerification":
        """Re-run the policy over the reconstructed basis and compare the verdict.

        `ReleasePolicy.evaluate` is a pure function of the candidate and the assessed
        assurance, both of which cross the wire, so the decision is fully recomputable by
        a reader holding nothing but the bundle. That is what closes "a payload may not
        alter the recorded evidence assessment": rewriting a dimension under a
        `permitted=true` verdict now produces a verdict that does not match.

        Thresholds are not on the wire, so an exact recomputation is only available for
        the policy this package ships. For any other policy id or version the check
        degrades to the coherence a reader can still verify -- a permission whose own
        assessment says WITHHOLD is refused either way -- and the limitation is stated
        rather than papered over.
        """
        from .policy import POLICY_ID, POLICY_VERSION, ReleasePolicy
        from .evidence import Release

        assessed = self.assurance.assessed
        if self.assurance.permitted and (
            assessed.evidence_assessment.release_decision() is Release.WITHHOLD
        ):
            raise ValueError(
                "the decision permitted release while its own evidence assessment "
                "withholds; the verdict does not follow from the basis recorded with it"
            )
        # The authorization, re-run against the delivery this record describes rather than
        # against the clearance's own fields. Only meaningful for a DELIVERED product: an
        # abstention may legitimately be the one whose entitlement did not permit.
        #
        # HOISTED ABOVE THE POLICY BRANCH, AND THAT ORDERING IS THE POINT.
        # It used to sit below, after the early return for a policy this package does not
        # ship -- so any string at all in `policy_id`, a free wire field, skipped it. A
        # forger could not defeat the entitlement check, so they arranged for the branch
        # that skips it: delivered to an unentitled recipient, under another tenant, for
        # an unauthorised purpose, on an unlicensed feed.
        #
        # The waiver flag that made that branch reachable on demand is gone, and the
        # ordering still matters, because the branch below is now the one that reports an
        # unreproducible policy as UNVERIFIABLE. "This reader could not reproduce the
        # verdict" must never silently mean "this reader waived the rights question".
        #
        # This check needs no policy thresholds. It compares a clearance to the delivery
        # recorded beside it, both of which are on the wire in full.
        if self.determination is Determination.DELIVERED:
            from .assessment import material_source_systems

            entitlement = assessed.context.entitlement_assertion
            if not entitlement.permits(
                recipient=self.recipient,
                purpose=self.purpose,
                subject=self.candidate.prediction_claim.subject,
                tenant=self.tenant,
                # THE SAME UNION `assess_evidence` USES, from the same function.
                #
                # This read `self.evidence.source_systems` -- the telemetry feeds alone --
                # while release checked the union of telemetry and REASON-derivation
                # sources. Two scopes for one rights question, on the two boundaries that
                # are supposed to describe the same universe, which is precisely the
                # structural inequivalence this whole increment exists to remove. A record
                # whose derivation joined an unlicensed business system passed here and
                # would have been refused at release.
                source_systems=material_source_systems(
                    evidence_source=self.release_evidence,
                    derivation=self.candidate.business_consequence.derivation,
                ),
                at=self.delivery_time,
            ):
                raise ValueError(
                    "the recorded entitlement does not authorise the delivery this record "
                    "describes; the clearance and the delivery disagree about recipient, "
                    "purpose, subject, tenant, licensed source systems or validity"
                )
        # Unresolved identity conflicts are the same shape as the rights question wave 3
        # hoisted: a coherence fact carried in full on the wire, blocking under ANY
        # policy, needing no thresholds to evaluate. It was left downstream of a gate that
        # `policy_id` -- a free wire field -- decides, so a record could name a policy this
        # package does not ship and arrive saying, simultaneously, "two systems disagree
        # about which asset this is" and "identity RESOLVED, delivered".
        #
        # The identity FLOOR stays below the gate, and that is deliberate: a floor is a
        # threshold, and thresholds of a policy we do not have are genuinely not on the
        # wire. A conflict is not a threshold.
        conflicts = assessed.context.identity_assertion.conflicts
        if conflicts and self.assurance.permitted:
            raise ValueError(
                f"the record permits release while its own identity assertion carries "
                f"unresolved conflicts {list(conflicts)}; no policy can authorise a claim "
                f"whose subject two systems disagree about"
            )
        if (
            self.assurance.policy_id != POLICY_ID
            or self.assurance.policy_version != POLICY_VERSION
        ):
            # Reported, not waived, and not silently skipped either. The thresholds of a
            # policy this package does not ship are genuinely not on the wire, so the
            # verdict cannot be reproduced -- which is a different statement from the
            # verdict being wrong. Returning quietly here once meant a payload could name
            # any policy it liked and be accepted on the strength of a coherence check no
            # test exercised. "We cannot check this" must not read as "this checks out",
            # and a named UNVERIFIABLE dimension is the only form of that sentence a
            # reader cannot mistake.
            #
            # Everything above this branch has already run: the entitlement scope, and
            # the identity-conflicts rule. Both are policy-free facts carried in full on
            # the wire, and both stay mandatory whatever policy the record names.
            return unverifiable(
                VerificationDimension.POLICY_REPLAY,
                f"the decision names policy "
                f"{self.assurance.policy_id}/{self.assurance.policy_version}, whose "
                f"thresholds this package does not have, so its verdict cannot be "
                f"reproduced from the recorded basis",
            )
        policy = ReleasePolicy()
        if self.assurance.policy_digest != policy.digest():
            raise ValueError(
                f"the decision names policy {self.assurance.policy_version} but carries a "
                f"digest that is not that policy's; a record claiming the rules everybody "
                f"trusts must have been decided under them"
            )
        recomputed = policy.evaluate(
            self.candidate, assessed, release_decision_time=self.assurance.release_decision_time
        )
        if (
            recomputed.permitted != self.assurance.permitted
            or recomputed.blocking_reasons != self.assurance.blocking_reasons
        ):
            raise ValueError(
                f"re-running {self.assurance.policy_version} over the recorded assurance "
                f"basis produces permitted={recomputed.permitted} with reasons "
                f"{list(recomputed.blocking_reasons)}, not the recorded "
                f"permitted={self.assurance.permitted} with "
                f"{list(self.assurance.blocking_reasons)}"
            )
        return verified(VerificationDimension.POLICY_REPLAY)

    def _verify_derived_wire_values(self, r: dict[str, Any]) -> None:
        """Derived values on the wire are re-derived AND compared, never read back.

        The choice not to read them back is right -- a derived value that can be supplied
        is a second authority. Silently re-deriving and discarding what the payload said
        is the other half of the mistake: it accepts a record asserting one policy version
        or one abstention reason, stores a different one, and re-exports a bundle that no
        longer matches the bytes it arrived as. Disagreement is refused.
        """
        derived = {
            "release_policy_version": self.assurance.policy_version,
            "abstention_reason": self.abstention_reason(),
        }
        for key, value in derived.items():
            if key in r and r[key] != value:
                raise ValueError(
                    f"the record's {key} is {r[key]!r} but the value derived from what it "
                    f"carries is {value!r}; a derived value that disagrees with its source "
                    f"is a second authority, and normalising it silently hides that"
                )

    def as_record(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "claim_series_id": self.claim_series_id,
            "supersedes_product_id": self.supersedes_product_id,
            "determination": self.determination.value,
            "recipient": self.recipient,
            "purpose": self.purpose,
            "tenant": self.tenant,
            "delivery_time": (
                self.delivery_time.isoformat() if self.delivery_time else None
            ),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            # Derived, not stored. AssuranceDecision is the single policy authority;
            # a second copy on the product is the drift pattern this refactor removes.
            "release_policy_version": self.assurance.policy_version,
            "abstention_reason": self.abstention_reason(),
            "candidate": self.candidate.as_record(),
            "assurance": self.assurance.as_record(),
            # This key did not exist. The bundle claimed to preserve the in-memory
            # guarantees while omitting the evidence every guarantee is about.
            "evidence": self.evidence.as_record(),
            # ...and this one carried the citation without the thing cited, which left the
            # importer able to re-run four of the six assurance dimensions and obliged to
            # take the other two on the record's word.
            "release_evidence": self.release_evidence.as_record(),
            "rendered_delivery": (
                self.rendered_delivery.as_record() if self.rendered_delivery else None
            ),
        }
