"""A bounded evidence algebra.

WHY NOT A SINGLE VERDICT
------------------------
An earlier version of this module answered one question: is the claim provable, yes or
no. That is too coarse to be useful. Six different situations collapsed into the same
answer:

    the operator had no right to deliver it
    the hash chain was broken
    the evidence arrived after the decision was made
    two sources disagree about which asset this is
    a required field was never recorded
    the data simply does not support the claim

Those demand different responses from different people. A rights problem goes to
commercial; a broken chain goes to engineering; a late arrival is nobody's fault and
merely bounds what the decision could have known. Collapsing them into NOT_RECONSTRUCTABLE
tells the reader something is wrong and nothing about what.

So the algebra keeps six dimensions independent, and the release decision is their
conjunction. Each dimension is small, closed, and separately testable.

WHAT IS AND IS NOT BEING CLAIMED
--------------------------------
Nothing here is a new idea. Reasoning about incomplete and conflicting information is
an established field with decades of literature behind it, and this module does not
extend it. What it does is apply those established semantics to a specific bounded
problem: whether a particular prediction may be delivered to a particular customer at a
particular moment, and whether that can be shown later.

Correctness is therefore claimed over *this finite rule set*, which is provable by
enumeration, and not for arbitrary queries, which would be a different and much larger
undertaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Support(str, Enum):
    """Does the evidence back the claim?"""

    UNSUPPORTED = "UNSUPPORTED"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    CONFLICTED = "CONFLICTED"
    """Sources disagree. Distinct from UNSUPPORTED: here there is evidence on both
    sides, which is a worse position than having none, because it means something is
    wrong upstream."""


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    MISSING = "MISSING"


class Integrity(str, Enum):
    """Whether the record itself can be trusted, independent of what it says."""

    VALID = "VALID"
    BROKEN = "BROKEN"


class TemporalEligibility(str, Enum):
    ELIGIBLE_AS_OF_DECISION = "ELIGIBLE_AS_OF_DECISION"
    LATE = "LATE"
    """Arrived after the decision. Not an error -- it simply was not available, and a
    reconstruction that uses it is describing a decision nobody actually made."""

    OUTSIDE_VALID_WINDOW = "OUTSIDE_VALID_WINDOW"


class Identity(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTED = "CONFLICTED"


class EntitlementState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNKNOWN = "UNKNOWN"
    """Never treated as permission. An unrecorded right is not a right."""


class Release(str, Enum):
    RELEASE = "RELEASE"
    WITHHOLD = "WITHHOLD"


@dataclass(frozen=True)
class EvidenceAssessment:
    """The six dimensions, held separately, plus the decision they imply."""

    support: Support
    completeness: Completeness
    integrity: Integrity
    temporal_eligibility: TemporalEligibility
    identity: Identity
    entitlement: EntitlementState
    missing_evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Keep the two representations from drifting apart. A MISSING assessment that
        # cannot say what is missing is exactly the uninformative verdict this module
        # exists to replace.
        if self.completeness is Completeness.MISSING and not self.missing_evidence:
            raise ValueError("MISSING requires naming the missing evidence")
        if self.completeness is Completeness.COMPLETE and self.missing_evidence:
            raise ValueError("COMPLETE contradicts a non-empty missing_evidence list")
        if self.support is Support.CONFLICTED and not self.conflicts:
            raise ValueError("CONFLICTED requires naming the conflicts")

    def release_decision(self) -> Release:
        """The conjunction. Every dimension must be at its permitting value.

        Written as an explicit list rather than a chain of ands so that the failing
        dimension can be named, which `blocking_reasons` relies on.
        """
        return (
            Release.RELEASE if not self.blocking_reasons() else Release.WITHHOLD
        )

    def blocking_reasons(self) -> tuple[str, ...]:
        """Every dimension currently preventing release, not merely the first.

        Returning all of them matters operationally: fixing one blocker and
        rediscovering the next on the following run wastes a cycle each time.
        """
        reasons: list[str] = []
        if self.support is not Support.SUPPORTED:
            reasons.append(f"support={self.support.value}")
        if self.completeness is not Completeness.COMPLETE:
            reasons.append(
                "completeness=MISSING(" + ",".join(self.missing_evidence) + ")"
            )
        if self.integrity is not Integrity.VALID:
            reasons.append(f"integrity={self.integrity.value}")
        if self.temporal_eligibility is not TemporalEligibility.ELIGIBLE_AS_OF_DECISION:
            reasons.append(f"temporal_eligibility={self.temporal_eligibility.value}")
        if self.identity is not Identity.RESOLVED:
            reasons.append(f"identity={self.identity.value}")
        if self.entitlement is not EntitlementState.AUTHORIZED:
            reasons.append(f"entitlement={self.entitlement.value}")
        if self.conflicts:
            reasons.append("unresolved_conflicts=" + ",".join(self.conflicts))
        return tuple(reasons)

    def as_record(self) -> dict[str, object]:
        """Platform-neutral form. This is the part that has to survive export."""
        return {
            "support": self.support.value,
            "completeness": self.completeness.value,
            "integrity": self.integrity.value,
            "temporal_eligibility": self.temporal_eligibility.value,
            "identity": self.identity.value,
            "entitlement": self.entitlement.value,
            "missing_evidence": list(self.missing_evidence),
            "conflicts": list(self.conflicts),
            "release": self.release_decision().value,
            "blocking_reasons": list(self.blocking_reasons()),
        }

    @classmethod
    def from_record(cls, r: dict[str, object]) -> "EvidenceAssessment":
        """Rebuild the six dimensions and CHECK the two derived values travelling with them.

        `release` and `blocking_reasons` are derived from the dimensions. Reading them back
        as inputs would make the wire copy a second authority; silently re-deriving them
        and discarding whatever the payload said is the other failure -- it accepts a
        record asserting one verdict, quietly stores a different one, and re-exports a
        bundle that no longer matches the bytes it arrived as.

        So they are re-derived AND compared, and a disagreement is refused. A record whose
        stated conclusion does not follow from its own dimensions is not a record with a
        cosmetic error in it.
        """
        rebuilt = cls(
            support=Support(r["support"]),
            completeness=Completeness(r["completeness"]),
            integrity=Integrity(r["integrity"]),
            temporal_eligibility=TemporalEligibility(r["temporal_eligibility"]),
            identity=Identity(r["identity"]),
            entitlement=EntitlementState(r["entitlement"]),
            missing_evidence=tuple(r.get("missing_evidence") or ()),  # type: ignore[arg-type]
            conflicts=tuple(r.get("conflicts") or ()),  # type: ignore[arg-type]
        )
        if "release" in r and r["release"] != rebuilt.release_decision().value:
            raise ValueError(
                f"the record states release={r['release']!r} but its own six dimensions "
                f"imply {rebuilt.release_decision().value!r}; a derived value that "
                f"disagrees with what it is derived from is a second authority"
            )
        if "blocking_reasons" in r and list(r["blocking_reasons"] or ()) != list(  # type: ignore[arg-type]
            rebuilt.blocking_reasons()
        ):
            raise ValueError(
                "the record's blocking reasons are not the reasons its dimensions produce"
            )
        return rebuilt


def fully_satisfied() -> EvidenceAssessment:
    """The one assessment that permits release. Useful as a test baseline."""
    return EvidenceAssessment(
        support=Support.SUPPORTED,
        completeness=Completeness.COMPLETE,
        integrity=Integrity.VALID,
        temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
        identity=Identity.RESOLVED,
        entitlement=EntitlementState.AUTHORIZED,
    )
