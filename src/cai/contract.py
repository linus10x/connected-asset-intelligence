"""The Intelligence Product Contract.

WHAT THIS IS
------------
When an operator delivers a prediction to a customer, that prediction stops being an
analytics output and becomes a *commercial claim*. It carries an implied promise, an
implied entitlement to the underlying data, and an implied obligation to explain
itself later. Analytics stacks model the pipeline that produced the number. They do
not model the promise.

This module defines the promise as a first-class unit: an `IntelligenceProduct`.

WHY IT IS NOT A LINEAGE SYSTEM
------------------------------
Lineage tooling (OpenLineage, DataHub, MLflow, feature stores) already answers "how
was this dataset produced." Those are mature and we interoperate with them rather
than reimplement them. None of them answers:

    Was this organisation entitled to deliver this claim, to this recipient,
    at this time -- and can that be shown afterwards, outside the platform that
    produced it?

That is the gap this contract fills. The record is deliberately platform-neutral:
it must survive export from whatever system produced it. Data is portable in most
modern stacks; decisions are not. This is a portable decision record.

DESIGN COMMITMENTS
------------------
1. Abstention is a first-class outcome, not an error. A product that declines to
   make a claim, and says why, is a valid product.
2. Every field that would be needed to defend the claim later must be present at
   delivery time, not reconstructable by luck afterwards.
3. Absence is never silently upgraded into presence. Missing evidence stays missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# RESTORED on a Control Tower ruling. These were deleted as dead code on the authority of
# §12(D) ("DEAD OR DUPLICATE LOGIC. Delete it."), and that authority was explicitly scoped
# to the removable-guard reconciliation, not to importable types and methods.
#
# The reasoning that justified the deletion was wrong in a specific way worth recording:
# zero call sites INSIDE this repository does not establish that a name is outside the
# package contract. There is no `__init__.py` declaring a surface, so every module-level
# name is importable by anyone, and `EvidenceStatus.NOT_RECONSTRUCTABLE` is named in
# RELEASE_EVIDENCE.md -- a frozen artifact. Surviving mutations prove a name is untested,
# not that removing it is compatibility-neutral.
#
# They are untested rather than dead, so they are now tested. If they should go, that is an
# API-surface change and belongs in its own decision, not smuggled into a guard sweep.

class EvidenceStatus(str, Enum):
    """Whether a claim can be reconstructed from what was actually retained.

    Both values are meaningful answers. The failure mode this guards against is a system
    that reports success because it filled a gap with a plausible surrogate.

    WHY NOT "PROVEN"
    ----------------
    These members were called PROVEN and NOT_PROVABLE, and that was an overclaim. Nothing
    here establishes that "elevated thermal-degradation risk" is *true*. What is
    established is narrower and worth stating exactly: the record contains every element
    the contract requires, so the decision can be reassembled and examined later.

    A reader who sees PROVEN beside a claim reasonably concludes the claim was verified.
    It was not. The word was doing work the mechanism could not support, which is the same
    defect this module spends its time preventing everywhere else.
    """

    RECONSTRUCTABLE = "RECONSTRUCTABLE"
    NOT_RECONSTRUCTABLE = "NOT_RECONSTRUCTABLE"


SCORE_SEMANTICS = (
    "relative degradation signal, ordering only -- not a calibrated "
    "probability of real-world failure"
)
"""The one interpretation this predictor's score carries.

