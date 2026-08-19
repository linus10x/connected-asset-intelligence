"""Invariants of the formation -> assurance -> release path.

MIGRATION NOTE
--------------
These replace the equivalents in test_release_join.py, test_epistemic_integrity.py and the
release portions of test_integration_chain.py. Every one is either the SAME invariant on
the new signature, or a STRONGER one made possible by the typed model. The ledger in
MIGRATION_LEDGER.md maps old test to new test and states which of the two it is.

Nothing here relaxes a safety assertion. Where an old assertion became unreachable -- for
example "build_product refuses author-supplied context" -- it is replaced by a structural
test proving the parameter cannot exist at all, which is a stronger guarantee than proving
a caller who passes it gets refused.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from cai.action import ActionRecommendation, ActionType, Priority
from cai.bitemporal import Observation, digest_observations
from cai.candidate import (
    ApplicabilityAssertion,
    AssuranceContext,
    EntitlementAssertion,
    IdentityAssertion,
    IntelligenceCandidate,
    TemporalAssertion,
)
from cai.consequence import CustomerCommitmentConsequence, DowntimeConsequence
from cai.context import RULE_VERSION
from cai.contract import (
    EvidenceSnapshot,
    PredictionClaim,
    PredictionInput,
    PredictionInputs,
)
from cai.decision import DecisionContext, TimeInterval
from cai.formation import release
from cai.policy import ReleasePolicy
from cai.predictor import predict_degradation
from cai.product import Determination, ProductStatus


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def observations() -> tuple[Observation, ...]:
    return tuple(
        Observation(f"a-{i}", "asset-4417", "battery_temp_c", v, t(8 + i, 6),
                    t(8 + i, 7), "source-a")
        for i, v in enumerate((41.0, 45.6, 51.4, 58.4, 66.6))
    )


def context() -> DecisionContext:
    return DecisionContext(t(12, 7), t(12, 7), t(12, 7),
                           TimeInterval(t(12, 7), t(15, 7)))


def claim(ctx: DecisionContext | None = None) -> PredictionClaim:
    ctx = ctx or context()
    obs = observations()
    pred = predict_degradation(
        metric="battery_temp_c", values=tuple(o.value for o in obs), horizon=ctx.horizon,
        bound=tuple((o.observation_id, o.content_digest()) for o in obs),
    )
    return PredictionClaim.from_prediction(pred, subject="asset-4417/battery-pack")


def graph():
    """The operational facts, in the four systems the scenario says they live in.

    A real graph rather than a hand-built derivation: a path constructed by the test is
    the author-supplied context this model refuses, and it would pass every assertion
    about paths while proving nothing about the walk.
    """
    from cai.context import (
        Assignment,
        Component,
        ContextGraph,
        CustomerCommitment,
        LoadingWindow,
        Shipment,
    )

    g = ContextGraph()
    g.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register", installed_from=t(1),
    )
    g.assignments.append(Assignment(
        "asset-4417", "zone-3", t(8), t(8, 1), source_system="yard-management"))
    g.windows.append(LoadingWindow(
        "win-9", "zone-3", t(13, 5), t(13, 11), "ship-22", recorded_at=t(9),
        source_system="dock-scheduler"))
    g.shipments["ship-22"] = Shipment(
        "ship-22", "commit-7", recorded_at=t(9), source_system="transport-management")
    g.commitments["commit-7"] = CustomerCommitment(
        "commit-7", "next-day delivery window", recorded_at=t(9),
        source_system="order-management")
    return g


def derivation(ctx: DecisionContext | None = None):
    """The path the graph walk actually produces for the hero decision."""
    ctx = ctx or context()
    impact = graph().derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=ctx.prediction_window.start,
        horizon_end=ctx.prediction_window.end,
        transaction_time_cutoff=ctx.knowledge_cutoff,
    )
    assert impact.derived, "the fixture graph is meant to derive; the rules changed"
    return impact.derivation()


def commitment(**over) -> CustomerCommitmentConsequence:
    return CustomerCommitmentConsequence(
        "CUSTOMER_COMMITMENT", TimeInterval(t(13, 5), t(13, 11)),
        over.get("derivation", derivation()),
        commitment_id="commit-7", commitment_description="next-day delivery window",
        counterparty="customer A",
    )


def action() -> ActionRecommendation:
    return ActionRecommendation(
        "act-001", ActionType.INSPECT, "battery-pack-1", "maintenance", t(13, 3),
        TimeInterval(t(13, 5), t(13, 11)),
        "degradation signal over the commitment horizon", Priority.BEFORE_NEXT_USE,
    )


def candidate(**over) -> IntelligenceCandidate:
    ctx = over.get("context", context())
    return IntelligenceCandidate(
        over.get("candidate_id", "cand-001"), ctx, over.get("claim", claim(ctx)),
        over.get("consequence", commitment()), over.get("action", action()),
    )


def evidence(c: PredictionClaim, *, digest: str | None = None,
             captured_at: datetime | None = None,
             identity_confidence: float = 0.97) -> EvidenceSnapshot:
    obs = observations()
    return EvidenceSnapshot(
        observation_ids=tuple(o.observation_id for o in obs),
        subject=observations()[0].subject,
        evidence_content_digest=digest if digest is not None else digest_observations(obs),
        prediction_inputs=PredictionInputs(
            metric=c.metric, values=tuple(o.value for o in obs),
            horizon_seconds=c.horizon_seconds, model_version=c.model_version,
            input_fingerprint=c.input_fingerprint,
            bound_inputs=tuple(
                PredictionInput(o.observation_id, o.content_digest(), o.value) for o in obs
            ),
        ),
        model_version=c.model_version, semantic_rule_version=RULE_VERSION,
        identity_confidence=identity_confidence, source_systems=("source-a",),
        captured_at=captured_at or t(12, 7),
    )


def claim_over(obs, ctx: DecisionContext | None = None) -> PredictionClaim:
    """`claim()` over an arbitrary set of readings.

    Added in wave 4, where several findings can only be exercised by varying the readings
    themselves -- a late transaction time, a feed the clearance does not cover, a value
    the bundle does not carry.
    """
    ctx = ctx or context()
    pred = predict_degradation(
        metric="battery_temp_c", values=tuple(o.value for o in obs), horizon=ctx.horizon,
        bound=tuple((o.observation_id, o.content_digest()) for o in obs),
    )
    return PredictionClaim.from_prediction(pred, subject="asset-4417/battery-pack")


def evidence_over(c: PredictionClaim, obs, *, identity_confidence: float = 0.97,
                  bound_digests=None) -> EvidenceSnapshot:
    """`evidence()` over an arbitrary set of readings.

    `bound_digests` exists so a test can carry the RIGHT content digests beside the WRONG
    values -- the forgery `release.py`'s bound-input comparison describes, and the only
    construction that reaches it without the aggregate-digest arm firing first.
    """
    digests = bound_digests or tuple(o.content_digest() for o in obs)
    return EvidenceSnapshot(
        observation_ids=tuple(o.observation_id for o in obs),
        subject=obs[0].subject,
        evidence_content_digest=digest_observations(obs),
        prediction_inputs=PredictionInputs(
            metric=c.metric, values=tuple(o.value for o in obs),
            horizon_seconds=c.horizon_seconds, model_version=c.model_version,
            input_fingerprint=c.input_fingerprint,
            bound_inputs=tuple(
                PredictionInput(o.observation_id, d, o.value)
                for o, d in zip(obs, digests)
            ),
        ),
        model_version=c.model_version, semantic_rule_version=RULE_VERSION,
        identity_confidence=identity_confidence,
        source_systems=tuple(dict.fromkeys(o.source_system for o in obs)),
        captured_at=t(12, 7),
    )


# Every system whose data materially forms the delivered product: the telemetry feed the
# prediction was computed from, and the five business systems the REASON walk joined to
# turn that prediction into "your commitment to customer A is at risk".
#
# The fixture licensed `("source-a",)` and nothing else, which is how a clearance covering
# one input out of six read as a fully authorised delivery. Widening the fixture is the
# honest fix; narrowing the entitlement model to telemetry-only would have been the other
# one, and it would have made the rights check describe less than the product contains.
CONSUMED_SOURCES = (
    "asset-register",
    "dock-scheduler",
    "order-management",
    "source-a",
    "transport-management",
    "yard-management",
)


def entitlement(**over) -> EntitlementAssertion:
    """The fully scoped clearance for the hero delivery. Overridable field by field."""
    return EntitlementAssertion(**{
        "recipient": "operations@customer",
        "purpose": "operational-advisory",
        "subject": "asset-4417/battery-pack",
        "tenant": "tenant-1",
        "basis": "MSA-2026-14 cl 7.2",
        "policy_id": "pol-1",
        "policy_version": "rights-policy@3.1.0",
        "valid_from": t(1),
        "authorized_source_systems": CONSUMED_SOURCES,
        "may_use_source_data": True,
        "may_deliver_to_recipient": True,
        **over,
    })


def assurance(**over) -> AssuranceContext:
    """The four assertions a caller supplies.

    The evidence assessment is deliberately absent: the release path computes it from the
    observations and discards anything a caller offers, so a parameter for it taught every
    fixture to hand over a `fully_satisfied()` nobody had reached.
    """
    return AssuranceContext(
        over.get("identity", IdentityAssertion(
            "asset-4417/battery-pack", "resolver-a", "1.0", 0.97,
            evidence_refs=("serial-plate-scan-8841", "fleet-register-row-4417"))),
        over.get("applicability", ApplicabilityAssertion(
            "degradation-baseline@1.3.0", "forklift/battery-pack", True,
            "metric within declared envelope")),
        over.get("temporal", TemporalAssertion(
            t(12, 7), t(12, 7), t(12, 7), True,
            basis="features drawn from the point-in-time view at the knowledge cutoff")),
        over.get("entitlement", entitlement()),
    )


def log_of(obs) -> "ObservationLog":
    """An `ObservationLog` holding exactly these readings.

    Release takes the LOG now, not a bundle, so a test that wants the release path to see
    a particular set of readings puts them in a log and lets release perform its own
    point-in-time query. That is the point of the change: there is no argument left
    through which a test -- or a caller -- can assert what the log would have said.

    Note the consequence for fixtures. A reading whose transaction time postdates the
    knowledge cutoff, or whose subject is not the snapshot's, does not reach the
    assessment at all: the query excludes it. Several tests below therefore prove the
    exclusion at the release path and the refusal at the import boundary, which is where
    such a reading can still arrive.
    """
    from cai.bitemporal import ObservationLog

    log = ObservationLog()
    for observation in obs:
        log.record(observation)
    return log


def release_log():
    """The log underwriting every release test in this file.

    WAVE 4 built the equivalent fixture by calling `EvidenceBundle(...)` directly while
    its docstring claimed it went through a log -- so the fixture took the one route the
    design says is unsupported. It was then routed through `ObservationLog.evidence_for`.

    This increment removes the question: `release` accepts no bundle, so a fixture cannot
    take the unsupported route even by accident.
    """
    return log_of(observations())


def deliver(**over):
    c = over.get("candidate", candidate())
    a = over.get("assurance", assurance())
    # The snapshot's identity confidence FOLLOWS the assertion's, because the two are one
    # fact and `binding.verify_bindings` now refuses a record carrying two answers to it.
    # Threading it here rather than hardcoding 0.97 is what makes the below-floor tests
    # exercise the floor instead of the binding.
    return release(
        candidate=c, assurance=a,
        evidence=over.get("evidence", evidence(
            c.prediction_claim,
            identity_confidence=a.identity_assertion.confidence)),
        observation_log=over.get("observation_log", release_log()),
        recipient=over.get("recipient", "operations@customer"),
        purpose=over.get("purpose", "operational-advisory"),
        tenant=over.get("tenant", "tenant-1"),
        product_id=over.get("product_id", "ip-001"),
        claim_series_id=over.get("claim_series_id", "series-4417-batt"),
        release_decision_time=over.get("release_decision_time", t(12, 7)),
        # WAS t(13, 11) -- the close of the loading window, and eight hours past the
        # deadline of the action this product recommends. That made the default fixture
        # a product which reported ACTIVE long after the only instruction it carried had
        # expired, and every test built on it inherited the state.
        #
        # Now the deadline itself, which is the longest horizon `valid_until` can honestly
        # carry: `status_at` expires AT this moment, so the card goes stale exactly when
        # the work was due.
        valid_until=over.get("valid_until", t(13, 3)),
        supersedes_product_id=over.get("supersedes_product_id"),
        policy=over.get("policy"),
    )


# ---------------------------------------------------------------------------
# STRUCTURAL. The escape hatches must be impossible, not merely refused.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hatch", [
    "claim", "prediction_horizon", "recommended_action", "confidence",
    "business_context", "economic_consequence",
])
def test_the_release_path_has_no_prose_parameters(hatch):
    """STRONGER than the old test, which proved a caller passing prose was refused.

    Every recurring defect came out of one of these parameters existing. A signature that
    cannot accept them is a better guarantee than a check that rejects them.
    """
    assert hatch not in inspect.signature(release).parameters


def test_evidence_verification_is_required_not_optional():
    """An optional verification argument is one a caller forgets -- which is exactly how a
    release path once ran unverified while a separately computed assessment printed beside
    it looked correct."""
    param = inspect.signature(release).parameters["observation_log"]
    assert param.default is inspect.Parameter.empty
    assert "observations" not in inspect.signature(release).parameters, (
        "a bare tuple of readings must not be passable; it is the shape that let the "
        "integrity conflicts found in them be left behind"
    )


def test_the_legacy_scalar_release_representation_is_gone():
    """Commit 5 claimed the old scalar API was deleted. It was not.

    `ReleaseDecision` and `evaluate_release` survived in release.py -- unimported by
    anything, and calling `assess_evidence(entitlement=...)` against a signature that had
    been renamed to `entitlement_assertion`, so the legacy path was both a second semantic
    representation AND already broken. A migration ledger asserting a deletion is not the
    deletion; this asserts it against the module.
    """
    import cai.assessment as assessment_module

    assert not hasattr(assessment_module, "ReleaseDecision")
    assert not hasattr(assessment_module, "evaluate_release")


def test_the_legacy_boolean_entitlement_representation_is_gone():
    """`EntitlementAssertion` replaced it; the boolean pair survived beside it anyway.

    Two representations of one rights question is the drift surface every other part of
    this refactor exists to remove, and an unused one is worse than a used one: nothing
    exercises it, so nothing notices when a caller reaches for the weaker of the two.
    Asserted against the module rather than against a ledger entry claiming a deletion.
    """
    import cai.contract as contract_module

    assert not hasattr(contract_module, "Entitlement")


def test_no_module_reintroduces_a_scalar_rights_representation():
    """The structural half. A deleted class comes back as a helpful convenience.

    Scans the shipped source rather than the import graph, because a re-added class that
    nothing imports yet is exactly the state the original defect was found in.
    """
    import pathlib
    import re

    import cai.contract

    # Matched on the exact class name. `EntitlementState` and `EntitlementAssertion` are
    # the two representations that SHOULD exist -- the algebra's dimension and the scoped
    # rights determination -- and a prefix match would flag both, which is the kind of
    # assertion that passes for the wrong reason and fails for the wrong reason too.
    exact_class = re.compile(r"^class Entitlement\s*[(:]")
    offenders = []
    for path in sorted(pathlib.Path(cai.contract.__file__).parent.glob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if exact_class.match(stripped):
                offenders.append(f"{path.name}:{lineno} (class Entitlement)")
            if (
                stripped.startswith("may_deliver_to_recipient")
                and path.name != "candidate.py"
            ):
                offenders.append(f"{path.name}:{lineno} (scalar rights field)")
    assert not offenders, f"a scalar rights representation is back: {offenders}"


def test_the_superseded_release_policy_constant_is_gone():
    """`release.POLICY_VERSION` named release-policy@1.0.0 and decided nothing.

    `ReleasePolicy` owns the version that is actually stamped onto a decision. A second
    constant naming a different version is the same two-authorities pattern, and a reader
    auditing which rules were in force could reasonably have cited the dead one.
    """
    import cai.assessment as assessment_module

    assert not hasattr(assessment_module, "POLICY_VERSION")


def test_the_product_does_not_store_a_second_policy_version():
    """AssuranceDecision owns policy_id / policy_version / policy_digest.

    `IntelligenceProduct.release_policy_version` was a second stored copy that happened to
    agree because the same policy filled both -- the drift pattern this refactor exists to
    remove. The record still reports it, derived from the one authority.
    """
    from cai.product import IntelligenceProduct

    assert "release_policy_version" not in IntelligenceProduct.__dataclass_fields__
    product = deliver()
    assert product.as_record()["release_policy_version"] == product.assurance.policy_version


@pytest.mark.parametrize("prose", [
    "the forklift battery will fail within three days",
    "",
    0.91,
    None,
    {"claim": "battery degradation", "confidence": 0.91},
])
def test_the_candidate_refuses_prose_in_place_of_a_typed_claim(prose):
    """The signature test above guards `release`. It does not guard the aggregate root.

    Closing the parameter on `release` moved the hatch upstream rather than shutting it: a
    caller could still seat arbitrary prose in the candidate and hand THAT to `release`. The
    old annotation was `Any`, so a string was accepted, and `as_record` then wrote the claim
    out as null -- the record lost the claim entirely and nothing raised.

    An annotation is not enforcement in Python. The guarantee has to be a runtime refusal.
    """
    with pytest.raises(TypeError):
        candidate(claim=prose)


def test_an_untyped_evidence_assessment_is_refused():
    """Same hole, same reason: `evidence_assessment` was `Any`, and `as_record` degraded a
    non-assessment to null instead of refusing it.

    The refusal moved with the field. `AssuranceContext` no longer has a place to seat an
    assessment at all -- the release path computes it -- so the guard now lives on
    `AssessedAssurance`, which is the type that does hold one.
    """
    from cai.candidate import AssessedAssurance

    with pytest.raises(TypeError):
        AssessedAssurance(
            context=assurance(), evidence_assessment="fully satisfied, trust me"
        )


def test_the_assurance_context_has_no_place_to_seat_an_assessment():
    """STRONGER than refusing a bad one: a caller cannot offer one at all.

    Every fixture used to hand over `fully_satisfied()` -- a verdict nobody had reached
    about evidence nobody had read -- because the parameter existed and had to be filled.
    The release path discarded it. A field a caller must fill and the system then ignores
    teaches the caller that filling it means something.
    """
    assert "evidence_assessment" not in AssuranceContext.__dataclass_fields__
    assert "evidence_assessment" not in inspect.signature(release).parameters


def test_a_rendered_delivery_cannot_carry_a_digest_of_other_content():
    """A digest that does not bind its content authenticates nothing.

    This is the whole reason the artifact carries a digest at all, so the object refuses to
    exist in the broken state rather than trusting every construction site to get it right.
    """
    from cai.delivery import RENDERER_VERSION, RenderedDelivery

    with pytest.raises(ValueError, match="digest"):
        RenderedDelivery(
            renderer_version=RENDERER_VERSION,
            locale="en",
            rendered_text="WHAT IS AT RISK?  a customer commitment",
            card={"what_is_at_risk": "a customer commitment"},
            content_digest="0" * 64,
            rendered_at=t(12, 7),
        )


def test_a_rendering_with_no_timestamp_cannot_exist():
    """The governing ruling asked for `rendered_at` and it was simply absent.

    An artifact that proves WHAT the recipient saw but not WHEN cannot be distinguished
    from a re-render produced days later, against a claim that has since expired or been
    retracted -- and the second one is exactly what a party in a dispute would produce.
    """
    from cai.delivery import RENDERER_VERSION, RenderedDelivery

    with pytest.raises(ValueError, match="rendered_at"):
        RenderedDelivery(
            renderer_version=RENDERER_VERSION, locale="en", rendered_text="x",
            card={}, content_digest="0" * 64,
        )


def test_the_rendering_timestamp_is_inside_the_digest():
    """A timestamp the digest does not cover is decoration on a tamper-evident artifact.

    Same words, same renderer, same card, different rendering moment -- and therefore a
    different artifact, which the digest has to be able to say.
    """
    from cai.delivery import RenderedDelivery

    at_delivery = RenderedDelivery.render(candidate(), rendered_at=t(12, 7))
    later = RenderedDelivery.render(candidate(), rendered_at=t(13, 7))
    assert at_delivery.rendered_text == later.rendered_text
    assert at_delivery.content_digest != later.content_digest


def test_the_envelope_refuses_anything_but_a_typed_product():
    """The last loose domain field, closed for the same reason as the other two.

    The envelope wraps a product rather than forming one, so this is not a route by which
    prose could reach the domain. It is closed anyway: leaving one field of a class we just
    declared shut is how the class comes back.
    """
    from cai.envelope import IntelligenceEnvelope

    with pytest.raises(TypeError):
        IntelligenceEnvelope(product={"claim": "battery will fail", "confidence": 0.91})


def test_the_delivered_text_is_what_the_digest_attests():
    """End-to-end, on the artifact the recipient actually received.

    The release path appends the trust line AFTER rendering, and for one revision rebuilt
    the artifact carrying the digest of the pre-trust-line text. Every delivered product
    therefore shipped a digest of a sentence the customer never saw -- so anyone verifying
    the delivery against its digest got a mismatch, and the provenance claim the whole
    system rests on was false at the last step.
    """
    product = deliver()
    rendered = product.rendered_delivery

    assert "WHY TRUST IT?" in rendered.rendered_text, "the trust line is part of delivery"
    assert rendered.content_digest == rendered.recomputed_digest()


# ---------------------------------------------------------------------------
# FORMATION. No product exists unless the pieces cohere.
# ---------------------------------------------------------------------------


def test_a_non_actionable_consequence_forms_no_candidate():
    """Half a shift of lost capacity is not something to interrupt an operator for."""
    trivial = DowntimeConsequence(
        "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
        asset_id="asset-4417", expected_hours_lost=0.4, affected_operation="loading",
    )
    with pytest.raises(ValueError, match="not actionable"):
        candidate(consequence=trivial)


def test_an_actionable_downtime_consequence_does_form():
    """Non-triviality twin, and proof the abstraction is not shaped around the hero.

    No customer commitment anywhere in this candidate. The durable principle is 'no
    actionable, defensible business consequence', not 'no customer commitment'.
    """
    real = DowntimeConsequence(
        "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
        asset_id="asset-4417", expected_hours_lost=6.0, affected_operation="loading",
    )
    assert candidate(consequence=real).business_consequence.is_actionable()


# ---------------------------------------------------------------------------
# THE REASON PATH. The scenario derived a BusinessImpact through the five-link
# graph -- source facts, rule version, knowledge cutoff, ambiguities, late
# relationships -- and threw all of it away when it built the consequence. The
# portable product carried the conclusion and not why the connected facts justify
# it, while the governing contract requires business consequence AND path.
# ---------------------------------------------------------------------------


def test_a_consequence_without_a_derivation_path_cannot_exist():
    """The conclusion and its justification are one object or the record is a label.

    Two halves, because the first one alone was catching Python's argument binder rather
    than anything this design decided: `pytest.raises((TypeError, ValueError))` around a
    call missing a required positional argument passes for any dataclass with any required
    field. The STRUCTURAL claim is that the field has no default to fall back to; the
    BEHAVIOURAL claim is that something that is not a derivation is refused by our check,
    with our message.
    """
    import dataclasses

    field = CustomerCommitmentConsequence.__dataclass_fields__["derivation"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING

    with pytest.raises(TypeError, match="ConsequenceDerivation"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(t(13, 5), t(13, 11)),
            "a walk, honestly, trust me",
            commitment_id="commit-7", commitment_description="asserted, not derived",
        )


def test_a_consequence_whose_path_does_not_reach_it_is_refused():
    """A real walk, ending somewhere else, attached to this conclusion.

    This is the failure a path-shaped field invites: carrying A DERIVATION rather than
    THE derivation for the thing being claimed. The terminal entity of the walk has to be
    the commitment the consequence names.
    """
    with pytest.raises(ValueError, match="commit-99|path|derivation"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(t(13, 5), t(13, 11)),
            derivation=derivation(),
            commitment_id="commit-99",
            commitment_description="a commitment the walk never reached",
        )


def test_a_downtime_consequence_whose_path_never_mentions_its_asset_is_refused():
    """The base membership check, which only DOWNTIME can exercise.

    A commitment consequence is caught by the stricter rule that the walk must TERMINATE
    at it, so the weaker "appears anywhere in the path" check is unreachable there --
    and a surviving mutant showed that no test reached it at all. Downtime is the type
    the base rule exists for: it does not need the walk to end at a commitment, only to
    have established where the asset was and what it was serving.
    """
    with pytest.raises(ValueError, match="never reaches"):
        DowntimeConsequence(
            "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
            asset_id="asset-9999", expected_hours_lost=6.0,
            affected_operation="loading",
        )


def test_a_downtime_consequence_about_an_asset_the_path_established_still_forms():
    """Non-triviality twin for the base rule."""
    real = DowntimeConsequence(
        "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
        asset_id="asset-4417", expected_hours_lost=6.0, affected_operation="loading",
    )
    assert real.is_actionable()


def test_a_consequence_naming_an_intermediate_step_is_refused():
    """Isolates the TERMINAL check from the weaker "appears in the path at all" check.

    `ship-22` really is in the walk -- the shipment the window loads. It is not what the
    walk concludes. A consequence naming an intermediate entity has a genuine path behind
    it that argues for something else, and the base membership check cannot tell the
    difference; a surviving mutant is how that came to light.
    """
    with pytest.raises(ValueError, match="terminat"):
        CustomerCommitmentConsequence(
            "CUSTOMER_COMMITMENT", TimeInterval(t(13, 5), t(13, 11)), derivation(),
            commitment_id="ship-22",
            commitment_description="the shipment, not the promise it fulfils",
        )


def test_a_derivation_from_another_decision_forms_no_candidate():
    """The walk must have been performed under this decision's clock.

    A path derived at a later cutoff knows relationships the decision-maker did not, and
    a path over a different window describes a different exposure. `DecisionContext` is
    the single temporal authority for the REASON stage too.
    """
    from cai.derivation import ConsequenceDerivation

    stale = ConsequenceDerivation(
        **{**derivation().__dict__, "knowledge_cutoff": t(11, 0)}
    )
    with pytest.raises(ValueError, match="cutoff|derivation"):
        candidate(consequence=commitment(derivation=stale))


def test_the_real_derivation_still_forms_and_survives_into_the_product():
    """Non-triviality twin, and the point of the whole finding.

    The record answers WHY: which facts, asserted by which systems, known by when, under
    which rule version, reaching which commitment.
    """
    product = deliver()
    path = product.candidate.business_consequence.derivation
    assert [s.relationship for s in path.steps] == [
        "HAS_COMPONENT", "ASSIGNED_TO", "SUPPORTS", "LOADS", "FULFILLS",
    ]
    assert path.terminal_entity == "commit-7"
    assert path.rule_version
    assert len(set(path.source_systems())) > 1, (
        "the premise is that these facts live in different systems; a path naming one "
        "source has not shown the join that makes the consequence non-obvious"
    )
    assert all(s.recorded_at <= path.knowledge_cutoff for s in path.steps)


def test_a_consequence_outside_the_prediction_window_forms_no_candidate():
    """The consequence belongs to a different decision.

    The action moves WITH the consequence here, and the assertion is on the word only this
    check emits. Otherwise the action-window check refuses the same fixture with a message
    that also contains "does not overlap", and deleting this check entirely leaves the
    test green -- which a surviving mutant is exactly how we found out.
    """
    elsewhere = CustomerCommitmentConsequence(
        "CUSTOMER_COMMITMENT", TimeInterval(t(20, 5), t(20, 11)), derivation(),
        commitment_id="commit-7", commitment_description="a window a week later",
    )
    alongside = ActionRecommendation(
        "act-far", ActionType.INSPECT, "battery-pack-1", "maintenance", t(20, 3),
        TimeInterval(t(20, 5), t(20, 11)), "an inspection for that later window",
        Priority.ROUTINE,
    )
    with pytest.raises(ValueError, match="threaten"):
        candidate(consequence=elsewhere, action=alongside)


def test_an_action_due_after_its_window_closes_is_refused():
    """It could not change the outcome it claims to prevent."""
    with pytest.raises(ValueError, match="could not change the outcome"):
        ActionRecommendation(
            "act-late", ActionType.INSPECT, "battery-pack-1", "maintenance", t(14, 0),
            TimeInterval(t(13, 5), t(13, 11)), "too late", Priority.ROUTINE,
        )


# ---------------------------------------------------------------------------
# TEMPORAL AUTHORITY
# ---------------------------------------------------------------------------


def test_knowledge_cannot_postdate_the_decision():
    """MIGRATED, same invariant. A decision cannot rest on evidence that had not arrived."""
    with pytest.raises(ValueError, match="had not arrived"):
        DecisionContext(t(12, 7), t(12, 9), t(12, 7), TimeInterval(t(12, 7), t(15, 7)))


def test_the_horizon_is_derived_not_stated():
    """STRONGER. The old model let the claim's horizon differ from the inputs' horizon."""
    ctx = context()
    assert ctx.horizon == timedelta(days=3)
    assert claim(ctx).horizon_seconds == int(ctx.horizon.total_seconds())


def test_an_inverted_prediction_window_is_refused():
    with pytest.raises(ValueError, match="negative prediction window"):
        TimeInterval(t(15, 7), t(12, 7))


def test_a_zero_length_interval_is_refused():
    """`end < start` was refused and `end == start` was not.

    An instant is not an interval. A zero-length prediction window derives a zero horizon,
    which the predictor refuses -- but only after a candidate claiming to describe a
    period of no duration has already been formed, and only if anybody replays it.
    """
    with pytest.raises(ValueError, match="zero-length|no duration"):
        TimeInterval(t(12, 7), t(12, 7))


def test_a_one_second_interval_still_forms():
    """Non-triviality twin: the refusal is of emptiness, not of shortness."""
    assert TimeInterval(t(12, 7), t(12, 7) + timedelta(seconds=1)).duration == timedelta(
        seconds=1
    )


def test_a_claim_whose_horizon_disagrees_with_the_window_forms_no_candidate():
    """The horizon was *derived* in the fixtures and free to disagree in the type.

    `test_the_horizon_is_derived_not_stated` demonstrates the happy fixture; it does not
    structurally prohibit disagreement. A claim about the next 24 hours seated in a
    decision whose window is 72 hours is two temporal authorities, which is precisely
    what `DecisionContext` exists to be the only one of.
    """
    ctx = context()
    honest = claim(ctx)
    from cai.contract import PredictionClaim

    disagreeing = PredictionClaim(
        **{**honest.__dict__, "horizon_seconds": 86400}
    )
    with pytest.raises(ValueError, match="horizon"):
        candidate(context=ctx, claim=disagreeing)


def test_the_agreeing_horizon_still_forms():
    """Non-triviality twin for the horizon binding."""
    ctx = context()
    assert candidate(context=ctx, claim=claim(ctx)).prediction_claim.horizon_seconds == int(
        ctx.horizon.total_seconds()
    )


def test_an_action_for_a_different_operational_event_is_refused():
    """`operational_window` and `exposure_window` were each checked against something
    else and never against each other.

    An action scheduled around a window that does not touch the exposure it claims to
    protect is an action for a different operational event, attached to this claim.
    """
    unrelated = ActionRecommendation(
        "act-elsewhere", ActionType.INSPECT, "battery-pack-1", "maintenance", t(20, 3),
        TimeInterval(t(20, 5), t(20, 11)),
        "an inspection around next week's window", Priority.ROUTINE,
    )
    with pytest.raises(ValueError, match="protect"):
        candidate(action=unrelated)


def test_the_coherent_operational_window_still_forms():
    """Non-triviality twin: the ordinary case, where the two windows are the same."""
    assert candidate().action.operational_window.overlaps(
        candidate().business_consequence.exposure_window
    )


# ---------------------------------------------------------------------------
# ASSURANCE
# ---------------------------------------------------------------------------


def test_an_unverifiable_digest_abstains():
    """MIGRATED, same invariant, now on the release path."""
    c = candidate()
    product = deliver(candidate=c, evidence=evidence(c.prediction_claim, digest="a" * 64))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_a_verified_claim_is_delivered():
    """Non-triviality twin. A system that only refuses is safe and useless."""
    assert deliver().determination is Determination.DELIVERED


# ---------------------------------------------------------------------------
# OBSERVATION INTEGRITY CONFLICTS ON THE ACTUAL RELEASE PATH.
#
# `ObservationLog` detected same-id/different-payload conflicts and `assess_evidence`
# could consume them -- through an optional argument `formation.release` never
# supplied. So the module-level test was green while the real product path released
# without ever seeing the conflict, which is the shape of defect this whole audit is
# about: a capability that exists, is tested in isolation, and is not wired in.
# ---------------------------------------------------------------------------


def conflicted_log():
    """A log where two sources disagree about the payload behind one observation id."""
    from cai.bitemporal import ObservationLog

    log = ObservationLog()
    for o in observations():
        log.record(o)
    # Same id, different value. The log keeps the first and records the disagreement.
    first = observations()[0]
    log.record(Observation(
        first.observation_id, first.subject, first.metric, 999.9,
        first.valid_time, first.transaction_time, "source-b",
    ))
    return log


def clean_log():
    """The twin: the same log with an ordinary at-least-once redelivery instead."""
    from cai.bitemporal import ObservationLog

    log = ObservationLog()
    for o in observations():
        log.record(o)
    log.record(observations()[0])  # byte-identical retry: ordinary traffic
    return log


def test_an_integrity_conflict_reaches_the_release_path_and_withholds():
    """PATH-level, not module-level. This is the test that was missing.

    Everything else about this candidate is perfect: genuine evidence, verified digest,
    replayable claim, fully scoped clearance. Two sources disagree about one reading, and
    the product is withheld for integrity because the release path now cannot be handed
    observations without the contradictions the log found in them.
    """
    c = candidate()
    product = deliver(candidate=c, observation_log=conflicted_log())
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)
    # The conflict is NAMED, and it is named on the product that travels. A refusal that
    # says "integrity" and not which reading two sources disagree about sends an engineer
    # to look at a hash rather than at the two systems that need reconciling.
    assessment = product.assurance.assessed.evidence_assessment
    assert any("a-0" in c for c in assessment.conflicts), assessment.conflicts


def test_an_ordinary_duplicate_redelivery_still_releases():
    """Non-triviality twin, and the one that matters most here.

    At-least-once delivery makes identical redelivery ordinary traffic. A release path
    that withheld on every duplicate would pass the test above while making the product
    useless on any real feed -- so the refusal has to be of DISAGREEMENT, not of repetition.
    """
    c = candidate()
    product = deliver(candidate=c, observation_log=clean_log())
    assert product.determination is Determination.DELIVERED


def test_the_release_path_cannot_be_handed_observations_without_their_conflicts():
    """STRUCTURAL, and stronger than the version it replaces.

    That version asserted the parameter was an `EvidenceBundle` with no default, and
    concluded there was "no arrangement of arguments in which release sees the evidence
    and not the disagreement about it". That conclusion did not follow. `EvidenceBundle`
    has a public constructor and `integrity_conflicts` defaults to `()`, so a caller could
    build one by hand, hand release the readings, and leave every contradiction behind --
    and release could not recompute them, because `ObservationLog.record` keeps the first
    reading and rejects the second, so the rogue was never in `observations` to be found.

    The parameter is gone. Release takes the log and performs the point-in-time query
    itself, so the authority that DETECTS a conflict is the authority that ISSUES the
    evidence. There is no longer any object a caller can build that release will accept as
    evidence.
    """
    from cai.bitemporal import EvidenceBundle
    from cai.assessment import _assess_evidence

    params = inspect.signature(release).parameters
    assert "evidence_source" not in params, (
        "a caller-supplied bundle is the shape that let conflicts be left behind"
    )
    assert "evidence_bundle" not in params
    assert params["observation_log"].default is inspect.Parameter.empty
    assert not any(
        p.annotation in (EvidenceBundle, "EvidenceBundle") for p in params.values()
    ), "no parameter of any name may accept a caller-assembled bundle"
    # And the seam below it: no optional conflicts argument survives anywhere.
    assess = inspect.signature(_assess_evidence).parameters
    assert "integrity_conflicts" not in assess
    assert "observations" not in assess


def test_a_hand_built_bundle_cannot_be_substituted_into_the_release_path():
    """The behavioural half of the structural test above.

    A signature check proves the parameter is named `observation_log`. It does not prove
    that seating a bundle there fails LOUDLY -- and a bundle duck-types far enough to be
    confusing, because it has `.observations`. The refusal is by name, with a reason.
    """
    from cai.bitemporal import EvidenceBundle

    hand_built = EvidenceBundle(observations=observations(), integrity_conflicts=())
    with pytest.raises(TypeError, match="must be an ObservationLog"):
        deliver(observation_log=hand_built)


def test_the_conflict_a_hand_built_bundle_would_have_hidden_still_withholds():
    """The forgery this whole change exists to close, spelled out end to end.

    Before: take a log that HAS a conflict, build `EvidenceBundle(observations=view)` by
    hand with no conflicts, and release delivers -- the readings are genuine, the digest
    verifies, the claim replays, and the contradiction the log found simply never travels.

    After: the same log, handed to release, withholds. The two calls below are the same
    evidence reached two ways, and only one of them is still reachable.
    """
    from cai.bitemporal import EvidenceBundle

    log = conflicted_log()
    view = log.evidence_for(knowledge_cutoff=t(12, 7))
    assert view.integrity_conflicts, "the log must actually have found the disagreement"

    laundered = EvidenceBundle(observations=view.observations)
    assert not laundered.integrity_conflicts, (
        "the hand-built bundle is what a caller could once have supplied"
    )
    with pytest.raises(TypeError, match="must be an ObservationLog"):
        deliver(observation_log=laundered)
    assert deliver(observation_log=log).determination is Determination.ABSTAINED


def test_entitlement_does_not_transfer_to_another_recipient():
    """STRONGER. Two booleans could not express scope, so a generic may_deliver=True was
    reusable against a recipient nobody had cleared."""
    other = entitlement(
        recipient="procurement@other-customer", purpose="benchmarking",
        subject="asset-4417", tenant="tenant-2",
        basis="no cross-customer clause", policy_id="pol-2",
        authorized_source_systems=(), may_deliver_to_recipient=False,
    )
    product = deliver(assurance=assurance(entitlement=other))
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_identity_below_the_floor_abstains():
    product = deliver(assurance=assurance(
        identity=IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", 0.42)))
    assert product.determination is Determination.ABSTAINED
    assert any("identity" in r for r in product.assurance.blocking_reasons)


def test_every_blocking_reason_is_reported_not_only_the_first():
    """MIGRATED. Fixing one blocker and rediscovering the next wastes a cycle each time."""
    product = deliver(assurance=assurance(
        identity=IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", 0.42),
        temporal=TemporalAssertion(
            t(12, 7), t(12, 7), t(12, 7), False,
            basis="the feature view was assembled after the knowledge cutoff"),
    ))
    assert len(product.assurance.blocking_reasons) >= 2


def test_the_decision_records_the_policy_that_produced_it():
    """STRONGER. policy_digest catches a threshold edited without a version bump."""
    product = deliver()
    assert product.assurance.policy_version == ReleasePolicy().policy_version
    assert product.assurance.policy_digest == ReleasePolicy().digest()


def test_a_refusal_always_states_a_reason():
    """MIGRATED. A silent abstention is indistinguishable from a crash."""
    product = deliver(assurance=assurance(
        identity=IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", 0.1)))
    assert product.abstention_reason()


# ---------------------------------------------------------------------------
# THE DELIVERED RECORD
# ---------------------------------------------------------------------------


def test_the_delivered_text_is_rendered_from_the_typed_objects():
    """STRONGER. There is no parameter through which prose could be supplied, so the only
    remaining question is whether what shipped matches what the objects say."""
    product = deliver()
    text = product.rendered_delivery.rendered_text
    assert f"{product.candidate.prediction_claim.score:.4f}" in text
    assert product.candidate.business_consequence.describe() in text
    assert product.candidate.action.rendered_text() in text


def test_evidence_captured_after_delivery_is_refused():
    """MIGRATED. The system was committing the temporal sin the paper warns about."""
    c = candidate()
    with pytest.raises(ValueError, match="postdates delivery"):
        deliver(candidate=c,
                evidence=evidence(c.prediction_claim, captured_at=t(20, 0)))


def test_a_delivered_product_carries_the_assessment_that_authorised_it():
    """MIGRATED. Recomputing it for display is how the printed dimensions diverged."""
    product = deliver()
    assert product.assurance.permitted
    # Confidence travels as a precision-carrying string so the record canonicalises.
    assert product.assurance.assurance_context_record["identity"]["confidence"] == "0.970000"


# ---------------------------------------------------------------------------
# PERISHABILITY, DERIVED RATHER THAN MUTATED
# ---------------------------------------------------------------------------


def test_status_is_derived_from_lineage_events_and_time():
    """NEW invariant. The operator's real question is 'is this still actionable?'"""
    product = deliver()
    assert product.status_at(t(12, 8)) is ProductStatus.ACTIVE
    assert product.status_at(t(14, 0)) is ProductStatus.EXPIRED


