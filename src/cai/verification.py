"""What a reader could and could not check, carried as a value rather than lost.

THE DEFECT THIS REPLACES
------------------------
`import_envelope(payload, accept_unverifiable_basis=True)` returned the same ordinary
`IntelligenceEnvelope` a fully verified import returned. The fact that a verification had
not happened -- because the claim named a predictor build this process does not have, or
a release policy whose thresholds are not on the wire -- disappeared at the API boundary.
A caller who passed the flag, or a helper three layers down that passed it on their
behalf, held an object indistinguishable from one that had been checked end to end.

That is the same failure this package refuses everywhere else, wearing a keyword
argument: absence of a verification silently upgraded into presence.

The single boolean also conflated two independent trust conditions. "I cannot replay this
model" and "I do not have this policy's thresholds" are different facts about different
parts of the record, and a record can be either, both or neither. One flag could not say
which, so a reader who accepted an unreplayable model also, silently, accepted an
unreproducible policy.

WHAT REPLACES IT
----------------
Strict import performs every verification available to this implementation and returns an
envelope only when all of them succeeded. It has no waiver.

`import_historical_envelope` returns the envelope AND this report, which states each
dimension independently. A dimension is VERIFIED, or it is UNVERIFIABLE with a reason.

THE DISTINCTION THAT MATTERS MOST
---------------------------------
A FAILED verification is not UNVERIFIABLE. A record whose claim replays to a different
score, whose policy verdict does not reproduce, whose card is not what its candidate
renders, or whose entitlement does not authorise its own delivery is REFUSED, in both
modes. UNVERIFIABLE means the check could not be run here at all, never that it was run
and did not pass.

Rights are never waived. `ENTITLEMENT_SCOPE` compares a clearance to the delivery
recorded beside it, and both are on the wire in full -- there is no threshold to be
missing and no build to be absent, so there is no honest way for it to be anything but
VERIFIED or refused.

WHY THE REPORT IS NOT STORED ON THE PRODUCT
-------------------------------------------
It describes THIS reader, on THIS build, at THIS moment: whether the predictor artifact
happens to be present, whether this package ships the policy the record names. Stamping
that into the immutable historical record would be a reconstruction of a reconstruction,
which is the failure the whole bitemporal apparatus exists to prevent. The report belongs
to the import operation, so it is returned beside the envelope and not welded into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class VerificationDimension(str, Enum):
    """The independent questions an import can answer about a record.

    Seven, and deliberately not one. A single "verified" boolean is what let two unrelated
    trust conditions share one waiver.
    """

    STRUCTURAL_CONFORMANCE = "structural_conformance"
    """Does the payload satisfy the published schema, name a schema version and a
    canonicalization this implementation understands, and survive reconstruction as the
    same record it arrived as?"""

    EVIDENCE_RECONSTRUCTION = "evidence_reconstruction"
    """Do the carried readings rebuild through their own invariants, and does re-running
    the release path's assessment over them reproduce the assessment on file?"""

    CLAIM_REPLAY = "claim_replay"
    """Does re-running the recorded predictor over the recorded inputs reproduce the score,
    its stated semantics, the evidence strength and every other field it determined?

    The one dimension that genuinely needs a build this process may not have."""

    POLICY_REPLAY = "policy_replay"
    """Does re-running the named release policy over the recorded basis reproduce the
    verdict and its blocking reasons?

    Thresholds are not on the wire, so a policy this package does not ship cannot be
    reproduced -- which is a different statement from its verdict being wrong."""

    ENTITLEMENT_SCOPE = "entitlement_scope"
    """Does the recorded clearance authorise the delivery recorded beside it -- this
    recipient, this purpose, this subject, this tenant, these source systems, at this
    moment?

    Mandatory in both modes. Never UNVERIFIABLE: both halves of the comparison travel in
    full, so there is nothing a reader could be missing."""

    RENDERED_ARTIFACT = "rendered_artifact"
    """Is the card the record attests the card this candidate renders?"""

    LIFECYCLE = "lifecycle"
    """Do the disposition trail, the typed outcome and the status events describe a
    history that could have happened, bound to this product?"""