A module constant rather than a literal inside `from_prediction`, because the release
path replays the predictor and compares the claim's semantics against what the predictor
would say. Two copies of the sentence would agree until somebody edited one.
"""


# The scalar `Entitlement` -- two booleans, a basis string and a
# `cross_customer_learning_permitted` flag -- used to live here beside
# `EntitlementAssertion`. It was deleted rather than deprecated. Two representations of
# one rights question is the drift surface this module spends its time removing
# everywhere else, and the weaker of the two authorised delivery on a bare
# `may_deliver=True` that named no recipient, no subject, no tenant and no source
# licence. `candidate.EntitlementAssertion` is the only rights representation that
# exists; `test_no_module_reintroduces_a_scalar_rights_representation` fails if it
# comes back.


@dataclass(frozen=True)
class PredictionClaim:
    """What is actually being sold, as one typed object.

    WHY THIS REPLACED FOUR PARAMETERS
    ---------------------------------
    `claim`, `prediction_horizon`, `confidence` and the evidence used to arrive
    independently, so nothing structurally required them to describe the predictor's
    output. That one gap produced several defects that looked unrelated: a claim of
    "peer-benchmarked degradation percentile" from a model computing no percentile; a
    horizon in the record that need not match the horizon in the inputs; a replay proving
    the inputs reproduce a score without proving the stored sentence corresponds to it.

    We had already refused hand-authored `business_context` and required a derived
    `BusinessImpact`. This does the same for the thing customers buy.

    `score_semantics` travels with the score on purpose. A number without its
    interpretation invites the reader to supply one, and the interpretation they supply
    is usually "probability".
    """

    subject: str
    metric: str
    score: float
    score_semantics: str
    horizon_seconds: int
    evidence_strength: float
    """How much weight the evidence supports, NOT statistical confidence.

    Named for what it is. The underlying number is an observation-count heuristic that
    saturates; calling it confidence invited an immediate and correct objection.
    """

    model_version: str
    model_artifact_digest: str
    """SHA-256 of the predictor implementation.

    A version string is etiquette: edit the algorithm, forget to bump 1.3.0, and a replay
    produces a different answer under the same name. For an artifact whose thesis is
    reconstruction, provenance has to be content-addressed.
    """

    input_fingerprint: str

    declared_envelope: "ModelEnvelope" = None  # type: ignore[assignment]
    """What the model that produced this claim declares itself valid for.

    Required in practice -- `__post_init__` refuses a claim without one. The dataclass
    default exists only so the field can be declared after the others without reordering
    the positional signature every construction site already uses.

    It travels ON the claim rather than being looked up when somebody verifies it,
    because the question a reconstruction asks is what the model declared at the time.
    A lookup against today's module answers a different question, confidently.
    """

    def __post_init__(self) -> None:
        import math

        from .predictor import ModelEnvelope

        if not math.isfinite(self.score):
            raise ValueError(f"score {self.score} is not finite")
        if self.horizon_seconds <= 0:
            raise ValueError(f"horizon {self.horizon_seconds}s must be positive")
        if not 0.0 <= self.evidence_strength <= 1.0:
            raise ValueError(f"evidence_strength {self.evidence_strength} outside [0, 1]")
        # An annotation is documentation. `ApplicabilityAssertion.subject_type` was an
        # assertion against an envelope no object carried, and the way that stops being
        # true is the claim refusing to exist without one.
        if not isinstance(self.declared_envelope, ModelEnvelope):
            raise ValueError(
                f"declared_envelope must be a ModelEnvelope, not "
                f"{type(self.declared_envelope).__name__}; a claim with no declared "
                f"envelope makes every applicability assertion about it an assertion "
                f"against nothing"
            )
        # Self-consistency. A claim carrying an envelope that describes a different model,
        # a different build, a metric it does not admit or a horizon beyond its maximum is
        # contradicting itself, and the contradiction must not survive construction.
        if self.declared_envelope.model_version != self.model_version:
            raise ValueError(
                f"the claim came from {self.model_version!r} but carries the envelope of "
                f"{self.declared_envelope.model_version!r}; the limits recorded belong to "
                f"a model that did not run"
            )
        if self.declared_envelope.model_artifact_digest != self.model_artifact_digest:
            raise ValueError(
                "the declared envelope's artifact digest is not the claim's; the envelope "
                "describes a different build of the model"
            )
        if not self.declared_envelope.admits_metric(self.metric):
            raise ValueError(
                f"metric {self.metric!r} is outside the claim's own declared envelope "
                f"{self.declared_envelope.supported_metrics}"
            )
        if not self.declared_envelope.admits_horizon(self.horizon_seconds):
            raise ValueError(
                f"horizon {self.horizon_seconds}s exceeds the declared envelope's maximum "
                f"of {self.declared_envelope.max_horizon_seconds}s"
            )

    @classmethod
    def from_prediction(cls, prediction: Any, *, subject: str) -> "PredictionClaim":
        """Build the claim from the predictor's own output. The only supported route."""
        from .predictor import declared_envelope, model_artifact_digest

        return cls(
            subject=subject,
            metric=prediction.feature_names[0],
            score=prediction.risk,
            score_semantics=SCORE_SEMANTICS,
            horizon_seconds=int(prediction.horizon.total_seconds()),
            evidence_strength=prediction.confidence,
            model_version=prediction.model_version,
            model_artifact_digest=model_artifact_digest(),
            input_fingerprint=prediction.input_fingerprint,
            declared_envelope=declared_envelope(),
        )

    def as_record(self) -> dict[str, Any]:
        """Portable form. Floats travel as strings with explicit precision.

        The canonicalizer refuses non-integer floats rather than risk two implementations
        formatting 0.4942 differently and producing two valid-looking digests for one
        record. Carrying the precision in the string is the honest way to keep the value.
        """
        return {
            "subject": self.subject,
            "metric": self.metric,
            "score": f"{self.score:.6f}",
            "score_semantics": self.score_semantics,
            "horizon_seconds": self.horizon_seconds,
            "evidence_strength": f"{self.evidence_strength:.6f}",
            "model_version": self.model_version,
            "model_artifact_digest": self.model_artifact_digest,
            "input_fingerprint": self.input_fingerprint,
            "declared_envelope": self.declared_envelope.as_record(),
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "PredictionClaim":
        """Rebuild from the wire, running this type's own invariants.

        Floats come back through the 6-decimal wire form they went out in. That is a real
        precision boundary, stated in `as_record` and honoured here rather than hidden
        behind a claim of exact fidelity.
        """
        from .predictor import ModelEnvelope

        return cls(
            subject=r["subject"],
            metric=r["metric"],
            score=float(r["score"]),
            score_semantics=r["score_semantics"],
            horizon_seconds=int(r["horizon_seconds"]),
            evidence_strength=float(r["evidence_strength"]),
            model_version=r["model_version"],
            model_artifact_digest=r["model_artifact_digest"],
            input_fingerprint=r["input_fingerprint"],
            declared_envelope=ModelEnvelope.from_record(r["declared_envelope"]),
        )

    def rendered_text(self) -> str:
        """The customer-facing sentence, derived rather than written.

        Rendering it means the words and the number cannot drift, which is the same
        reason `business_context` is rendered from the graph walk.
        """
        hours = self.horizon_seconds // 3600
        return (
            f"{self.metric}: {self.score:.4f} over {hours}h "
            f"({self.score_semantics})"
        )


@dataclass(frozen=True)
class PredictionInput:
    """One predictor input, bound to the observation it came from.

    Without the binding, the record holds an evidence digest over observations and,
    separately, a tuple of values -- and nothing connects them. A producer could cite
    observations A, B and C, compute their perfectly valid digest, and put unrelated
    numbers in the inputs. Both halves validate independently and the replay reproduces
    whatever the record supplied rather than what the cited evidence says.

    One explicit join closes it. No lineage platform required.
    """

    observation_id: str
    content_digest: str
    value_used: float

    def as_record(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "content_digest": self.content_digest,
            "value_used": f"{self.value_used:.6f}",
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "PredictionInput":
        return cls(
            observation_id=r["observation_id"],
            content_digest=r["content_digest"],
            value_used=float(r["value_used"]),
        )


@dataclass(frozen=True)
class PredictionInputs:
    """The exact inputs that produced the claim, carried inside the record.

    An evidence snapshot naming observation ids and a model version says which readings
    were involved. It does not let anyone re-run the prediction: the ids are pointers
    into a store the reader may not have, in an order the record does not fix.

    Carrying the ordered values, the metric, the horizon and the model version means a
    consumer holding nothing but the exported record can call the predictor and check
    that it still returns the claim on file. That is the difference between a record you
    can read and a record you can verify -- and it is what "reconstruct the claim from
    the record" has to mean if the phrase is going to be used at all.
    """

    metric: str
    values: tuple[float, ...]
    horizon_seconds: int
    model_version: str
    input_fingerprint: str

    def as_record(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "values": [f"{v:.6f}" for v in self.values],
            "horizon_seconds": self.horizon_seconds,
            "model_version": self.model_version,
            "input_fingerprint": self.input_fingerprint,
            "bound_inputs": [b.as_record() for b in self.bound_inputs],
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "PredictionInputs":
        return cls(
            metric=r["metric"],
            values=tuple(float(v) for v in r["values"]),
            horizon_seconds=int(r["horizon_seconds"]),
            model_version=r["model_version"],
            input_fingerprint=r["input_fingerprint"],
            bound_inputs=tuple(
                PredictionInput.from_record(b) for b in r.get("bound_inputs", ())
            ),
        )
    bound_inputs: tuple[PredictionInput, ...] = ()
    """Per-value provenance. REQUIRED -- see `__post_init__`.

    The default exists so the field can be declared after the others without reordering
    every construction site, exactly as `declared_envelope` and `rendered_at` do. It is
    not a permitted value.
    """

    def __post_init__(self) -> None:
        # EMPTY IS NOT A PERMITTED STATE, AND IT USED TO BE.
        #
        # `PredictionInput` exists because "an evidence digest over observations and,
        # separately, a tuple of values" connects nothing: a producer can cite genuine
        # readings, carry their perfectly valid digest, and put unrelated numbers in the
        # inputs. Both halves validate independently and the replay reproduces whatever
        # the record supplied rather than what the cited evidence says.
        #
        # One explicit join closed that -- and the join was skipped when there was
        # nothing in it. Every check downstream reads `if pi.bound_inputs:`, so an EMPTY
        # tuple disabled all of them, and the docstring here said so in as many words:
        # "Empty means the values are unbound assertions." An unbound assertion is exactly
        # the state this type was introduced to make impossible, and it was reachable by
        # leaving a field out.
        #
        # A hostile pass built it: five fabricated values, no bound inputs, the real five
        # readings cited, the real digest, a fingerprint and a replay that both verify
        # because they are computed over the fabricated values. It released as DELIVERED
        # with a score of 0.0255 where the honest claim is 0.4942, and imported cleanly.
        #
        # Refused at construction rather than checked at each boundary: the boundaries
        # were already checking, and all three of them skipped on empty.
        if not self.bound_inputs:
            raise ValueError(
                "prediction inputs with no bound observations are unbound assertions: "
                "the values would replay to a claim while the cited readings say "
                "something else entirely, which is the one thing this type exists to "
                "make impossible"
            )
        bound = tuple(b.value_used for b in self.bound_inputs)
        if bound != tuple(self.values):
            raise ValueError(
                "bound_inputs disagree with values -- the record would replay "
                "numbers the cited observations do not contain"
            )
        # The wire carries values at six decimals; the fingerprint hashes them at full
        # precision. A reading of 41.0000001 therefore produced an entirely honest
        # DELIVERED product whose own envelope its own importer refused, because the
        # re-derived fingerprint no longer matched. Refused at the boundary, where the
        # producer can still do something about it, rather than discovered by a reader.
        lossy = [v for v in self.values if float(f"{v:.6f}") != v]
        if lossy:
            raise ValueError(
                f"{lossy} carry more precision than the six-decimal wire form preserves, "
                f"so this record would not survive its own round trip; quantize the "
                f"readings before they enter the claim rather than after"
            )


@dataclass(frozen=True)
class EvidenceSnapshot:
    """What was known at delivery time, captured at delivery time.

    Captured eagerly and deliberately: a snapshot assembled after the fact is a
    reconstruction of a reconstruction, and inherits every gap that opened in
    between.
    """

    observation_ids: tuple[str, ...]
    model_version: str | None
    semantic_rule_version: str | None
    identity_confidence: float | None
    """Confidence that the subject was correctly resolved. None means unresolved.

    An input, not something this module computes -- mature entity-resolution products
    exist. What is modelled here is the *consequence* of identity uncertainty.
    """

    def __post_init__(self) -> None:
        if self.captured_at is None:
            raise ValueError(
                "captured_at is required -- evidence with no capture time cannot be "
                "shown to have existed at delivery"
            )
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must carry a timezone")
        if self.identity_confidence is not None and not (
            0.0 <= self.identity_confidence <= 1.0
        ):
            raise ValueError(
                f"identity_confidence {self.identity_confidence} outside [0, 1]"
            )
        # A value that cannot be a SHA-256 is a malformed input, not a business
        # withholding, and the shape is knowable here without the readings. It used to be
        # checked only in `assess_evidence`, which has the observations -- so release
        # reported integrity=BROKEN and the import boundary, which has neither, delivered.
        digest = self.evidence_content_digest
        if digest is not None and (
            len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower())
        ):
            raise ValueError(
                f"{digest!r} cannot be a content digest; a record whose integrity field "
                f"is not even the right shape has nothing for a reader to check against"
            )
        # Every reading the model actually consumed must be one the record tells a reader
        # to follow. Both lists are on the wire -- the cited ids, and the ids replayed in
        # `prediction_inputs.bound_inputs` -- and nothing compared them at import, so a
        # record cited five readings that produced nothing in it and graded itself VALID.
        #
        # SUBSET, not equality, and the scenario is what settled it. An intermediate
        # version of this check demanded the two lists be identical, on the reasoning that
        # `assess_evidence` requires the cited ids to equal the bundle. That conflates two
        # different comparisons: release compares the citation to the BUNDLE, and this
        # compares it to what the model CONSUMED. The reference scenario collects from two
        # feeds and computes over one, so it cites nine readings and binds five -- honest
        # over-collection, which equality refused outright.
        #
        # What must never happen is the other direction: a reading the claim was computed
        # from that the record does not tell a reader to look at.
        # `and pi.bound_inputs` is gone from this condition: `PredictionInputs`
        # refuses an empty tuple, so the only reachable absence is the whole object.
        pi = self.prediction_inputs
        if pi is not None:
            bound = {b.observation_id for b in pi.bound_inputs}
            uncited = sorted(bound - set(self.observation_ids))
            if uncited:
                raise ValueError(
                    f"the claim was computed from {uncited}, which the snapshot never "
                    f"cites; the pointers a reader follows are not the readings the "
                    f"number came from"
                )

    prediction_inputs: PredictionInputs | None = None
    """The inputs needed to re-run the predictor. See `PredictionInputs`."""

    evidence_content_digest: str | None = None
    """SHA-256 binding this snapshot to the *contents* of the observations it cites.

    Without it, `observation_ids` are bare pointers. A digest over the serialized
    record then proves the record unaltered and proves nothing whatever about the
    evidence: change the value behind an id and every pointer still resolves, every
    signature still verifies, and the reconstruction confidently describes a reading
    that no longer exists.

    Compute with `bitemporal.digest_observations`. It is tamper-evident, not
    tamper-proof -- a party who controls the readings can alter them and recompute it.
    """

    subject: str = ""
    """What the cited readings are about.

    The snapshot recorded which observations a claim rested on and never what they were
    OBSERVATIONS OF, so `claim.subject` was a free variable: every check that consumed a
    subject read it from the claim itself, and relabelling the asset consistently across
    the claim, the identity assertion, the entitlement and the rendered card produced a
    delivered product about one machine computed entirely from another's telemetry.

    Absent here counts as MISSING rather than as a permissive default, which is the same
    treatment every other element of this snapshot gets.
    """

    source_systems: tuple[str, ...] = ()
    captured_at: datetime | None = None
    """When this snapshot was taken. Required, and never defaulted to a wall clock.

    It used to default to `datetime.now()`. The hero built the snapshot without setting
    it and stamped the product as delivered on 12 June, so an August run produced a
    record delivered in June whose evidence was captured in August -- a reconstruction of
    a reconstruction, which is the exact failure the fourth release question exists to
    prevent. The system was committing the sin the paper warns about.
    """

    def as_record(self) -> dict[str, Any]:
        """The portable form this class did not have.

        `IntelligenceProduct.as_record()` omitted evidence altogether, so the bundle that
        claimed to preserve the in-memory guarantees shipped without the evidence the
        claim rests on: no observation ids, no content digest, no predictor inputs, no
        source systems, no capture time. A reader could not check the claim against
        anything, which is the one job the portable form has.
        """
        return {
            "observation_ids": list(self.observation_ids),
            "subject": self.subject,
            "model_version": self.model_version,
            "semantic_rule_version": self.semantic_rule_version,
            "identity_confidence": (
                None if self.identity_confidence is None
                else f"{self.identity_confidence:.6f}"
            ),
            "prediction_inputs": (
                self.prediction_inputs.as_record() if self.prediction_inputs else None
            ),
            "evidence_content_digest": self.evidence_content_digest,
            "source_systems": list(self.source_systems),
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "EvidenceSnapshot":
        captured = r.get("captured_at")
        return cls(
            observation_ids=tuple(r.get("observation_ids") or ()),
            subject=r.get("subject") or "",
            model_version=r.get("model_version"),
            semantic_rule_version=r.get("semantic_rule_version"),
            identity_confidence=(
                None if r.get("identity_confidence") is None
                else float(r["identity_confidence"])
            ),
            prediction_inputs=(
                PredictionInputs.from_record(r["prediction_inputs"])
                if r.get("prediction_inputs") else None
            ),
            evidence_content_digest=r.get("evidence_content_digest"),
            source_systems=tuple(r.get("source_systems") or ()),
            captured_at=datetime.fromisoformat(captured) if captured else None,
        )

    def missing_elements(self) -> tuple[str, ...]:
        """Name what is absent. Order is stable so callers can assert on it."""
        missing: list[str] = []
        if not self.observation_ids:
            missing.append("observation_ids")
        if not self.subject:
            missing.append("subject")
        if self.model_version is None:
            missing.append("model_version")
        if self.semantic_rule_version is None:
            missing.append("semantic_rule_version")
        if self.identity_confidence is None:
            missing.append("identity_confidence")
        if self.evidence_content_digest is None:
            missing.append("evidence_content_digest")
        if self.prediction_inputs is None:
            missing.append("prediction_inputs")
        if not self.source_systems:
            missing.append("source_systems")
        return tuple(missing)

    def is_complete(self) -> bool:
        return not self.missing_elements()


@dataclass(frozen=True)
class Reconstruction:
    """The result of asking a delivered claim to justify itself."""

    status: EvidenceStatus
    missing: tuple[str, ...]
    subject: str

    def is_reconstructable(self) -> bool:
        return self.status is EvidenceStatus.RECONSTRUCTABLE

    # NOTE: `Reconstruction.as_record` follows; `EvidenceSnapshot`'s own wire form lives
    # on that class. It had none at all, which is how the evidence came to be missing
    # from the portable bundle entirely.

    def as_record(self) -> dict[str, Any]:
        """Platform-neutral form. This is the part that has to survive export."""
        return {
            "subject": self.subject,
            "status": self.status.value,
            "missing_evidence": list(self.missing),
        }
