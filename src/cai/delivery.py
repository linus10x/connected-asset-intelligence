"""What the customer literally saw, and the decision that let them see it.

THE PROBLEM THIS SOLVES
-----------------------
The typed claim removed author-supplied prose from the product. That left a real question:
eighteen months later, how do we prove what the customer actually read?

The wrong answer -- and the one that was briefly in the code -- is to keep the typed objects
AND store `claim`, `business_context`, `recommended_action` and `confidence` as independent
strings beside them. That is two semantic authorities for one fact, which is the exact drift
surface the typed objects exist to remove.

`RenderedDelivery` is the right answer: a DERIVED artifact, produced by a versioned renderer
at delivery time and digested. It is evidence of a rendering, never a second source of truth.
Nobody can author prose here that disagrees with the claim, because nobody authors it at all.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .canonical import canonicalize
from .decision import format_moment

if TYPE_CHECKING:  # imported for typing only; candidate.py must not depend on this module
    from .candidate import AssessedAssurance, IntelligenceCandidate

RENDERER_VERSION = "cai.renderer@1.0.0"


def trust_line(*, identity_confidence: float) -> str:
    """The assurance line appended to the card at delivery.

    A module function because it is now derived in TWO places -- once by the release path
    that stamps it, and once by the import boundary that re-renders the artifact to check
    it. Two copies of this string would mean an honest bundle failing to reproduce, which
    is the drift this file exists to prevent, expressed in the file itself.
    """
    return " · ".join(
        ["evidence complete", f"identity {identity_confidence:.2f}", "rights permitted"]
    )


def _digest_of(
    *,
    renderer_version: str,
    locale: str,
    rendered_text: str,
    card: dict[str, str],
    rendered_at: datetime,
) -> str:
    """One implementation, used to both stamp and check. Two would drift.

    `rendered_at` is inside the digest, not beside it. A timestamp the digest does not
    cover can be edited without breaking anything, which would make it decoration on an
    artifact whose entire job is being tamper-evident.
    """
    return hashlib.sha256(
        canonicalize({
            "renderer_version": renderer_version,
            "locale": locale,
            "rendered_text": rendered_text,
            "card": dict(card),
            "rendered_at": rendered_at.isoformat(),
        }).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class RenderedDelivery:
    """The immutable record of one rendering, for one recipient, at one moment."""

    renderer_version: str
    locale: str
    rendered_text: str
    card: dict[str, str]
    content_digest: str
    rendered_at: datetime = None  # type: ignore[assignment]
    """When this rendering was produced. Required; the default exists only so the field
    can be declared after `content_digest` without reordering every call site.

    The governing ruling asked for it and it was not there, so the artifact proved WHAT
    the recipient saw and not WHEN. A re-render days later -- against a claim that has
    since expired or been retracted -- was indistinguishable in the record from the one
    actually delivered.
    """

    def __post_init__(self) -> None:
        """A digest that does not bind its own content authenticates nothing.

        Checked here rather than trusted at each construction site, because it was not: the
        release path appended the trust line to an already-rendered artifact and carried the
        old digest forward, so every delivered product attested a sentence the recipient
        never saw. The verification is the artifact's whole purpose, and an object that can
        exist in the broken state will eventually be built in it.
        """
        if self.rendered_at is None:
            raise ValueError(
                "rendered_at is required -- an artifact that says what the recipient saw "
                "but not when cannot be told apart from a later re-render"
            )
        if self.rendered_at.tzinfo is None:
            raise ValueError("rendered_at must be timezone-aware")
        if self.content_digest != self.recomputed_digest():
            raise ValueError(
                "content_digest does not match the rendered content it claims to attest; "
                "a delivery record that cannot be verified against itself is not evidence"
            )

    def recomputed_digest(self) -> str:
        """The digest this artifact's content implies.

        Over the rendering identity as well as the text: the same words produced by a
        different renderer version are a different artifact, and a digest that cannot tell
        them apart cannot reconstruct what was delivered.
        """
        return _digest_of(
            renderer_version=self.renderer_version,
            locale=self.locale,
            rendered_text=self.rendered_text,
            card=self.card,
            rendered_at=self.rendered_at,
        )

    def with_trust_line(self, trust_line: str) -> "RenderedDelivery":
        """The assurance decision's line, added at delivery, digest restamped.

        A method rather than a caller-side rebuild because the caller-side rebuild is what
        carried the stale digest. There is now one way to do this and it cannot forget.
        """
        text = self.rendered_text + f"\nWHY TRUST IT?     {trust_line}"
        card = {**self.card, "why_trust_it": trust_line}
        return RenderedDelivery(
            renderer_version=self.renderer_version,
            locale=self.locale,
            rendered_text=text,
            card=card,
            content_digest=_digest_of(
                renderer_version=self.renderer_version,
                locale=self.locale,
                rendered_text=text,
                card=card,
                rendered_at=self.rendered_at,
            ),
            rendered_at=self.rendered_at,
        )

    @classmethod
    def render(
        cls,
        candidate: "IntelligenceCandidate",
        *,
        rendered_at: datetime,
        locale: str = "en",
    ) -> "RenderedDelivery":
        """Build the operator-facing card from the typed objects. The only route.

        The card's shape is the operator's mental model, not ours. They should never need
        to learn CONNECT/PREDICT/REASON/PRODUCTIZE/LEARN -- that is our architecture and
        not their job. Five questions, answered in the order somebody acting on it asks.
        """
        claim = candidate.prediction_claim
        consequence = candidate.business_consequence
        action = candidate.action

        card = {
            "what_is_at_risk": consequence.describe(),
            "why": (
                f"{claim.subject} shows {claim.metric} at {claim.score:.4f} "
                f"({claim.score_semantics})"
            ),
            "what_should_i_do": action.rendered_text(),
            "by_when": format_moment(action.due_by),
            "why_trust_it": "",  # filled by the assurance decision at delivery
        }
        text = (
            f"WHAT IS AT RISK?  {card['what_is_at_risk']}\n"
            f"WHY?              {card['why']}\n"
            f"WHAT SHOULD I DO? {card['what_should_i_do']}\n"
            f"BY WHEN?          {card['by_when']}"
        )
        return cls(
            renderer_version=RENDERER_VERSION,
            locale=locale,
            rendered_text=text,
            card=card,
            content_digest=_digest_of(
                renderer_version=RENDERER_VERSION,
                locale=locale,
                rendered_text=text,
                card=card,
                rendered_at=rendered_at,
            ),
            rendered_at=rendered_at,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "renderer_version": self.renderer_version,
            "locale": self.locale,
            "rendered_text": self.rendered_text,
            "card": dict(self.card),
            "content_digest": self.content_digest,
            "rendered_at": self.rendered_at.isoformat(),
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "RenderedDelivery":
        """The digest is re-verified on import by `__post_init__`, not trusted.

        This is where the wire form earns the word evidence: a payload whose text was
        edited in transit no longer matches the digest travelling beside it, and the
        object refuses to exist. Nothing here needs to compare anything by hand.
        """
        return cls(
            renderer_version=r["renderer_version"],
            locale=r["locale"],
            rendered_text=r["rendered_text"],
            card=dict(r["card"]),
            content_digest=r["content_digest"],
            rendered_at=datetime.fromisoformat(r["rendered_at"]),
        )


@dataclass(frozen=True)
class AssuranceDecision:
    """Immutable. Carries the assertions actually consulted, not a summary of them.

    A decision that records only its verdict leaves a reader unable to ask the one question
    that matters in a dispute: on what basis. Carrying the policy digest as well as its
    version means a policy edited without a version bump is still detectable.
    """

    permitted: bool
    blocking_reasons: tuple[str, ...]
    policy_id: str
    policy_version: str
    policy_digest: str
    assessed: "AssessedAssurance"
    """The typed basis this decision was reached on.

    It used to be `assurance_context_record: dict[str, Any]` -- the assertions flattened
    into a bag of scalars at the moment the decision was made, and taken back as-is on
    import. So the wire form of "why this qualified for release" was the one part of the
    bundle that reconstructed into nothing, and a payload could alter the recorded basis
    without any of the binding guarantees that apply at live release running over it.
    """

    release_decision_time: datetime
    """When the release gate authorised this delivery -- NOT when the model decided.

    Formerly `decided_at`, which read as a synonym for `DecisionContext.decision_time`
    and is not one. This clock selects which policy thresholds and which entitlement
    validity window were in force, so it is what the import boundary replays the policy
    against. `IntelligenceProduct` binds it equal to `delivery_time` and after the
    model's decision.
    """

    def __post_init__(self) -> None:
        from .candidate import AssessedAssurance

        if self.permitted and self.blocking_reasons:
            raise ValueError("a permitted decision cannot carry blocking reasons")
        if not self.permitted and not self.blocking_reasons:
            raise ValueError(
                "a refusal with no stated reason is indistinguishable from a crash"
            )
        if not isinstance(self.assessed, AssessedAssurance):
            raise TypeError(
                f"assessed must be an AssessedAssurance, not "
                f"{type(self.assessed).__name__}; a decision carrying an untyped basis "
                f"records a verdict nobody can re-derive"
            )
        # WHICH policy decided, in a form that cannot be confused with "some other policy".
        #
        # The import boundary branches on this: a record naming the policy this package
        # ships has its verdict recomputed and compared, and one naming another policy is
        # reported as an unreproducible basis. A blank or malformed identifier must not be
        # able to take the second branch -- "this record names no policy at all" would be
        # reclassified as "this record names a policy I do not have", which is a
        # structurally broken record laundered into a merely unverifiable one.
        for label, value in (
            ("policy_id", self.policy_id), ("policy_version", self.policy_version)
        ):
            if not value:
                raise ValueError(
                    f"a decision with a blank {label} names no rules at all; a reader "
                    f"cannot tell a record decided under rules they do not have from one "
                    f"decided under no rules"
                )
        digest = self.policy_digest
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise ValueError(
                f"{digest!r} cannot be a policy digest; the digest exists so a threshold "
                f"edited without a version bump is still detectable, and one that is not "
                f"even the right shape detects nothing"
            )
        if self.release_decision_time.tzinfo is None:
            raise ValueError("release_decision_time must be timezone-aware")

    @property
    def assurance_context_record(self) -> dict[str, Any]:
        """The flattened view, derived from the typed basis rather than stored beside it.

        Kept because a reader printing the six dimensions should not have to walk the
        object graph. Derived, so it cannot disagree with what it summarises.
        """
        return self.assessed.as_record()

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "AssuranceDecision":
        """`__post_init__` re-checks the permitted/reasons coherence on the way in.

        A refusal with no stated reason and a permission carrying blockers are both
        refused here exactly as in memory -- the two states a decision record must never
        be able to hold, whichever side of the wire it was built on. The assurance basis
        is now REBUILT rather than carried through as a dict, so each assertion's own
        invariants fire here too.
        """
        from .candidate import AssessedAssurance

        return cls(
            permitted=bool(r["permitted"]),
            blocking_reasons=tuple(r.get("blocking_reasons") or ()),
            policy_id=r["policy_id"],
            policy_version=r["policy_version"],
            policy_digest=r["policy_digest"],
            assessed=AssessedAssurance.from_record(r["assurance_context"]),
            release_decision_time=datetime.fromisoformat(r["release_decision_time"]),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "permitted": self.permitted,
            "blocking_reasons": list(self.blocking_reasons),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "release_decision_time": self.release_decision_time.isoformat(),
            "assurance_context": self.assessed.as_record(),
        }
