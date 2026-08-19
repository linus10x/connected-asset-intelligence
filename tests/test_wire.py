"""The import boundary: does a bundle off the wire carry the in-memory guarantees?

WHY THIS SUITE EXISTS
---------------------
The repository claimed a language-neutral portable contract and tested deterministic
canonical bytes, changed-field-changes-digest, unknown-schema rejection and causal-language
rejection. All true, and none of them the claim being made.

`validate_envelope_payload` checked five things: schema version, the attributed-effect
vocabulary, lifecycle transition order, lifecycle chronology, and whether an outcome
matched an outcome state. It never reconstructed the candidate, the claim, the decision
context, the consequence, the action, the assurance assertions, the entitlement scope, the
rendered-delivery digest, or the product's validity semantics. The JSON Schema left the
load-bearing structures as unconstrained `"type": "object"`. And the test calling itself
"round-trip fidelity" serialized, digested, and never parsed anything back.

So a payload could be schema-shaped, pass validation, and assert a claim whose knowledge
cutoff postdated its decision -- the exact defect the in-memory types make impossible.

The fix is reconstruction rather than a parallel wire validator. Rebuilding the typed
objects runs their own `__post_init__` invariants, so there is one semantics engine and the
importer cannot drift from it. A second hand-written validator would be a second engine,
and the two would disagree on the day it mattered.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import test_formation as T
from cai.envelope import (
    IntelligenceEnvelope,
    UnsupportedAttributedEffect,
    UnsupportedSchemaVersion,
    import_envelope,
)


def wire(**over) -> dict:
    """A delivered product, serialized exactly as it would cross a boundary."""
    env = IntelligenceEnvelope(product=T.deliver(**over))
    return json.loads(env.canonical_json())


def broken(mutate) -> dict:
    """A payload with exactly one invariant violated, everything else untouched."""
    payload = wire()
    mutate(payload)
    return payload


# ---------------------------------------------------------------------------
# ROUND TRIP. Not "it serializes deterministically" -- it comes back.
# ---------------------------------------------------------------------------


def test_a_delivered_product_survives_the_wire_intact():
    """typed domain -> record -> canonical bytes -> parse -> import -> typed domain.

    Byte-identical re-serialization is the strongest available assertion: any field the
    importer silently drops, coerces, or reorders shows up as a diff. A field-by-field
    comparison would only check the fields somebody remembered to list.
    """
    original = IntelligenceEnvelope(product=T.deliver())
    text = original.canonical_json()

    rebuilt = import_envelope(json.loads(text))

    assert rebuilt.canonical_json() == text
    assert rebuilt.digest() == original.digest()


def test_the_reconstruction_is_typed_not_a_bag_of_scalars():
    """A dict that re-serializes correctly but is not the domain proves nothing.

    The point of reconstruction is that the domain's own invariants run. If import
    returned dictionaries, every assertion below this line would be vacuous.
    """
    from cai.candidate import IntelligenceCandidate
    from cai.contract import EvidenceSnapshot, PredictionClaim
    from cai.decision import DecisionContext
    from cai.delivery import RenderedDelivery
    from cai.product import IntelligenceProduct

    rebuilt = import_envelope(wire())
    product = rebuilt.product

    assert isinstance(product, IntelligenceProduct)
    assert isinstance(product.candidate, IntelligenceCandidate)
    assert isinstance(product.candidate.context, DecisionContext)
    assert isinstance(product.candidate.prediction_claim, PredictionClaim)
    assert isinstance(product.evidence, EvidenceSnapshot)
    assert isinstance(product.rendered_delivery, RenderedDelivery)


def test_the_protected_values_are_semantically_equal_not_merely_present():
    original = T.deliver()
    rebuilt = import_envelope(wire()).product

    assert rebuilt.product_id == original.product_id
    assert rebuilt.determination is original.determination
    assert rebuilt.recipient == original.recipient
    assert rebuilt.delivery_time == original.delivery_time
    assert rebuilt.valid_until == original.valid_until
    assert rebuilt.claim_series_id == original.claim_series_id

    oc, rc = original.candidate, rebuilt.candidate
    assert rc.context.model_decision_time == oc.context.model_decision_time
    assert rc.context.knowledge_cutoff == oc.context.knowledge_cutoff
    assert rc.context.prediction_window == oc.context.prediction_window
    assert rc.prediction_claim.subject == oc.prediction_claim.subject
    assert rc.prediction_claim.score == oc.prediction_claim.score
    assert rc.prediction_claim.input_fingerprint == oc.prediction_claim.input_fingerprint
    assert rc.prediction_claim.model_artifact_digest == (
        oc.prediction_claim.model_artifact_digest
    )
    assert rc.business_consequence.exposure_window == oc.business_consequence.exposure_window
    assert rc.action.due_by == oc.action.due_by

    assert rebuilt.assurance.policy_digest == original.assurance.policy_digest
    assert rebuilt.assurance.permitted is original.assurance.permitted
    assert rebuilt.evidence.evidence_content_digest == (
        original.evidence.evidence_content_digest
    )
    assert rebuilt.rendered_delivery.content_digest == (
        original.rendered_delivery.content_digest
    )


def test_the_evidence_snapshot_actually_crosses_the_wire():
    """It did not. `IntelligenceProduct.as_record()` omitted `evidence` entirely.

    The bundle claimed to preserve the in-memory guarantees while leaving out the evidence
    the whole claim rests on -- observation ids, content digest, prediction inputs, input
    fingerprint, source systems, capture time. A reader could not check the claim against
    anything, which is the one thing the portable form is for.
    """
    rebuilt = import_envelope(wire()).product.evidence
    original = T.deliver().evidence

    assert rebuilt.observation_ids == original.observation_ids
    assert rebuilt.evidence_content_digest == original.evidence_content_digest
    assert rebuilt.source_systems == original.source_systems
    assert rebuilt.captured_at == original.captured_at
    assert rebuilt.prediction_inputs.input_fingerprint == (
        original.prediction_inputs.input_fingerprint
    )
    assert rebuilt.prediction_inputs.bound_inputs == original.prediction_inputs.bound_inputs


def test_the_entitlement_scope_crosses_the_wire():
    """The record carried recipient, purpose, tenant, policy and basis.

    It dropped subject, validity window, the authorized source systems and both permission
    booleans -- so an importer could not re-run the authorization it claims to preserve,
    and the scope that was just made load-bearing in memory vanished on export.
    """
    original = T.deliver().assurance.assessed.context.entitlement_assertion
    rebuilt = import_envelope(wire()).product.assurance.assessed.context.entitlement_assertion

    # VALUES, not `hasattr`. On a frozen dataclass every field is always present, so the
    # old loop could not fail: an audit that corrupted `basis` and `policy_version` on
    # export left this test green while a different test caught it. `basis` matters most
    # -- an empty one is the sole trigger for EntitlementState.UNKNOWN.
    for field in ("recipient", "purpose", "subject", "tenant", "basis", "policy_id",
                  "policy_version", "valid_from", "valid_to",
                  "authorized_source_systems",
                  "may_use_source_data", "may_deliver_to_recipient"):
        assert getattr(rebuilt, field) == getattr(original, field), (
            f"{field} did not survive export unchanged"
        )
    assert rebuilt == original, "the whole clearance must round-trip, not a summary of it"


# ---------------------------------------------------------------------------
# THE LEARN BOUNDARY. `lifecycle_events` was `tuple[dict]` and `outcome` was
# `dict | None`, and the importer kept both as dictionaries -- while
# `DispositionEvent` and `OutcomeObservation` were real typed objects sitting
# beside them. So the portable contract preserved neither the typed boundary nor
# the outcome-to-action join that is the entire reason outcomes are collected.
# ---------------------------------------------------------------------------


def learned(**over) -> dict:
    """A delivered product carried through the whole loop: trail, outcome, envelope."""
    from cai.action import OutcomeObservation, OutcomeType
    from cai.decision import TimeInterval
    from cai.envelope import IntelligenceEnvelope
    from cai.lifecycle import DispositionEvent, DispositionState

    product = T.deliver()
    action_id = product.candidate.action.action_id
    trail = tuple(
        DispositionEvent(state, at, actor)
        for state, at, actor in (
            (DispositionState.DELIVERED, T.t(12, 7), "system"),
            (DispositionState.ACKNOWLEDGED, T.t(12, 9), "operations@customer"),
            (DispositionState.ACCEPTED, T.t(12, 14), "operations@customer"),
            (DispositionState.ACTION_COMPLETED, T.t(13, 2), "maintenance@customer"),
            (DispositionState.OUTCOME_OBSERVED, T.t(13, 4), "maintenance@customer"),
        )
    )
    outcome = OutcomeObservation(
        outcome_id=over.get("outcome_id", "out-001"),
        outcome_type=OutcomeType.DEFECT_FOUND_ON_INSPECTION,
        subject=over.get("subject", product.candidate.prediction_claim.subject),
        observation_window=TimeInterval(T.t(13, 2), T.t(13, 5)),
        observed_at=over.get("observed_at", T.t(13, 4)),
        source="maintenance-system",
        related_action_id=over.get("related_action_id", action_id),
        note="degraded cell; pack swapped before the window opened",
    )
    env = IntelligenceEnvelope(
        product=product, lifecycle_events=trail, outcome=outcome
    )
    return json.loads(env.canonical_json())


def test_the_lifecycle_trail_and_outcome_come_back_typed():
    """One representation, not two. `DispositionEvent` existed the whole time."""
    from cai.action import OutcomeObservation
    from cai.lifecycle import DispositionEvent, DispositionState

    rebuilt = import_envelope(learned())

    assert all(isinstance(e, DispositionEvent) for e in rebuilt.lifecycle_events)
    assert rebuilt.lifecycle_events[0].state is DispositionState.DELIVERED
    assert isinstance(rebuilt.outcome, OutcomeObservation)
    assert rebuilt.outcome.related_action_id == "act-001"


def test_the_learned_envelope_round_trips_byte_identically():
    """Any field the importer drops, coerces or reorders shows up as a diff."""
    from cai.envelope import IntelligenceEnvelope

    text = json.dumps(learned(), separators=(",", ":"), sort_keys=True)
    rebuilt = import_envelope(learned())
    assert json.dumps(
        json.loads(rebuilt.canonical_json()), separators=(",", ":"), sort_keys=True
    ) == text


@pytest.mark.parametrize("name,over,pattern", [
    ("an outcome about another subject", {"subject": "asset-9999"}, "subject"),
    ("an outcome joined to another action",
     {"related_action_id": "act-somebody-elses"}, "action"),
])
def test_an_outcome_that_does_not_bind_to_this_product_is_refused(name, over, pattern):
    """Without the join an evaluation dataset cannot separate 'acted and no failure'
    from 'ignored and no failure', and those two rows are the entire value of
    collecting outcomes. A join the importer does not check is not a join."""
    with pytest.raises(ValueError, match=pattern):
        import_envelope(learned(**over))


def test_an_outcome_observed_before_delivery_is_refused():
    """An outcome cannot be the outcome of a recommendation that had not been sent.

    Expressed through the observation WINDOW rather than the observation moment: the
    outcome type already refuses a reading taken before its own window opens, so a window
    starting after delivery makes the moment check unreachable. Testing the reachable one
    is the difference between guarding an invariant and appearing to.
    """
    # ONLY the window start moves. Moving `observed_at` as well now trips the rule binding
    # the trail's OUTCOME_OBSERVED moment to the outcome's own -- an earlier and different
    # check -- so this case would pass while the window rule was deleted. And moving the
    # trail event to match would trip lifecycle chronology instead. The window opening
    # before delivery is the one thing left that this fixture can be wrong about.
    payload = learned()
    payload["outcome"]["observation_window_start"] = "2026-06-11T00:00:00+00:00"
    with pytest.raises(ValueError, match="before the recommendation was delivered"):
        import_envelope(payload)


def test_the_genuine_learned_envelope_still_imports():
    """Non-triviality twin for the whole LEARN boundary."""
    rebuilt = import_envelope(learned())
    assert rebuilt.outcome.outcome_id == "out-001"
    assert len(rebuilt.lifecycle_events) == 5


def test_an_imported_lifecycle_trail_out_of_order_is_still_refused():
    """MIGRATED to the typed representation. The old check read raw dicts, which meant
    the wire and the memory each had their own idea of what a trail was.

    Raised as `IllegalTransition`, which is a `ValueError` -- a caller wrapping the import
    boundary in `except ValueError` must not let a malformed trail through while catching
    every other refusal.
    """
    from cai.lifecycle import IllegalTransition

    payload = learned()
    payload["lifecycle_events"][1]["at"] = "2026-06-12T06:00:00+00:00"
    with pytest.raises(IllegalTransition, match="chronolog|order"):
        import_envelope(payload)
    assert issubclass(IllegalTransition, ValueError)


def test_an_imported_lifecycle_trail_skipping_acknowledgement_is_refused():
    from cai.lifecycle import IllegalTransition

    payload = learned()
    payload["lifecycle_events"][1]["state"] = "ACTION_COMPLETED"
    with pytest.raises(IllegalTransition, match="transition"):
        import_envelope(payload)


def test_the_reason_path_survives_the_wire():
    """The walk was performed, used, and dropped on the floor before export.

    A reader outside the platform got "at risk: next-day delivery window, customer A" and
    nothing about why a battery temperature implies it. The governing contract asks for
    business consequence AND path; the bundle carried the first half.
    """
    from cai.derivation import ConsequenceDerivation, DerivationStep

    original = T.deliver().candidate.business_consequence.derivation
    rebuilt = import_envelope(wire()).product.candidate.business_consequence.derivation

    assert isinstance(rebuilt, ConsequenceDerivation)
    assert all(isinstance(s, DerivationStep) for s in rebuilt.steps)
    assert rebuilt == original
    # The six things a reader needs to answer WHY, none of which survived before.
    assert rebuilt.explain() == original.explain()            # relationship identity
    assert rebuilt.steps[0].valid_from == original.steps[0].valid_from  # temporal relevance
    assert rebuilt.steps[0].recorded_at == original.steps[0].recorded_at   # knowledge time
    assert rebuilt.rule_version == original.rule_version                  # rule version
    assert rebuilt.source_systems() == original.source_systems()          # provenance
    assert rebuilt.terminal_entity == original.terminal_entity            # the consequence


def test_a_payload_whose_derivation_does_not_reach_its_conclusion_is_refused():
    """A real path attached to somebody else's conclusion, arriving off the wire.

    The path and the conclusion are one object in memory precisely so they cannot be
    recombined; that guarantee is worth nothing if the importer will pair any path with
    any consequence.
    """
    payload = broken(lambda p: p["product"]["candidate"]["business_consequence"]
                     ["derivation"]["steps"][-1].__setitem__("object", "commit-99"))
    with pytest.raises(ValueError, match="derivation|terminat|path"):
        import_envelope(payload)


def test_a_payload_whose_derivation_used_a_fact_recorded_after_the_cutoff_is_refused():
    """The cutoff filters the walk; a reader must be able to check that it did.

    Every step carries the moment this system learned the fact, so a walk that used
    something recorded later is detectable from the record alone rather than something a
    reader has to take on faith.
    """
    payload = broken(lambda p: p["product"]["candidate"]["business_consequence"]
                     ["derivation"]["steps"][0].__setitem__(
                         "recorded_at", "2026-06-20T00:00:00+00:00"))
    with pytest.raises(ValueError, match="cutoff|recorded"):
        import_envelope(payload)


def test_a_payload_stripping_a_step_source_system_is_refused():
    """A fact nobody is recorded as having asserted cannot be challenged or corrected,
    and the premise of the whole derivation is that these facts come from different
    systems that have to agree."""
    payload = broken(lambda p: p["product"]["candidate"]["business_consequence"]
                     ["derivation"]["steps"][0].__setitem__("source_system", ""))
    with pytest.raises(ValueError, match="source"):
        import_envelope(payload)


# ---------------------------------------------------------------------------
# TYPED ASSURANCE ACROSS THE WIRE. `AssuranceDecision` stored the assurance basis
# as a raw dict, `from_record` took the dict as-is, and `import_envelope` never
# reconstructed the assertions or re-ran the bindings. A payload could therefore
# alter the recorded basis for a decision and the import boundary applied none of
# the guarantees that apply at live release.
# ---------------------------------------------------------------------------


def test_the_assurance_basis_comes_back_as_typed_assertions():
    """A dict that re-serializes is not the domain. If import returned dictionaries,
    every refusal below this line would be vacuous."""
    from cai.candidate import (
        ApplicabilityAssertion,
        AssessedAssurance,
        AssuranceContext,
        EntitlementAssertion,
        IdentityAssertion,
        TemporalAssertion,
    )
    from cai.evidence import EvidenceAssessment

    assessed = import_envelope(wire()).product.assurance.assessed

    assert isinstance(assessed, AssessedAssurance)
    assert isinstance(assessed.context, AssuranceContext)
    assert isinstance(assessed.context.identity_assertion, IdentityAssertion)
    assert isinstance(assessed.context.applicability_assertion, ApplicabilityAssertion)
    assert isinstance(assessed.context.temporal_assertion, TemporalAssertion)
    assert isinstance(assessed.context.entitlement_assertion, EntitlementAssertion)
    assert isinstance(assessed.evidence_assessment, EvidenceAssessment)


def test_the_assertion_provenance_survives_rather_than_degrading_to_a_verdict():
    """P1-1. Each of these existed in memory and was summarised away on export.

    `evidence_refs` is what an identity resolution can be challenged on; `subject_type` is
    the thing applicability is asserted ABOUT; a temporal assertion with no basis is a
    naked `valid=True`; and an entitlement with no policy version cannot be compared
    against the policy that was in force.
    """
    original = T.deliver().assurance.assessed.context
    rebuilt = import_envelope(wire()).product.assurance.assessed.context

    assert rebuilt.identity_assertion.evidence_refs == (
        original.identity_assertion.evidence_refs
    )
    assert rebuilt.identity_assertion.evidence_refs, "the fixture must exercise this"
    assert rebuilt.applicability_assertion.subject_type == (
        original.applicability_assertion.subject_type
    )
    assert rebuilt.temporal_assertion.basis == original.temporal_assertion.basis
    assert rebuilt.temporal_assertion.basis, "a verdict with no basis is an opinion"
    assert rebuilt.entitlement_assertion.policy_version == (
        original.entitlement_assertion.policy_version
    )


def test_an_imported_product_re_runs_the_bindings_live_release_ran(monkeypatch):
    """One set of binding functions, called from both boundaries -- proven by sabotage.

    This used to assert `"verify_bindings" in inspect.getsource(from_record)`, which the
    `from .binding import (...)` line inside that method satisfied all on its own: delete
    the CALL, keep the import, and the test still passed. Its second assertion,
    `verify_bindings.__module__ == "cai.binding"`, was a tautology.

    Replacing the module attribute and watching the import boundary blow up is behaviour:
    it can only pass if `from_record` actually reaches through `cai.binding` at call time.
    `formation` binds the name at import, so identity is the right assertion there.
    """
    import cai.binding as binding
    import cai.formation as formation

    assert formation.verify_bindings is binding.verify_bindings, (
        "the release path must use the shared function, not a local copy of its rules"
    )

    def sabotaged(*_args, **_kwargs):
        raise RuntimeError("the shared binding function was reached")

    monkeypatch.setattr(binding, "verify_bindings", sabotaged)
    with pytest.raises(RuntimeError, match="was reached"):
        import_envelope(wire())


@pytest.mark.parametrize("name,mutate,fragment", [
    ("identity resolves another entity", lambda p: _assurance(p)["identity"].__setitem__(
        "resolved_entity", "asset-0000"), "this is assurance for a different asset"),
    ("applicability names another model", lambda p: _assurance(p)["applicability"]
        .__setitem__("model_version", "some-other-model@9.9"),
     "the envelope checked belongs to a model that did not run"),
    ("applicability claims a subject type outside the envelope",
     lambda p: _assurance(p)["applicability"].__setitem__(
         "subject_type", "wind-turbine/gearbox"),
     "the assertion invents an envelope of its own"),
    ("temporal assertion names another decision", lambda p: _assurance(p)["temporal"]
        .__setitem__("model_decision_time", "2026-06-13T00:00:00+00:00"),
     "the context is the single temporal authority"),
    # Two cases, because the one that used to stand here was refused by a guard other
    # than the one it named. Moving the cutoff EARLIER makes the assertion internally
    # incoherent and never reaches `binding.py` at all; moving it LATER leaves it
    # internally fine and disagreeing with the context, which is the binding this case
    # was always meant to exercise. Both are real; only the second is the wire half of
    # `binding.verify_bindings`.
    ("temporal assertion draws features past its own cutoff",
     lambda p: _assurance(p)["temporal"].__setitem__(
         "knowledge_cutoff", "2026-06-11T00:00:00+00:00"),
     "features drawn past the knowledge cutoff"),
    ("temporal assertion names another knowledge cutoff",
     lambda p: _assurance(p)["temporal"].__setitem__(
         "knowledge_cutoff", "2026-06-13T00:00:00+00:00"),
     "the context is the single temporal authority"),
])
def test_a_payload_altering_the_recorded_assurance_basis_is_refused(name, mutate, fragment):
    """Each was enforced at live release and unenforced on import.

    The payload stays schema-shaped and internally consistent; only the recorded basis for
    the decision moves. That is the attack the import boundary existed to stop and did not.

    WAVE 4. This carried no `match=` at all, in a suite whose ledger claims "every
    adversarial wire case now carries the message fragment only its own invariant emits".
    One of the five was vacuous: the knowledge-cutoff case is refused by
    `TemporalAssertion.__post_init__`, not by the `binding.py` guard it names, so deleting
    that guard left all five green and only the in-memory test noticed. `binding.py`
    exists to be one set of functions called from BOTH boundaries, and the wire half of
    that binding had no test.
    """
    with pytest.raises((ValueError, TypeError, KeyError), match=fragment):
        import_envelope(broken(mutate))


def test_a_payload_altering_the_entitlement_scope_is_refused():
    """The clearance is re-run against the delivery the product records, not read back.

    The product now carries the purpose and tenant it was actually delivered under, so
    `permits()` can be re-evaluated by a reader holding nothing but the bundle. Without
    them the record asserted an authorization nobody outside the process could check.
    """
    payload = broken(lambda p: _assurance(p)["entitlement"].__setitem__(
        "subject", "asset-9999"))
    with pytest.raises(ValueError, match="entitlement|authoris|authoriz"):
        import_envelope(payload)


def test_a_payload_rewriting_a_dimension_under_its_own_verdict_is_refused():
    """The assessment is what decided, and its conclusion is derived from its dimensions.

    Rewriting one dimension while leaving `release` and `blocking_reasons` alone produces
    a record whose stated conclusion does not follow from its own contents. Re-deriving
    and silently overwriting it would be the other failure -- the bundle would import as
    something other than the bytes it arrived as, and nobody would be told.
    """
    payload = broken(lambda p: _assurance(p)["evidence"].__setitem__(
        "identity", "AMBIGUOUS"))
    with pytest.raises(ValueError, match="release|derived"):
        import_envelope(payload)


def test_a_payload_whose_permission_contradicts_its_own_assessment_is_refused():
    """One level up: an internally consistent assessment that withholds, under a decision
    that permitted. This is the system contradicting itself about the only question that
    matters, and it is checkable by any reader of any policy."""
    def rewrite(p):
        _assurance(p)["evidence"].update({
            "identity": "AMBIGUOUS",
            "release": "WITHHOLD",
            "blocking_reasons": ["identity=AMBIGUOUS"],
        })

    with pytest.raises(ValueError, match="permitted|withhold"):
        import_envelope(broken(rewrite))


def test_a_payload_whose_recorded_verdict_the_policy_does_not_reproduce_is_refused():
    """The strongest form, and only available because `evaluate` is a pure function of
    two things that both cross the wire.

    Here the six dimensions are untouched and permitting, and the identity confidence is
    untouched too, so the evidence-derivation check and the binding to the snapshot both
    pass. What moves is `identity.conflicts` -- which the POLICY consults and nothing else
    does. Re-running the named policy over the reconstructed basis is the only thing that
    can catch it, and it is only possible because the decision carries a typed basis
    rather than a dictionary nobody rebuilds.
    """
    payload = broken(lambda p: _assurance(p)["identity"].__setitem__(
        "conflicts", ["serial plate and fleet register disagree"]))
    with pytest.raises(ValueError, match="re-running|policy"):
        import_envelope(payload)


def test_a_payload_naming_a_policy_this_package_does_not_have_is_refused():
    """Fail closed on a verdict that cannot be reproduced.

    The recompute used to return quietly for an unknown policy, leaving only a coherence
    check that no test exercised -- so a payload could name any policy it liked and be
    accepted on the strength of an unguarded branch. "We cannot check this" must not read
    to a consumer as "this checks out".
    """
    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_id", "acme.custom-release-policy"))
    with pytest.raises(ValueError, match="does not have|cannot be reproduced"):
        import_envelope(payload)


def test_an_unverifiable_basis_is_readable_only_through_the_historical_api():
    """Non-triviality twin for both fail-closed refusals.

    A historical record decided under a policy we do not ship, or produced by a build we
    do not have, is not thereby fraudulent -- it is unverifiable, and a reader may still
    want to read it. What changed is where that decision is recorded: it used to be a
    boolean that returned an envelope indistinguishable from a verified one, and it is now
    a separate function returning the gap by name.
    """
    from cai.envelope import import_historical_envelope
    from cai.verification import VerificationDimension, VerificationState

    foreign_policy = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_id", "acme.custom-release-policy"))
    read = import_historical_envelope(foreign_policy)
    assert read.envelope.product.product_id == "ip-001"
    assert read.verification_report.state_of(
        VerificationDimension.POLICY_REPLAY
    ) is VerificationState.UNVERIFIABLE


def test_a_payload_altering_the_policy_digest_is_refused():
    """A decision naming the default policy must carry that policy's digest.

    Otherwise a payload can claim the rules everybody trusts while having been decided
    under rules nobody can see.
    """
    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_digest", "c" * 64))
    with pytest.raises(ValueError, match="polic"):
        import_envelope(payload)


def test_a_payload_whose_claim_does_not_match_its_recorded_inputs_is_refused():
    """Build-independent, so it holds for a record this process CANNOT replay.

    The claim below names a model artifact this build does not have, so the replay is
    unavailable -- correctly, since comparing two different models and blaming the record
    for the difference would be nonsense. The fingerprint is a pure function of the
    recorded metric, values, horizon and bound observations, so it can still be re-derived
    without the model. That is the whole point of checking it separately, and a test that
    let the replay do the catching would not have shown it.
    """
    foreign = "e" * 64

    def rewrite(p):
        claim = p["product"]["candidate"]["prediction_claim"]
        claim["model_artifact_digest"] = foreign
        claim["declared_envelope"]["model_artifact_digest"] = foreign
        # The substituted inputs are INTERNALLY consistent: the last value and the bound
        # input that cites it move together, so `PredictionInputs` own bound-versus-values
        # check passes. That is the attack -- a record that agrees with itself and does
        # not agree with the fingerprint the claim carries.
        inputs = p["product"]["evidence"]["prediction_inputs"]
        inputs["values"][-1] = "99.900000"
        inputs["bound_inputs"][-1]["value_used"] = "99.900000"

    with pytest.raises(ValueError, match="does not bind to its evidence"):
        import_envelope(broken(rewrite))


def _foreign_build(p):
    """A claim naming a model artifact this build does not have. Self-consistent: the
    declared envelope moves with it, so the claim's own invariants still pass."""
    foreign = "e" * 64
    claim = p["product"]["candidate"]["prediction_claim"]
    claim["model_artifact_digest"] = foreign
    claim["declared_envelope"]["model_artifact_digest"] = foreign


