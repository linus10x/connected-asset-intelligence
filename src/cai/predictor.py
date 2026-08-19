"""A deliberately simple, deliberately interpretable degradation baseline.

WHY THIS IS SIMPLE ON PURPOSE
-----------------------------
The point of this repository is not that the model is good. It is that a claim
produced by a model can be governed and, later, defended. A sophisticated model would
actively obscure that: readers would evaluate the model and miss the contract.

So the predictor here is a monotonic degradation fit that any reader can verify by
hand in a minute. It is a placeholder in the honest sense — swap in a gradient-boosted
survival model and nothing downstream changes, which is precisely the claim being made.

WHAT IT MUST DO ANYWAY
----------------------
Being simple does not excuse being sloppy. This predictor still has to:

  * declare what it is valid for, and refuse politely outside that envelope
  * carry a version and a fingerprint of the exact inputs that determined it
  * emit uncertainty rather than a bare point estimate
  * be deterministic, so the same inputs reproduce the same claim forever

The last one matters more than it looks. A reconstruction is worthless if re-running
the predictor on the recorded inputs produces a different answer than the one on
file.
"""

from __future__ import annotations

import hashlib
import math
import pathlib
from dataclasses import dataclass
from datetime import timedelta

MODEL_VERSION = "degradation-baseline@1.3.0"


def model_artifact_digest() -> str:
    """SHA-256 of this module's source.

    A version string is a promise somebody has to keep by hand. Edit the algorithm,
    forget to bump 1.3.0, and a stored claim replays to a different answer under the same
    name -- which is precisely the failure a reconstruction artifact cannot have.
    """
    return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()

# The envelope this model is honest about. Outside it, the model abstains rather
# than extrapolating, because extrapolation is where an interpretable model quietly
# becomes a confident liar.
MIN_OBSERVATIONS = 3
MAX_HORIZON = timedelta(days=7)


@dataclass(frozen=True)
class MetricApplicability:
    """One metric on one kind of subject. The unit this model is actually fitted for.

    WHY A PAIR AND NOT TWO SETS
    ---------------------------
    The envelope declared `supported_metrics` and `supported_subject_types` as independent
    tuples, and independence is a cross-product. Two metrics and two subject types declare
    four combinations, of which this model is fitted for two: a `battery_temp_c` series
    off a hydraulic system, or a `hydraulic_pressure_kpa` series off a battery pack, were
    each composed of an individually valid metric and an individually valid subject type,
    and satisfied an envelope that had no way to say otherwise.

    That is not hypothetical arithmetic. `predict_degradation` orients the sign of the
    trend by metric -- pressure degrades downward, temperature upward -- so the model
    genuinely answers a different question per metric, and which physical thing the series
    came off decides whether that answer means anything.

    DELIBERATELY NOT A CAPABILITY FRAMEWORK
    ---------------------------------------
    Two fields and a tuple. One reference predictor declares which combinations it
    supports; there is no registry, no negotiation, no matching language. The flat views
    the refusal paths use are DERIVED from these, so widening a pair widens both and an
    operator cannot produce a model that admits more than it declares.
    """

    metric: str
    subject_type: str

    def __post_init__(self) -> None:
        if not self.metric or not self.subject_type:
            raise ValueError(
                "an applicability pair naming no metric or no subject type bounds "
                "nothing; an empty half reads as 'anything' to every caller"
            )

    def as_record(self) -> dict[str, str]:
        return {"metric": self.metric, "subject_type": self.subject_type}

    @classmethod
    def from_record(cls, r: dict[str, str]) -> "MetricApplicability":
        return cls(metric=str(r["metric"]), subject_type=str(r["subject_type"]))


SUPPORTED_APPLICABILITY = (
    MetricApplicability("battery_temp_c", "forklift/battery-pack"),
    MetricApplicability("hydraulic_pressure_kpa", "forklift/hydraulic-system"),
)
"""Exactly what this reference predictor is fitted for. Nothing invented.

These are the two combinations the scenario and the reference predictor already use. A
third would need a model that had been fitted for it, and this file is not the place to
assert one exists.

Narrow on purpose. The refusal paths below check the metric, the observation count and
the horizon; none of them can tell that a `battery_temp_c` series came off a wind-turbine
gearbox instead of a forklift pack. That is a question about the subject, not about the
numbers, so it is answered by the assurance layer -- which needs something to answer it
*against*, and a pair is what that something has to be.
"""

SUPPORTED_METRICS = tuple(dict.fromkeys(a.metric for a in SUPPORTED_APPLICABILITY))
SUPPORTED_SUBJECT_TYPES = tuple(
    dict.fromkeys(a.subject_type for a in SUPPORTED_APPLICABILITY)
)
"""The flat views, DERIVED. They were the declaration and are now a projection of it, so
the two cannot disagree about what this model admits."""