def test_the_product_cannot_be_told_that_it_is_retracted():
    """`status_at` took `retracted` and `superseded_by` FROM THE CALLER.

    The envelope owns typed retraction and supersession events, and the governing rule is
    that current status derives from lineage plus events plus time. A caller who can pass
    `retracted=True` is a second authority on the one question this architecture exists to
    have a single authority for -- and the old test asserted the parameters worked, which
    is how the defect survived a suite that looked thorough.
    """
    sig = inspect.signature(deliver().status_at)
    assert "retracted" not in sig.parameters
    assert "superseded_by" not in sig.parameters


def test_status_derives_retraction_and_supersession_from_envelope_events():
    """The single authority, exercised through the object that owns the events."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    product = deliver()
    retracted = IntelligenceEnvelope(
        product=product,
        status_events=(StatusEvent(
            StatusEventType.RETRACTED, t(12, 9), "ops-lead",
            reason="asset reassigned out of zone-3"),),
    )
    superseded = IntelligenceEnvelope(
        product=product,
        status_events=(StatusEvent(
            StatusEventType.SUPERSEDED, t(12, 9), "system",
            replacement_product_id="ip-002"),),
    )
    assert retracted.status_at(t(12, 10)) is ProductStatus.RETRACTED
    assert superseded.status_at(t(12, 10)) is ProductStatus.SUPERSEDED


def test_a_status_event_has_not_taken_effect_before_it_happened():
    """Status is a function of the moment asked about, not of the event list existing.

    Reading the events as flags -- the old caller-supplied booleans -- makes a claim
    retracted retrospectively, which rewrites what an operator acting at 08:00 was
    entitled to believe.
    """
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    env = IntelligenceEnvelope(
        product=deliver(),
        status_events=(StatusEvent(
            StatusEventType.RETRACTED, t(12, 9), "ops-lead", reason="reassigned"),),
    )
    assert env.status_at(t(12, 8)) is ProductStatus.ACTIVE
    assert env.status_at(t(12, 10)) is ProductStatus.RETRACTED


def test_an_envelope_with_no_status_events_stays_active():
    """Non-triviality twin: derivation must not make everything retracted."""
    from cai.envelope import IntelligenceEnvelope

    assert IntelligenceEnvelope(product=deliver()).status_at(
        t(12, 8)) is ProductStatus.ACTIVE


def test_a_status_event_predating_delivery_is_refused():
    """A claim cannot be retracted before it was made."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="deliver"):
        IntelligenceEnvelope(
            product=deliver(),
            status_events=(StatusEvent(
                StatusEventType.RETRACTED, t(11, 0), "ops-lead", reason="too early"),),
        )