def test_a_claim_that_cannot_be_replayed_here_is_refused_by_default():
    """The forger used to choose whether the strongest check ran.

    `model_artifact_digest` is supplied BY THE RECORD and cross-checked only against the
    claim's own declared envelope, so setting a digest naming no build we have cost
    nothing and skipped the only check binding score, score_semantics and
    evidence_strength. Both independent audits reached DELIVERED this way, carrying a
    fabricated 0.99 and "calibrated probability of real-world failure".

    A record from another build genuinely cannot be replayed here. Treating that as
    verified was the defect; refusing unless a reader accepts it knowingly is the fix.
    """
    with pytest.raises(ValueError, match="not the build running here"):
        import_envelope(broken(_foreign_build))


def test_a_claim_that_cannot_be_replayed_here_is_readable_as_history():
    """Non-triviality twin: the boundary is stated, not a wall.

    And the gap does not vanish on the way through. The old flag returned an ordinary
    envelope, so a caller three layers down from the decision held an object that looked
    exactly like a verified one. The report is the difference.
    """
    from cai.envelope import import_historical_envelope
    from cai.verification import VerificationDimension, VerificationState

    read = import_historical_envelope(broken(_foreign_build))
    assert read.envelope.product.product_id == "ip-001"
    assert read.verification_report.state_of(
        VerificationDimension.CLAIM_REPLAY
    ) is VerificationState.UNVERIFIABLE
    # ...and the dimensions that COULD be checked were, rather than being swept up with it.
    assert read.verification_report.state_of(
        VerificationDimension.POLICY_REPLAY
    ) is VerificationState.VERIFIED
    assert read.verification_report.state_of(
        VerificationDimension.ENTITLEMENT_SCOPE
    ) is VerificationState.VERIFIED


