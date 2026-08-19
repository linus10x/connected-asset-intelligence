"""Release policy as an abstraction, not as thresholds scattered through the domain.

WHY THIS IS SEPARATE
--------------------
The global floors used to live in `release.py`, which meant business policy was compiled
into a domain entity. That is fine for one product type and wrong the moment a second one
needs a different bar -- higher identity certainty for a safety claim, human review above a
cost threshold, a different entitlement basis for a regulated recipient.

So policy becomes a thing with a version and a digest that evaluates a candidate against an
assurance context. This is NOT a policy engine, and deliberately so: one implementation,
literal thresholds, no rule language. What matters is that the seam exists and that every
decision records which policy produced it.

THE DIGEST
----------
`policy_digest` hashes the parameters that actually decided, so a threshold edited without
a version bump is still detectable. A version string is a promise somebody keeps by hand.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from .candidate import AssessedAssurance, IntelligenceCandidate
from .delivery import AssuranceDecision
from .evidence import Release

POLICY_ID = "cai.default-release-policy"
POLICY_VERSION = "release-policy@2.0.0"

# Below this, subject identity is treated as unresolved. Explicit and tunable rather than
# buried: an operator raising it to 0.99 is making a policy decision and it should look
# like one.
IDENTITY_CONFIDENCE_FLOOR = 0.85

# A claim carrying less evidential weight than this is not actionable advice, it is noise
# with a decimal point attached.
MIN_EVIDENCE_STRENGTH = 0.60


@dataclass(frozen=True)
class ReleasePolicy:
    """One versioned policy. Evaluates a candidate against gathered assurance."""

    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    identity_floor: float = IDENTITY_CONFIDENCE_FLOOR
    min_evidence_strength: float = MIN_EVIDENCE_STRENGTH

    def digest(self) -> str:
        payload = (
            f"{self.policy_id}\x1f{self.policy_version}\x1f"
            f"{self.identity_floor!r}\x1f{self.min_evidence_strength!r}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def evaluate(
        self,
        candidate: IntelligenceCandidate,
        assessed: AssessedAssurance,
        *,
        release_decision_time: datetime,
    ) -> AssuranceDecision:
        """Return an immutable decision carrying the assertions actually consulted.

        Every failing check is collected rather than the first one returned. Fixing one
        blocker and rediscovering the next on the following run wastes a cycle each time.

        A pure function of the candidate and the assessed assurance, deliberately: the
        import boundary re-runs it against the reconstructed objects and compares, which
        it could not do if this consulted anything that does not cross the wire.
        """
        reasons: list[str] = []
        assurance = assessed.context

        identity = assurance.identity_assertion
        if identity.confidence < self.identity_floor:
            reasons.append(
                f"identity: confidence {identity.confidence:.2f} below floor "
                f"{self.identity_floor:.2f}"
            )
        if identity.conflicts:
            reasons.append(f"identity: unresolved conflicts {list(identity.conflicts)}")

        if not assurance.applicability_assertion.valid:
            reasons.append(
                f"applicability: {assurance.applicability_assertion.basis}"
            )

        if not assurance.temporal_assertion.valid:
            reasons.append("temporal: features are not point-in-time correct")

        # Entitlement is NOT re-decided here. The scoped assertion is projected into the
        # sixth assurance dimension and arrives via the evidence assessment below. A
        # second permits() gate at this layer would be exactly the two-authorities
        # pattern this refactor exists to remove.

        evidence = assessed.evidence_assessment
        if evidence.release_decision() is Release.WITHHOLD:
            reasons.extend(evidence.blocking_reasons())

        strength = candidate.prediction_claim.evidence_strength
        if strength < self.min_evidence_strength:
            reasons.append(
                f"authority: evidence strength {strength:.2f} below deliverable "
                f"minimum {self.min_evidence_strength:.2f}"
            )

        return AssuranceDecision(
            permitted=not reasons,
            blocking_reasons=tuple(reasons),
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            policy_digest=self.digest(),
            assessed=assessed,
            release_decision_time=release_decision_time,
        )