@dataclass(frozen=True)
class ModelEnvelope:
    """What this predictor declares itself valid for, as a portable object.

    WHY THE CLAIM HAS TO CARRY IT
    -----------------------------
    `ApplicabilityAssertion` answers "does THIS use satisfy the model's declared
    envelope". For several revisions there was no declared envelope: the assertion
    carried a `subject_type`, a `valid` boolean and a basis string, and compared them
    against nothing. That is not an applicability check, it is a caller repeating what
    they would like to be true, and the assurance layer recorded it as though somebody
    had verified something.

    The envelope travels ON the claim rather than being looked up at verification time,
    because the question a reconstruction asks eighteen months later is what the model
    declared *then*. A lookup against today's module answers a different question and
    answers it confidently.

    Deliberately NOT a plugin platform. One reference predictor declares one envelope;
    the shape is what a second implementation would have to publish, not a registry for
    models this repository does not have.
    """

    model_version: str
    model_artifact_digest: str
    supported_applicability: tuple[MetricApplicability, ...]
    """WHICH COMBINATIONS, not which metrics and separately which subject types.

    Two independent sets are a cross-product, and this model is not fitted for the
    cross-product. The flat views below are derived from this, so there is one declaration
    and two projections of it rather than three things that have to agree.
    """

    min_observations: int
    max_horizon_seconds: int

    def __post_init__(self) -> None:
        if not self.supported_applicability:
            raise ValueError(
                "an envelope declaring no metric/subject-type combination places no bound "
                "on use; an empty declaration reads as 'anything' to every caller"
            )
        if len(set(self.supported_applicability)) != len(self.supported_applicability):
            raise ValueError(
                "an envelope declaring the same combination twice says nothing twice; "
                "duplicates make the declaration's length meaningless to a reader"
            )
        if self.max_horizon_seconds <= 0 or self.min_observations <= 0:
            raise ValueError("an envelope's bounds must be positive to bound anything")

    @property
    def supported_metrics(self) -> tuple[str, ...]:
        """Derived. Order-preserving so the record and a reader agree on presentation."""
        return tuple(dict.fromkeys(a.metric for a in self.supported_applicability))

    @property
    def supported_subject_types(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(a.subject_type for a in self.supported_applicability))

    def admits_metric(self, metric: str) -> bool:
        return metric in self.supported_metrics

    def admits_subject_type(self, subject_type: str) -> bool:
        return subject_type in self.supported_subject_types

    def admits_pair(self, metric: str, subject_type: str) -> bool:
        """The question the two flat checks together could not ask.

        `admits_metric(m) and admits_subject_type(s)` is true for every cell of the
        cross-product. This is true only for the cells the model was fitted for.
        """
        return MetricApplicability(metric, subject_type) in self.supported_applicability

    def admits_horizon(self, horizon_seconds: int) -> bool:
        return 0 < horizon_seconds <= self.max_horizon_seconds

    def as_record(self) -> dict[str, object]:
        # `supported_metrics` and `supported_subject_types` are NOT written. They are
        # derived views, and a derived value on the wire is a second authority -- one that
        # would have to be re-derived and compared, for no information a reader cannot get
        # from the pairs themselves.
        return {
            "model_version": self.model_version,
            "model_artifact_digest": self.model_artifact_digest,
            "supported_applicability": [
                a.as_record() for a in self.supported_applicability
            ],
            "min_observations": self.min_observations,
            "max_horizon_seconds": self.max_horizon_seconds,
        }

    @classmethod
    def from_record(cls, r: dict[str, object]) -> "ModelEnvelope":
        return cls(
            model_version=str(r["model_version"]),
            model_artifact_digest=str(r["model_artifact_digest"]),
            supported_applicability=tuple(
                MetricApplicability.from_record(a)
                for a in r["supported_applicability"]  # type: ignore[union-attr]
            ),
            min_observations=int(r["min_observations"]),  # type: ignore[arg-type]
            max_horizon_seconds=int(r["max_horizon_seconds"]),  # type: ignore[arg-type]
        )


def declared_envelope() -> ModelEnvelope:
    """The envelope, built from the constants the refusal paths are written in terms of.

    Assembled here rather than written out again, so an operator widening MAX_HORIZON
    cannot produce a model that admits more than it declares.
    """
    return ModelEnvelope(
        model_version=MODEL_VERSION,
        model_artifact_digest=model_artifact_digest(),
        supported_applicability=SUPPORTED_APPLICABILITY,
        min_observations=MIN_OBSERVATIONS,
        max_horizon_seconds=int(MAX_HORIZON.total_seconds()),
    )


class OutsideApplicability(Exception):
    """Raised when the model is asked something it has no business answering."""


@dataclass(frozen=True)
class Prediction:
    """A risk estimate with everything needed to judge it later."""

    risk: float
    """Probability-like score in [0, 1]. Not calibrated against real outcomes --
    see `calibration_note`, which says so out loud."""

    confidence: float
    """How much weight to put on `risk`, given how much evidence supported it."""

    horizon: timedelta
    model_version: str
    input_fingerprint: str
    feature_names: tuple[str, ...]
    calibration_note: str

    # RESTORED on a Control Tower ruling, for the reason given in `context.py`: §12(D)
    # authorised deleting dead GUARDS, not importable methods, and this one is importable.
    def is_actionable(self, floor: float) -> bool:
        return self.confidence >= floor