def test_the_historical_api_does_not_excuse_a_claim_this_build_CAN_check():
    """The historical path must not be a general amnesty.

    A replayable claim is replayed in both modes. A check that RUNS and FAILS refuses; a
    check that cannot be run is reported. Collapsing those two is the whole defect the
    single boolean had.
    """
    from cai.envelope import import_historical_envelope

    payload = broken(lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
        "score", "0.990000"))
    with pytest.raises(ValueError, match="replays differently"):
        import_historical_envelope(payload)


def test_a_payload_whose_claim_replays_to_a_different_score_is_refused():
    """The import boundary runs the same replay live release runs, when it can.

    Everything here is internally consistent: the fingerprint still matches the recorded
    inputs, the envelope agrees with the claim, the build is ours. Only re-running the
    predictor shows that the number being sold is not the number this evidence produces.
    """
    payload = broken(lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
        "score", "0.990000"))
    with pytest.raises(ValueError, match="replays differently"):
        import_envelope(payload)


def test_the_untouched_assurance_basis_still_imports():
    """Non-triviality twin for every refusal in this section.

    Without it they would all pass against an importer that refuses every payload, which
    is the failure mode a refusal-only suite structurally cannot see.
    """
    rebuilt = import_envelope(wire()).product
    assert rebuilt.assurance.permitted
    assert rebuilt.assurance.assessed.evidence_assessment.release_decision().value == (
        "RELEASE"
    )