def test_a_product_cannot_supersede_itself():
    """Self-supersession reads as a live replacement and terminates no lineage.

    A reader walking the chain to find the current view arrives back where they started,
    and the claim is simultaneously the superseded one and the one superseding it.
    """
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="itself|self"):
        IntelligenceEnvelope(
            product=deliver(product_id="ip-001"),
            status_events=(StatusEvent(
                StatusEventType.SUPERSEDED, t(12, 9), "system",
                replacement_product_id="ip-001"),),
        )


def test_a_second_retraction_is_refused():
    """A claim withdrawn twice describes an impossible sequence, and the second event's
    actor and reason silently displace the first in any reader's summary."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="retract"):
        IntelligenceEnvelope(
            product=deliver(),
            status_events=(
                StatusEvent(StatusEventType.RETRACTED, t(12, 9), "a", reason="first"),
                StatusEvent(StatusEventType.RETRACTED, t(12, 10), "b", reason="again"),
            ),
        )


def test_status_events_out_of_order_are_refused():
    """An unreplayable sequence is not a record -- the same rule the lifecycle trail has."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="order|chronolog"):
        IntelligenceEnvelope(
            product=deliver(),
            status_events=(
                StatusEvent(StatusEventType.SUPERSEDED, t(12, 11), "system",
                            replacement_product_id="ip-002"),
                StatusEvent(StatusEventType.RETRACTED, t(12, 9), "a", reason="earlier"),
            ),
        )


