"""Tests for the degradation baseline.

The model is deliberately simple, so these tests do not chase accuracy — there is no
ground truth to be accurate against, and pretending otherwise would be the exact
theatre this project avoids.

What they do check is the part that has to hold regardless of which model sits here:
determinism, a declared applicability envelope that is actually enforced, uncertainty
that is emitted rather than hidden, and a fingerprint that ties a claim to the data it
came from.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cai.predictor import (
    MAX_HORIZON,
    MIN_OBSERVATIONS,
    MODEL_VERSION,
    SUPPORTED_METRICS,
    OutsideApplicability,
    predict_degradation,
)

RISING = (41.0, 43.5, 46.2, 49.0, 52.1)
FLAT = (41.0, 41.0, 41.0, 41.0, 41.0)
FALLING_PRESSURE = (980.0, 962.0, 941.0, 918.0)


def test_determinism_same_inputs_same_claim_forever():
    """A reconstruction is worthless if re-running the model contradicts the record."""
    a = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    b = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    assert a == b


def test_fingerprint_ties_a_claim_to_its_inputs():
    """Different data must produce a different fingerprint, identical data the same."""
    a = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    b = predict_degradation(
        metric="battery_temp_c", values=FLAT, horizon=timedelta(days=3)
    )
    c = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    assert a.input_fingerprint != b.input_fingerprint
    assert a.input_fingerprint == c.input_fingerprint


def test_degrading_series_scores_higher_than_stable_one():
    """Non-triviality: the model must actually discriminate.

    Without this, a predictor returning a constant would satisfy every other test
    here -- the same vacuous-stub failure caught elsewhere in this suite.
    """
    degrading = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    stable = predict_degradation(
        metric="battery_temp_c", values=FLAT, horizon=timedelta(days=3)
    )
    assert degrading.risk > stable.risk
    assert stable.risk == 0.0


def test_direction_is_metric_aware():
    """Falling pressure is degradation; falling temperature is not."""
    pressure = predict_degradation(
        metric="hydraulic_pressure_kpa",
        values=FALLING_PRESSURE,
        horizon=timedelta(days=3),
    )
    assert pressure.risk > 0.0, "falling pressure should register as degradation"

    cooling = predict_degradation(
        metric="battery_temp_c",
        values=tuple(reversed(RISING)),
        horizon=timedelta(days=3),
    )
    assert cooling.risk == 0.0, "cooling should not register as thermal degradation"


def test_refuses_unsupported_metric():
    with pytest.raises(OutsideApplicability, match="not in declared envelope"):
        predict_degradation(
            metric="tyre_pressure_psi", values=RISING, horizon=timedelta(days=3)
        )


def test_refuses_insufficient_observations():
    with pytest.raises(OutsideApplicability, match="minimum"):
        predict_degradation(
            metric="battery_temp_c", values=(41.0, 42.0), horizon=timedelta(days=3)
        )


def test_refuses_horizon_beyond_declared_maximum():
    """The model must not extrapolate past what it claims to support."""
    with pytest.raises(OutsideApplicability, match="exceeds declared maximum"):
        predict_degradation(
            metric="battery_temp_c",
            values=RISING,
            horizon=MAX_HORIZON + timedelta(days=1),
        )


def test_accepts_the_boundary_horizon():
    """Anti-conservatism: the declared maximum must itself be allowed.

    An off-by-one here would make the envelope narrower than advertised, which is a
    quieter kind of dishonesty than extrapolating.
    """
    p = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=MAX_HORIZON
    )
    assert p.risk >= 0.0


def test_confidence_grows_with_evidence_but_never_reaches_certainty():
    few = predict_degradation(
        metric="battery_temp_c", values=RISING[:3], horizon=timedelta(days=3)
    )
    many = predict_degradation(
        metric="battery_temp_c", values=RISING * 3, horizon=timedelta(days=3)
    )
    assert many.confidence > few.confidence
    assert many.confidence < 1.0, "no evidence volume should yield certainty"


def test_risk_stays_within_bounds():
    """A runaway series must saturate rather than emit a nonsense score."""
    extreme = tuple(float(v) for v in range(0, 500, 25))
    p = predict_degradation(
        metric="battery_temp_c", values=extreme, horizon=MAX_HORIZON
    )
    assert 0.0 <= p.risk <= 1.0


def test_carries_version_and_states_its_own_limits():
    """The claim must arrive with its provenance and an honest caveat attached."""
    p = predict_degradation(
        metric="battery_temp_c", values=RISING, horizon=timedelta(days=3)
    )
    assert p.model_version == MODEL_VERSION
    assert p.feature_names == ("battery_temp_c",)
    assert "NOT a calibrated probability" in p.calibration_note


# ---------------------------------------------------------------------------
# THE DECLARED ENVELOPE. The model refused outside its limits and never published
# them, so `ApplicabilityAssertion` asserted a use fell inside an envelope no object
# carried. These assert the declaration is the same one the code enforces, rather than
# a second copy of it free to drift.
# ---------------------------------------------------------------------------


def test_the_declared_envelope_reports_the_limits_the_model_actually_enforces():
    """A published envelope restating the limits by hand is a second authority.

    Each field below is compared against the constant the refusal paths above are
    written in terms of, so an operator widening MAX_HORIZON without touching the
    declaration cannot produce a model that admits more than it says it does.
    """
    from cai.predictor import (
        MIN_OBSERVATIONS,
        SUPPORTED_METRICS,
        declared_envelope,
        model_artifact_digest,
    )

    env = declared_envelope()
    assert env.model_version == MODEL_VERSION
    assert env.model_artifact_digest == model_artifact_digest()
    assert env.supported_metrics == SUPPORTED_METRICS
    assert env.min_observations == MIN_OBSERVATIONS
    assert env.max_horizon_seconds == int(MAX_HORIZON.total_seconds())
    assert env.supported_subject_types, "an envelope admitting no subject type admits use"


def test_the_envelope_admits_what_the_model_answers_and_refuses_what_it_does_not():
    """Both directions. An envelope that admits everything is decorative, and one that
    admits nothing would pass every refusal test in this file."""
    from cai.predictor import declared_envelope

    env = declared_envelope()
    assert env.admits_metric("battery_temp_c")
    assert not env.admits_metric("peer_benchmark_percentile")
    assert env.admits_horizon(int(MAX_HORIZON.total_seconds()))
    assert not env.admits_horizon(int(MAX_HORIZON.total_seconds()) + 1)
    assert env.admits_subject_type(env.supported_subject_types[0])
    assert not env.admits_subject_type("wind-turbine/gearbox")


# ---------------------------------------------------------------------------
# INPUT FINGERPRINT. Added after an audit found it collided across inputs that
# change the answer -- it hashed the numbers and nothing else.
# ---------------------------------------------------------------------------


def test_fingerprint_distinguishes_metrics_with_identical_values():
    """The collision that mattered most.

    These two series are numerically identical and predict in opposite directions:
    rising temperature degrades, rising pressure does not. A fingerprint that cannot
    tell them apart invites a reconstruction to conclude two different claims came from
    the same evidence.
    """
    values = (900.0, 910.0, 920.0, 930.0)
    a = predict_degradation(
        metric="battery_temp_c", values=values, horizon=timedelta(days=3)
    )
    b = predict_degradation(
        metric="hydraulic_pressure_kpa", values=values, horizon=timedelta(days=3)
    )
    assert a.risk != b.risk, "fixture no longer exercises opposite directions"
    assert a.input_fingerprint != b.input_fingerprint


def test_fingerprint_distinguishes_horizons():
    """Same readings, different horizon, different answer -- so different fingerprint."""
    values = (41.0, 45.6, 51.4, 58.4)
    a = predict_degradation(metric="battery_temp_c", values=values, horizon=timedelta(days=1))
    b = predict_degradation(metric="battery_temp_c", values=values, horizon=timedelta(days=6))
    assert a.risk != b.risk
    assert a.input_fingerprint != b.input_fingerprint


def test_fingerprint_is_stable_for_identical_inputs():
    """Non-triviality twin: it must not simply differ every time.

    A fingerprint that changes on identical inputs cannot support the determinism claim
    the module makes about itself.
    """
    kwargs = dict(
        metric="battery_temp_c", values=(41.0, 45.6, 51.4), horizon=timedelta(days=3)
    )
    assert (
        predict_degradation(**kwargs).input_fingerprint
        == predict_degradation(**kwargs).input_fingerprint
    )


def test_fingerprint_is_a_full_sha256():
    """Truncation bought nothing and weakened the only property the value has."""
    p = predict_degradation(
        metric="battery_temp_c", values=(41.0, 45.6, 51.4), horizon=timedelta(days=3)
    )
    assert len(p.input_fingerprint) == 64


def test_the_upper_clamp_actually_binds():
    """`min(1.0, raw)` was deletable with the suite green.

    `test_risk_stays_within_bounds` never reaches saturation, so the clamp -- the only
    thing keeping a runaway series from reporting a risk above 1.0, which every downstream
    reader treats as a probability-like score -- was unguarded. A steeply accelerating
    series scores 3.5556 without it.
    """
    runaway = tuple(float(v) for v in (10, 60, 160, 360, 760))
    p = predict_degradation(
        metric="battery_temp_c", values=runaway, horizon=MAX_HORIZON
    )
    assert p.risk == 1.0, "a runaway series must saturate at the top of the range"


def test_the_declared_maximum_horizon_is_pinned_to_a_literal():
    """Every envelope assertion is written in terms of MAX_HORIZON itself, so changing
    7 days to 10 years leaves the suite green while the model silently starts answering
    questions it has no business answering. One literal, stated once."""
    assert MAX_HORIZON == timedelta(days=7)
    assert MIN_OBSERVATIONS == 3
    assert SUPPORTED_METRICS == ("battery_temp_c", "hydraulic_pressure_kpa")


def test_a_non_positive_horizon_is_refused():
    """Asserted as fact in `test_a_zero_length_interval_is_refused`'s docstring, which
    reasons that a zero-length window "derives a zero horizon, which the predictor
    refuses". It does; nothing tested that it does."""
    from cai.predictor import OutsideApplicability

    with pytest.raises(OutsideApplicability, match="must be positive"):
        predict_degradation(
            metric="battery_temp_c", values=RISING, horizon=timedelta(0)
        )