# ---------------------------------------------------------------------------
# DERIVED DUPLICATES ON THE WIRE. Four values are exported and then ignored on
# import. Not reading them back is right -- a derived value that can be supplied is
# a second authority. Silently accepting a contradictory one and normalising it is
# the other half of the mistake: the bundle then imports as something other than the
# bytes it arrived as, and nobody is told.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,mutate,pattern", [
    ("action rendered text",
     lambda p: p["product"]["candidate"]["action"].__setitem__(
         "rendered_text", "replace the pack immediately (safety)"), "rendered"),
    ("consequence description",
     lambda p: p["product"]["candidate"]["business_consequence"].__setitem__(
         "description", "at risk: nothing much"), "description"),
    ("consequence actionable flag",
     lambda p: p["product"]["candidate"]["business_consequence"].__setitem__(
         "actionable", False), "actionable"),
    ("product release policy version",
     lambda p: p["product"].__setitem__(
         "release_policy_version", "release-policy@0.0.1"), "release_policy_version"),
    ("product abstention reason",
     lambda p: p["product"].__setitem__(
         "abstention_reason", "withheld for rights"), "abstention_reason"),
    ("evidence assessment release verdict",
     lambda p: _assurance(p)["evidence"].__setitem__("release", "WITHHOLD"), "release"),
])
def test_a_derived_value_contradicting_its_source_is_refused_not_normalised(
    name, mutate, pattern
):
    """Each of these is a sentence or a verdict a reader would act on.

    `rendered_text` is the one that matters most: it is what a human was shown. Quietly
    re-deriving it on import means a bundle can arrive saying the operator was told to
    replace a pack immediately, import cleanly, and re-export saying they were told to
    inspect it -- with the digest recomputed over the version nobody saw.
    """
    with pytest.raises(ValueError, match=pattern):
        import_envelope(broken(mutate))


def test_the_untouched_derived_values_still_import():
    """Non-triviality twin: re-derivation must agree with an honest record."""
    rebuilt = import_envelope(wire()).product
    assert rebuilt.candidate.action.rendered_text()
    assert rebuilt.as_record()["release_policy_version"] == rebuilt.assurance.policy_version


def test_the_rendered_delivery_records_when_it_was_rendered():
    """P1-5. `rendered_at` was required by the governing ruling and absent.

    Without it the artifact proves WHAT was shown and not WHEN, so a re-render days later
    -- against a claim that has since expired or been retracted -- is indistinguishable in
    the record from the one the recipient actually saw at delivery.
    """
    product = T.deliver()
    assert product.rendered_delivery.rendered_at == product.delivery_time
    rebuilt = import_envelope(wire()).product
    assert rebuilt.rendered_delivery.rendered_at == product.delivery_time


def test_a_rendering_timestamped_away_from_its_delivery_is_refused():
    """Bound coherently to `delivery_time`, per the ruling, rather than merely present.

    The substituted artifact is INTERNALLY VALID -- its digest is recomputed over the new
    timestamp, so the self-verification passes. Only the product-level binding can catch
    it, which is what makes this a test of that binding rather than of the digest.
    """
    from cai.delivery import RenderedDelivery, _digest_of

    original = T.deliver().rendered_delivery
    later = T.t(20, 7)
    content = {
        "renderer_version": original.renderer_version,
        "locale": original.locale,
        "rendered_text": original.rendered_text,
        "card": dict(original.card),
    }
    valid_but_later = RenderedDelivery(
        **content,
        content_digest=_digest_of(**content, rendered_at=later),
        rendered_at=later,
    )
    assert valid_but_later.content_digest == valid_but_later.recomputed_digest(), (
        "the substituted artifact must verify against itself, or this tests the digest "
        "rather than the binding to delivery_time"
    )
    payload = broken(lambda p: p["product"].__setitem__(
        "rendered_delivery", valid_but_later.as_record()))
    with pytest.raises(ValueError, match="rendered"):
        import_envelope(payload)


def test_the_float_precision_boundary_is_six_decimals_and_stated():
    """A stated limit, not a discovered one.

    The canonicalizer refuses non-integer floats rather than risk two implementations
    formatting 0.4942 differently and producing two valid-looking digests for one record,
    so floats cross as strings at six decimal places. Values carrying more precision than
    that do not survive exactly, and the current claims happen to sit inside the boundary.
    Asserting it here means a future predictor emitting finer scores fails this test
    rather than silently shipping a lossy round trip.
    """
    from cai.contract import PredictionClaim

    original = T.deliver().candidate.prediction_claim
    rebuilt = import_envelope(wire()).product.candidate.prediction_claim

    assert f"{original.score:.6f}" == f"{rebuilt.score:.6f}"
    assert original.score == rebuilt.score, (
        "this claim's score sits inside the six-decimal wire precision; a predictor "
        "emitting finer values would need the wire format widened, not this test relaxed"
    )
    assert PredictionClaim.from_record(
        {**original.as_record(), "score": "0.1234567"}
    ).score == pytest.approx(0.1234567)


def test_an_abstained_product_survives_the_wire_intact():
    """The withheld case round-trips too. Only ever testing the happy path is how an
    abstention's reasons quietly stopped being exported."""
    withheld = IntelligenceEnvelope(product=T.deliver(recipient="nobody@elsewhere"))
    text = withheld.canonical_json()
    assert import_envelope(json.loads(text)).canonical_json() == text


# ---------------------------------------------------------------------------
# ADVERSARIAL WIRE. Structurally valid JSON, one material invariant violated.
# Each of these passed the old validator.
# ---------------------------------------------------------------------------


def _ctx(p):
    return p["product"]["candidate"]["context"]


def _assurance(p):
    return p["product"]["assurance"]["assurance_context"]


def _exposure(p):
    return p["product"]["candidate"]["business_consequence"]