def test_a_later_product_points_backward_without_rewriting_the_earlier_one():
    """Retraction and supersession never mutate history."""
    first = deliver(product_id="ip-001")
    second = deliver(product_id="ip-002", supersedes_product_id="ip-001")
    assert second.supersedes_product_id == first.product_id
    assert first.claim_series_id == second.claim_series_id
    assert not hasattr(first, "retracted_at")


def test_a_claim_expiring_at_delivery_was_never_actionable():
    with pytest.raises(ValueError, match="never actionable"):
        deliver(valid_until=t(12, 7))


def test_a_clearance_for_one_recipient_does_not_authorise_another():
    """The scoping must be checked against the ACTUAL delivery, not the assertion itself.

    An entitlement validated against its own recipient field is always true, which makes
    every scope field decorative. The clearance below is entirely valid -- for somebody
    else.
    """
    cleared_for_ops = entitlement()
    product = deliver(
        assurance=assurance(entitlement=cleared_for_ops),
        recipient="procurement@other-customer",
    )
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_the_cleared_recipient_still_receives_it():
    """Non-triviality twin."""
    assert deliver().determination is Determination.DELIVERED


# ---------------------------------------------------------------------------
# CROSS-BINDING. Every assertion must be ABOUT the candidate being released.
#
# Each of these fields existed, was carried into the record, was printed in the
# hero, and was read by anyone auditing the decision -- while binding to nothing.
# The assurance layer could assert identity for a different asset, applicability of
# a different model, and point-in-time correctness for a different decision, and the
# product shipped. A field that does not participate in its claimed invariant is
# decorative, whatever it is named.
# ---------------------------------------------------------------------------


def test_an_identity_assertion_about_another_entity_is_refused():
    """`resolved_entity` named the asset; the claim was about its battery pack.

    They differed in the fixture itself and nothing noticed -- so "we resolved the
    identity" was a statement about something other than the thing being sold.
    """
    with pytest.raises(ValueError, match="identity"):
        deliver(assurance=assurance(
            identity=IdentityAssertion("asset-0000", "resolver-a", "1.0", 0.97)))


def test_an_applicability_assertion_about_another_model_is_refused():
    """Otherwise "the model is applicable" refers to a model that did not run."""
    with pytest.raises(ValueError, match="applicab"):
        deliver(assurance=assurance(applicability=ApplicabilityAssertion(
            "some-other-model@9.9", "forklift/battery-pack", True, "x")))


def test_a_temporal_assertion_naming_another_decision_time_is_refused():
    """DecisionContext is the temporal authority. An assertion free to disagree with
    it is a second one, which is the defect the context was introduced to remove.

    Isolated from the knowledge-cutoff case below because a surviving mutant proved they
    were not: a single test moving both fields left either half deletable on its own.
    """
    with pytest.raises(ValueError, match="single temporal authority"):
        deliver(assurance=assurance(
            temporal=TemporalAssertion(
                t(13, 0), t(12, 7), t(12, 7), True,
                basis="asserted for a decision made an hour later")))


def test_a_temporal_assertion_naming_another_knowledge_cutoff_is_refused():
    """The other half. A claim asserted point-in-time correct as of a different cutoff
    was checked against evidence the decision did not have."""
    with pytest.raises(ValueError, match="single temporal authority"):
        deliver(assurance=assurance(
            temporal=TemporalAssertion(
                t(12, 7), t(11, 0), t(11, 0), True,
                basis="asserted against evidence available an hour earlier")))


def test_evidence_produced_by_another_model_is_refused():
    """The snapshot names the model that produced the readings the claim rests on.
    Free to differ from the claim's own model, it describes a different computation."""
    c = candidate()
    from cai.contract import EvidenceSnapshot
    mismatched = EvidenceSnapshot(
        **{**evidence(c.prediction_claim).__dict__, "model_version": "other-model@0.1"}
    )
    with pytest.raises(ValueError, match="model"):
        deliver(candidate=c, evidence=mismatched)


def test_the_coherent_assurance_context_still_delivers():
    """Non-triviality twin for all four bindings at once."""
    assert deliver().determination is Determination.DELIVERED


# ---------------------------------------------------------------------------
# ENTITLEMENT SCOPE. Recipient and purpose were checked; subject, tenant and source
# data were carried and ignored, so a clearance for the right person but the wrong
# asset, the wrong tenant, or unlicensed source data authorised delivery anyway.
# ---------------------------------------------------------------------------


def test_a_clearance_for_one_subject_does_not_authorise_another():
    """`subject` existed on the assertion and never participated in authorization.

    A clearance covering one asset must not release a claim about a different asset on
    the same contract. The assertion below is entirely valid -- for another machine.
    """
    cleared_for_other_asset = entitlement(subject="asset-9999")
    product = deliver(assurance=assurance(entitlement=cleared_for_other_asset))
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_a_clearance_for_one_purpose_does_not_authorise_another_use():
    """Found by a surviving mutant, not by reading.

    `purpose` was compared in `permits`, but no test varied it alone -- every existing
    case changed the recipient too, so deleting the purpose comparison broke nothing.
    A scope dimension no test isolates is indistinguishable from one that is decorative.
    """
    product = deliver(purpose="benchmarking")
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_a_clearance_for_one_tenant_does_not_authorise_another():
    """`tenant` had the same defect, and it is the one that leaks across customers."""
    cleared_for_other_tenant = entitlement(tenant="tenant-77")
    product = deliver(assurance=assurance(entitlement=cleared_for_other_tenant))
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_evidence_from_an_unlicensed_source_system_is_not_cleared():
    """`may_use_source_data` was a bare boolean -- permission to use *some* data.

    Which source systems the contract actually covers is the question that matters, and
    a claim resting on a feed outside the licence is a data-rights breach whatever the
    boolean says.
    """
    licensed_elsewhere = entitlement(authorized_source_systems=("source-z",))
    product = deliver(assurance=assurance(entitlement=licensed_elsewhere))
    assert product.determination is Determination.ABSTAINED
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)


def test_an_entitlement_licensing_no_source_system_authorises_nothing():
    """Fail-closed: an unstated source scope is not an unrestricted one."""
    unscoped = entitlement(authorized_source_systems=())
    assert deliver(
        assurance=assurance(entitlement=unscoped)
    ).determination is Determination.ABSTAINED


def test_the_fully_scoped_clearance_still_delivers():
    """Non-triviality twin for all three scope dimensions at once.

    Without this, every assertion above would pass on a release path that refused
    everything, which is the failure mode a refusal-only suite cannot see.
    """
    assert deliver().determination is Determination.DELIVERED


def test_an_entitlement_valid_over_no_interval_is_refused():
    """P1-5. `valid_to > valid_from` was never enforced.

    A clearance whose window ends at or before it opens authorises nothing, and reads in
    every report exactly like an ordinary bounded one. The `permits` check would refuse it
    at any moment -- which means it produces a silent, permanent abstention that looks
    like a rights problem with the delivery rather than a defect in the clearance.
    """
    with pytest.raises(ValueError, match="valid|interval|before"):
        entitlement(valid_from=t(5), valid_to=t(5))


def test_an_entitlement_with_a_real_window_still_authorises():
    """Non-triviality twin: the refusal is of emptiness, not of having an end date."""
    scoped = entitlement(valid_from=t(1), valid_to=t(30))
    assert deliver(
        assurance=assurance(entitlement=scoped)
    ).determination is Determination.DELIVERED


