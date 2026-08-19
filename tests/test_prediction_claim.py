"""The prediction claim must be a typed object, not four independent parameters.

WHY THIS EXISTS
---------------
We refused hand-authored `business_context` and required a derived `BusinessImpact`. We
did not do the same for the thing customers actually buy. `claim`, `prediction_horizon`,
`confidence` and the evidence arrived as independent values, so nothing structurally
required them to describe the predictor's output.

That single gap produced several separate-looking defects: a claim of "peer-benchmarked
degradation percentile" from a model that computes no percentile; a horizon in the record
that need not match the horizon in the inputs; a replay that proves the inputs reproduce a
score without proving the stored customer-facing text corresponds to that score.

One typed object closes all of them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cai.bitemporal import Observation
from cai.product import Determination
from cai.predictor import predict_degradation
from cai.formation import release

from _fixtures import derived_impact, sample_observations, ts


def _claim():
    from cai.contract import PredictionClaim

    prediction = predict_degradation(
        metric="battery_temp_c", values=(41.0, 45.6, 51.4, 58.4, 66.6),
        horizon=timedelta(days=3),
    )
    return PredictionClaim.from_prediction(
        prediction, subject="asset-4417/battery-pack",
    )


def test_the_claim_text_is_rendered_from_the_prediction_not_authored():
    """A customer-facing sentence must be derivable from the numbers behind it."""
    claim = _claim()
    assert f"{claim.score:.4f}" in claim.rendered_text()
    assert claim.metric in claim.rendered_text()
    assert claim.score_semantics in claim.rendered_text()


def test_the_claim_carries_the_semantics_of_its_own_score():
    """The predictor says its score is a relative ordering, not a probability. The claim
    has to carry that with it, or a downstream reader supplies the wrong interpretation.
    """
    claim = _claim()
    assert "relative" in claim.score_semantics.lower()
    # Not a token check. "probability" appears, and must -- as the disclaimer. What
    # matters is that the text never asserts the score IS one.
    text = claim.rendered_text().lower()
    assert "not a calibrated probability" in text


def test_horizon_cannot_disagree_between_the_claim_and_the_inputs():
    """One was an int of seconds, the other arbitrary text. They could differ."""
    from cai.contract import PredictionClaim

    prediction = predict_degradation(
        metric="battery_temp_c", values=(41.0, 45.6, 51.4), horizon=timedelta(days=3)
    )
    claim = PredictionClaim.from_prediction(prediction, subject="s")
    assert claim.horizon_seconds == int(timedelta(days=3).total_seconds())


# ---------------------------------------------------------------------------
# THE DECLARED MODEL ENVELOPE. `ApplicabilityAssertion.subject_type` asserted that a
# use fell inside an envelope the claim did not carry, which made it an assertion
# against nothing. The claim now carries what its model declares itself valid for.
# ---------------------------------------------------------------------------


def test_a_claim_carries_the_envelope_its_model_declares():
    """The envelope is the predictor's, taken from the predictor, not re-stated."""
    from cai.predictor import declared_envelope

    claim = _claim()
    assert claim.declared_envelope == declared_envelope()
    assert claim.metric in claim.declared_envelope.supported_metrics
    assert claim.horizon_seconds <= claim.declared_envelope.max_horizon_seconds


def test_a_claim_whose_metric_is_outside_its_declared_envelope_is_refused():
    """A claim about something its own envelope does not admit is self-contradictory."""
    from cai.contract import PredictionClaim

    with pytest.raises(ValueError, match="metric|envelope"):
        PredictionClaim(**{**_claim().__dict__, "metric": "peer_benchmark_percentile"})


def test_a_claim_whose_envelope_names_another_model_is_refused():
    """An envelope belonging to a different model describes different limits."""
    from cai.contract import PredictionClaim
    from cai.predictor import ModelEnvelope

    claim = _claim()
    with pytest.raises(ValueError, match="envelope|model"):
        PredictionClaim(**{
            **claim.__dict__,
            "declared_envelope": ModelEnvelope(
                **{**claim.declared_envelope.__dict__,
                   "model_version": "some-other-model@9.9"}
            ),
        })


def test_a_claim_whose_horizon_exceeds_its_declared_envelope_is_refused():
    """The predictor refuses to answer beyond its maximum; the claim must not assert one."""
    from cai.contract import PredictionClaim

    claim = _claim()
    beyond = claim.declared_envelope.max_horizon_seconds + 1
    with pytest.raises(ValueError, match="horizon|envelope"):
        PredictionClaim(**{**claim.__dict__, "horizon_seconds": beyond})


def test_a_claim_at_the_envelope_boundary_still_constructs():
    """Non-triviality twin: the refusal is of exceeding the bound, not of reaching it."""
    from cai.contract import PredictionClaim

    claim = _claim()
    at_edge = PredictionClaim(**{
        **claim.__dict__,
        "horizon_seconds": claim.declared_envelope.max_horizon_seconds,
    })
    assert at_edge.horizon_seconds == claim.declared_envelope.max_horizon_seconds


# ---------------------------------------------------------------------------
# P0-10 -- the evidence snapshot must not be captured after it was delivered
# ---------------------------------------------------------------------------


def test_an_evidence_snapshot_with_no_capture_time_is_refused():
    """RENAMED. The old name claimed the postdates-delivery rule and tested this instead.

    This fixture passes `captured_at=None` and trips the required-field check; it never
    reaches `IntelligenceProduct`'s comparison against delivery time. That rule is real
    and is covered by `test_formation.test_evidence_captured_after_delivery_is_refused`
    and the `evidence postdates delivery` wire case -- but a maintainer reading the old
    name here would have believed it was guarded twice when it was guarded once.

    What this DOES test is still worth testing: captured_at defaulted to now(), so an
    August run produced a record delivered in June with evidence captured in August.
    """
    from cai.contract import EvidenceSnapshot

    with pytest.raises(ValueError, match="captured"):
        EvidenceSnapshot(
            observation_ids=("o-1",),
            model_version="m",
            semantic_rule_version="r",
            identity_confidence=0.9,
            captured_at=None,
        )


def test_captured_at_has_no_wallclock_default():
    """A default of now() is the mechanism that produced the impossible record."""
    import inspect

    from cai.contract import EvidenceSnapshot

    param = inspect.signature(EvidenceSnapshot).parameters["captured_at"]
    assert param.default is inspect.Parameter.empty or param.default is None, (
        "captured_at must not default to a wall-clock reading"
    )