# Each case carries the message fragment the invariant it names actually emits.
#
# It used to carry none, and every case was asserted with
# `pytest.raises((ValueError, TypeError, KeyError))`. That tuple cannot tell a domain
# refusal from a crash: with the delivery-time guard deleted, "delivered with no delivery
# time" still passed on an incidental `TypeError: '>' not supported between datetime and
# NoneType` several lines later. Two more cases were refused by an invariant OTHER than
# the one they were named for, so the checks they claimed to guard were deletable with the
# suite green. A fragment only the intended check emits is what makes each case evidence.
ADVERSARIAL = {
    "knowledge postdates the decision": (
        lambda p: _ctx(p).__setitem__("knowledge_cutoff", "2026-06-20T07:00:00+00:00"),
        "had not arrived",
    ),
    "prediction window is inverted": (
        lambda p: _ctx(p).__setitem__(
            "prediction_window_end", "2026-06-01T07:00:00+00:00"),
        "negative prediction window",
    ),
    # BOTH ends move. Moving only the start produced an INVERTED interval, which the
    # negative-window check above refuses first -- so this case never reached the overlap
    # check and that check was deletable with the suite green. The in-memory twin had the
    # identical defect, was fixed, and its wire counterpart was left carrying it.
    "consequence does not overlap the prediction window": (
        lambda p: _exposure(p).update({
            "exposure_window_start": "2026-09-01T05:00:00+00:00",
            "exposure_window_end": "2026-09-01T11:00:00+00:00",
        }),
        "threaten",
    ),
    # Carries a blocking reason deliberately. Flipping `permitted` alone trips the
    # refusal-needs-a-reason invariant first, so the payload never reaches the check it
    # is meant to exercise -- which a surviving mutant is how we found out.
    "delivered on a refusing assurance": (
        lambda p: p["product"]["assurance"].update(
            {"permitted": False, "blocking_reasons": ["entitlement=UNAUTHORIZED"]}),
        "DELIVERED contradicts",
    ),
    "expires at or before delivery": (
        lambda p: p["product"].__setitem__(
            "valid_until", "2026-06-12T07:00:00+00:00"),
        "never actionable",
    ),
    "rendered digest does not verify": (
        lambda p: p["product"]["rendered_delivery"].__setitem__(
            "rendered_text", "WHAT IS AT RISK?  something else entirely"),
        "does not match the rendered content",
    ),
    "evidence postdates delivery": (
        lambda p: p["product"]["evidence"].__setitem__(
            "captured_at", "2026-06-30T07:00:00+00:00"),
        "postdates delivery",
    ),
    # "refusal carries no reason" LIVED HERE and has moved to STRUCTURAL. The schema now
    # expresses the decision/reasons coherence in both directions, so this dict -- whose
    # entire premise is "the structural validator passes every one of these" -- was the
    # wrong home for it. Its typed half is asserted by name below, against the constructor
    # rather than the wire, so both authorities are still exercised independently.
    # P0-2 at the wire. The behaviour was present and no declared test reached it.
    "claim horizon disagrees with the prediction window": (
        lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
            "horizon_seconds", 86400),
        "two temporal authorities",
    ),
    "prediction window has zero length": (
        lambda p: _ctx(p).__setitem__(
            "prediction_window_end", _ctx(p)["prediction_window_start"]),
        "zero-length duration",
    ),
    # `rendered_text` moves with `due_by`, because it is DERIVED from it and the importer
    # re-derives and compares. An internally inconsistent forgery would be caught by that
    # check instead, and this case would stop testing the window coherence it names.
    "action window does not touch the exposure": (
        lambda p: p["product"]["candidate"]["action"].update({
            "operational_window_start": "2026-09-01T05:00:00+00:00",
            "operational_window_end": "2026-09-01T11:00:00+00:00",
            "due_by": "2026-09-01T03:00:00+00:00",
            "rendered_text": "inspect battery-pack-1 by 03:00 UTC on 01 Sep (maintenance)",
        }),
        "protect",
    ),
}


# The cases the PUBLISHED SCHEMA refuses, now that the importer actually runs it.
#
# All three used to live in ADVERSARIAL above and were caught by a domain invariant
# further down. They are structurally malformed -- a DELIVERED product with no delivery
# time or no rendered artifact contradicts the schema's own `if`/`then`, and a timestamp
# with no offset is not an RFC 3339 date-time -- so the honest place to catch them is the
# structural validator, and the honest thing to assert is that it did.
#
# Their domain twins have not been deleted. Each invariant still fires on an object built
# in memory, where no schema is involved: see `test_formation`'s delivery-time,
# rendered-artifact and timezone tests. Two boundaries, two tests, one rule.
STRUCTURAL = {
    "timestamp is not timezone-aware": (
        lambda p: _ctx(p).__setitem__("model_decision_time", "2026-06-12T07:00:00"),
        "model_decision_time",
    ),
    "delivered with no delivery time": (
        lambda p: p["product"].__setitem__("delivery_time", None),
        "delivery_time",
    ),
    "delivered with no rendered artifact": (
        lambda p: p["product"].__setitem__("rendered_delivery", None),
        "rendered_delivery",
    ),
    "an unspecified property is smuggled in": (
        lambda p: p["product"].__setitem__("shadow_score", "0.990000"),
        "shadow_score",
    ),
    "a required key is deleted": (
        lambda p: p["product"].pop("release_policy_version"),
        "release_policy_version",
    ),
    "the evidence digest is not a digest": (
        lambda p: p["product"]["evidence"].__setitem__(
            "evidence_content_digest", "not-a-digest"),
        "evidence_content_digest",
    ),
    "the schema uri points somewhere else": (
        lambda p: p.__setitem__("schema_uri", "https://example.invalid/other.json"),
        "schema_uri",
    ),
    "a commitment consequence carries a downtime detail": (
        lambda p: _exposure(p).__setitem__(
            "detail",
            {"asset_id": "asset-4417", "expected_hours_lost": "6.00",
             "affected_operation": "loading"},
        ),
        "detail",
    ),
    # ---- ADDED BY THE SCHEMA/DOMAIN RECONCILIATION PASS.
    #
    # Each of these is a constructor-level invariant the typed domain has enforced all
    # along and the published schema did not express -- so a reader implementing against
    # the schema in another language would have built a validator that accepts records
    # this system refuses. Every one is a conditional over sibling keys or a nullability,
    # which is what JSON Schema can say; none needed a new vocabulary.
    "a refusal carries no reason": (
        lambda p: p["product"]["assurance"].update(
            {"permitted": False, "blocking_reasons": []}),
        "blocking_reasons",
    ),
    "a permission carries a blocking reason": (
        lambda p: p["product"]["assurance"].update(
            {"permitted": True, "blocking_reasons": ["entitlement=UNAUTHORIZED"]}),
        "blocking_reasons",
    ),
    "evidence carries no capture time": (
        lambda p: p["product"]["evidence"].__setitem__("captured_at", None),
        "captured_at",
    ),
    "a delivered product carries no validity horizon": (
        lambda p: p["product"].__setitem__("valid_until", None),
        "valid_until",
    ),
    "completeness is MISSING and names nothing": (
        lambda p: _assessment(p).update(
            {"completeness": "MISSING", "missing_evidence": []}),
        "missing_evidence",
    ),
    "completeness is COMPLETE and names something missing": (
        lambda p: _assessment(p).update(
            {"completeness": "COMPLETE", "missing_evidence": ["prediction_inputs"]}),
        "missing_evidence",
    ),
    "support is CONFLICTED and names no conflict": (
        lambda p: _assessment(p).update({"support": "CONFLICTED", "conflicts": []}),
        "conflicts",
    ),
    "the trail does not open at DELIVERED": (
        lambda p: p.__setitem__("lifecycle_events", [
            {"state": "ACKNOWLEDGED", "at": "2026-06-12T07:00:00+00:00",
             "actor": "operator", "note": ""}]),
        "lifecycle_events",
    ),
}


def _assessment(p: dict) -> dict:
    return p["product"]["assurance"]["assurance_context"]["evidence"]


# The three collections an abstention may not carry. Parametrized separately because they
# need an ABSTAINED payload rather than the delivered one `broken()` starts from.
WITHHELD_STRUCTURAL = {
    "an abstention carries a delivery trail": (
        "lifecycle_events",
        [{"state": "DELIVERED", "at": "2026-06-12T08:00:00+00:00",
          "actor": "gateway", "note": ""}],
    ),
    "an abstention carries a retraction": (
        "status_events",
        [{"event_type": "RETRACTED", "at": "2026-06-12T09:00:00+00:00",
          "actor": "analyst", "reason": "pack replaced",
          "replacement_product_id": None}],
    ),
    "an abstention carries a supersession": (
        "status_events",
        [{"event_type": "SUPERSEDED", "at": "2026-06-12T09:00:00+00:00",
          "actor": "analyst", "reason": "", "replacement_product_id": "ip-002"}],
    ),
}


@pytest.mark.parametrize("name", sorted(STRUCTURAL))
def test_a_structurally_malformed_payload_is_refused_by_the_published_schema(name):
    """The schema is the structural validator, and it is now RUN.

    The project published a Draft 2020-12 schema and called it normative while the
    importer validated nothing against it -- two descriptions of the accepted universe
    with nothing keeping them in agreement. The `match` names the path that violated, so
    each case is evidence about the rule it is named for rather than about validation in
    general.
    """
    from cai.envelope import SchemaViolation

    mutate, path_fragment = STRUCTURAL[name]
    with pytest.raises(SchemaViolation, match=path_fragment):
        import_envelope(broken(mutate))


@pytest.mark.parametrize("name", sorted(WITHHELD_STRUCTURAL))
def test_a_withheld_product_carrying_a_delivery_history_is_refused_by_the_schema(name):
    """An abstention is a record that a candidate was withheld. Nothing followed it.

    The three collections are all histories of a delivery, and the schema described them
    as freely populated whatever the determination said -- so a conforming implementation
    could publish a withheld candidate with a full disposition trail, an outcome and a
    retraction.
    """
    from cai.envelope import SchemaViolation

    key, value = WITHHELD_STRUCTURAL[name]
    payload = json.loads(IntelligenceEnvelope(
        product=T.deliver(recipient="procurement@other-customer", purpose="benchmarking")
    ).canonical_json())
    assert payload["product"]["determination"] == "ABSTAINED"
    payload[key] = value

    with pytest.raises(SchemaViolation, match=key):
        import_envelope(payload)