def test_a_temporal_verdict_with_no_basis_is_refused():
    """P1-1. `basis` defaulted to empty, so point-in-time correctness could be asserted
    with nothing behind it.

    `ApplicabilityAssertion` had required a basis from the start -- "a verdict with no
    basis is an opinion" -- and the assertion where it matters most was left open.
    """
    with pytest.raises(ValueError, match="basis|naked"):
        TemporalAssertion(t(12, 7), t(12, 7), t(12, 7), True)


def test_a_temporal_verdict_stating_its_basis_is_accepted():
    """Non-triviality twin."""
    assert TemporalAssertion(
        t(12, 7), t(12, 7), t(12, 7), True, basis="point-in-time view at the cutoff"
    ).valid


def test_entitlement_scope_is_checked_against_the_candidate_not_itself():
    """The structural half: `permits` cannot be satisfied by its own fields.

    Every scope argument is keyword-only and required, so a caller cannot quietly omit
    one and inherit a pass -- the omission that made subject and tenant decorative.
    """
    sig = inspect.signature(EntitlementAssertion.permits)
    for scope in ("recipient", "purpose", "subject", "tenant", "source_systems", "at"):
        assert scope in sig.parameters, f"{scope} must participate in authorization"
        assert sig.parameters[scope].default is inspect.Parameter.empty


def test_a_claim_the_predictor_never_produced_cannot_be_delivered():
    """MIGRATED from test_prediction_claim, now on the release path.

    The case that made 'every technical signal green, refused only on rights' false: a
    peer-benchmarked percentile asserted over a model that computes no percentile. The
    technical signal for the claim being made did not exist.

    The forgery now needs two steps rather than one: the claim's declared envelope must
    also be forged to admit the invented metric, or the type refuses it outright. That is
    the point -- a self-consistent lie is still caught, because the release join replays
    the recorded predictor rather than reading the record back to itself.
    """
    from cai.predictor import MetricApplicability, ModelEnvelope

    forged = PredictionClaim(
        subject="asset-4417/battery-pack",
        metric="peer_benchmark_percentile",
        score=0.91,
        score_semantics="percentile against a peer cohort",
        horizon_seconds=259200,
        evidence_strength=0.91,
        model_version="degradation-baseline@1.3.0",
        model_artifact_digest="0" * 64,
        input_fingerprint="f" * 64,
        declared_envelope=ModelEnvelope(
            model_version="degradation-baseline@1.3.0",
            model_artifact_digest="0" * 64,
            # The forged envelope has to declare the invented metric AS A PAIR with the
            # subject type the assertion names, because a metric and a subject type are no
            # longer independently declarable. That makes the forgery marginally harder to
            # build and does not save it: the release join replays the recorded predictor.
            supported_applicability=(
                MetricApplicability("peer_benchmark_percentile",
                                    "forklift/battery-pack"),
            ),
            min_observations=3,
            max_horizon_seconds=604800,
        ),
    )
    c = candidate(claim=forged)
    product = deliver(candidate=c, evidence=evidence(claim()))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


# ---------------------------------------------------------------------------
# THE PREDICTOR-OUTPUT BINDING. `assess_evidence` bound the claim to the input
# fingerprint, the metric and the horizon -- and to none of the values the predictor
# actually produced. A caller could keep a legitimate fingerprint, substitute a
# different score or a different meaning for it, and reach DELIVERED with every other
# signal green. The whole product thesis is that this cannot happen.
#
# Direct dataclass construction below is deliberate and is NOT the hole being tested.
# Typed objects arrive from the wire too, so banning the constructor would move the
# forgery one boundary outward rather than closing it. The release join has to establish
# that this typed claim is what the recorded predictor produced.
# ---------------------------------------------------------------------------


def substituted(**over) -> PredictionClaim:
    """An honest claim with exactly one predictor-derived field replaced.

    Everything else -- fingerprint, inputs, evidence digest, entitlement, identity --
    stays genuine, so anything that refuses this refused it on the substituted field.
    """
    return PredictionClaim(**{**claim().__dict__, **over})


@pytest.mark.parametrize("field,value", [
    ("score", 0.99),
    ("score_semantics", "calibrated probability of failure within the horizon"),
    ("evidence_strength", 0.95),
])
def test_a_substituted_predictor_output_field_is_refused_by_replay(field, value):
    """Each is a separate lie a customer would act on differently.

    A substituted score sells a risk the model never computed. Substituted semantics sell
    the same number as a probability, which is the interpretation a reader supplies by
    default and the one this repository spends a paragraph refusing. A substituted
    evidence strength sells weight the evidence does not carry.
    """
    c = candidate(claim=substituted(**{field: value}))
    product = deliver(candidate=c, evidence=evidence(claim()))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_a_substituted_model_artifact_digest_is_refused_by_replay():
    """A two-step forgery: the claim's own type requires its envelope to agree with it,
    so the digest has to be changed in both places to construct at all.

    It still fails, because the digest is verified against the implementation that
    replays the claim rather than against the record's own copy of itself.
    """
    from cai.predictor import ModelEnvelope

    honest = claim()
    fake = "b" * 64
    forged = PredictionClaim(**{
        **honest.__dict__,
        "model_artifact_digest": fake,
        "declared_envelope": ModelEnvelope(
            **{**honest.declared_envelope.__dict__, "model_artifact_digest": fake}
        ),
    })
    product = deliver(candidate=candidate(claim=forged), evidence=evidence(claim()))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_the_genuine_predictor_output_still_delivers():
    """Non-triviality twin for the replay.

    Without it the four refusals above would pass against a release path that refused
    every claim -- which is the failure a refusal-only suite structurally cannot see, and
    the reason a replay comparison that is subtly wrong looks exactly like a strict one.
    """
    product = deliver()
    assert product.determination is Determination.DELIVERED
    assert product.candidate.prediction_claim.score == claim().score


def test_an_applicability_assertion_outside_the_declared_envelope_is_refused():
    """P1-1/P1-2. `subject_type` was asserted against an envelope the claim never carried.

    With the model's declared envelope now on the claim, "this use is applicable" is a
    statement about something checkable. Asserting `valid=True` for a subject type the
    model does not declare is not a business refusal -- it is an assertion about a
    different model's applicability, and incoherent in the same way as the other bindings.
    """
    with pytest.raises(ValueError, match="subject type|envelope"):
        deliver(assurance=assurance(applicability=ApplicabilityAssertion(
            "degradation-baseline@1.3.0", "wind-turbine/gearbox", True,
            "asserted for a subject type this model never declared")))


def test_an_applicability_assertion_may_still_report_an_invalid_use():
    """Non-triviality twin. Saying 'this use is outside the envelope' must stay possible.

    The refusal above is of an incoherent claim to validity, not of the honest verdict
    that a model was used somewhere it does not belong -- which must abstain, with a
    reason, rather than raise.
    """
    product = deliver(assurance=assurance(applicability=ApplicabilityAssertion(
        "degradation-baseline@1.3.0", "wind-turbine/gearbox", False,
        "subject type outside the model's declared envelope")))
    assert product.determination is Determination.ABSTAINED
    assert any("applicab" in r for r in product.assurance.blocking_reasons)


# ---------------------------------------------------------------------------
# PORTABILITY. Migrated from test_portability.py, rebuilt for the envelope.
# The four invariants that suite protected are each re-asserted here.
# ---------------------------------------------------------------------------


def test_the_envelope_canonicalises_and_digests():
    """MIGRATED (round-trip fidelity + digest). Same canonical bytes, same digest."""
    from cai.envelope import IntelligenceEnvelope

    env = IntelligenceEnvelope(product=deliver())
    assert env.canonical_json() == IntelligenceEnvelope(product=deliver()).canonical_json()
    assert len(env.digest()) == 64


def test_the_digest_detects_alteration():
    """MIGRATED. Change one field, get a different digest."""
    from cai.envelope import IntelligenceEnvelope

    a = IntelligenceEnvelope(product=deliver(product_id="ip-001"))
    b = IntelligenceEnvelope(product=deliver(product_id="ip-002"))
    assert a.digest() != b.digest()


def test_an_unknown_schema_version_is_refused_not_guessed():
    """MIGRATED. A consumer that guesses produces confident nonsense."""
    from cai.envelope import UnsupportedSchemaVersion, validate_envelope_payload

    with pytest.raises(UnsupportedSchemaVersion):
        validate_envelope_payload({"schema_version": "cai.something-else/9"})


def test_an_envelope_claiming_the_intervention_worked_is_refused():
    """MIGRATED and STRONGER. The causal boundary now holds across the wire."""
    from cai.envelope import (
        SCHEMA_VERSION, UnsupportedAttributedEffect, validate_envelope_payload,
    )

    with pytest.raises(UnsupportedAttributedEffect):
        validate_envelope_payload({
            "schema_version": SCHEMA_VERSION,
            "attributed_effect": "PREVENTED",
            "lifecycle_events": [],
        })


def test_a_non_integer_float_is_refused_rather_than_approximated():
    """NEW. Two implementations formatting 0.1 differently produce two valid-looking
    digests for one record, which is worse than refusing to serialize it."""
    from cai.canonical import NotCanonicalizable, canonicalize

    with pytest.raises(NotCanonicalizable):
        canonicalize({"score": 0.4942})


def test_the_envelope_carries_the_release_rationale():
    """NEW. The old bundle let a reader replay the predictor while leaving 'why did this
    qualify for release' unreconstructable."""
    from cai.envelope import IntelligenceEnvelope

    record = IntelligenceEnvelope(product=deliver()).as_record()
    assurance = record["product"]["assurance"]
    assert assurance["policy_digest"]
    assert assurance["assurance_context"]["entitlement"]["policy_id"]
    assert record["product"]["candidate"]["business_consequence"]["description"]


def test_retraction_is_an_event_not_a_mutation():
    """NEW. The delivered record never changes; status is derived."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    product = deliver()
    env = IntelligenceEnvelope(
        product=product,
        status_events=(StatusEvent(
            StatusEventType.RETRACTED, t(12, 9), "ops-lead",
            reason="asset reassigned out of zone-3"),),
    )
    assert env.status_events[0].reason
    assert not hasattr(product, "retracted_at")
    assert env.status_at(t(12, 10)) is ProductStatus.RETRACTED
    # The historical record is untouched by what later became true about it.
    assert product.status_at(t(12, 10)) is ProductStatus.ACTIVE


# ---------------------------------------------------------------------------
# GUARDS THAT HAD NO TEST AT ALL.
#
# A sweep deleting each of the 137 `raise` guards in src/cai one at a time found 73
# that could be removed with the whole suite green. Most were timezone hygiene. These
# were not: each is a rule some other test's docstring ASSERTS AS FACT while nothing
# exercised it, which is the same "claimed, not verified" pattern the audit is about.
# ---------------------------------------------------------------------------


def test_a_derivation_over_a_different_window_forms_no_candidate():
    """The other half of the derivation-clock binding.

    Its twin -- the knowledge cutoff -- was guarded and this was not, so the window
    comparison was deletable with the suite green. The suite splits exactly this kind of
    pair deliberately for the temporal assertion and missed it here.
    """
    from cai.derivation import ConsequenceDerivation

    ctx = context()
    elsewhere = ConsequenceDerivation(**{
        **derivation().__dict__,
        "evaluated_window": TimeInterval(t(12, 7), t(14, 7)),
    })
    with pytest.raises(ValueError, match="different window"):
        candidate(context=ctx, consequence=commitment(derivation=elsewhere))


def test_an_abstained_product_carrying_a_permitting_decision_is_refused():
    """One direction of the self-contradiction the product exists to prevent.

    `DELIVERED` with a refusing assurance was guarded and tested. Its mirror was guarded
    and untested, so half of "the determination and the decision cannot disagree" rested
    on nothing.
    """
    product = deliver()
    from cai.product import IntelligenceProduct

    with pytest.raises(ValueError, match="ABSTAINED contradicts"):
        IntelligenceProduct(**{
            **product.__dict__, "determination": Determination.ABSTAINED,
        })


def test_a_permitting_decision_cannot_carry_blocking_reasons():
    """The same contradiction one layer down, on the decision itself."""
    from cai.delivery import AssuranceDecision

    decision = deliver().assurance
    with pytest.raises(ValueError, match="cannot carry blocking reasons"):
        AssuranceDecision(**{
            **decision.__dict__, "blocking_reasons": ("entitlement=UNAUTHORIZED",),
        })


def test_a_claim_whose_envelope_digest_is_not_its_own_is_refused():
    """Asserted as fact in another test's docstring and never tested.

    `test_a_substituted_model_artifact_digest_is_refused_by_replay` says the digest "has
    to be changed in both places to construct at all" and relies on it to describe the
    forgery as two-step. That sentence was true and unguarded.
    """
    from cai.predictor import ModelEnvelope

    honest = claim()
    with pytest.raises(ValueError, match="different build"):
        PredictionClaim(**{
            **honest.__dict__,
            "declared_envelope": ModelEnvelope(
                **{**honest.declared_envelope.__dict__,
                   "model_artifact_digest": "c" * 64}
            ),
        })


def test_prediction_inputs_disagreeing_with_their_bound_observations_are_refused():
    """The wire test builds its attack AROUND this check and never tests it.

    Without it the record replays numbers the cited observations do not contain, which is
    the whole reason `bound_inputs` exists.
    """
    obs = observations()
    with pytest.raises(ValueError, match="bound_inputs disagree"):
        PredictionInputs(
            metric="battery_temp_c",
            values=tuple(o.value for o in obs),
            horizon_seconds=259200,
            model_version="degradation-baseline@1.3.0",
            input_fingerprint="f" * 64,
            bound_inputs=tuple(
                PredictionInput(o.observation_id, o.content_digest(), 99.9) for o in obs
            ),
        )


def test_a_trail_that_does_not_open_at_delivered_is_refused_by_the_shared_checker():
    """`check_trail` is called from both boundaries; only `advance` was tested."""
    from cai.lifecycle import DispositionEvent, DispositionState, IllegalTransition, check_trail

    with pytest.raises(IllegalTransition, match="before it was delivered"):
        check_trail((
            DispositionEvent(DispositionState.ACKNOWLEDGED, t(12, 9), "ops"),
        ))


def test_a_trail_opening_before_delivery_is_refused():
    """A product cannot be acknowledged before it was sent, even by a well-formed trail.

    The refusal is now the equality rule rather than an ordering one: the trail's opening
    event IS the delivery, so any moment other than the delivery's own is two answers to
    one question. Before and after are refused by the same comparison, which is why the
    message no longer says "before".
    """
    from cai.envelope import IntelligenceEnvelope
    from cai.lifecycle import DispositionEvent, DispositionState

    with pytest.raises(ValueError, match="two moments"):
        IntelligenceEnvelope(
            product=deliver(),
            lifecycle_events=(
                DispositionEvent(DispositionState.DELIVERED, t(11, 0), "system"),
            ),
        )


@pytest.mark.parametrize("kwargs,pattern", [
    ({"event_type": "RETRACTED", "reason": ""}, "no reason"),
    ({"event_type": "SUPERSEDED", "replacement_product_id": None}, "name what replaced"),
])
def test_a_status_event_that_says_nothing_is_refused(kwargs, pattern):
    """Both were asserted in the class docstring and neither was exercised."""
    from cai.envelope import StatusEvent, StatusEventType

    with pytest.raises(ValueError, match=pattern):
        StatusEvent(
            StatusEventType(kwargs.pop("event_type")), t(12, 9), "ops-lead", **kwargs
        )


def test_two_supersessions_naming_different_replacements_are_refused():
    """A reader following the lineage forward has to pick one, and nothing says which."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="two current replacements"):
        IntelligenceEnvelope(
            product=deliver(),
            status_events=(
                StatusEvent(StatusEventType.SUPERSEDED, t(12, 9), "system",
                            replacement_product_id="ip-002"),
                StatusEvent(StatusEventType.SUPERSEDED, t(12, 10), "system",
                            replacement_product_id="ip-003"),
            ),
        )