def _input_fingerprint(
    *,
    metric: str,
    values: tuple[float, ...],
    horizon: timedelta,
    model_version: str,
    bound: tuple[tuple[str, str], ...] = (),
) -> str:
    """Stable hash of everything that determined this prediction.

    WHY THIS IS NOT CALLED A TRAINING FINGERPRINT
    ---------------------------------------------
    It was, and the name was wrong twice over. There is no training process here -- the
    model is a closed-form fit computed at call time. And the old version hashed the
    ordered numeric values and nothing else, so the same numbers read as a temperature
    series and as a pressure series produced an identical fingerprint despite yielding
    different predictions, in opposite directions. A fingerprint that collides across
    inputs that change the answer is worse than none: it invites a reconstruction to
    conclude two different claims came from the same evidence.

    Metric, horizon and model version are therefore part of the hash. The full digest is
    kept rather than truncated -- 64 bits saved nothing anybody needed and weakened the
    only property the value has.
    """
    payload = "\x1f".join(
        (
            model_version,
            metric,
            str(int(horizon.total_seconds())),
            # float.hex() round-trips exactly. Formatting to six decimals meant two
            # inputs differing beyond the sixth place shared a fingerprint while
            # producing different predictions -- quantizing the inputs before hashing
            # them undoes the reason for keeping the full digest.
            ",".join(v.hex() for v in values),
            # The observations these values came from. Without them the fingerprint
            # protects the numbers and says nothing about their provenance, so a record
            # could cite one set of readings and replay a different set of values.
            ";".join(f"{oid}={digest}" for oid, digest in bound),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def input_fingerprint_for(
    *,
    metric: str,
    values: tuple[float, ...],
    horizon_seconds: int,
    model_version: str,
    bound: tuple[tuple[str, str], ...] = (),
) -> str:
    """The fingerprint a set of recorded inputs implies, computed without the model.

    Published so a verifier holding nothing but an exported record can re-derive the
    fingerprint and check it against the claim, rather than comparing the record's copy of
    the fingerprint to the record's other copy of the fingerprint -- which proves only
    that the record agrees with itself.

    Pure in metric, values, horizon and model version, so it holds for a record produced
    by a build of this predictor that the verifier does not have.
    """
    return _input_fingerprint(
        metric=metric,
        values=tuple(values),
        horizon=timedelta(seconds=horizon_seconds),
        model_version=model_version,
        bound=bound,
    )


def predict_degradation(
    *,
    metric: str,
    values: tuple[float, ...],
    horizon: timedelta,
    bound: tuple[tuple[str, str], ...] = (),
) -> Prediction:
    """Estimate degradation risk from an ordered series of readings.

    Deterministic: identical inputs always produce an identical Prediction, which is
    what makes a stored claim re-checkable years later.

    Raises OutsideApplicability rather than guessing when asked to work beyond its
    declared envelope. A model that answers everything is a model that cannot be
    trusted on anything.
    """
    if any(not math.isfinite(v) for v in values):
        raise OutsideApplicability("telemetry contains a non-finite value")
    if horizon <= timedelta(0):
        raise OutsideApplicability(f"horizon {horizon} must be positive")
    if metric not in SUPPORTED_METRICS:
        raise OutsideApplicability(
            f"metric {metric!r} not in declared envelope {SUPPORTED_METRICS}"
        )
    if len(values) < MIN_OBSERVATIONS:
        raise OutsideApplicability(
            f"{len(values)} observations, minimum {MIN_OBSERVATIONS}"
        )
    if horizon > MAX_HORIZON:
        raise OutsideApplicability(
            f"horizon {horizon} exceeds declared maximum {MAX_HORIZON}"
        )

    # Monotonic trend: mean step between consecutive readings, normalised by the
    # magnitude of the series so that the score is comparable across metrics.
    steps = [b - a for a, b in zip(values, values[1:])]
    mean_step = sum(steps) / len(steps)
    scale = max(abs(v) for v in values) or 1.0

    # hydraulic pressure degrades downward, temperature upward. Orienting the sign
    # here rather than at the call site keeps the caller from having to know.
    direction = -1.0 if metric == "hydraulic_pressure_kpa" else 1.0
    normalised = (mean_step * direction) / scale

    horizon_factor = horizon / MAX_HORIZON
    raw = normalised * 12.0 * horizon_factor
    risk = max(0.0, min(1.0, raw))

    # Confidence grows with evidence and saturates -- more readings help, but not
    # without limit, and never to certainty.
    confidence = min(0.95, 0.45 + 0.06 * len(values))

    return Prediction(
        risk=round(risk, 4),
        confidence=round(confidence, 4),
        horizon=horizon,
        model_version=MODEL_VERSION,
        input_fingerprint=_input_fingerprint(
            metric=metric, values=values, horizon=horizon,
            model_version=MODEL_VERSION, bound=bound,
        ),
        feature_names=(metric,),
        calibration_note=(
            "Illustrative baseline fitted on synthetic data. Risk is a relative "
            "ordering, NOT a calibrated probability of real-world failure. No claim "
            "is made that this generalises to production telemetry."
        ),
    )