def test_a_decision_and_its_reasons_are_refused_in_memory_too():
    """THE TYPED HALF, asserted against the constructor rather than the wire.

    "refusal carries no reason" used to sit in ADVERSARIAL, whose premise is that the
    schema passes every case in it. The schema now expresses this one, so leaving it there
    would have made that dict's docstring false -- and moving it to STRUCTURAL alone would
    have left the typed rule asserted by nothing at all.

    Both authorities, separately. This is the shape the reconciliation is FOR: a rule the
    schema can express should be expressed there AND enforced by reconstruction, and
    neither one standing in for the other.
    """
    from cai.candidate import AssessedAssurance
    from cai.delivery import AssuranceDecision

    honest = T.deliver().assurance
    basis = AssessedAssurance(
        context=honest.assessed.context,
        evidence_assessment=honest.assessed.evidence_assessment,
    )
    common = dict(
        assessed=basis, policy_id=honest.policy_id,
        policy_version=honest.policy_version, policy_digest=honest.policy_digest,
        release_decision_time=honest.release_decision_time,
    )

    with pytest.raises(ValueError, match="no stated reason"):
        AssuranceDecision(permitted=False, blocking_reasons=(), **common)
    with pytest.raises(ValueError, match="cannot carry blocking reasons"):
        AssuranceDecision(
            permitted=True, blocking_reasons=("entitlement=UNAUTHORIZED",), **common
        )


def test_every_honest_payload_this_package_produces_satisfies_its_own_schema():
    """The other direction, and the one a conformance claim actually rests on.

    A schema that refuses malformed payloads and also refuses honest ones is a schema
    nobody can implement against. Both determinations, and the learned envelope, which is
    the only shape carrying lifecycle events, an outcome and a status event.
    """
    from cai.envelope import validate_against_schema

    validate_against_schema(wire())
    validate_against_schema(learned())
    abstained = json.loads(IntelligenceEnvelope(
        product=T.deliver(recipient="procurement@other-customer", purpose="benchmarking")
    ).canonical_json())
    assert abstained["product"]["determination"] == "ABSTAINED"
    validate_against_schema(abstained)


def test_the_date_time_format_is_checked_and_not_merely_declared():
    """The polarity test for the format checker.

    Without `FormatChecker`, `"format": "date-time"` is annotation only: jsonschema
    accepts any string and reports conformance. A schema that declares a constraint it
    does not apply is worse than one that declares nothing, because it is believed.
    """
    from cai.envelope import SchemaViolation, validate_against_schema

    payload = wire()
    payload["product"]["delivery_time"] = "yesterday afternoon"
    with pytest.raises(SchemaViolation, match="delivery_time"):
        validate_against_schema(payload)


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_a_schema_shaped_payload_violating_one_invariant_is_refused(name):
    """Each of these is valid JSON of the right shape, and now valid against the published
    schema too -- which is exactly what makes them interesting.

    These are the cross-field semantics JSON Schema cannot express: a knowledge cutoff
    later than its decision time, a consequence that does not overlap the window it
    claims to threaten, an expiry at or before delivery. The structural validator passes
    every one of them; the typed domain refuses every one of them.

    The `match` is the load-bearing part: it is what separates "the payload was refused"
    from "the payload was refused BY THE CHECK THIS CASE IS NAMED FOR".
    """
    mutate, expected = ADVERSARIAL[name]
    with pytest.raises((ValueError, TypeError, KeyError), match=expected):
        import_envelope(broken(mutate))


def test_a_delivered_payload_carrying_a_refusing_assurance_is_refused():
    """Named rather than parametrized, so a mutant can be attributed to it.

    The harness matches failing test names up to the first whitespace, so a parametrized
    id containing spaces cannot carry an attribution -- it fails closed and reports the
    mutant as surviving, which is the right direction to fail but leaves the invariant
    unguarded on paper. This is the single most important refusal in the product: a
    delivered claim whose assurance refused release is the system contradicting itself.
    """
    payload = broken(lambda p: p["product"]["assurance"].update(
        {"permitted": False, "blocking_reasons": ["entitlement=UNAUTHORIZED"]}))
    with pytest.raises(ValueError, match="DELIVERED"):
        import_envelope(payload)


def test_an_unknown_schema_version_is_refused():
    with pytest.raises(UnsupportedSchemaVersion):
        import_envelope(broken(lambda p: p.__setitem__("schema_version", "who-knows/9")))


def test_an_unknown_canonicalization_is_refused():
    """Canonical bytes are only reproducible against a named algorithm. An importer that
    accepts an unfamiliar one has agreed to a digest it cannot recompute."""
    with pytest.raises(ValueError, match="canonicali"):
        import_envelope(broken(lambda p: p.__setitem__("canonicalization", "whatever/1")))


def test_a_payload_claiming_the_intervention_worked_is_refused():
    with pytest.raises(UnsupportedAttributedEffect):
        import_envelope(broken(lambda p: p.__setitem__("attributed_effect", "PREVENTED")))


# ---------------------------------------------------------------------------
# THE PUBLISHED SCHEMA. It is the normative contract, so it has to be the one
# the code actually generates, and real payloads have to satisfy it.
# ---------------------------------------------------------------------------


def test_the_committed_schema_matches_the_one_the_code_generates():
    """A published contract that has drifted from the code is worse than none.

    A reader implementing against the file would conform to a spec this system no longer
    honours, and every conformance claim either side makes would be false.
    """
    import pathlib

    from cai.envelope import json_schema

    on_disk = json.loads(pathlib.Path("schema/envelope-1.json").read_text())
    assert on_disk == json_schema(), (
        "schema/envelope-1.json is stale -- regenerate with cai.envelope.write_schema()"
    )


# `if` / `then` / `else` / `not` are applicators: they refine a SUBSET of an object
# already defined elsewhere, so they neither can nor should close `additionalProperties`
# -- doing so would reject every property the conditional does not happen to mention.
# Auditing them as structure definitions is a false positive, and a false positive here
# is worse than a gap: it is the pressure that gets an audit relaxed until it finds
# nothing.
_APPLICATORS = ("if", "then", "else", "not")


def _object_nodes(schema):
    """Every object node that DEFINES a structure, with the path a reader would follow."""
    found = []

    def walk(node, path="", under_applicator=False):
        if isinstance(node, dict):
            if (node.get("type") == "object" or "properties" in node) and not under_applicator:
                found.append((path or "(root)", node))
            for k, v in node.items():
                if k == "x-semantic-validations":
                    continue
                conditional = under_applicator or k in _APPLICATORS
                if k == "properties":
                    for name, sub in v.items():
                        walk(sub, f"{path}.{name}", conditional)
                else:
                    walk(v, f"{path}.{k}", conditional)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", under_applicator)

    walk(schema)
    return found


def test_no_load_bearing_structure_is_left_unconstrained():
    """`candidate` and `assurance` were bare `{"type": "object"}`.

    The two structures carrying the entire claim were the two the published contract
    declined to describe, so a conforming implementation could put anything in either.

    STRONGER THAN THE VERSION THIS REPLACES. The old check only detected a BARE
    `{"type": "object"}`. It could not see an object with two properties listed and eight
    required fields missing, or one left open to unspecified extra properties -- and both
    of those were in the schema it was passing. A test that detects the one shape somebody
    already fixed is a regression guard, not an audit.
    """
    from cai.envelope import json_schema

    bare, open_objects, unrequired, phantom = [], [], [], []
    for path, node in _object_nodes(json_schema()):
        if node.get("type") == "object" and not (
            {"properties", "additionalProperties", "oneOf"} & set(node)
        ):
            bare.append(path)
            continue
        if "properties" not in node:
            continue
        if "additionalProperties" not in node:
            open_objects.append(path)
        if "required" not in node:
            unrequired.append(path)
        missing = set(node.get("required", ())) - set(node["properties"])
        if missing:
            phantom.append(f"{path}: requires {sorted(missing)} it does not define")

    assert not bare, f"unconstrained structures: {bare}"
    assert not open_objects, (
        f"objects open to unspecified extra properties: {open_objects}; openness has to "
        f"be a decision, written down, not an omission"
    )
    assert not unrequired, (
        f"objects specifying no required properties: {unrequired}; a conforming "
        f"implementation could omit every one of them"
    )
    assert not phantom, f"required names no property defines: {phantom}"


def test_the_schema_requires_every_field_a_real_payload_carries():
    """Derived from a live payload, not from a list somebody maintains.

    The version this replaces hardcoded nine names at one level of the tree. It passed
    while **170 of 179** `required` entries elsewhere in the schema could be deleted with
    the whole suite green -- so the audit that was written to stop "detects only the shape
    somebody already fixed" was itself exactly that.

    A field a real delivered envelope carries is a field a conforming implementation must
    produce. Walking the actual payload against the actual schema makes the required sets
    self-maintaining: add a field to the wire form and this fails until the schema says
    it is required.
    """
    from cai.envelope import json_schema

    schema = json_schema()
    missing: list[str] = []

    def walk(node, payload, path=""):
        if not isinstance(node, dict) or not isinstance(payload, dict):
            return
        for variant in node.get("oneOf", ()):
            if variant.get("type") == "object" and "properties" in variant:
                walk(variant, payload, path)
        props = node.get("properties")
        if not props:
            return
        required = set(node.get("required", ()))
        for name, value in payload.items():
            if name in props and name not in required:
                missing.append(f"{path}.{name}")
            if name in props:
                walk(props[name], value, f"{path}.{name}")
                if isinstance(value, list) and value:
                    items = props[name].get("items")
                    if items:
                        walk(items, value[0], f"{path}.{name}[]")

    delivered = wire()
    walk(schema, delivered)
    abstained = json.loads(
        IntelligenceEnvelope(product=T.deliver(recipient="nobody@elsewhere"))
        .canonical_json()
    )
    walk(schema, abstained)

    # `schema_uri` is the one deliberate exemption: it is a convenience pointer, and a
    # conforming implementation that omits it is still conforming.
    missing = [m for m in missing if not m.endswith(".schema_uri")]
    assert not missing, (
        f"{len(missing)} field(s) a real payload carries are optional in the published "
        f"contract: {sorted(missing)}"
    )