def test_an_event_after_a_retraction_is_refused():
    """A claim already withdrawn has no standing left to change, and a reader deriving
    status from the last event would report the wrong one."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    with pytest.raises(ValueError, match="follows a retraction"):
        IntelligenceEnvelope(
            product=deliver(),
            status_events=(
                StatusEvent(StatusEventType.RETRACTED, t(12, 9), "ops", reason="moved"),
                StatusEvent(StatusEventType.SUPERSEDED, t(12, 10), "system",
                            replacement_product_id="ip-002"),
            ),
        )


def test_a_duplicate_status_event_is_refused():
    """A sequence recording one fact twice cannot be replayed into a single history."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    event = StatusEvent(StatusEventType.SUPERSEDED, t(12, 9), "system",
                        replacement_product_id="ip-002")
    with pytest.raises(ValueError, match="duplicate"):
        IntelligenceEnvelope(product=deliver(), status_events=(event, event))


def test_one_supersession_and_one_retraction_before_it_still_form():
    """Non-triviality twin for the whole sequence audit: the ordinary histories must
    remain expressible, or the rules above would pass against an envelope that refused
    every sequence."""
    from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType

    superseded = IntelligenceEnvelope(
        product=deliver(),
        status_events=(StatusEvent(StatusEventType.SUPERSEDED, t(12, 9), "system",
                                   replacement_product_id="ip-002"),),
    )
    then_retracted = IntelligenceEnvelope(
        product=deliver(),
        status_events=(
            StatusEvent(StatusEventType.SUPERSEDED, t(12, 9), "system",
                        replacement_product_id="ip-002"),
            StatusEvent(StatusEventType.RETRACTED, t(12, 11), "ops", reason="recalled"),
        ),
    )
    assert superseded.status_at(t(12, 10)) is ProductStatus.SUPERSEDED
    assert then_retracted.status_at(t(12, 12)) is ProductStatus.RETRACTED


def test_a_snapshot_citing_readings_the_release_never_saw_is_refused():
    """Fires on the LIVE release path, not merely on import.

    `observation_ids` is the pointer list a later reader follows, and it was checked only
    for non-emptiness -- so a record could cite readings that do not exist while the
    aggregate digest and the bound inputs both verified against a different set entirely.

    WAVE 4 NOTE. The original construction -- citing ids while the bound inputs named a
    different set -- is now refused by `EvidenceSnapshot.__post_init__` itself, so it can
    no longer reach the release path at all.

    The replacement has to be built with care, and the first attempt was wrong: handing
    release a bundle of entirely different readings makes THIS test pass on the bound-input
    check instead, and the surviving mutant said so. The construction below isolates the
    cited-vs-verified comparison and nothing else -- the bundle holds one reading MORE than
    the snapshot cites, the digest is taken over the whole bundle so the digest arm cannot
    fire, and every bound input still resolves. The only thing wrong with this record is
    that it tells a reader to follow five pointers when six readings were verified.
    """
    c = candidate()
    wider = observations() + (
        Observation("a-5", "asset-4417", "battery_temp_c", 71.2, t(11, 6), t(11, 7),
                    "source-a"),
    )
    snapshot = EvidenceSnapshot(**{
        **evidence(c.prediction_claim).__dict__,
        "evidence_content_digest": digest_observations(wider),
    })
    product = deliver(candidate=c, evidence=snapshot,
                      observation_log=log_of(wider))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_the_policy_digest_covers_the_thresholds_that_actually_decide():
    """The digest exists "so a threshold edited without a version bump is still
    detectable", and for the numbers that decided the identity and support DIMENSIONS it
    could not: those lived in a second copy in `release.py` that the digest never hashed.

    Moving the policy's floor must move the outcome. That is only true if the dimension
    reads the policy's number rather than a duplicate of it.
    """
    from cai.evidence import Identity

    strict = ReleasePolicy(identity_floor=0.99)
    assert strict.digest() != ReleasePolicy().digest(), "the digest must track the floor"
    assert deliver().determination is Determination.DELIVERED

    withheld = deliver(policy=strict)
    assert withheld.determination is Determination.ABSTAINED
    # On the RECORDED DIMENSION, not on the blocking reasons. The policy derives an
    # identity reason of its own from the same confidence, so a reasons-only assertion
    # passes whether or not the assessment's own floor came from the policy -- and a
    # hardcoded 0.85 back in `assess_evidence` would survive it.
    assert withheld.assurance.assessed.evidence_assessment.identity is Identity.AMBIGUOUS
    assert deliver().assurance.assessed.evidence_assessment.identity is Identity.RESOLVED


def test_a_relabelled_asset_is_refused_on_the_live_release_path_too():
    """The subject was free at BOTH boundaries, so this is not only a wire defect.

    Nothing anywhere compared `claim.subject` to `Observation.subject`. Relabelling the
    claim, the identity assertion and the entitlement together produced a DELIVERED
    product about a machine whose telemetry the release path never saw.
    """
    honest = claim()
    forged = PredictionClaim(**{**honest.__dict__, "subject": "asset-9999/battery-pack"})
    with pytest.raises(ValueError, match="does not describe its own evidence"):
        deliver(
            candidate=candidate(claim=forged),
            assurance=assurance(
                identity=IdentityAssertion(
                    "asset-9999/battery-pack", "resolver-a", "1.0", 0.97,
                    evidence_refs=("serial-plate-scan-8841",)),
                entitlement=entitlement(subject="asset-9999/battery-pack")),
            evidence=evidence(forged),
        )


def test_a_reading_about_another_asset_never_reaches_the_release_assessment():
    """WAS a refusal test; is now an exclusion test, and the change is the point.

    The old version handed release a bundle mixing two subjects and asserted the
    multi-subject refusal fired. Release no longer accepts a bundle: it asks the log for
    the point-in-time view OF THE SNAPSHOT'S SUBJECT, so a reading about another asset is
    not refused, it is never in scope. That is the stronger outcome -- an invalid state
    that cannot be constructed beats one that is detected.

    The refusal itself has not been deleted and is not untested. It remains reachable at
    the import boundary, where a bundle DOES arrive from outside, and
    `test_wire.test_an_imported_bundle_mixing_two_subjects_is_refused` exercises it there.
    """
    mixed = observations() + (
        Observation("b-0", "asset-9999", "battery_temp_c", 41.0, t(8, 6), t(8, 7),
                    "source-a"),
    )
    product = deliver(observation_log=log_of(mixed))
    assert product.determination is Determination.DELIVERED
    carried = {o.subject for o in product.release_evidence.observations}
    assert carried == {"asset-4417"}, carried
    assert "b-0" not in {o.observation_id for o in product.release_evidence.observations}


def test_a_claim_the_walk_never_mentions_is_refused():
    """The derivation is the one place the record states, in its own words, which asset
    this decision is for. Evidence and reasoning describing different things is a record
    contradicting itself in plain text."""
    elsewhere = tuple(
        Observation(o.observation_id, "asset-0001", o.metric, o.value, o.valid_time,
                    o.transaction_time, o.source_system)
        for o in observations()
    )
    with pytest.raises(ValueError, match="does not describe its own evidence"):
        deliver(observation_log=log_of(elsewhere))


def test_a_claim_cannot_outlive_the_window_it_describes():
    """`valid_until` answered to nothing at the far end.

    The only check was "after delivery", so a product about the next 72 hours could be
    stamped valid until 2099 and read ACTIVE forever -- on the one question perishability
    exists to answer.
    """
    from datetime import datetime as _dt

    with pytest.raises(ValueError, match="cannot outlive the window"):
        deliver(valid_until=_dt(2099, 1, 1, tzinfo=timezone.utc))


def test_a_valid_until_inside_the_window_still_delivers_and_still_expires():
    """Non-triviality twin: the bound is on outliving the window, not on having one.

    `t(13, 11)` was the close of the loading window and eight hours past the action's
    deadline, so this now sits strictly inside both bounds rather than outside the
    tighter one.
    """
    product = deliver(valid_until=t(13, 2))
    assert product.determination is Determination.DELIVERED
    assert product.status_at(t(13, 1)) is ProductStatus.ACTIVE
    assert product.status_at(t(13, 3)) is ProductStatus.EXPIRED


def test_release_does_not_emit_a_record_its_own_importer_would_refuse():
    """The fingerprint check ran at import and not at release, and the wave-1 reasoning
    for that was wrong: the replay recomputes a fingerprint and compares it to the CLAIM's,
    never to the copy stored in `prediction_inputs`.

    So a stored fingerprint could disagree with both, release would deliver, and the
    importer would refuse the record this path had just produced.
    """
    c = claim()
    snapshot = evidence(c)
    mismatched = EvidenceSnapshot(**{
        **snapshot.__dict__,
        "prediction_inputs": PredictionInputs(**{
            **snapshot.prediction_inputs.__dict__, "input_fingerprint": "a" * 64,
        }),
    })
    product = deliver(candidate=candidate(claim=c), evidence=mismatched)
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_telemetry_finer_than_the_wire_form_is_refused_at_the_boundary():
    """An entirely honest product whose own envelope its own importer refuses is worse
    than a refusal: the producer can still fix a refusal.

    Values cross at six decimals and the fingerprint hashes them at full precision, so
    one reading of 41.0000001 delivered cleanly and then failed to re-import.
    """
    # The bound inputs are present and correct. Without them `PredictionInputs` refuses
    # for a different and earlier reason -- unbound values -- and this test would pass on
    # that instead of on the precision boundary it is named for.
    lossy = (41.0000001, 45.6, 51.4)
    with pytest.raises(ValueError, match="more precision than"):
        PredictionInputs(
            metric="battery_temp_c", values=lossy,
            horizon_seconds=259200, model_version="degradation-baseline@1.3.0",
            input_fingerprint="f" * 64,
            bound_inputs=tuple(
                PredictionInput(f"a-{i}", f"{i:064d}", v) for i, v in enumerate(lossy)
            ),
        )


def test_prediction_inputs_with_no_bound_observations_cannot_exist():
    """THE HOSTILE PASS FOUND THIS ONE, and it re-opened the defect `PredictionInput`
    was introduced to close.

    Every downstream check read `if pi.bound_inputs:`, so an EMPTY tuple disabled all
    three of them -- and the field's own docstring blessed it: "Empty means the values
    are unbound assertions." An unbound assertion is precisely the state the join exists
    to make impossible, reachable by leaving a field out.

    The constructed attack: five fabricated values, no bound inputs, the five genuine
    readings still cited, the genuine aggregate digest, and a fingerprint and replay that
    both verify because both are computed over the fabricated values. It released as
    DELIVERED with a score of 0.0255 where the honest claim is 0.4942, and imported
    cleanly. See `test_portable_evidence` for the end-to-end version.
    """
    with pytest.raises(ValueError, match="no bound observations are unbound assertions"):
        PredictionInputs(
            metric="battery_temp_c", values=(41.0, 45.6, 51.4),
            horizon_seconds=259200, model_version="degradation-baseline@1.3.0",
            input_fingerprint="f" * 64,
        )


