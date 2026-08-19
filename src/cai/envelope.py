"""The portable envelope: one artifact carrying the whole loop out of the platform.

WHAT TRAVELS
------------
    candidate (context, claim, consequence, action)
    assurance decision (verdict, blocking reasons, policy id/version/digest, assertions)
    rendered delivery (what the recipient literally saw, digested)
    lifecycle events
    outcome observation
    status events (retraction, supersession)

A reader outside this codebase can therefore answer the question the old bundle could not:
**why did this claim qualify for release?** The previous version carried rendered context
text and the product, which let somebody replay the predictor while leaving the release
rationale unreconstructable.

IMMUTABILITY
------------
Retraction and supersession are EVENTS here, never fields mutated onto the delivered
product. The product is a historical record of what was sent and what was known when it
was sent; editing it would undo the reason decision-time evidence is worth keeping. Current
status is derived from lineage plus events plus time.

WHAT THE DIGEST IS
------------------
SHA-256 over the canonical bytes. Tamper-EVIDENT, not tamper-proof: anyone who alters the
envelope can recompute it. Signatures are deliberately not implemented rather than
implemented badly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .canonical import CANONICALIZATION, canonicalize
from .derivation import DerivationRelationship
from .evidence import (
    Completeness,
    EntitlementState,
    Identity,
    Integrity,
    Release,
    Support,
    TemporalEligibility,
)
from .lifecycle import (
    AttributedEffect,
    DispositionEvent,
    DispositionState,
    check_trail,
)
from .product import (
    Determination,
    IntelligenceProduct,
    ProductStatus,
    UnverifiableBasis,
)
from .verification import (
    VerificationDimension,
    VerificationReport,
    verified,
)

SCHEMA_VERSION = "cai.intelligence-envelope/1"
SCHEMA_URI = "https://linus10x.github.io/connected-asset-intelligence/schema/envelope-1.json"


class UnsupportedSchemaVersion(Exception):
    """Raised rather than best-guessing a record shape we do not understand."""


class UnsupportedAttributedEffect(Exception):
    """Raised when an imported envelope asserts a causal claim the design refuses.

    `AttributedEffect` has one member and a test fails if anyone adds a second. Storing the
    effect as a bare string let a file arriving from outside assert exactly the claim the
    type system exists to prevent, so the importer parses it through the enum.
    """


class StatusEventType(str, Enum):
    RETRACTED = "RETRACTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class StatusEvent:
    """A fact about the product's standing, recorded beside it rather than inside it."""

    event_type: StatusEventType
    at: datetime
    actor: str
    reason: str = ""
    replacement_product_id: str | None = None

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("a status event's timestamp must be timezone-aware")
        if not self.actor:
            raise ValueError(
                "a status event with no actor records that a claim was withdrawn and not "
                "who withdrew it"
            )
        if self.event_type is StatusEventType.RETRACTED and not self.reason:
            raise ValueError("a retraction with no reason is unauditable")
        if (
            self.event_type is StatusEventType.SUPERSEDED
            and not self.replacement_product_id
        ):
            raise ValueError("a supersession must name what replaced it")

    def as_record(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "reason": self.reason,
            "replacement_product_id": self.replacement_product_id,
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "StatusEvent":
        """A retraction with no reason and a supersession naming nothing are refused here
        by `__post_init__`, on the same terms as in memory."""
        return cls(
            event_type=StatusEventType(r["event_type"]),
            at=datetime.fromisoformat(r["at"]),
            actor=r["actor"],
            reason=r.get("reason", ""),
            replacement_product_id=r.get("replacement_product_id"),
        )


@dataclass(frozen=True)
class IntelligenceEnvelope:
    """One product and everything that later became true about it.

    THE SINGLE AUTHORITY ON CURRENT STATUS
    --------------------------------------
    `IntelligenceProduct.status_at` used to take `retracted` and `superseded_by` from the
    caller, which meant a caller told the product whether it had been withdrawn -- exactly
    the second authority this architecture exists to eliminate, sitting on the question it
    exists to answer. The typed events live here, so the derivation lives here too.
    """

    product: "IntelligenceProduct"
    lifecycle_events: tuple[DispositionEvent, ...] = ()
    outcome: "OutcomeObservation | None" = None
    attributed_effect: AttributedEffect = AttributedEffect.NOT_ESTABLISHED
    """Typed, like everything else the envelope carries.

    It was a bare `str`, so `IntelligenceEnvelope(product=..., attributed_effect="PREVENTED")`
    constructed happily in memory -- refused on import, but "one representation" was not
    true of the field whose whole purpose is that exactly one value can exist."""
    status_events: tuple[StatusEvent, ...] = ()

    def __post_init__(self) -> None:
        from .action import OutcomeObservation

        if not isinstance(self.product, IntelligenceProduct):
            raise TypeError(
                f"product must be an IntelligenceProduct, not "
                f"{type(self.product).__name__}; the envelope carries the typed product, "
                f"never a loose record standing in for one"
            )
        if not all(isinstance(e, DispositionEvent) for e in self.lifecycle_events):
            raise TypeError(
                "lifecycle_events must be typed DispositionEvents; a trail of loose "
                "dictionaries is a second representation of a class that already exists"
            )
        if self.outcome is not None and not isinstance(self.outcome, OutcomeObservation):
            raise TypeError(
                f"outcome must be an OutcomeObservation, not "
                f"{type(self.outcome).__name__}; the join to the action it is about is "
                f"the only reason outcomes are collected"
            )
        # One implementation of the trail rules, called from here and from `advance`.
        check_trail(self.lifecycle_events)
        # FIRST, because everything after it assumes a delivery happened. Each of the
        # three checks below joined its collection to `delivery_time`, and each returned
        # early when that was None -- so an abstention, which has None by construction,
        # skipped all three.
        self._check_nothing_was_recorded_against_a_withheld_product()
        self._check_lifecycle_against_delivery()
        self._check_outcome_binds_to_this_product()
        self._check_status_events()

    def _check_nothing_was_recorded_against_a_withheld_product(self) -> None:
        """An abstention is a record that a candidate was WITHHELD. Nothing followed it.

        `IntelligenceProduct.__post_init__` already refuses an abstention carrying a
        rendered card or a delivery time, and that reads like the question is closed. It
        is not: it closes what the PRODUCT carries and says nothing about what is
        recorded beside it. The three collections on this envelope are all histories of
        a delivery, and all three were joined to `delivery_time` by a guard that returned
        early on None -- which is every abstention.

        So the state was constructible, internally consistent and impossible: a lifecycle
        opening at DELIVERED, running to OUTCOME_OBSERVED, carrying the outcome, and
        retracted afterwards, on a product whose own determination says nothing was ever
        sent. Every event was well-formed. The sequence described a delivery that did not
        happen.

        Refused here rather than dimension by dimension because the reason is one reason,
        and a reader who sees three differently-worded refusals for one contradiction has
        to work out that they are the same rule.
        """
        if self.product.determination is Determination.DELIVERED:
            return
        for label, recorded in (
            ("lifecycle_events", self.lifecycle_events),
            ("status_events", self.status_events),
            ("an outcome", (self.outcome,) if self.outcome is not None else ()),
        ):
            if recorded:
                raise ValueError(
                    f"the product was {self.product.determination.value} and carries "
                    f"{label}; a candidate that was withheld was never delivered, "
                    f"acknowledged, acted on, observed, retracted or superseded, and a "
                    f"record that says otherwise describes a delivery that did not happen"
                )

    def _check_lifecycle_against_delivery(self) -> None:
        """ONE DELIVERY, ONE MOMENT.

        This compared with `<`, so the trail could open strictly after the delivery it
        describes: the product said 07:00, the trail said 09:00, and one delivery carried
        two timestamps. The package already refused exactly this shape one state further
        along -- "one event cannot have happened at two moments, and a reader replaying
        the sequence gets two answers" -- and left the opening event free.

        `check_trail` has already established that a non-empty trail opens at DELIVERED,
        so the event compared here is the delivery event and not merely the first one.
        The lifecycle could legitimately open later only if DELIVERED named a different
        event from `delivery_time`, and it does not; inventing a second delivery concept
        to justify the gap would be building a name for a defect.
        """
        if not self.lifecycle_events:
            return
        # Guaranteed by the withheld check above: only a DELIVERED product reaches here,
        # and a DELIVERED product has a delivery time.
        delivery = self.product.delivery_time
        assert delivery is not None
        opening = self.lifecycle_events[0]
        if opening.at != delivery:
            raise ValueError(
                f"the trail records DELIVERED at {opening.at.isoformat()} but the "
                f"product was delivered at {delivery.isoformat()}; one event cannot "
                f"have happened at two moments, and a reader replaying the sequence "
                f"gets two answers about when the operator received it"
            )

    def _check_outcome_binds_to_this_product(self) -> None:
        if self.outcome is None:
            if self.lifecycle_events and (
                self.lifecycle_events[-1].state is DispositionState.OUTCOME_OBSERVED
            ):
                raise ValueError(
                    "the trail reached OUTCOME_OBSERVED but no outcome is recorded"
                )
            return
        if not self.lifecycle_events or (
            self.lifecycle_events[-1].state is not DispositionState.OUTCOME_OBSERVED
        ):
            raise ValueError(
                "an outcome is recorded but the trail never reached OUTCOME_OBSERVED"
            )
        # ONE EVENT, ONE MOMENT. The trail says when the outcome was observed and the
        # typed outcome says when it was observed, and nothing compared them -- so a
        # record could place the disposition on one day and the observation it describes on
        # another, and a reader reconstructing the sequence would get two answers.
        #
        # No separate `recorded_at` concept is introduced. There is one event here -- an
        # outcome being observed -- and a second timestamp for it would need a reason and a
        # name, which is precisely the two-authorities pattern the scalar outcome field was
        # just deleted for.
        observed_state = self.lifecycle_events[-1]
        if observed_state.at != self.outcome.observed_at:
            raise ValueError(
                f"the trail records OUTCOME_OBSERVED at {observed_state.at.isoformat()} "
                f"but the outcome it refers to was observed at "
                f"{self.outcome.observed_at.isoformat()}; one event cannot have happened "
                f"at two moments, and a reader replaying the sequence gets two answers"
            )
        subject = self.product.candidate.prediction_claim.subject
        if self.outcome.subject != subject:
            raise ValueError(
                f"the outcome observes {self.outcome.subject!r} but this product's claim "
                f"is about {subject!r}; an outcome attached to the wrong subject is a row "
                f"an evaluation dataset will count against the wrong recommendation"
            )
        action_id = self.product.candidate.action.action_id
        if self.outcome.related_action_id != action_id:
            raise ValueError(
                f"the outcome joins action {self.outcome.related_action_id!r} but this "
                f"product recommended {action_id!r}; without the join 'acted and no "
                f"failure' and 'ignored and no failure' are the same row"
            )
        # One check, not two. `observed_at < delivery_time` was here as well and is
        # unreachable: `OutcomeObservation` already refuses an observation made before its
        # own window opens, so a window that starts at or after delivery forces the
        # observation to as well. A check no input can reach is the decorative-field
        # pattern this package spends its time removing -- it reads as protection, no
        # mutation can be attributed to it, and it would survive any audit that counted
        # checks instead of testing them.
        # `delivery is not None` guarded this and can no longer be false. An outcome on
        # a withheld product is refused one check earlier, so anything reaching this line
        # is DELIVERED and therefore has a delivery time. A condition no input can make
        # false reads as protection and proves nothing, which is why the other two in
        # this class went the same way in the same pass.
        delivery = self.product.delivery_time
        assert delivery is not None
        if self.outcome.observation_window.start < delivery:
            raise ValueError(
                f"the outcome's observation window opens "
                f"{self.outcome.observation_window.start.isoformat()}, before the "
                f"recommendation was delivered at {delivery.isoformat()}; it cannot be "
                f"observing the response to something nobody had received"
            )
        # No comparison against NOT_ESTABLISHED here. `AttributedEffect` has exactly one
        # member, so the constructor either raises or returns that member -- a branch no
        # input can reach. The causal boundary is enforced by the enum having one value
        # (guarded by `test_no_code_path_can_claim_the_intervention_worked`) and by
        # `validate_envelope_payload` parsing the wire string through it.
        AttributedEffect(self.attributed_effect)

    def _check_status_events(self) -> None:
        """Coherence of the events status is now derived from.

        Derivation is only as good as the sequence it derives over. A retraction dated
        before delivery, a supersession naming the product itself, or two retractions
        each with their own actor and reason all produce a confident answer to
        "is this still actionable" from a record that does not describe a possible history.
        """
        if not all(isinstance(e, StatusEvent) for e in self.status_events):
            raise TypeError(
                "status_events must be typed StatusEvents; this is the collection that "
                "decides RETRACTED and SUPERSEDED, and it was the one left unchecked"
            )
        # Non-None for the same reason as in `_check_outcome_binds_to_this_product`: a
        # status event on a withheld product is already refused, so only a DELIVERED
        # product can reach a loop body below.
        delivery = self.product.delivery_time
        assert delivery is not None or not self.status_events
        seen_retraction = False
        seen_supersession = False
        seen: set[tuple[str, str, str | None]] = set()
        for earlier, later in zip(self.status_events, self.status_events[1:]):
            if later.at < earlier.at:
                raise ValueError(
                    f"status events are not in chronological order: "
                    f"{later.at.isoformat()} follows {earlier.at.isoformat()}"
                )
        for event in self.status_events:
            # `StatusEvent.__post_init__` already refuses a naive timestamp and an
            # unnamed actor, and `status_events` only ever holds StatusEvents, so
            # re-checking those here would be a guard no input can reach -- the
            # decorative-check pattern this file removed two of elsewhere.
            key = (event.event_type.value, event.at.isoformat(), event.replacement_product_id)
            if key in seen:
                raise ValueError(
                    f"a duplicate {event.event_type.value} event at "
                    f"{event.at.isoformat()}; a sequence that records one fact twice "
                    f"cannot be replayed into a single history"
                )
            seen.add(key)
            if seen_retraction:
                raise ValueError(
                    f"a {event.event_type.value} event follows a retraction; a claim "
                    f"already withdrawn has no standing left to change, and a reader "
                    f"deriving status from the last event would report the wrong one"
                )
            if event.at < delivery:
                raise ValueError(
                    f"a {event.event_type.value} event at {event.at.isoformat()} predates "
                    f"delivery at {delivery.isoformat()}; a claim cannot be withdrawn "
                    f"before it was made"
                )
            # No `if seen_retraction` branch here: the generic "nothing follows a
            # retraction" check above fires first in the same iteration, so a
            # double-retraction arm would be unreachable. A second retraction IS refused
            # -- by that rule, with that message.
            if event.event_type is StatusEventType.RETRACTED:
                seen_retraction = True
            if event.event_type is StatusEventType.SUPERSEDED:
                if event.replacement_product_id == self.product.product_id:
                    raise ValueError(
                        f"{self.product.product_id} supersedes itself; a reader walking "
                        f"the lineage for the current view arrives back where they started"
                    )
                if seen_supersession:
                    raise ValueError(
                        "a product superseded twice names two current replacements; a "
                        "reader following the lineage forward has to pick one, and "
                        "nothing in the record says which"
                    )
                seen_supersession = True

    def status_at(self, moment: datetime) -> "ProductStatus":
        """Current status: lineage, plus the events that had happened, plus time.

        The single authority. Events that have not yet occurred do not apply -- reading
        them as flags would make a claim retracted retrospectively, rewriting what an
        operator acting earlier was entitled to believe.

        Retraction outranks supersession: a superseded claim has a live replacement, a
        retracted one has been withdrawn, and a reader shown the weaker of the two would
        go looking for a successor that does not exist.
        """
        from .product import ProductStatus

        effective = [e for e in self.status_events if e.at <= moment]
        if any(e.event_type is StatusEventType.RETRACTED for e in effective):
            return ProductStatus.RETRACTED
        if any(e.event_type is StatusEventType.SUPERSEDED for e in effective):
            return ProductStatus.SUPERSEDED
        return self.product.status_at(moment)

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "schema_uri": SCHEMA_URI,
            "canonicalization": CANONICALIZATION,
            "product": self.product.as_record(),
            "lifecycle_events": [e.as_record() for e in self.lifecycle_events],
            "outcome": self.outcome.as_record() if self.outcome else None,
            "attributed_effect": AttributedEffect(self.attributed_effect).value,
            "status_events": [e.as_record() for e in self.status_events],
        }

    def canonical_json(self) -> str:
        return canonicalize(self.as_record())

    def digest(self) -> str:
        """SHA-256 over the canonical bytes. Tamper-evident, not tamper-proof."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoricalEnvelopeImport:
    """A readable record and an honest account of what could not be checked about it.

    Returned only by `import_historical_envelope`. The report is NOT welded onto the
    product: it describes this reader, on this build, at this moment -- whether the
    predictor artifact happens to be present, whether this package ships the policy the
    record names -- and stamping today's verification state into an immutable historical
    record is the reconstruction-of-a-reconstruction this codebase names as its worst
    failure elsewhere.
    """

    envelope: "IntelligenceEnvelope"
    verification_report: VerificationReport

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, IntelligenceEnvelope):
            raise TypeError(
                f"envelope must be an IntelligenceEnvelope, not "
                f"{type(self.envelope).__name__}"
            )
        if not isinstance(self.verification_report, VerificationReport):
            raise TypeError(
                f"verification_report must be a VerificationReport, not "
                f"{type(self.verification_report).__name__}; a historical import whose "
                f"report is a loose dict is the boolean this type replaced"
            )


def import_historical_envelope(payload: dict[str, Any]) -> HistoricalEnvelopeImport:
    """Read a record this build may not be able to check end to end, and say which parts.

    WHAT THIS IS FOR
    ----------------
    A record produced by a predictor build this process does not have, or under a release
    policy whose thresholds this package does not ship, cannot be fully reproduced here.
    That is an ordinary situation for an artifact whose whole purpose is being read years
    later, and refusing to read it at all would make the format useless for the one job
    it exists to do.

    WHAT IT IS NOT
    --------------
    Not a waiver, and not a weaker strict import. Every check this implementation CAN run
    still runs, and a check that runs and fails still refuses -- in this mode exactly as
    in the strict one. What differs is only the treatment of a check that cannot be run at
    all: strict import refuses; this returns the envelope with the gap named.

    The entitlement scope is checked here identically. Rights are never waived, because
    both halves of that comparison travel in full -- there is no threshold to be missing
    and no build to be absent, so "we could not check the rights question" is never an
    honest answer.
    """
    envelope, report = _reconstruct(payload)
    return HistoricalEnvelopeImport(envelope=envelope, verification_report=report)


def import_envelope(payload: dict[str, Any]) -> "IntelligenceEnvelope":
    """Strict import: every verification available to this implementation, or refuse.

    NO WAIVER FLAG, AND THAT IS THE POINT
    -------------------------------------
    This used to take `accept_unverifiable_basis`, and with it set the function returned
    the same ordinary `IntelligenceEnvelope` a fully verified import returned. The fact
    that a verification had not happened disappeared at the API boundary: a caller who
    passed the flag -- or a helper three layers down that passed it on their behalf --
    held an object indistinguishable from one checked end to end. Absence of a
    verification silently upgraded into presence, which is the defect this package refuses
    everywhere else, wearing a keyword argument.

    The flag also conflated two independent trust conditions. "I cannot replay this model"
    and "I do not have this policy's thresholds" are different facts about different parts
    of the record, and one boolean could not say which -- so a reader who accepted an
    unreplayable model also, silently, accepted an unreproducible policy.

    A reader who needs to READ such a record calls `import_historical_envelope`, which
    returns the verification report beside the envelope. The unverifiable basis stays
    visible instead of being laundered into a verified one.

    WHY RECONSTRUCTION RATHER THAN VALIDATION
    -----------------------------------------
    `validate_envelope_payload` checked five things -- schema version, the attributed-
    effect vocabulary, lifecycle transition order, lifecycle chronology, and whether an
    outcome matched an outcome state. It never touched the candidate, the claim, the
    decision context, the consequence, the action, the assurance assertions, the
    entitlement scope, the rendered digest or the product's validity semantics. So a
    payload could be schema-shaped, pass validation, and assert a claim whose knowledge
    cutoff postdated its decision -- the precise thing the in-memory types make impossible.

    The alternative to this function was a hand-written wire validator restating each of
    those rules. That is a second semantics engine, and two engines drift: the day they
    disagree is the day the portable form stops meaning what the in-memory form means.
    Rebuilding the objects runs the domain's own `__post_init__` invariants, so there is
    one set of rules and the wire cannot be more permissive than the memory.

    Structural checks first, so a payload asserting a forbidden causal claim is refused on
    that ground rather than on some incidental parse error further down.
    """
    envelope, report = _reconstruct(payload)
    blocked = report.unverifiable()
    if blocked:
        raise UnverifiableBasis(
            "strict import cannot verify this record: "
            + "; ".join(d.describe() for d in blocked)
            + ". Read it with import_historical_envelope(), which returns the "
            "verification report beside the envelope; absence of a verification is not "
            "a verification"
        )
    return envelope


def _reconstruct(
    payload: dict[str, Any],
) -> tuple["IntelligenceEnvelope", VerificationReport]:
    """The one implementation both public entry points run.

    Strict import is this plus "no dimension may be UNVERIFIABLE". Written that way on
    purpose: two implementations would let the strict path drift into being the weaker of
    the pair, which is the failure the flag it replaced actually produced.
    """
    validate_envelope_payload(payload)
    validate_against_schema(payload)

    from .action import OutcomeObservation
    from .product import IntelligenceProduct

    product, findings = IntelligenceProduct.from_record_with_findings(payload["product"])
    outcome = payload.get("outcome")
    envelope = IntelligenceEnvelope(
        product=product,
        # Typed on the way in, so `IntelligenceEnvelope.__post_init__` runs the trail
        # rules, the outcome bindings and the status-event coherence over the imported
        # objects -- the same code that runs in memory, rather than a wire validator that
        # restates a subset of it and drifts.
        lifecycle_events=tuple(
            DispositionEvent.from_record(e) for e in payload.get("lifecycle_events") or ()
        ),
        outcome=OutcomeObservation.from_record(outcome) if outcome else None,
        # No default. `validate_envelope_payload` has already refused a payload with no
        # `attributed_effect`, so a fallback here could never be used -- and a fallback
        # that silently supplies the one permitted value would be absence upgraded into
        # presence, on the field that exists to refuse exactly that.
        attributed_effect=AttributedEffect(payload["attributed_effect"]),
        status_events=tuple(
            StatusEvent.from_record(e) for e in payload.get("status_events") or ()
        ),
    )
    _verify_nothing_was_dropped_or_invented(payload, envelope)
    # The two dimensions the envelope layer owns. `IntelligenceEnvelope.__post_init__`
    # ran `check_trail`, the outcome bindings and the status-event coherence during
    # construction above, and `validate_against_schema` plus the round-trip comparison
    # settle structural conformance -- so reaching this line IS the verification.
    report = VerificationReport(dimensions=tuple(findings) + (
        verified(VerificationDimension.STRUCTURAL_CONFORMANCE),
        verified(VerificationDimension.LIFECYCLE),
    ))
    return envelope, report


def _verify_nothing_was_dropped_or_invented(
    payload: dict[str, Any], envelope: "IntelligenceEnvelope"
) -> None:
    """The bundle must import as exactly the record it arrived as.

    WHY A BLANKET CHECK AND NOT ONLY THE FIELD-BY-FIELD ONES
    -------------------------------------------------------
    Every derived value on the wire is re-derived and compared -- but each comparison was
    written `if <key> in r and ...`, so the protection was bypassable by DELETING the field
    rather than contradicting it. And reconstruction ignores keys it does not know, so a
    payload could carry extra properties, import cleanly, and re-export without them.

    Both are the same failure: the record that arrives and the record that is understood
    are not the same record, and nobody is told. One comparison closes the whole class,
    including the cases nobody thought to enumerate -- which is the point, since the
    field-by-field list is exactly the kind of thing that goes stale when a field is added.

    The field-by-field checks stay: they say WHICH value disagrees, which a reader chasing
    a rejected bundle needs. This one says that something did.
    """
    # CANONICAL FORMS, not raw bytes -- and the docstring above used to say bytes, which
    # is not what this does. The canonicalizer folds an integral float to an int, so a
    # payload carrying `259200.0` imports and re-exports as `259200`. That is inert here
    # and it is still a difference between what arrived and what is understood, so it is
    # stated rather than glossed.
    reserialized = envelope.as_record()
    if canonicalize(reserialized) != canonicalize(payload):
        dropped = sorted(set(payload) - set(reserialized))
        invented = sorted(set(reserialized) - set(payload))
        detail = ""
        if dropped or invented:
            detail = f" (payload-only keys: {dropped}; reconstruction-only: {invented})"
        raise ValueError(
            "the payload does not survive reconstruction unchanged; a bundle that imports "
            "as something other than the bytes it arrived as has been silently rewritten"
            + detail
        )


def validate_envelope_payload(payload: dict[str, Any]) -> None:
    """The three refusals that must happen BEFORE anything else runs.

    A payload written against a schema version we do not understand, canonicalised by an
    algorithm we cannot reproduce, or asserting a causal claim this design refuses to
    express, should be refused on that ground rather than on whatever incidental error
    comes first.

    THE CANONICALIZATION CHECK MOVED HERE, AND THE MOVE IS THE POINT.
    It sat below `validate_against_schema`, which declares `canonicalization` as a `const`
    -- so the schema refused an unfamiliar algorithm first and this guard could not fire.
    `guard_sweep.py` found it: the raise was removable with the suite green.

    Deleting it would have been wrong. Which algorithm produced the canonical bytes is a
    semantic fact about whether a reader can recompute the digest at all, and reporting it
    as one violation among a list of schema errors buries the one thing that makes the
    rest of the bundle uncheckable. Above the schema it fires first, with its own message,
    and is reachable again.

    WHAT THIS DELIBERATELY NO LONGER DOES
    -------------------------------------
    It used to re-implement the lifecycle rules over raw dictionaries: first state,
    permitted transitions, chronology, outcome-reached-the-end. That was a second
    semantics engine reading a second representation, and it drifted exactly as predicted
    -- it never checked the actor, never checked a timezone, and could not check the
    outcome's binding to the action because the outcome was a dict. Those rules now run
    once, over the typed objects, in `IntelligenceEnvelope.__post_init__` and
    `lifecycle.check_trail`.
    """
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"{payload.get('schema_version')!r} is not {SCHEMA_VERSION!r}"
        )

    effect = payload.get("attributed_effect")
    try:
        AttributedEffect(effect)
    except ValueError as exc:
        raise UnsupportedAttributedEffect(
            f"{effect!r} is not an attributed effect this system can express. Outcome "
            f"capture records what was observed, never what was caused."
        ) from exc

    # AFTER the attributed-effect refusal, deliberately. A payload asserting a causal
    # claim this design refuses to express should be refused on THAT ground -- it is the
    # one refusal in this package that is about what the system will not say, rather than
    # about whether it can read the bytes.
    canonicalization = payload.get("canonicalization")
    if canonicalization != CANONICALIZATION:
        raise ValueError(
            f"canonicalization {canonicalization!r} is not {CANONICALIZATION!r}; "
            f"canonical bytes are only reproducible against a named algorithm, and an "
            f"importer accepting an unfamiliar one has agreed to a digest it cannot "
            f"recompute"
        )


class MalformedEnvelopeText(ValueError):
    """The bytes are not a JSON document this contract can have one reading of.

    Distinct from `SchemaViolation`, which is about a structure that parsed cleanly and
    then failed to conform. This is about text whose MEANING is not determined: two
    parsers would build two different structures from it, and every guarantee downstream
    is a guarantee about whichever one happened to be built.
    """


def _parse_envelope_payload(text: str) -> dict[str, Any]:
    """Parse envelope JSON into the one structure this contract says it denotes.

    PRIVATE, on a Control Tower ruling, and the reasoning is worth keeping.

    This was public, so that a reader of a HISTORICAL record could parse under these
    rules rather than falling back to `json.loads`. That solved a real problem the wrong
    way: it put a function returning an UNVALIDATED dictionary on the public surface, and
    a caller could stop there -- taking the duplicate-key safety and skipping the domain
    reconstruction entirely. §6 authorised a narrow parser to close one defect, not a
    general payload API.

    The need was real; the shape was wrong. `parse_envelope` and
    `parse_historical_envelope` are the two supported text entry points, and both come
    through here, so neither can reopen the hole and neither hands anyone a raw dict.

    THE DEFECT
    ----------
    `import_envelope` receives an already-parsed dict, so the parse happened somewhere
    else, under rules nobody stated. JSON does not define what a duplicate object key
    means: `json.loads` keeps the last, some parsers keep the first, some collect both,
    some error. So ONE textual artifact could produce different semantic records
    depending on who read it -- and by the time the importer sees a dict, the duplicate is
    gone and every check downstream verifies whichever reading arrived.

    That is a hole in the central proposition. "The decision survives the platform that
    produced it" cannot be true of an artifact whose meaning depends on the reader's JSON
    library, and no amount of domain checking closes it, because the domain never sees the
    ambiguity.

    WHAT THIS REFUSES
    -----------------
    Duplicate object keys, at every nesting level, detected BEFORE dictionary construction
    destroys the evidence. `object_pairs_hook` receives the pairs in document order, which
    is the only point at which "this key appeared twice" is still a fact.

    Non-standard numeric literals. `NaN`, `Infinity` and `-Infinity` are Python
    extensions, not JSON, and the canonicalizer refuses them anyway -- so accepting them
    here would parse a document that cannot be re-serialized. Float literals are refused
    outright: this contract carries no raw floats. Every decimal travels as a string with
    explicit precision, precisely so two implementations cannot format one value two ways,
    and a float literal on the wire is either a mistake or an attempt to exploit that.

    WHAT IT IS NOT
    --------------
    Not a second interpretation of the domain. This function decides what structure the
    bytes denote and stops; `parse_envelope` hands that structure to the same import path
    every other caller uses. Exposed separately from `parse_envelope` only so a reader of
    a HISTORICAL record can parse under these rules too -- without it they would have to
    call `json.loads` themselves and the duplicate-key hole would reopen for exactly the
    records least able to defend themselves.
    """
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise MalformedEnvelopeText(
                    f"the object key {key!r} appears more than once; JSON does not define "
                    f"which value wins, so this text denotes different records to "
                    f"different parsers and no downstream check can tell which one it "
                    f"verified"
                )
            seen.add(key)
        return dict(pairs)

    def no_float_literals(literal: str) -> float:
        raise MalformedEnvelopeText(
            f"the numeric literal {literal!r} is a float; every decimal in this contract "
            f"travels as a string carrying its own precision, so that two implementations "
            f"cannot format one value two ways and produce two valid-looking digests"
        )

    def no_extended_constants(literal: str) -> float:
        raise MalformedEnvelopeText(
            f"{literal!r} is a Python extension to JSON, not JSON; the canonicalizer has "
            f"no form for it, so a document containing one could not be re-serialized as "
            f"the record it arrived as"
        )

    try:
        payload = json.loads(
            text,
            object_pairs_hook=no_duplicate_keys,
            parse_float=no_float_literals,
            parse_constant=no_extended_constants,
        )
    except json.JSONDecodeError as exc:
        raise MalformedEnvelopeText(f"not parseable as JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MalformedEnvelopeText(
            f"an envelope is a JSON object; this text denotes a "
            f"{type(payload).__name__}"
        )
    return payload


def parse_envelope(text: str) -> "IntelligenceEnvelope":
    """Read envelope JSON text and return the STRICTLY imported envelope.

    Parses under the rules above and hands the result to `import_envelope`. There is no
    second interpretation of the domain here, and this is deliberately not the beginning
    of an SDK.
    """
    return import_envelope(_parse_envelope_payload(text))


def parse_historical_envelope(text: str) -> HistoricalEnvelopeImport:
    """Read envelope JSON text as history, with the verification report beside it.

    The text-mode twin of `import_historical_envelope`, and the reason the parser is a
    shared private function rather than a public one: a reader of a record this build
    cannot fully check needs the SAME duplicate-key safety a strict reader gets. Without
    this entry point they would reach for `json.loads`, and one textual artifact would
    denote different records to different readers -- for exactly the records least able to
    defend themselves.
    """
    return import_historical_envelope(_parse_envelope_payload(text))


class SchemaViolation(ValueError):
    """The payload does not conform to the published schema.

    A `ValueError` for the same reason `IllegalTransition` is: every refusal at this
    boundary is one, and a caller wrapping the import in `except ValueError` must not let
    a malformed payload through while catching everything else.
    """


def validate_against_schema(payload: dict[str, Any]) -> None:
    """Validate the wire structure against the schema this package publishes.

    WHY THIS HAD TO EXIST
    ---------------------
    The project published a Draft 2020-12 JSON Schema and called it normative, and the
    importer never validated anything against it. So there were two descriptions of the
    accepted universe -- the schema an implementer in another language builds against, and
    the Python reconstruction that actually decides -- with nothing keeping them in
    agreement. Every gap between them is a bundle a conforming implementation produces
    that this system refuses, or worse, accepts.

    Calling the schema normative while not running it is the same defect this repository
    keeps finding in its own evidence: a claim about a mechanism that is not the mechanism.

    THE DIVISION OF LABOUR, WHICH IS NOT DUPLICATION
    ------------------------------------------------
    The schema is the STRUCTURAL validator: which keys exist, which are required, what
    shape their values take, which enumerations are closed, and -- through `if`/`then` --
    the two conditional shapes JSON Schema can express.

    The typed domain is the SEMANTIC validator: knowledge cutoff no later than decision
    time, a digest matching the readings it attests, a claim replaying to the score on
    file, an entitlement authorising the delivery beside it. None of those can be written
    in JSON Schema, and none of them is restated here.

    Two responsibilities, one implementation each. That is the opposite of the second
    semantics engine `validate_envelope_payload` used to be.

    `Draft202012Validator` is named explicitly rather than inferred from `$schema`,
    because inference silently falls back to "the latest draft" when the metaschema is not
    resolvable -- and a validator that quietly validates against a different specification
    than the one the document names is a worse failure than no validator.
    """
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(
        json_schema(),
        # date-time is checked rather than merely declared. Without a format checker a
        # `format` keyword is annotation only, so "delivery_time": "yesterday" would
        # conform -- a schema describing a constraint it does not apply.
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    # Every violation, not the first. A producer fixing one and rediscovering the next on
    # the following run wastes a cycle each time -- the reason `blocking_reasons` returns
    # all of them too.
    detail = "; ".join(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors[:10]
    )
    more = f" (and {len(errors) - 10} further violations)" if len(errors) > 10 else ""
    raise SchemaViolation(
        f"the payload does not conform to {SCHEMA_URI}: {detail}{more}"
    )


def json_schema() -> dict[str, Any]:
    """The language-neutral contract, written to be NORMATIVE rather than descriptive.

    Published so the definition is not "whatever these Python dataclasses and json.dumps()
    happen to mean". A reader implementing in another language builds against this file,
    and every gap in it is a bundle they will produce that this system refuses -- or worse,
    accepts.

    WHAT WAS WRONG WITH IT
    ----------------------
    Two rounds of fixes, and the second one is the interesting one.

    First, `candidate` and `assurance` were bare `{"type": "object"}`: the two structures
    carrying the entire claim were the two the contract declined to describe. Those were
    spelled out, and the test guarding it looked for exactly that shape.

    What the test could not see -- and what was still true afterwards -- is that the
    product's `required` set named five things and omitted four the in-memory type refuses
    to exist without: the evidence, the recipient, and the purpose and tenant the delivery
    was authorised under. Several object layers were also left open to unspecified extra
    properties. So a conforming implementation could ship a bundle with no evidence at all,
    and be told it conformed. Absence was silently permitted, which is the same defect this
    package refuses everywhere else, expressed in JSON.

    Now: every structurally mandatory field is required, `additionalProperties` is a
    decision written down on every object rather than an omission, and the two conditional
    shapes JSON Schema CAN express -- DELIVERED needs a delivery time and a rendered
    artifact, ABSTAINED needs a reason -- are expressed with `if`/`then` instead of being
    filed under what the schema cannot say.

    THE BOUNDARY IS STILL REAL AND STILL STATED
    -------------------------------------------
    Genuinely cross-field semantics -- knowledge cutoff no later than decision time, a
    digest matching the text it attests, a claim replaying to the score on file -- cannot
    be written in JSON Schema and are enforced on import by reconstructing the typed
    domain. `x-semantic-validations` names them, so an implementer reading only this file
    learns what they still owe rather than validating structurally and believing they are
    done.
    """
    timestamp = {"type": "string", "format": "date-time"}
    nullable_timestamp = {"type": ["string", "null"], "format": "date-time"}
    decimal_string = {
        "type": "string",
        "pattern": r"^-?\d+\.\d{6}$",
        "description": (
            "Floats cross as fixed six-decimal strings. The canonicalizer refuses "
            "non-integer floats rather than risk two implementations formatting the "
            "same value differently and producing two valid-looking digests."
        ),
    }
    unit_decimal = {
        "type": "string",
        "pattern": r"^(0\.\d{6}|1\.000000)$",
        "description": (
            "A confidence in [0, 1], in the same fixed six-decimal wire form as every "
            "other float. The range is part of the type: `IdentityAssertion` and "
            "`PredictionClaim` both refuse a value outside it, and a schema that "
            "accepted 9.000000 would call a bundle conforming that the domain refuses."
        ),
    }
    sha256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    nonempty = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": {"type": "string"}}

    model_envelope = {
        "type": "object",
        "description": (
            "What the model that produced this claim declares itself valid for. "
            "`ApplicabilityAssertion.subject_type` asserts a use falls inside this; until "
            "the claim carried one, that assertion was compared against nothing."
        ),
        "required": [
            "model_version", "model_artifact_digest", "supported_applicability",
            "min_observations", "max_horizon_seconds",
        ],
        "additionalProperties": False,
        "properties": {
            "model_version": nonempty,
            "model_artifact_digest": sha256,
            # PAIRS, replacing two independent lists. Independent sets are a
            # cross-product: a metric valid somewhere and a subject type valid somewhere
            # read as valid together, and this model is fitted for two of the four
            # combinations its old declaration admitted.
            #
            # `supported_metrics` and `supported_subject_types` are not on the wire at
            # all. They are derived views of these pairs, and a derived value on the wire
            # is a second authority for no information a reader cannot compute.
            "supported_applicability": {
                "type": "array",
                "minItems": 1,
                # `ModelEnvelope` refuses a repeated pair -- declaring the same
                # combination twice bounds nothing further -- and `uniqueItems` says
                # exactly that. Structural, and it was missing.
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "required": ["metric", "subject_type"],
                    "additionalProperties": False,
                    "properties": {
                        "metric": nonempty,
                        "subject_type": nonempty,
                    },
                },
            },
            "min_observations": {"type": "integer", "exclusiveMinimum": 0},
            "max_horizon_seconds": {"type": "integer", "exclusiveMinimum": 0},
        },
    }

    derivation_step = {
        "type": "object",
        "required": [
            "relationship", "subject", "object", "recorded_at", "source_system",
            # Nullable, and always PRESENT: a step that is not time-scoped says so with a
            # null rather than by omitting the key, so a reader can tell "not scoped" from
            # "the producer did not tell me".
            "valid_from", "valid_to",
        ],
        "additionalProperties": False,
        "properties": {
            # CLOSED. It was `nonempty`, so a payload could relabel the relations of an
            # otherwise real, fully connected walk and produce a derivation that means
            # nothing while satisfying every structural rule. v1 walks five relations;
            # `DerivationRelationship` is the vocabulary and this is it on the wire.
            "relationship": {
                "enum": [r.value for r in DerivationRelationship],
                "description": (
                    "Which relation may follow which is a semantic rule "
                    "`ConsequenceDerivation` enforces; the schema closes the vocabulary."
                ),
            },
            "subject": nonempty,
            "object": nonempty,
            "recorded_at": timestamp,
            "source_system": nonempty,
            "valid_from": nullable_timestamp,
            "valid_to": nullable_timestamp,
        },
    }

    derivation = {
        "type": "object",
        "description": (
            "The REASON path. The walk produced this and the consequence was built from "
            "its answer, so the portable product carried the conclusion and not why the "
            "connected facts justify it. The governing contract requires both."
        ),
        "required": [
            "rule_version", "knowledge_cutoff", "evaluated_window_start",
            "evaluated_window_end", "steps",
        ],
        "additionalProperties": False,
        "properties": {
            "rule_version": nonempty,
            "knowledge_cutoff": timestamp,
            "evaluated_window_start": timestamp,
            "evaluated_window_end": timestamp,
            "steps": {"type": "array", "items": derivation_step, "minItems": 1},
        },
    }

    commitment_detail = {
        "type": "object",
        "title": "CUSTOMER_COMMITMENT detail",
        "required": ["commitment_id", "commitment_description", "counterparty"],
        "additionalProperties": False,
        "properties": {
            "commitment_id": nonempty,
            "commitment_description": {"type": "string"},
            "counterparty": {"type": "string"},
        },
    }

    downtime_detail = {
        "type": "object",
        "title": "DOWNTIME detail",
        "required": ["asset_id", "expected_hours_lost", "affected_operation"],
        "additionalProperties": False,
        "properties": {
            "asset_id": nonempty,
            "expected_hours_lost": {"type": "string", "pattern": r"^\d+\.\d{2}$"},
            "affected_operation": {"type": "string"},
        },
    }

    observation = {
        "type": "object",
        "description": (
            "One reading, carried in full rather than cited. The snapshot's "
            "observation_ids are pointers; a reader holding only pointers can check that "
            "the record agrees with itself and nothing else. These are what the release "
            "assessment ran over, so an importer can run it again."
        ),
        "required": [
            "observation_id", "subject", "metric", "value", "valid_time",
            "transaction_time", "source_system", "supersedes",
        ],
        "additionalProperties": False,
        "properties": {
            "observation_id": nonempty,
            "subject": nonempty,
            "metric": nonempty,
            "value": decimal_string,
            "valid_time": timestamp,
            "transaction_time": timestamp,
            "source_system": nonempty,
            "supersedes": {"type": ["string", "null"]},
        },
    }

    release_evidence = {
        "type": "object",
        "description": (
            "The evidence bundle the release assessment consumed: the point-in-time view "
            "AND the same-id/different-payload contradictions found in it. Both travel, "
            "because a contradiction a producer can decline to mention is a withholding "
            "that never happens."
        ),
        "required": ["observations", "integrity_conflicts"],
        "additionalProperties": False,
        "properties": {
            "observations": {"type": "array", "items": observation},
            "integrity_conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kept", "rejected"],
                    "additionalProperties": False,
                    "properties": {"kept": observation, "rejected": observation},
                },
            },
        },
    }

    prediction_inputs = {
        "type": ["object", "null"],
        "required": [
            "metric", "values", "horizon_seconds", "model_version", "input_fingerprint",
            "bound_inputs",
        ],
        "additionalProperties": False,
        "properties": {
            "metric": nonempty,
            "horizon_seconds": {"type": "integer", "exclusiveMinimum": 0},
            "model_version": nonempty,
            "input_fingerprint": sha256,
            "values": {"type": "array", "items": decimal_string, "minItems": 1},
            "bound_inputs": {
                "type": "array",
                # `PredictionInputs` refuses an empty tuple outright -- values with no
                # bound observations are an assertion about numbers nobody can trace --
                # and the schema said `[]` was fine. A rule this simple sitting only in
                # the typed domain is what makes "normative" an overstatement.
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["observation_id", "content_digest", "value_used"],
                    "additionalProperties": False,
                    "properties": {
                        "observation_id": nonempty,
                        "content_digest": sha256,
                        "value_used": decimal_string,
                    },
                },
            },
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URI,
        "title": "Intelligence Envelope",
        "x-semantic-validations": {
            "description": (
                "Cross-field invariants this schema cannot express. An implementation "
                "that validates against the structure above and stops has NOT enforced "
                "the contract. The reference importer enforces these by reconstructing "
                "the typed domain, so the rules exist once rather than twice."
            ),
            "rules": [
                "knowledge_cutoff <= model_decision_time",
                "prediction_window_end > prediction_window_start, strictly: a zero-length "
                "interval is an instant, not a window",
                "all timestamps are timezone-aware",
                "the claim's horizon equals the prediction window's duration, not a "
                "separate value free to disagree with it",
                "business_consequence.exposure_window overlaps the prediction window",
                "action.operational_window overlaps the consequence's exposure window",
                "action.due_by falls no later than its operational window closes",
                "the claim's metric and horizon fall inside its own declared_envelope, and "
                "the envelope describes the model and build the claim came from",
                "the claim replays: re-running the recorded predictor over the recorded "
                "inputs reproduces score, score_semantics, evidence_strength, metric, "
                "horizon, model version, artifact digest and input fingerprint",
                "input_fingerprint is the fingerprint OF the recorded inputs, recomputable "
                "without the model",
                "the consequence's derivation terminates at the consequence's own subject, "
                "is rooted where its type requires, continues only along relations that "
                "may follow one another, and reaches every entity it names",
                "every derivation step was recorded by the knowledge cutoff; a walk cannot "
                "use a fact the decision-maker had not received",
                "the walk carries at most one step per relationship. ContextGraph refuses "
                "outright when the facts admit two -- two zones at horizon start, two "
                "loading windows overlapping the horizon -- so a walk with a second "
                "branch is one no supported producer emitted",
                "a CUSTOMER_COMMITMENT walk carries ASSIGNED_TO, SUPPORTS, LOADS and "
                "FULFILLS. HAS_COMPONENT is optional: derive_impact emits it only when a "
                "component was named, so requiring it would refuse an honest record",
                "a step's validity interval is in force when the loading window opens AND "
                "when the evaluated window opens, which is the pair of moments the graph "
                "rechecks; an unscoped relation carries no interval at all",
                "the derivation's cutoff and window are the decision context's",
                "determination=DELIVERED requires assurance.permitted=true and a "
                "rendered_delivery whose rendered_at equals delivery_time",
                "determination=ABSTAINED requires at least one blocking reason",
                "assurance.permitted=true requires an empty blocking_reasons AND an "
                "evidence assessment that releases",
                "re-running the named release policy over the recorded assurance basis "
                "reproduces permitted and blocking_reasons exactly",
                "evidence.captured_at does not postdate delivery_time",
                "valid_until, when present, postdates delivery_time and does not outlive "
                "the prediction window it describes",
                "model_decision_time <= release_decision_time for every determination, "
                "delivered or abstained. They are different domain events -- one bounds "
                "the evidence, the other selects the rules -- so equality is not required "
                "and the ordering is",
                "no product is actionable after action.due_by: the action is due no "
                "earlier than the model decided, delivery falls strictly before the "
                "deadline, and valid_until falls at or before it. A gate that runs late "
                "must not hand an operator an instruction that has already expired",
                "an ABSTAINED product carries no lifecycle events, no outcome and no "
                "status events. A candidate that was withheld was never delivered, "
                "acknowledged, acted on, observed, retracted or superseded",
                "the trail's opening event is timestamped exactly delivery_time. One "
                "delivery is one event, and a trail opening later gives a reader two "
                "answers about when the operator received it",
                "observation ids are unique within the bundle",
                "an integrity conflict names two readings sharing an observation id whose "
                "content genuinely differs, and the kept reading is the one the bundle "
                "carries",
                "rendered_delivery.content_digest verifies against renderer_version, "
                "locale, rendered_text, card and rendered_at",
                "entitlement scope is re-checked against the product's own recipient, "
                "purpose, tenant, subject and evidence source systems -- never against "
                "the assertion's own fields",
                "derived values on the wire (action.rendered_text, "
                "consequence.description/actionable, evidence assessment "
                "release/blocking_reasons, product.release_policy_version, "
                "product.abstention_reason, outcome.description) are re-derived and must "
                "EQUAL what they were derived from; a disagreement is refused, not "
                "normalised",
                "lifecycle events open at DELIVERED, follow permitted transitions, run "
                "chronologically, and do not predate delivery",
                "outcome.subject is the claim's subject and "
                "outcome.related_action_id is the candidate's action",
                "status events are chronological, postdate delivery, contain at most one "
                "retraction, and no supersession names the product itself",
                "attributed_effect is NOT_ESTABLISHED; outcome capture never implies "
                "causation",
            ],
        },
        "type": "object",
        "required": [
            # `schema_uri` was optional here and unconditional in `as_record`, so the
            # schema described a universe the producer could not emit. A required key the
            # producer always writes is the honest description of what travels.
            "schema_version", "schema_uri", "canonicalization", "product",
            "lifecycle_events", "outcome", "attributed_effect", "status_events",
        ],
        "additionalProperties": False,
        # NOTHING FOLLOWS A WITHHELD PRODUCT, AND A TRAIL OPENS WHERE THE DELIVERY DID.
        #
        # These three collections are histories of a delivery, and for an abstention there
        # is no delivery for them to be a history of. The typed envelope refuses all three;
        # the schema described them as freely populated whatever the determination said,
        # so an implementer in another language could publish a withheld candidate with a
        # full disposition trail, an outcome and a retraction, and be told it conformed.
        #
        # Expressible here because it is a conditional over sibling keys of one object.
        # What is NOT expressible is the equality that goes with it -- the opening event's
        # `at` must equal `product.delivery_time`, two values in different subtrees, which
        # JSON Schema has no vocabulary for. That one stays in x-semantic-validations,
        # which is the honest place for it rather than an omission.
        "allOf": [
            {
                "if": {
                    "properties": {
                        "product": {
                            "properties": {
                                "determination": {"const": "ABSTAINED"},
                            },
                            "required": ["determination"],
                        },
                    },
                    "required": ["product"],
                },
                "then": {
                    "properties": {
                        "lifecycle_events": {"maxItems": 0},
                        "status_events": {"maxItems": 0},
                        "outcome": {"type": "null"},
                    },
                },
            },
            {
                "if": {
                    "properties": {
                        "lifecycle_events": {"minItems": 1},
                    },
                    "required": ["lifecycle_events"],
                },
                "then": {
                    "properties": {
                        "lifecycle_events": {
                            # The first thing that happens to a delivered product is that
                            # it is delivered. `check_trail` says so in memory; this is the
                            # structural half of the same rule.
                            "prefixItems": [
                                {"properties": {"state": {"const": "DELIVERED"}}},
                            ],
                        },
                    },
                },
            },
        ],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            # `{"type": "string"}` let a payload point readers at somebody else's contract
            # while claiming this one's version. The URI identifies the document these
            # rules live in; it is not a free field.
            "schema_uri": {"const": SCHEMA_URI},
            "canonicalization": {"const": CANONICALIZATION},
            "attributed_effect": {
                "description": (
                    "Single-valued by design. Outcome capture records what was observed, "
                    "never what was caused."
                ),
                "enum": [AttributedEffect.NOT_ESTABLISHED.value],
            },
            "product": {
                "type": "object",
                "required": [
                    "product_id", "claim_series_id", "determination", "candidate",
                    "assurance", "evidence", "release_evidence", "recipient", "purpose",
                    "tenant", "delivery_time", "valid_until", "supersedes_product_id",
                    "rendered_delivery", "release_policy_version", "abstention_reason",
                ],
                "additionalProperties": False,
                # The two conditional shapes JSON Schema can express. Leaving them to prose
                # meant a conforming implementation could publish a DELIVERED product with
                # no delivery time and no record of what the recipient saw.
                "allOf": [
                    {
                        "if": {"properties": {"determination": {"const": "DELIVERED"}}},
                        "then": {
                            "properties": {
                                "delivery_time": timestamp,
                                # A DELIVERED PRODUCT HAS A VALIDITY HORIZON.
                                # `IntelligenceProduct.__post_init__` refuses one without:
                                # "a delivered claim with no validity horizon never
                                # expires; perishability cannot be expressed by leaving it
                                # out". The schema left it nullable in both arms, so the
                                # published contract admitted the exact record the domain
                                # was changed to refuse.
                                "valid_until": timestamp,
                                # Not `{"type": "object"}`: a bare object is exactly the
                                # unconstrained shape this schema was criticised for. The
                                # rendered artifact's structure is specified once, below;
                                # here the conditional says only that it must be present.
                                "rendered_delivery": {"not": {"type": "null"}},
                                "abstention_reason": {"type": "null"},
                            },
                        },
                    },
                    {
                        "if": {"properties": {"determination": {"const": "ABSTAINED"}}},
                        "then": {
                            "properties": {
                                "abstention_reason": nonempty,
                                "rendered_delivery": {"type": "null"},
                                "delivery_time": {"type": "null"},
                                "assurance": {
                                    "properties": {
                                        "permitted": {"const": False},
                                        "blocking_reasons": {"minItems": 1},
                                    },
                                },
                            },
                            "required": ["abstention_reason"],
                        },
                    },
                    # THE DECISION AND ITS REASONS, IN BOTH DIRECTIONS.
                    #
                    # `AssuranceDecision.__post_init__` refuses a permitted decision
                    # carrying blocking reasons and an unpermitted one carrying none. Only
                    # half of the second was on the wire, and only inside the ABSTAINED
                    # arm -- so a DELIVERED product could carry permitted=true beside a
                    # populated reason list and conform. The two facts are the decision
                    # and its justification, and a record where they disagree is one no
                    # policy evaluation produced.
                    {
                        "if": {
                            "properties": {
                                "assurance": {
                                    "properties": {"permitted": {"const": True}},
                                    "required": ["permitted"],
                                },
                            },
                            "required": ["assurance"],
                        },
                        "then": {
                            "properties": {
                                "assurance": {
                                    "properties": {"blocking_reasons": {"maxItems": 0}},
                                },
                            },
                        },
                    },
                    {
                        "if": {
                            "properties": {
                                "assurance": {
                                    "properties": {"permitted": {"const": False}},
                                    "required": ["permitted"],
                                },
                            },
                            "required": ["assurance"],
                        },
                        "then": {
                            "properties": {
                                "assurance": {
                                    "properties": {"blocking_reasons": {"minItems": 1}},
                                },
                            },
                        },
                    },
                ],
                "properties": {
                    "product_id": nonempty,
                    "claim_series_id": nonempty,
                    "supersedes_product_id": {"type": ["string", "null"]},
                    "determination": {"enum": ["DELIVERED", "ABSTAINED"]},
                    # NONEMPTY, all three, for delivered and abstained alike. These are
                    # the scope the entitlement is re-checked against, and `permits()`
                    # compares purpose and tenant with `!=` -- so a blank on both sides
                    # satisfied two of the six scope dimensions by matching emptiness.
                    # `EntitlementAssertion` already refuses a blank purpose or tenant on
                    # its own side; the delivery's copy was the half left open.
                    "recipient": nonempty,
                    "purpose": {
                        **nonempty,
                        "description": (
                            "What this delivery was FOR, as opposed to what the clearance "
                            "covers. Absent from the record until this revision, so an "
                            "importer could only check the entitlement against itself."
                        ),
                    },
                    "tenant": nonempty,
                    "delivery_time": nullable_timestamp,
                    "valid_until": nullable_timestamp,
                    "release_policy_version": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Derived from the assurance decision. Re-derived on import and "
                            "compared; a disagreement is refused rather than normalised."
                        ),
                    },
                    "abstention_reason": {"type": ["string", "null"]},
                    "candidate": {
                        "type": "object",
                        "required": [
                            "candidate_id", "context", "prediction_claim",
                            "business_consequence", "action",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "candidate_id": nonempty,
                            "context": {
                                "type": "object",
                                "required": [
                                    "model_decision_time", "knowledge_cutoff",
                                    "evaluation_time", "prediction_window_start",
                                    "prediction_window_end",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "model_decision_time": timestamp,
                                    "knowledge_cutoff": timestamp,
                                    "evaluation_time": timestamp,
                                    "prediction_window_start": timestamp,
                                    "prediction_window_end": timestamp,
                                },
                            },
                            "prediction_claim": {
                                "type": "object",
                                "required": [
                                    "subject", "metric", "score", "score_semantics",
                                    "horizon_seconds", "evidence_strength",
                                    "model_version", "model_artifact_digest",
                                    "input_fingerprint", "declared_envelope",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "subject": nonempty,
                                    "metric": nonempty,
                                    "score": decimal_string,
                                    "score_semantics": nonempty,
                                    "horizon_seconds": {
                                        "type": "integer", "exclusiveMinimum": 0,
                                    },
                                    "evidence_strength": unit_decimal,
                                    "model_version": nonempty,
                                    "model_artifact_digest": sha256,
                                    "input_fingerprint": sha256,
                                    "declared_envelope": model_envelope,
                                },
                            },
                            "business_consequence": {
                                "type": "object",
                                "required": [
                                    "consequence_type", "exposure_window_start",
                                    "exposure_window_end", "actionable", "detail",
                                    "description", "derivation",
                                ],
                                "additionalProperties": False,
                                # THE DETAIL IS BOUND TO THE TYPE, which `oneOf` alone did
                                # not do. `oneOf` said the detail must be one of the two
                                # shapes; it said nothing about WHICH, so a
                                # CUSTOMER_COMMITMENT carrying a DOWNTIME detail -- an
                                # asset id and expected hours lost where a commitment
                                # should be -- conformed to the published contract. The
                                # typed domain refuses it (`from_record` dispatches on the
                                # type and reads the keys that type needs), so the schema
                                # and the importer described different universes on the one
                                # field whose whole purpose is polymorphism.
                                "allOf": [
                                    {
                                        "if": {
                                            "properties": {
                                                "consequence_type": {
                                                    "const": "CUSTOMER_COMMITMENT",
                                                },
                                            },
                                            "required": ["consequence_type"],
                                        },
                                        "then": {
                                            "properties": {
                                                "detail": commitment_detail,
                                            },
                                        },
                                    },
                                    {
                                        "if": {
                                            "properties": {
                                                "consequence_type": {"const": "DOWNTIME"},
                                            },
                                            "required": ["consequence_type"],
                                        },
                                        "then": {
                                            "properties": {"detail": downtime_detail},
                                        },
                                    },
                                ],
                                "properties": {
                                    "consequence_type": {
                                        "enum": ["CUSTOMER_COMMITMENT", "DOWNTIME"],
                                        "description": (
                                            "v1 implements exactly two. The abstraction "
                                            "is extensible; the vocabulary is not open."
                                        ),
                                    },
                                    "exposure_window_start": timestamp,
                                    "exposure_window_end": timestamp,
                                    "description": {"type": "string"},
                                    "actionable": {"type": "boolean"},
                                    "derivation": derivation,
                                    # Polymorphic by consequence_type, so constrained per
                                    # variant rather than left open. "It varies" is not a
                                    # reason to publish an unconstrained object when the
                                    # variants are a closed set of two. WHICH variant is
                                    # decided by the `allOf` above, not by this `oneOf`.
                                    "detail": {
                                        "oneOf": [commitment_detail, downtime_detail],
                                    },
                                },
                            },
                            "action": {
                                "type": "object",
                                "required": [
                                    "action_id", "action_type", "target",
                                    "responsible_role", "due_by",
                                    "operational_window_start",
                                    "operational_window_end", "reason", "priority",
                                    "prerequisites", "rendered_text",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "action_id": nonempty,
                                    "action_type": {
                                        "enum": [
                                            "INSPECT", "SERVICE", "REPLACE",
                                            "RESCHEDULE", "MONITOR",
                                        ],
                                    },
                                    "target": nonempty,
                                    "responsible_role": {"type": "string"},
                                    "due_by": timestamp,
                                    "operational_window_start": timestamp,
                                    "operational_window_end": timestamp,
                                    "reason": {"type": "string"},
                                    "priority": {
                                        "enum": [
                                            "ROUTINE", "BEFORE_NEXT_USE", "IMMEDIATE",
                                        ],
                                    },
                                    "prerequisites": strings,
                                    "rendered_text": {
                                        "type": "string",
                                        "description": (
                                            "Derived on export. Re-derived on import and "
                                            "COMPARED -- never read back as an input, and "
                                            "never silently overwritten either: this is "
                                            "the sentence a human was shown."
                                        ),
                                    },
                                },
                            },
                        },
                    },
                    "assurance": {
                        "type": "object",
                        "required": [
                            "permitted", "blocking_reasons", "policy_id",
                            "policy_version", "policy_digest", "release_decision_time",
                            "assurance_context",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "permitted": {"type": "boolean"},
                            "blocking_reasons": strings,
                            "policy_id": nonempty,
                            "policy_version": nonempty,
                            "policy_digest": sha256,
                            "release_decision_time": timestamp,
                            "assurance_context": {
                                "type": "object",
                                "required": [
                                    "identity", "applicability", "temporal",
                                    "entitlement", "evidence",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "identity": {
                                        "type": "object",
                                        "required": [
                                            "resolved_entity", "resolver",
                                            "resolver_version", "confidence",
                                            "evidence_refs", "conflicts",
                                        ],
                                        "additionalProperties": False,
                                        "properties": {
                                            "resolved_entity": nonempty,
                                            "resolver": nonempty,
                                            "resolver_version": {"type": "string"},
                                            "confidence": unit_decimal,
                                            "evidence_refs": strings,
                                            "conflicts": strings,
                                        },
                                    },
                                    "applicability": {
                                        "type": "object",
                                        "required": [
                                            "model_version", "subject_type", "valid",
                                            "basis",
                                        ],
                                        "additionalProperties": False,
                                        "properties": {
                                            "model_version": nonempty,
                                            "subject_type": nonempty,
                                            "valid": {"type": "boolean"},
                                            "basis": nonempty,
                                        },
                                    },
                                    "temporal": {
                                        "type": "object",
                                        "required": [
                                            "model_decision_time", "knowledge_cutoff",
                                            "feature_cutoff", "valid", "basis",
                                        ],
                                        "additionalProperties": False,
                                        "properties": {
                                            "model_decision_time": timestamp,
                                            "knowledge_cutoff": timestamp,
                                            "feature_cutoff": timestamp,
                                            "valid": {"type": "boolean"},
                                            "basis": nonempty,
                                        },
                                    },
                                    "entitlement": {
                                        "type": "object",
                                        "description": (
                                            "The full scope, not a summary. Subject, "
                                            "validity, licensed sources and both "
                                            "permission booleans were previously dropped "
                                            "on export, so an importer could not re-run "
                                            "the authorization this bundle asserts."
                                        ),
                                        "required": [
                                            "recipient", "purpose", "subject", "tenant",
                                            "basis", "policy_id", "policy_version",
                                            "valid_from", "valid_to",
                                            "authorized_source_systems",
                                            "may_use_source_data",
                                            "may_deliver_to_recipient",
                                        ],
                                        "additionalProperties": False,
                                        "properties": {
                                            # `permits()` compares purpose and tenant
                                            # with `!=`, so two blanks satisfy a scope
                                            # dimension by matching emptiness. The
                                            # assertion refuses them; the schema did not.
                                            "recipient": nonempty,
                                            "purpose": nonempty,
                                            "subject": {"type": "string"},
                                            "tenant": nonempty,
                                            "basis": nonempty,
                                            "policy_id": nonempty,
                                            "policy_version": nonempty,
                                            "valid_from": timestamp,
                                            "valid_to": nullable_timestamp,
                                            "authorized_source_systems": strings,
                                            "may_use_source_data": {"type": "boolean"},
                                            "may_deliver_to_recipient": {
                                                "type": "boolean",
                                            },
                                        },
                                    },
                                    "evidence": {
                                        "type": "object",
                                        "description": (
                                            "The six-dimension assessment that actually "
                                            "decided. Enumerated, not free text: the "
                                            "whole state space is closed and exactly one "
                                            "combination releases."
                                        ),
                                        "required": [
                                            "support", "completeness", "integrity",
                                            "temporal_eligibility", "identity",
                                            "entitlement", "release", "missing_evidence",
                                            "conflicts", "blocking_reasons",
                                        ],
                                        "additionalProperties": False,
                                        # A DIMENSION AND THE LIST THAT JUSTIFIES IT.
                                        #
                                        # `EvidenceAssessment.__post_init__` keeps three
                                        # pairs from drifting: MISSING must name what is
                                        # missing, COMPLETE must name nothing, and
                                        # CONFLICTED must name the conflicts. All three
                                        # are conditionals over sibling keys, which is the
                                        # one cross-field shape JSON Schema does express
                                        # -- and none of the three was here. The published
                                        # contract accepted "completeness=MISSING" with an
                                        # empty list, which is the uninformative verdict
                                        # this module exists to replace, conforming.
                                        "allOf": [
                                            {
                                                "if": {
                                                    "properties": {
                                                        "completeness": {
                                                            "const": "MISSING",
                                                        },
                                                    },
                                                    "required": ["completeness"],
                                                },
                                                "then": {
                                                    "properties": {
                                                        "missing_evidence": {
                                                            "minItems": 1,
                                                        },
                                                    },
                                                },
                                            },
                                            {
                                                "if": {
                                                    "properties": {
                                                        "completeness": {
                                                            "const": "COMPLETE",
                                                        },
                                                    },
                                                    "required": ["completeness"],
                                                },
                                                "then": {
                                                    "properties": {
                                                        "missing_evidence": {
                                                            "maxItems": 0,
                                                        },
                                                    },
                                                },
                                            },
                                            {
                                                "if": {
                                                    "properties": {
                                                        "support": {
                                                            "const": "CONFLICTED",
                                                        },
                                                    },
                                                    "required": ["support"],
                                                },
                                                "then": {
                                                    "properties": {
                                                        "conflicts": {"minItems": 1},
                                                    },
                                                },
                                            },
                                        ],
                                        "properties": {
                                            "support": {"enum": [s.value for s in Support]},
                                            "completeness": {
                                                "enum": [c.value for c in Completeness],
                                            },
                                            "integrity": {
                                                "enum": [i.value for i in Integrity],
                                            },
                                            "temporal_eligibility": {
                                                "enum": [
                                                    t.value for t in TemporalEligibility
                                                ],
                                            },
                                            "identity": {
                                                "enum": [i.value for i in Identity],
                                            },
                                            "entitlement": {
                                                "enum": [
                                                    e.value for e in EntitlementState
                                                ],
                                            },
                                            "release": {
                                                "enum": [r.value for r in Release],
                                            },
                                            "missing_evidence": strings,
                                            "conflicts": strings,
                                            "blocking_reasons": strings,
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "evidence": {
                        "type": "object",
                        "description": (
                            "The evidence the claim rests on. Absent from the bundle "
                            "entirely until this revision, which left every guarantee "
                            "about the claim uncheckable by any reader."
                        ),
                        "required": [
                            "observation_ids", "subject", "evidence_content_digest",
                            "source_systems", "captured_at", "model_version",
                            "semantic_rule_version", "identity_confidence",
                            "prediction_inputs",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "observation_ids": strings,
                            "subject": {
                                "type": "string",
                                "description": (
                                    "What the cited readings are about. Absent until the "
                                    "claim's subject was found to be a free variable: "
                                    "every check that consumed a subject read it from the "
                                    "claim itself."
                                ),
                            },
                            "model_version": {"type": ["string", "null"]},
                            "semantic_rule_version": {"type": ["string", "null"]},
                            "identity_confidence": {
                                "oneOf": [unit_decimal, {"type": "null"}],
                            },
                            "evidence_content_digest": {
                                "oneOf": [sha256, {"type": "null"}],
                            },
                            "source_systems": strings,
                            # NOT NULLABLE. `EvidenceSnapshot.__post_init__` refuses a
                            # snapshot with no capture time -- "evidence with no capture
                            # time cannot be placed against a decision" -- so the producer
                            # cannot emit null here and the schema said it could. A reader
                            # implementing in another language would have built a validator
                            # that accepts a record this system refuses, which is the
                            # asymmetry the reconciliation pass exists to remove.
                            "captured_at": timestamp,
                            "prediction_inputs": prediction_inputs,
                        },
                    },
                    "release_evidence": release_evidence,
                    "rendered_delivery": {
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "required": [
                                    "renderer_version", "locale", "rendered_text",
                                    "card", "content_digest", "rendered_at",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "renderer_version": nonempty,
                                    "locale": nonempty,
                                    "rendered_text": {"type": "string"},
                                    "card": {
                                        "type": "object",
                                        "additionalProperties": {"type": "string"},
                                        "description": (
                                            "Deliberately open in its KEYS: the card is "
                                            "the operator's mental model and a renderer "
                                            "may add a field. Its values are constrained, "
                                            "and the whole card is inside the digest."
                                        ),
                                    },
                                    "content_digest": sha256,
                                    "rendered_at": timestamp,
                                },
                            },
                        ],
                    },
                },
            },
            "lifecycle_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["state", "at", "actor", "note"],
                    "additionalProperties": False,
                    "properties": {
                        "state": {
                            "enum": [s.value for s in DispositionState],
                        },
                        "at": timestamp,
                        "actor": nonempty,
                        "note": {"type": "string"},
                    },
                },
            },
            "outcome": {
                "description": (
                    "The typed LEARN boundary. This was `{\"type\": [\"object\", "
                    "\"null\"]}` -- unconstrained -- while `OutcomeObservation` was a real "
                    "type carrying the action join that makes an evaluation dataset "
                    "possible."
                ),
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "required": [
                            "outcome_id", "outcome_type", "subject",
                            "observation_window_start", "observation_window_end",
                            "observed_at", "source", "related_action_id", "metric",
                            "value", "severity", "note", "description",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "outcome_id": nonempty,
                            "outcome_type": {
                                "enum": [
                                    "FAILURE_OCCURRED", "NO_FAILURE_OBSERVED",
                                    "DEFECT_FOUND_ON_INSPECTION", "NO_DEFECT_FOUND",
                                    "NOT_OBSERVED",
                                ],
                            },
                            "subject": nonempty,
                            "observation_window_start": timestamp,
                            "observation_window_end": timestamp,
                            "observed_at": timestamp,
                            "source": {"type": "string"},
                            "related_action_id": {"type": ["string", "null"]},
                            "metric": {"type": ["string", "null"]},
                            "value": {"oneOf": [decimal_string, {"type": "null"}]},
                            "severity": {"type": ["string", "null"]},
                            "note": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                ],
            },
            "status_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "event_type", "at", "actor", "reason", "replacement_product_id",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "event_type": {
                            "enum": [e.value for e in StatusEventType],
                        },
                        "at": timestamp,
                        "actor": nonempty,
                        "reason": {"type": "string"},
                        "replacement_product_id": {"type": ["string", "null"]},
                    },
                    # THE TWO CONDITIONAL SHAPES `StatusEvent` REFUSES, in the same
                    # if/then form the determination already uses. A retraction with no
                    # reason is unauditable and a supersession that does not name its
                    # replacement leaves a lineage walk with nowhere to go -- both refused
                    # by the typed domain, both accepted by the schema calling itself
                    # normative.
                    "allOf": [
                        {
                            "if": {"properties": {"event_type": {"const": "RETRACTED"}}},
                            "then": {"properties": {"reason": nonempty}},
                        },
                        {
                            "if": {"properties": {"event_type": {"const": "SUPERSEDED"}}},
                            "then": {
                                "properties": {"replacement_product_id": nonempty}
                            },
                        },
                    ],
                },
            },
        },
    }


def write_schema(path: str = "schema/envelope-1.json") -> None:
    import pathlib

    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(json_schema(), indent=2) + "\n")