def test_the_schema_expresses_the_delivered_and_abstained_conditionals():
    """DELIVERED requires a delivery time and a rendered artifact; ABSTAINED requires a
    blocking reason. Both are expressible in JSON Schema, so both are expressed rather
    than deferred to the prose list of what the schema cannot say."""
    jsonschema = pytest.importorskip("jsonschema")
    from cai.envelope import json_schema

    schema = json_schema()
    missing_delivery = wire()
    missing_delivery["product"]["delivery_time"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=missing_delivery, schema=schema)

    no_reason = json.loads(
        IntelligenceEnvelope(product=T.deliver(recipient="nobody@elsewhere"))
        .canonical_json()
    )
    no_reason["product"]["assurance"]["blocking_reasons"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=no_reason, schema=schema)


def test_the_schema_rejects_an_unspecified_extra_property():
    """Closed where openness was not a deliberate choice. An implementation smuggling an
    extra semantic field into the claim is not conforming, and the file has to say so."""
    jsonschema = pytest.importorskip("jsonschema")
    from cai.envelope import json_schema

    payload = wire()
    payload["product"]["candidate"]["prediction_claim"]["adjusted_score"] = "0.990000"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=json_schema())


def test_the_schema_names_what_it_cannot_express():
    """The honest half of a published contract.

    JSON Schema cannot say "knowledge_cutoff <= model_decision_time". Leaving that unsaid
    invites an implementer to validate structurally, stop, and believe they conform.
    """
    from cai.envelope import json_schema

    rules = json_schema()["x-semantic-validations"]["rules"]
    assert any("knowledge_cutoff" in r for r in rules)
    assert any("DELIVERED" in r for r in rules)
    assert any("content_digest" in r for r in rules)


def test_a_real_delivered_payload_validates_against_the_published_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from cai.envelope import json_schema

    jsonschema.validate(instance=wire(), schema=json_schema())


def test_a_real_abstained_payload_validates_against_the_published_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from cai.envelope import json_schema

    payload = json.loads(
        IntelligenceEnvelope(product=T.deliver(recipient="nobody@elsewhere")).canonical_json()
    )
    jsonschema.validate(instance=payload, schema=json_schema())


def test_the_schema_rejects_a_payload_the_old_one_accepted():
    """Non-triviality for the schema itself.

    A schema that validates everything is decorative. This one now has enough structure
    to catch a malformed claim on shape alone, before the importer's semantics run.
    """
    jsonschema = pytest.importorskip("jsonschema")
    from cai.envelope import json_schema

    payload = wire()
    payload["product"]["candidate"]["prediction_claim"]["score"] = "not-a-number"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=json_schema())


def test_the_non_triviality_twin_still_imports():
    """Without this, every refusal above would pass against an importer that refuses
    everything -- the failure mode a refusal-only suite structurally cannot see."""
    assert import_envelope(wire()).product.product_id == "ip-001"


# ---------------------------------------------------------------------------
# WAVE 2. Each of these is a forgery an independent auditor actually built and
# imported cleanly against the previous revision. They are recorded here as the
# payloads they were, not as paraphrases.
# ---------------------------------------------------------------------------


def test_a_payload_whose_assessment_contradicts_its_own_evidence_is_refused():
    """`completeness` is derivable from the evidence in the same bundle, and was not derived.

    Re-running the policy over the recorded assessment proves the verdict follows from the
    assessment. It proves nothing about whether the assessment follows from the evidence
    sitting beside it -- so a payload could carry a snapshot with no observation ids at all
    next to a recorded `completeness=COMPLETE`, and the importer would agree with the
    record about itself while the record's own `is_complete()` said otherwise.

    WAVE 4 NOTE. This used to strip `observation_ids`, which is now refused earlier and
    on stronger grounds: a snapshot whose cited ids disagree with the inputs the claim was
    computed from is incoherent before any assessment is consulted. The invariant here is
    a different one -- does the recorded assessment follow from the evidence beside it --
    so it is exercised through another element `missing_elements()` counts, and the
    observation-id case has its own test on the release path.
    """
    payload = broken(lambda p: p["product"]["evidence"].__setitem__(
        "semantic_rule_version", None))
    with pytest.raises(ValueError, match="but the evidence it carries produces"):
        import_envelope(payload)


def test_a_payload_whose_identity_confidence_contradicts_its_assertion_is_refused():
    """The root cause of the assessment gap: the number was stored twice.

    `EvidenceSnapshot.identity_confidence` is a bare float; `IdentityAssertion.confidence`
    has a resolver, a version and evidence refs behind it. Nothing bound them, so the
    assessment was projected from one copy and the policy consulted the other.
    """
    payload = broken(lambda p: p["product"]["evidence"].__setitem__(
        "identity_confidence", "0.020000"))
    with pytest.raises(ValueError, match="two numbers for one question"):
        import_envelope(payload)


def test_a_payload_whose_delivered_card_was_rewritten_is_refused():
    """The one derived artifact never compared on import was the one a human read.

    Every other derived string is re-derived and checked. This one only had to match its
    own digest -- so restamping the digest over "94% probability of failure within 72h"
    imported cleanly while the typed claim beside it still said "relative degradation
    signal, ordering only".
    """
    from cai.delivery import _digest_of

    def rewrite(p):
        rd = p["product"]["rendered_delivery"]
        lie = "94% probability of failure within 72h"
        honest = (
            "relative degradation signal, ordering only -- not a calibrated "
            "probability of real-world failure"
        )
        text = rd["rendered_text"].replace(honest, lie)
        card = {**rd["card"], "why": rd["card"]["why"].replace(honest, lie)}
        rd["rendered_text"], rd["card"] = text, card
        rd["content_digest"] = _digest_of(
            renderer_version=rd["renderer_version"], locale=rd["locale"],
            rendered_text=text, card=card,
            rendered_at=datetime.fromisoformat(rd["rendered_at"]),
        )

    with pytest.raises(ValueError, match="not what this candidate renders"):
        import_envelope(broken(rewrite))


def test_a_payload_that_does_not_reconstruct_as_itself_is_refused():
    """The blanket check, exercised on a case the published schema PERMITS.

    Deleting a required key and smuggling an unspecified property both used to land here.
    Both are now refused by the schema first, and both keep a case in STRUCTURAL above --
    so this test needed a payload the structural validator accepts and reconstruction
    still changes, or it would have been proving the schema works twice.

    An empty `supersedes` is exactly that. The schema allows `["string", "null"]`;
    `Observation.from_record` reads `r.get("supersedes") or None`, so `""` comes back as
    null and re-exports as null. Inert in itself, and still a difference between the
    record that arrived and the record that is understood -- which is the whole class this
    comparison exists to close, including the cases nobody thought to enumerate.
    """
    with pytest.raises(ValueError, match="does not survive reconstruction"):
        import_envelope(broken(
            lambda p: p["product"]["release_evidence"]["observations"][0].__setitem__(
                "supersedes", "")))


# ---------------------------------------------------------------------------
# WAVE 3. A fourth fresh-context auditor attacked the wave-2 result. Both P0s it
# found are recorded here as the payloads it actually built and imported.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,mutate,pattern", [
    ("unentitled recipient", lambda p: (
        p["product"]["assurance"].__setitem__("policy_id", "acme.forged"),
        p["product"].__setitem__("recipient", "procurement@other-customer")),
     "does not authorise the delivery"),
    ("another tenant", lambda p: (
        p["product"]["assurance"].__setitem__("policy_version", "forged@9.9"),
        p["product"].__setitem__("tenant", "tenant-77")),
     "does not authorise the delivery"),
    # Narrows the CLEARANCE rather than rewriting the snapshot's declared feeds. Now that
    # the readings travel, a snapshot claiming feeds its own readings did not come from is
    # refused by the integrity dimension first -- a different and better rule -- so the
    # old fixture would have passed while the rights check was deleted. Dropping a feed
    # from the licence leaves every other invariant intact and reaches this one.
    ("unlicensed source feed", lambda p: (
        p["product"]["assurance"].__setitem__("policy_id", "acme.forged"),
        p["product"]["assurance"]["assurance_context"]["entitlement"].__setitem__(
            "authorized_source_systems",
            [s for s in T.CONSUMED_SOURCES if s != "source-a"])),
     "does not authorise the delivery"),
    # ...and the REASON half of the same union, which the clearance also has to cover.
    ("unlicensed business-context feed", lambda p: (
        p["product"]["assurance"].__setitem__("policy_id", "acme.forged"),
        p["product"]["assurance"]["assurance_context"]["entitlement"].__setitem__(
            "authorized_source_systems",
            [s for s in T.CONSUMED_SOURCES if s != "dock-scheduler"])),
     "does not authorise the delivery"),
])
def test_the_historical_api_does_not_waive_the_rights_question(name, mutate, pattern):
    """The forger could not defeat the entitlement check, so they arranged for the branch
    that skipped it.

    The unknown-policy early return sat ABOVE the entitlement authorization, and both
    `policy_id` and `policy_version` are free wire fields — so the old waiver flag plus
    any string at all delivered to an unentitled recipient, under another tenant, on an
    unlicensed feed. The check needs no policy thresholds; it compares a clearance to the
    delivery recorded beside it, and both are on the wire in full.

    Rights are never waived, in either mode. `ENTITLEMENT_SCOPE` cannot be UNVERIFIABLE,
    because there is nothing a reader could be missing -- and this is the test that says
    so on a record whose policy genuinely cannot be reproduced.
    """
    from cai.envelope import import_historical_envelope

    with pytest.raises(ValueError, match=pattern):
        import_historical_envelope(broken(mutate))