def test_the_operator_facing_timestamp_does_not_read_the_process_locale():
    """`%b` renders month names through LC_TIME.

    A producer under fr_FR.UTF-8 stamped "13 juin" into the delivered card and the
    action's sentence while recording `locale="en"` beside it -- and every reader in a
    different locale then refused the bundle, because both strings are re-derived and
    compared on import. "Verifiable outside the platform that produced it" was false
    across process locales.
    """
    import locale as _locale

    from cai.decision import format_moment

    rendered = format_moment(t(13, 3))
    assert rendered == "03:00 UTC on 13 Jun"
    for candidate_locale in ("fr_FR.UTF-8", "de_DE.UTF-8"):
        try:
            _locale.setlocale(_locale.LC_TIME, candidate_locale)
        except _locale.Error:
            continue
        try:
            assert format_moment(t(13, 3)) == rendered, (
                f"{candidate_locale} changed the operator-facing timestamp"
            )
        finally:
            _locale.setlocale(_locale.LC_TIME, "C")


def test_a_claim_whose_subject_the_walk_never_mentions_is_refused():
    """Isolates the derivation half of the subject binding from the prefix half.

    Here the claim's subject and the readings' subject AGREE -- so the "a claim is about
    the observed subject or a part of it" rule passes -- and the walk that produced the
    consequence names a different machine entirely. Without this, the evidence and the
    reasoning in one record describe different things and nothing says so.
    """
    spare = tuple(
        Observation(o.observation_id, "asset-4417-spare", o.metric, o.value,
                    o.valid_time, o.transaction_time, o.source_system)
        for o in observations()
    )
    honest = claim()
    forged = PredictionClaim(**{**honest.__dict__, "subject": "asset-4417-spare"})
    with pytest.raises(ValueError, match="never mentions"):
        deliver(
            candidate=candidate(claim=forged),
            assurance=assurance(
                identity=IdentityAssertion(
                    "asset-4417-spare", "resolver-a", "1.0", 0.97,
                    evidence_refs=("serial-plate-scan-8841",)),
                entitlement=entitlement(subject="asset-4417-spare")),
            evidence=EvidenceSnapshot(**{
                **evidence(forged).__dict__, "subject": "asset-4417-spare"}),
            observation_log=log_of(spare),
        )


def test_a_snapshot_that_misreports_what_it_observed_is_refused():
    """The RELEASE-path half: the snapshot's own `subject` must be the bundle's.

    The refusal is now a raise rather than an abstention, and that is the honest
    classification. The snapshot's subject is what release asks the log for, so a snapshot
    naming an asset the log has nothing about produces a claim resting on no readings at
    all -- an incoherent input, not a business withholding. An abstention is a product
    that exists and was withheld; there is no product here to withhold.
    """
    c = candidate()
    misreported = EvidenceSnapshot(**{
        **evidence(c.prediction_claim).__dict__, "subject": "asset-9999",
    })
    with pytest.raises(ValueError, match="rests on no observations at all"):
        deliver(candidate=c, evidence=misreported)


def test_a_snapshot_naming_a_subject_the_log_does_have_is_still_refused():
    """The twin that does NOT rest on the log being empty for that subject.

    Without it the test above passes on "no observations" for any misreported subject,
    and would keep passing if the subject comparison itself were deleted. Here the log has
    readings for both assets, so the query returns a real bundle -- about the wrong thing.
    """
    c = candidate()
    elsewhere = tuple(
        Observation(f"z-{i}", "asset-9999", o.metric, o.value, o.valid_time,
                    o.transaction_time, o.source_system)
        for i, o in enumerate(observations())
    )
    misreported = EvidenceSnapshot(**{
        **evidence(c.prediction_claim).__dict__, "subject": "asset-9999",
    })
    with pytest.raises(ValueError, match="but every reading it rests on is about"):
        deliver(candidate=c, evidence=misreported,
                observation_log=log_of(observations() + elsewhere))


# ---------------------------------------------------------------------------
# WAVE 4. Four independent auditors attacked the wave-3 result. The
# build->read direction they were hunting was closed; what they found instead
# was the mirror image, on the release side, plus a REASON path that was never
# required to be a path. WAVE4_AUDIT_FINDINGS.md records all thirty.
# ---------------------------------------------------------------------------


def _walk(*steps):
    """A derivation over the hero clock, so a test can vary only the steps."""
    from cai.derivation import ConsequenceDerivation

    return ConsequenceDerivation(
        rule_version="context-rules@0.8.0",
        knowledge_cutoff=t(12, 7),
        evaluated_window=TimeInterval(t(12, 7), t(15, 7)),
        steps=steps,
    )


def _step(rel, subj, obj, hour=1):
    """A topology fixture, scoped the way the graph scopes each relation.

    The intervals are not incidental. Since the derivation checks each relation at the
    moments the graph checks it, a fixture that leaves them off is asserting a shape no
    source system can hold -- so a test about WHERE the walk goes would fail on WHEN.
    """
    from cai.derivation import DerivationStep

    scope = {
        "HAS_COMPONENT": (t(1), None),
        "ASSIGNED_TO": (t(8), None),
        "SUPPORTS": (t(13, 5), t(13, 11)),
    }
    valid_from, valid_to = scope.get(getattr(rel, "value", rel), (None, None))
    return DerivationStep(rel, subj, obj, t(9, hour), "some-system", valid_from, valid_to)


def test_a_walk_whose_links_do_not_join_is_refused():
    """B1. `entities()` is a flat set and `terminal_entity` is only `steps[-1].object`,
    so every path check was satisfied by a walk that established nothing.

    The forgery kept the step naming the asset and the step naming the commitment and
    deleted the three in between. It reached DELIVERED, and `explain()` rendered `->`
    between links that do not join -- the record sold a commitment at risk while its own
    stated reason never connected the asset to it.
    """
    with pytest.raises(ValueError, match="which nothing earlier in the walk reached"):
        _walk(
            _step("ASSIGNED_TO", "asset-4417", "zone-3"),
            # SUPPORTS(zone-3,win-9) and LOADS(win-9,ship-22) are simply not here.
            _step("FULFILLS", "ship-22", "commit-7"),
        )


def test_the_walk_the_graph_actually_produces_still_forms():
    """The non-triviality twin. A connectivity rule that refused the real walk would be
    a rule that refuses everything, and the suite would still be green."""
    real = derivation()
    assert real.steps
    assert real.explain().startswith("HAS_COMPONENT(asset-4417,battery-pack-1)")


def test_a_walk_may_branch_from_anything_it_has_already_reached():
    """The hero walk itself branches: HAS_COMPONENT and ASSIGNED_TO both start at the
    asset. The rule is reachability, not a single-file chain, and this fixes that
    reading in place so a later tightening to `steps[i].object == steps[i+1].subject`
    cannot pass unnoticed."""
    walk = _walk(
        _step("HAS_COMPONENT", "asset-4417", "battery-pack-1"),
        _step("ASSIGNED_TO", "asset-4417", "zone-3"),
        _step("SUPPORTS", "zone-3", "win-9"),
    )
    assert walk.terminal_entity == "win-9"


def test_a_claim_about_a_part_nobody_asserted_is_refused():
    """B2. The derivation check tested the OBSERVED subject, never the claim's, so
    everything after the first `/` was a free variable. A claim about
    `asset-4417/hydraulic-pump` released on `battery_temp_c` telemetry, with the walk
    naming `battery-pack-1` at every step.

    The part is bound to the one field that asserts what kind of thing this is: the
    applicability assertion's `subject_type`, which is already checked against the
    model's declared envelope.
    """
    import dataclasses as dc

    c = candidate()
    relabelled = dc.replace(c.prediction_claim, subject="asset-4417/hydraulic-pump")
    with pytest.raises(ValueError, match="no assertion says this claim is about"):
        deliver(
            candidate=candidate(claim=relabelled),
            assurance=assurance(
                identity=IdentityAssertion(
                    "asset-4417/hydraulic-pump", "resolver-a", "1.0", 0.97,
                    evidence_refs=("serial-plate-scan-8841",)),
                entitlement=entitlement(subject="asset-4417/hydraulic-pump")),
        )


def test_the_part_the_applicability_assertion_names_still_releases():
    """The twin. The hero claim IS about a part -- `asset-4417/battery-pack` over
    readings about `asset-4417` -- so a rule that refused parts outright would refuse
    the reference path."""
    product = deliver()
    assert product.determination is Determination.DELIVERED
    assert product.candidate.prediction_claim.subject == "asset-4417/battery-pack"


def test_an_action_aimed_at_something_the_record_never_mentions_is_refused():
    """C1. `action.target` was read in exactly two places -- to render the sentence and
    to write it to the wire. `rendered_text` is re-derived and compared on import, so
    that check confirmed the record faithfully reproduced the wrong instruction.

    The delivered card read `replace asset-8899/hydraulic-pump` over evidence about
    asset-4417's battery pack. It is the one field an operator physically acts on.
    """
    misdirected = ActionRecommendation(
        "act-001", ActionType.REPLACE, "asset-8899/hydraulic-pump", "maintenance",
        t(13, 3), TimeInterval(t(13, 5), t(13, 11)),
        "degradation signal over the commitment horizon", Priority.IMMEDIATE,
    )
    with pytest.raises(ValueError, match="the instruction is about a different thing"):
        deliver(candidate=candidate(action=misdirected))


def test_an_action_aimed_at_the_component_the_walk_reached_still_releases():
    """The twin. The hero action targets `battery-pack-1`, which is not the claim's
    subject -- it is what the walk's HAS_COMPONENT step reached. A rule comparing the
    target to the claim's subject alone would refuse the reference path."""
    product = deliver()
    assert product.determination is Determination.DELIVERED
    assert product.candidate.action.target == "battery-pack-1"


def test_a_snapshot_citing_readings_it_did_not_use_is_refused():
    """D1. Both halves are on the wire: the ids a reader is told to follow, and the ids
    actually replayed in `prediction_inputs.bound_inputs`. Release compared them; import
    did not, so a record cited five readings that produced nothing in it and graded its
    own integrity VALID.

    The rule lives on the snapshot, which is the one object holding both, so it fires for
    a record built in process and one arriving off the wire without either boundary
    having to remember.
    """
    c = candidate()
    honest = evidence(c.prediction_claim)
    with pytest.raises(ValueError, match="the readings the number came from"):
        EvidenceSnapshot(**{
            **honest.__dict__,
            "observation_ids": ("batch-77-r1", "batch-77-r2", "batch-77-r3",
                                "batch-77-r4", "batch-77-r5"),
        })


def test_a_snapshot_citing_more_readings_than_the_model_consumed_still_forms():
    """The twin, and it is not hypothetical: the reference scenario collects from two
    feeds and computes over one, citing nine readings while binding five.

    An intermediate version of this rule demanded the two lists be identical and broke
    exactly that. The comparison release makes is citation-against-BUNDLE; the comparison
    here is citation-against-what-was-CONSUMED, and they are not the same rule. Only the
    direction that hides a reading from the reader is refused.
    """
    c = candidate()
    honest = evidence(c.prediction_claim)
    wider = EvidenceSnapshot(**{
        **honest.__dict__,
        "observation_ids": honest.observation_ids + ("b-9-collected-not-used",),
    })
    assert "b-9-collected-not-used" in wider.observation_ids


def test_a_snapshot_whose_digest_is_not_a_digest_is_refused():
    """D3. Purely syntactic, needing no observations, and it existed on one side only:
    release reported `integrity=BROKEN` and import delivered. A value that cannot be a
    SHA-256 is a malformed input rather than a business withholding, so it raises where
    the shape is known instead of travelling to a place that has the readings."""
    c = candidate()
    honest = evidence(c.prediction_claim)
    with pytest.raises(ValueError, match="cannot be a content digest"):
        EvidenceSnapshot(**{**honest.__dict__, "evidence_content_digest": "not-a-digest"})


def test_an_entitlement_with_a_blank_purpose_or_tenant_is_refused():
    """D8. `permits()` compares purpose and tenant with `!=`, so a blank on both sides
    satisfied two of the six scope dimensions vacuously. `recipient` is required and
    `authorized_source_systems` is fail-closed on empty; these two were neither, on the
    field whose own docstring calls tenant 'the dimension that leaks across customers'.
    """
    with pytest.raises(ValueError, match="authorises nothing it can be checked against"):
        entitlement(purpose="")
    with pytest.raises(ValueError, match="authorises nothing it can be checked against"):
        entitlement(tenant="")


def test_a_product_that_supersedes_itself_is_refused():
    """D5. The identical cycle expressed as a status event was already refused; expressed
    as lineage it was accepted. `test_a_product_cannot_supersede_itself` only ever
    exercised the status-event arm."""
    with pytest.raises(ValueError, match="arrives back where they started"):
        deliver(supersedes_product_id="ip-001")


def test_a_delivered_claim_with_no_validity_horizon_is_refused():
    """D6. Wave 3 closed 'stamped valid until 2099' and left the absent case open, so a
    72-hour claim read ACTIVE in 2099 and `release()` emitted it by default. The absence
    twin of a closed finding, in a module whose stated principle is that absence is never
    silently upgraded into presence."""
    with pytest.raises(ValueError, match="perishability"):
        deliver(valid_until=None)