class VerificationState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIABLE = "UNVERIFIABLE"
    """The check could not be run here. NOT "the check failed" -- a failure refuses."""


@dataclass(frozen=True)
class DimensionVerification:
    """One dimension's answer, and the reason when there isn't one."""

    dimension: VerificationDimension
    state: VerificationState
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state is VerificationState.UNVERIFIABLE and not self.reason:
            raise ValueError(
                f"{self.dimension.value} is UNVERIFIABLE with no reason given; a reader "
                f"told a check did not happen and not why cannot decide what to do about "
                f"it, which is the whole difference between this and a boolean"
            )
        if self.state is VerificationState.VERIFIED and self.reason:
            raise ValueError(
                f"{self.dimension.value} is VERIFIED and carries the reason "
                f"{self.reason!r}; a verification that needs an excuse beside it is not "
                f"one, and a reader skimming states would never see the excuse"
            )

    def describe(self) -> str:
        if self.state is VerificationState.VERIFIED:
            return f"{self.dimension.value}: VERIFIED"
        return f"{self.dimension.value}: UNVERIFIABLE({self.reason})"

    def as_record(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "state": self.state.value,
            "reason": self.reason,
        }


def verified(dimension: VerificationDimension) -> DimensionVerification:
    return DimensionVerification(dimension, VerificationState.VERIFIED)


def unverifiable(dimension: VerificationDimension, reason: str) -> DimensionVerification:
    return DimensionVerification(dimension, VerificationState.UNVERIFIABLE, reason)


@dataclass(frozen=True)
class VerificationReport:
    """Every dimension, answered exactly once.

    WHY ALL SEVEN, ALWAYS
    ---------------------
    A report that lists only the interesting dimensions is a report whose silence a reader
    has to interpret, and they will interpret it as "fine". Requiring the full set means a
    dimension cannot be quietly dropped when somebody adds a code path that forgets it --
    the constructor refuses a report that is missing one.
    """

    dimensions: tuple[DimensionVerification, ...]

    def __post_init__(self) -> None:
        # The lookup is built here, once, and `__getitem__` is a plain dict index.
        #
        # It used to walk the tuple and end with `raise KeyError(dimension)`, and that
        # raise could not fire: the checks below guarantee every dimension is present.
        # `guard_sweep.py` reported it removable, and it could not simply be deleted --
        # a `__getitem__` that falls off the end returns None, which is worse than
        # raising. Indexing a total mapping needs no hand-written guard at all, and
        # KeyError still comes back for a caller who passes something that is not a
        # `VerificationDimension`.
        seen = [d.dimension for d in self.dimensions]
        duplicates = sorted({d.value for d in seen if seen.count(d) > 1})
        if duplicates:
            raise ValueError(
                f"the report answers {duplicates} more than once; two answers to one "
                f"question is the second authority this package spends its time removing"
            )
        missing = sorted(
            d.value for d in VerificationDimension if d not in set(seen)
        )
        if missing:
            raise ValueError(
                f"the report says nothing about {missing}; a reader reads silence as "
                f"'fine', so every dimension is answered or the report does not exist"
            )
        object.__setattr__(
            self, "_by_dimension", {d.dimension: d for d in self.dimensions}
        )

    def __getitem__(self, dimension: VerificationDimension) -> DimensionVerification:
        return self._by_dimension[dimension]  # type: ignore[attr-defined]

    def state_of(self, dimension: VerificationDimension) -> VerificationState:
        return self[dimension].state

    def unverifiable(self) -> tuple[DimensionVerification, ...]:
        return tuple(
            d for d in self.dimensions if d.state is VerificationState.UNVERIFIABLE
        )

    def fully_verified(self) -> bool:
        return not self.unverifiable()

    def describe(self) -> str:
        return "\n".join(d.describe() for d in self.dimensions)

    def as_record(self) -> dict[str, Any]:
        """For printing and logging by the reader who performed the import.

        Deliberately NOT part of any envelope's `as_record`. This describes a reader on a
        build at a moment; welding it into the historical record would make the artifact
        assert something about a process that was not running when it was created.
        """
        return {"dimensions": [d.as_record() for d in self.dimensions]}