def test_the_historical_api_still_admits_an_honest_unverifiable_record():
    """Non-triviality twin: the historical path must still do the job it exists for, and
    must report the entitlement it DID check as verified rather than as skipped."""
    from cai.envelope import import_historical_envelope
    from cai.verification import VerificationDimension, VerificationState

    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_id", "acme.custom-release-policy"))
    read = import_historical_envelope(payload)
    assert read.envelope.product.product_id == "ip-001"
    assert read.verification_report.state_of(
        VerificationDimension.ENTITLEMENT_SCOPE
    ) is VerificationState.VERIFIED


def test_a_relabelled_asset_is_refused_on_import():
    """`claim.subject` was a free variable, and this is the payload that proved it.

    Every check that consumed a subject read it FROM THE CLAIM — the entitlement scope,
    the identity assertion, the rendered card, even the replay's own comparison claim,
    which constructs itself with `subject=claim.subject`. So relabelling the asset
    consistently across all of them imported cleanly with DEFAULT flags: a delivered
    product about `asset-9999/battery-pack` computed entirely from `asset-4417`'s
    telemetry, while the derivation walk carried inside the same bundle named
    `asset-4417` at every step.
    """
    def relabel(p):
        p["product"]["candidate"]["prediction_claim"]["subject"] = "asset-9999/battery-pack"
        ctx = _assurance(p)
        ctx["identity"]["resolved_entity"] = "asset-9999/battery-pack"
        ctx["entitlement"]["subject"] = "asset-9999/battery-pack"

    with pytest.raises(ValueError, match="does not describe its own evidence"):
        import_envelope(broken(relabel))


def test_a_claim_about_a_part_of_the_observed_subject_still_imports():
    """Non-triviality twin, and the convention stated.

    The hero claim is about `asset-4417/battery-pack` while every reading is about
    `asset-4417`. A rule demanding string equality would refuse the only shape this
    package actually ships.
    """
    rebuilt = import_envelope(wire()).product
    assert rebuilt.candidate.prediction_claim.subject == "asset-4417/battery-pack"
    assert rebuilt.evidence.subject == "asset-4417"


# ---------------------------------------------------------------------------
# WAVE 4. Four auditors on the wave-3 result. The build->read direction they
# were hunting was closed; these are what the read side still admitted.
# WAVE4_AUDIT_FINDINGS.md records all thirty.
# ---------------------------------------------------------------------------


def test_a_payload_permitting_release_over_unresolved_identity_conflicts_is_refused():
    """D2. The escape hatch, again, on a different question.

    Wave 3 hoisted the entitlement re-check above the unknown-policy gate because it
    "needs no policy thresholds". `identity.conflicts` is the same shape -- a coherence
    fact carried in full on the wire, blocking under any policy -- and it was left
    downstream of a gate that `policy_id`, a free wire field, decides. So a record could
    name a policy this package does not ship and arrive saying, in one breath, that two
    systems disagree about which asset this is and that identity is RESOLVED.
    """
    payload = broken(lambda p: (
        p["product"]["assurance"]["assurance_context"]["identity"].__setitem__(
            "conflicts", ["fleet-register says asset-4417, telematics says asset-9001"]),
        p["product"]["assurance"].__setitem__("policy_id", "acme.house-rules"),
    ))
    from cai.envelope import import_historical_envelope

    with pytest.raises(ValueError, match="two systems disagree about"):
        import_historical_envelope(payload)


def test_the_historical_api_still_admits_a_record_whose_identity_nobody_disputes():
    """The twin. Reading an unverifiable record must remain possible for an honest
    historical one -- the refusal above is of a conflict, not of the mode."""
    from cai.envelope import import_historical_envelope

    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_id", "acme.house-rules"))
    assert import_historical_envelope(payload).envelope.product


def test_a_decision_taken_at_another_time_than_the_delivery_is_refused():
    """D4. Release always stamps `release_decision_time` equal to `delivery_time`; import accepted
    any value at all. It is what the policy re-evaluation is replayed against, so a free
    value there is a free hand over which rules were in force."""
    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "release_decision_time", "2099-01-01T00:00:00+00:00"))
    with pytest.raises(ValueError, match="authorised by a decision taken at another time"):
        import_envelope(payload)


def test_a_payload_whose_evidence_digest_is_not_a_digest_is_refused():
    """D3, at the boundary that used to take it. Release reported integrity=BROKEN for a
    value that could not be a SHA-256; import delivered. The check now lives on the type
    that owns the field, so both boundaries get it from the same place."""
    from cai.contract import EvidenceSnapshot

    # IN MEMORY, where no schema is involved. The wire half of this case moved into
    # STRUCTURAL above once the importer began running the published schema, which
    # rejects a non-hex digest by pattern before the domain sees it. Both boundaries keep
    # a test; neither rule is now proved only by the other.
    with pytest.raises(ValueError, match="cannot be a content digest"):
        EvidenceSnapshot(
            observation_ids=("a-0",), subject="asset-4417",
            model_version=None, semantic_rule_version=None, identity_confidence=None,
            evidence_content_digest="not-a-digest", captured_at=T.t(12, 7),
        )


# ===========================================================================
# THE SCHEMA MUST SAY EVERY STRUCTURAL THING IT CAN SAY.
#
# `schema/envelope-1.json == json_schema()` proves the file matches the generator.
# It proves nothing about whether either matches the typed domain, and two rules the
# domain enforces were simply absent: `PredictionInputs` refuses empty `bound_inputs`
# and `ModelEnvelope` refuses a duplicate applicability pair, while the schema
# accepted `[]` and accepted the duplicate.
#
# An implementer in another language builds against this file. Every rule left out of
# it is a bundle they will ship believing it conforms, and this system will refuse.
#
# Each case below is validated by the SCHEMA ALONE -- `validate_against_schema`, not
# `import_envelope` -- because reaching a refusal through typed reconstruction would
# prove the opposite of what is being asked.
# ===========================================================================


def _schema_refuses(mutate) -> str:
    from cai.envelope import SchemaViolation, validate_against_schema

    payload = wire()
    mutate(payload)
    try:
        validate_against_schema(payload)
    except SchemaViolation as exc:
        return str(exc)
    raise AssertionError("the schema accepted a payload the typed domain refuses")


def test_the_schema_itself_refuses_a_prediction_with_no_bound_inputs():
    """Values with no bound observations are an assertion about numbers nobody can
    trace back to a reading. `minItems: 1`, and it was missing."""
    detail = _schema_refuses(
        lambda p: p["product"]["evidence"]["prediction_inputs"].__setitem__(
            "bound_inputs", []
        )
    )
    assert "bound_inputs" in detail


def test_the_schema_itself_refuses_a_duplicate_applicability_pair():
    """Declaring the same metric/subject-type combination twice bounds nothing further.
    `uniqueItems`, and it was missing."""
    def duplicate(p):
        env = p["product"]["candidate"]["prediction_claim"]["declared_envelope"]
        env["supported_applicability"] = env["supported_applicability"] * 2

    assert "unique" in _schema_refuses(duplicate).lower()


def test_the_schema_itself_refuses_a_confidence_outside_the_unit_interval():
    """The confidences cross as six-decimal STRINGS, so `minimum`/`maximum` do not
    apply and the pattern has to carry the range. It carried only the shape, and
    `9.000000` validated against a schema for a number the domain refuses."""
    detail = _schema_refuses(
        lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
            "evidence_strength", "9.000000"
        )
    )
    assert "evidence_strength" in detail


def test_the_schema_itself_refuses_an_entitlement_scoped_to_a_blank_tenant():
    """`permits()` compares tenant with `!=`, so a blank on both sides satisfies a
    scope dimension by matching emptiness. The assertion refuses it; the schema did
    not, on the field that decides whose data this was."""
    def blank(p):
        ent = p["product"]["assurance"]["assurance_context"]["entitlement"]
        ent["tenant"] = ""

    assert "tenant" in _schema_refuses(blank)


def test_the_schema_itself_refuses_a_retraction_with_no_reason():
    """`StatusEvent` refuses it as unauditable. Conditional on the event type, which
    JSON Schema expresses with if/then -- the same form the determination already uses,
    so this was an omission rather than a limit."""
    def retract(p):
        p["status_events"] = [{
            "event_type": "RETRACTED", "at": "2026-06-13T09:00:00+00:00",
            "actor": "ops", "reason": "", "replacement_product_id": None,
        }]

    assert "reason" in _schema_refuses(retract)


def test_the_schema_itself_refuses_a_supersession_naming_no_replacement():
    def supersede(p):
        p["status_events"] = [{
            "event_type": "SUPERSEDED", "at": "2026-06-13T09:00:00+00:00",
            "actor": "ops", "reason": "newer view", "replacement_product_id": None,
        }]

    assert "replacement_product_id" in _schema_refuses(supersede)


def test_the_honest_payload_still_validates_against_every_added_rule():
    """The twin, and it earns its place: five of the six rules above are tightenings,
    and a tightening that refuses the reference bundle is worse than the gap it closed.
    """
    from cai.envelope import validate_against_schema

    validate_against_schema(wire())
    validate_against_schema(learned())


def test_the_semantic_boundary_is_still_real_and_still_reached():
    """The other half of the ruling: do NOT push domain semantics into JSON Schema.

    A knowledge cutoff after the decision time is a comparison between two fields, and
    the honest place for it is typed reconstruction. This payload is STRUCTURALLY
    valid -- the schema passes it -- and the import boundary refuses it. That pair is
    what `x-semantic-validations` promises a reader.
    """
    from cai.envelope import import_envelope, validate_against_schema

    payload = wire()
    ctx = payload["product"]["candidate"]["context"]
    ctx["knowledge_cutoff"] = "2026-06-14T07:00:00+00:00"

    validate_against_schema(payload)
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        import_envelope(payload)