def test_a_withheld_product_carrying_delivery_prose_is_refused():
    """C3. Every rendering check returned early for anything not DELIVERED, so 'nobody
    can author prose here because nobody authors it at all' was false for exactly the
    products nobody rendered. An abstained record carried a card reading '94% probability
    of pack failure within 72h'."""
    delivered = deliver()
    withheld = deliver(assurance=assurance(applicability=ApplicabilityAssertion(
        "degradation-baseline@1.3.0", "wind-turbine/gearbox", False,
        "subject type outside the model's declared envelope")))
    assert withheld.determination is Determination.ABSTAINED
    with pytest.raises(ValueError, match="nobody delivered"):
        type(withheld)(**{
            **withheld.__dict__, "rendered_delivery": delivered.rendered_delivery,
        })


def test_a_claim_below_the_release_authority_floor_abstains():
    """F1. Question five of the five `release.py`'s own docstring enumerates -- is the
    claim certain enough to act on -- had no coverage in either place that enforces it.
    Disabling the projection in `release.py` AND the reason in `policy.py` left the suite
    at 321 passed and the mutation harness at 118/118, while a claim of strength 0.75
    delivered under a policy requiring 0.99.

    Both halves are asserted here: the dimension the release path projects, and the
    reason the policy gives. A test on one of them alone leaves the other free.
    """
    strict = ReleasePolicy(min_evidence_strength=0.99)
    product = deliver(policy=strict)
    assert product.determination is Determination.ABSTAINED
    assert any("support=UNSUPPORTED" in r for r in product.assurance.blocking_reasons)
    assert any("evidence strength" in r for r in product.assurance.blocking_reasons)


def test_a_claim_above_the_release_authority_floor_still_delivers():
    """The twin. The hero claim is 0.75 against a default floor of 0.6, so the gate must
    let it through -- a floor that refused everything would satisfy the test above and
    ship nothing."""
    product = deliver(policy=ReleasePolicy(min_evidence_strength=0.6))
    assert product.determination is Determination.DELIVERED


def test_bound_inputs_fabricated_beside_genuine_readings_are_refused():
    """A4. The single line between fabricated telemetry and DELIVERED had no test at all.
    Replacing `release.py`'s bound-input comparison with `if False:` left the suite at
    321 passed, verified directly.

    The forgery is the one its own comment describes: cite genuine observations, carry
    their correct aggregate digest, and bind fabricated-but-internally-consistent inputs
    beside them. Everything the record says about itself agrees; only the readings
    disagree.

    The construction is deliberate. The bundle is the REAL readings, so the aggregate
    digest and the cited-id comparison both verify and cannot be what refuses this. The
    bound inputs carry the real content digests beside inflated values, which is the only
    way to reach the value comparison rather than the digest one.
    """
    obs = observations()
    inflated = obs[:-1] + (
        Observation("a-4", "asset-4417", "battery_temp_c", 120.0, t(12, 6), t(12, 7),
                    "source-a"),
    )
    real_digests = tuple(o.content_digest() for o in obs)
    forged_claim = PredictionClaim.from_prediction(
        predict_degradation(
            metric="battery_temp_c",
            values=tuple(o.value for o in inflated),
            horizon=context().horizon,
            bound=tuple(zip((o.observation_id for o in obs), real_digests)),
        ),
        subject="asset-4417/battery-pack",
    )
    snapshot = EvidenceSnapshot(**{
        **evidence_over(forged_claim, inflated, bound_digests=real_digests).__dict__,
        "evidence_content_digest": digest_observations(obs),
    })
    assert forged_claim.score > claim().score, "the forgery must actually inflate the claim"
    product = deliver(
        candidate=candidate(claim=forged_claim),
        evidence=snapshot,
        observation_log=log_of(obs),
    )
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_the_same_record_over_the_readings_it_actually_cites_still_delivers():
    """The twin for A4: the identical construction, with the bundle the record was built
    from. Otherwise the test above would pass against a check that refuses everything."""
    obs = observations()
    c = candidate(claim=claim_over(obs))
    product = deliver(
        candidate=c,
        evidence=evidence_over(c.prediction_claim, obs),
        observation_log=log_of(obs),
    )
    assert product.determination is Determination.DELIVERED


def test_evidence_the_decision_had_not_received_never_reaches_the_assessment():
    """A3, restated for the structural fix.

    The wave-4 version handed release a bundle containing a reading delivered eight days
    AFTER the decision and asserted a refusal, because nothing required the bundle to have
    come from `point_in_time_view`. Release performs that query itself now, so the late
    reading is excluded before anything is assessed -- and the product is withheld because
    the snapshot cites a reading the verified evidence does not contain, which is the
    honest description of what is wrong with this record.

    The refusal for a late reading is still enforced, at the boundary where one can still
    arrive: see `test_wire.test_an_imported_reading_the_decision_had_not_received_is_refused`.
    """
    late = observations()[:-1] + (
        Observation("a-4", "asset-4417", "battery_temp_c", 66.6, t(12, 6), t(20, 0),
                    "source-a"),
    )
    c = candidate(claim=claim_over(late))
    product = deliver(
        candidate=c,
        evidence=evidence_over(c.prediction_claim, late),
        observation_log=log_of(late),
    )
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)
    assert "a-4" not in {o.observation_id for o in product.release_evidence.observations}


def test_evidence_recorded_right_up_to_the_cutoff_still_releases():
    """The twin. The boundary is inclusive -- a reading recorded AT the cutoff was
    received by the decision-maker -- and a rule that refused it would refuse the hero,
    whose last reading lands hours before."""
    at_cutoff = observations()[:-1] + (
        Observation("a-4", "asset-4417", "battery_temp_c", 66.6, t(12, 6), t(12, 7),
                    "source-a"),
    )
    c = candidate(claim=claim_over(at_cutoff))
    product = deliver(
        candidate=c,
        evidence=evidence_over(c.prediction_claim, at_cutoff),
        observation_log=log_of(at_cutoff),
    )
    assert product.determination is Determination.DELIVERED


def test_a_snapshot_understating_which_feeds_it_used_is_refused():
    """A1. `permits()` was handed the snapshot's own CLAIM about which feeds it used.
    `Observation.source_system` exists, is in the bundle, and is inside `content_digest()`
    -- and nothing compared them, so the honest producer that declared both feeds was
    refused while the one that understated its feed list delivered on an unlicensed feed
    with the card reading "rights permitted".

    `assess_evidence` already verifies the snapshot's ids, digest, subject and bound
    inputs against the actual readings. This is the one declaration it did not check.
    """
    mixed = observations()[:-1] + (
        Observation("a-4", "asset-4417", "battery_temp_c", 66.6, t(12, 6), t(12, 7),
                    "source-BLACKMARKET"),
    )
    c = candidate(claim=claim_over(mixed))
    snapshot = EvidenceSnapshot(**{
        **evidence_over(c.prediction_claim, mixed).__dict__,
        "source_systems": ("source-a",),
    })
    product = deliver(candidate=c, evidence=snapshot,
                      observation_log=log_of(mixed))
    assert product.determination is Determination.ABSTAINED
    assert any("integrity" in r for r in product.assurance.blocking_reasons)


def test_a_confidence_finer_than_the_wire_form_is_refused():
    """E1. The six-decimal fix closed ONE call site of a class, not the class.

    `identity_confidence` is written at six decimals and rendered on the card at two, so
    a confidence of 0.8749999999 delivered honestly, crossed as "0.875000", and re-imported
    as a card reading 0.88 beside a producer's card reading 0.87 -- refused by this
    package's own importer, on the hero path, with an ordinary-looking number.

    Same rule as `PredictionInputs`: a value that does not survive its own wire form is
    refused where the producer can still quantize it, not discovered by a reader.
    """
    with pytest.raises(ValueError, match="would not survive its own round trip"):
        IdentityAssertion("asset-4417/battery-pack", "resolver-a", "1.0", 0.8749999999,
                          evidence_refs=("serial-plate-scan-8841",))


def test_a_confidence_the_wire_form_carries_exactly_still_forms():
    """The twin. Six decimals is a real precision, not a ban on decimals: the hero's 0.97
    and anything else expressible at 6dp must still form, or the rule refuses everything
    and the test above proves nothing."""
    for value in (0.97, 0.875, 0.123456, 1.0, 0.0):
        assert IdentityAssertion(
            "asset-4417/battery-pack", "resolver-a", "1.0", value,
            evidence_refs=("serial-plate-scan-8841",)).confidence == value


def test_downtime_hours_finer_than_the_wire_form_are_refused():
    """The same class, on the other float that crosses at a fixed precision.
    `expected_hours_lost` is written at two decimals and described with `:g`, so every
    value with more precision than 2dp delivered and could not re-import."""
    with pytest.raises(ValueError, match="would not survive its own round trip"):
        DowntimeConsequence(
            "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
            asset_id="asset-4417", affected_operation="loading",
            expected_hours_lost=3.456,
        )


def test_downtime_hours_the_wire_form_carries_exactly_still_form():
    """The twin, for the two-decimal field."""
    c = DowntimeConsequence(
        "DOWNTIME", TimeInterval(t(13, 5), t(13, 11)), derivation(),
        asset_id="asset-4417", affected_operation="loading",
        expected_hours_lost=3.45,
    )
    assert c.expected_hours_lost == 3.45


def test_evidence_naming_different_semantic_rules_than_the_walk_is_refused():
    """B4. Which rules produced the walk is ONE fact, recorded twice with nothing
    comparing the copies -- and the shipped fixture itself carried `context-rules@0.7.0`
    on the evidence beside `context-rules@0.8.0` on the derivation. No forgery was
    required to find it; the honest release path emitted the disagreement.

    The model version and the two identity confidences are bound for exactly this reason.
    """
    c = candidate()
    stale = EvidenceSnapshot(**{
        **evidence(c.prediction_claim).__dict__,
        "semantic_rule_version": "context-rules@0.7.0",
    })
    with pytest.raises(ValueError, match="two answers out of one bundle"):
        deliver(candidate=c, evidence=stale)


def test_the_shipped_record_names_one_set_of_semantic_rules():
    """The twin, and the regression guard for the fixture that was wrong. A rule nothing
    satisfies would refuse the hero; a fixture nobody checks drifts again."""
    product = deliver()
    assert product.evidence.semantic_rule_version == (
        product.candidate.business_consequence.derivation.rule_version
    )


def test_facts_cannot_be_evaluated_as_true_after_the_decision_was_taken():
    """D9. `evaluation_time` is the moment facts are evaluated as true-in-the-world, and
    it was the one member of the temporal triple bound to nothing: `knowledge_cutoff <=
    model_decision_time` was enforced and evaluation_time accepted 2099.

    A decision cannot have evaluated the world at a moment that had not happened when it
    was taken -- that is the same anachronism the cutoff rule exists to refuse, on the
    third clock rather than the second.
    """
    with pytest.raises(ValueError, match="had not happened when the decision was taken"):
        DecisionContext(t(12, 7), t(12, 7), datetime(2099, 1, 1, tzinfo=timezone.utc),
                        TimeInterval(t(12, 7), t(15, 7)))


def test_facts_evaluated_at_the_moment_of_decision_still_form():
    """The twin. The hero evaluates at exactly the decision time, so the boundary is
    inclusive and a rule refusing it would refuse every fixture in this suite."""
    ctx = DecisionContext(t(12, 7), t(12, 7), t(12, 7), TimeInterval(t(12, 7), t(15, 7)))
    assert ctx.evaluation_time == ctx.model_decision_time


def test_a_fingerprint_that_matches_while_its_inputs_disagree_is_still_refused():
    """F6. `input_fingerprint_mismatch` has three discriminators AFTER the fingerprint
    comparison -- metric, horizon and model version -- and all three were reachable and
    untested: an attacker can set the claim's fingerprint to the inputs' fingerprint so
    the comparison above them passes, leaving these to decide.

    Backstopped by the whole-record replay, which is why the auditor rated this P1 rather
    than P0 -- but a check whose only evidence is another check is not evidence.

    The MODEL-VERSION discriminator is deliberately not exercised here, and the reason is
    worth recording rather than leaving as a gap somebody re-finds: a claim whose
    `model_version` disagrees with the envelope it carries is refused by
    `PredictionClaim.__post_init__` first, so that arm is not reachable through a validly
    constructed claim. It is reachable only by moving the declared envelope too, at which
    point `verify_bindings` refuses on the envelope instead. Asserting it here would mean
    asserting against a claim this package cannot produce.
    """
    from cai.binding import input_fingerprint_mismatch
    import dataclasses as dc

    c = candidate()
    snapshot = evidence(c.prediction_claim)
    for field, value, fragment in (
        ("metric", "hydraulic_pressure_kpa", "the inputs are"),
        ("horizon_seconds", 999, "the inputs cover"),
    ):
        forged = dc.replace(c.prediction_claim, **{field: value})
        reason = input_fingerprint_mismatch(
            dc.replace(snapshot, prediction_inputs=dc.replace(
                snapshot.prediction_inputs,
                input_fingerprint=forged.input_fingerprint)),
            forged,
        )
        assert reason is not None and fragment in reason, (field, reason)
