"""Can a record be built that import accepts and release could not have produced?

THE GOVERNING QUESTION
----------------------
Everything in this file is one question asked forty different ways: can a product exist,
on the wire, in a semantic state the real release path could not have reached from the
evidence travelling with that same artifact?

Until this increment the honest answer was yes, and not because of a bug. The portable
form carried a CITATION of the evidence -- observation ids, an aggregate digest, a list of
source systems, the bound predictor inputs -- and not the evidence. A reader holding only
a citation can check that a record agrees with itself, which is a much weaker property
than it sounds: every internal cross-reference can be consistent while the readings they
point at say something else entirely, or do not exist, or were contradicted by a second
source the producer chose not to mention.

So the portable representation was strictly weaker than the in-memory one, on an artifact
whose entire proposition is that the decision survives the platform that produced it.

WHAT CHANGED, AND WHY THE TESTS LOOK LIKE THIS
----------------------------------------------
`IntelligenceProduct` now carries the `EvidenceBundle` the assessment ran over, and the
import boundary re-runs `assess_evidence` -- the SAME function `formation.release` calls,
with the same arguments read out of the record -- and refuses any record whose recorded
assessment its own evidence does not produce.

That is why almost every test below mutates ONE field of an honest envelope and asserts a
specific message. A generic "integrity" assertion would pass for all fourteen mutations
and prove that none of them reaches the arm it names, which is the failure mode a
refusal-only suite structurally cannot see. `release.integrity_findings` names each arm,
so each test can say which invariant it violated.

THE LIMIT, STATED RATHER THAN DISCOVERED
-----------------------------------------
None of this is cryptographic authenticity. A party who can rewrite the whole unsigned
artifact can rewrite the readings, recompute every digest over them, and produce a
self-consistent forgery. The evidence is tamper-EVIDENT: a record and the evidence it
carries can no longer drift apart unnoticed. Signatures are deliberately not implemented
rather than implemented badly, and `test_the_carried_evidence_is_not_a_signature` says so
in executable form.
"""

from __future__ import annotations

import copy
import json

import pytest

import test_formation as T
from cai.bitemporal import EvidenceBundle, Observation, ObservationLog
from cai.envelope import IntelligenceEnvelope, import_envelope


def wire(**over) -> dict:
    """An honest delivered envelope, serialized exactly as it would cross a boundary."""
    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


def forged(mutate, **over) -> dict:
    """An honest envelope with exactly one thing wrong with it."""
    payload = wire(**over)
    mutate(payload)
    return payload


def _observations(p) -> list[dict]:
    return p["product"]["release_evidence"]["observations"]


def _snapshot(p) -> dict:
    return p["product"]["evidence"]


# ---------------------------------------------------------------------------
# THE HONEST TWIN. Every refusal below is worthless without it: a suite of
# refusals passes perfectly against an importer that refuses everything.
# ---------------------------------------------------------------------------


def test_an_untouched_delivered_envelope_round_trips():
    original = IntelligenceEnvelope(product=T.deliver())
    text = original.canonical_json()

    rebuilt = import_envelope(json.loads(text))

    assert rebuilt.canonical_json() == text
    assert rebuilt.digest() == original.digest()
    carried = rebuilt.product.release_evidence
    assert [o.observation_id for o in carried.observations] == [
        o.observation_id for o in T.observations()
    ]


def test_the_readings_come_back_as_typed_observations_not_a_bag_of_strings():
    """Reconstruction, not validation. If these came back as dicts every assertion in
    this file about their invariants would be vacuous."""
    carried = import_envelope(wire()).product.release_evidence

    assert isinstance(carried, EvidenceBundle)
    assert all(isinstance(o, Observation) for o in carried.observations)
    # And the digest survives the wire, which is the property the six-decimal value form
    # exists to guarantee. A reading whose digest changed in transit would break every
    # binding that names it.
    original = {o.observation_id: o.content_digest() for o in T.observations()}
    assert {o.observation_id: o.content_digest() for o in carried.observations} == original


def test_a_reading_finer_than_the_wire_form_is_refused_where_it_is_created():
    """The same rule `PredictionInputs`, `IdentityAssertion` and `DowntimeConsequence`
    each learned at their own boundary, applied at the one place a reading enters.

    A value carrying more precision than six decimals would digest one way in memory and
    another after the round trip, so a wholly honest product would be refused by its own
    importer. Refused where the producer can still quantize the reading.
    """
    with pytest.raises(ValueError, match="more precision than the 6-decimal wire form"):
        Observation("a-9", "asset-4417", "battery_temp_c", 41.00000015,
                    T.t(8, 6), T.t(8, 7), "source-a")


def test_an_integer_reading_digests_the_same_either_side_of_the_wire():
    """Non-triviality twin, and a real defect rather than a hypothetical one.

    The scenario's partner feed reports charge cycles as an `int`. `repr(1236)` is not
    `repr(1236.0)`, and the content digest hashes `repr(value)` -- so the same reading
    digested differently once it had been through a wire form that reads back as a float.
    Normalising in the constructor is what makes this test able to pass at all.
    """
    counted = Observation("b-9", "asset-4417", "charge_cycles", 1236,
                          T.t(8, 6), T.t(8, 7), "source-b")
    assert isinstance(counted.value, float)
    assert Observation.from_record(counted.as_record()).content_digest() == (
        counted.content_digest()
    )


# ---------------------------------------------------------------------------
# THE FOURTEEN. One honest envelope, one mutation each, one named invariant.
# ---------------------------------------------------------------------------


def _restamp_fingerprint(p):
    """Recompute the input fingerprint over whatever the record now says its inputs were.

    Every mutation of a bound input moves the fingerprint, so the naive forgery is caught
    by `input_fingerprint_mismatch` before anything looks at the readings -- and a test
    that stopped there would prove the fingerprint check works, which was never in doubt,
    while claiming to prove something about carried evidence.

    A real forger recomputes. The fingerprint is a published pure function precisely so
    that a verifier can re-derive it without the model, which means an attacker can too.
    Restamping it here is what makes these tests reach the arms they name.
    """
    from cai.predictor import input_fingerprint_for

    inputs = _snapshot(p)["prediction_inputs"]
    fingerprint = input_fingerprint_for(
        metric=inputs["metric"],
        values=tuple(float(v) for v in inputs["values"]),
        horizon_seconds=inputs["horizon_seconds"],
        model_version=inputs["model_version"],
        bound=tuple((b["observation_id"], b["content_digest"])
                    for b in inputs["bound_inputs"]),
    )
    inputs["input_fingerprint"] = fingerprint
    p["product"]["candidate"]["prediction_claim"]["input_fingerprint"] = fingerprint


def _replace_snapshot_ids(p):
    """Cite a reading the bundle does not carry, keeping every other invariant intact.

    Replacing the whole citation list breaks `bound_inputs subset of observation_ids`
    first, which is a different and earlier invariant. Appending one ghost keeps the
    subset rule, the aggregate digest and the fingerprint all valid, so the only thing
    wrong with this record is that it tells a reader to follow six pointers when five
    readings were verified.
    """
    _snapshot(p)["observation_ids"] = _snapshot(p)["observation_ids"] + ["ghost-1"]


def _remove_a_cited_observation(p):
    """Drop a reading from the carried bundle while the snapshot still cites it."""
    del _observations(p)[-1]


def _add_an_unrelated_observation(p):
    extra = copy.deepcopy(_observations(p)[0])
    extra["observation_id"] = "a-99"
    _observations(p).append(extra)
    _snapshot(p)["observation_ids"] = _snapshot(p)["observation_ids"] + ["a-99"]


def _snapshot_subject_disagrees_with_the_readings(p):
    """Relabel the readings and everything that names them EXCEPT the snapshot.

    Changing one reading's subject makes the bundle describe two assets, which
    `subject_binding_mismatch` refuses first and on better grounds. To reach the arm that
    compares the snapshot's own declared subject to the readings, the claim and the
    readings have to agree with each other and the snapshot alone has to be wrong.
    """
    _relabel_everything_but_the_readings(p)
    for observation in _observations(p):
        observation["subject"] = "asset-9999"
    _snapshot(p)["subject"] = "asset-4417"


def _change_an_observation_metric(p):
    _observations(p)[0]["metric"] = "coolant_temp_c"


def _change_an_observation_value(p):
    _observations(p)[0]["value"] = "99.900000"


def _change_an_observation_source_system(p):
    """A LICENSED feed, deliberately.

    An unlicensed one ("source-BLACKMARKET") is refused by the entitlement check, which
    runs first and is a different rule -- so this case would pass while the arm comparing
    the snapshot's declared feeds to its readings' actual feeds was deleted. Substituting
    a feed the clearance does cover isolates that arm.
    """
    _observations(p)[0]["source_system"] = "asset-register"


def _change_a_transaction_time_to_after_the_cutoff(p):
    _observations(p)[0]["transaction_time"] = T.t(20, 0).isoformat()


def _change_a_bound_input_observation_id(p):
    _snapshot(p)["prediction_inputs"]["bound_inputs"][0]["observation_id"] = "a-99"
    _snapshot(p)["observation_ids"] = _snapshot(p)["observation_ids"] + ["a-99"]
    _restamp_fingerprint(p)


def _change_a_bound_input_content_digest(p):
    _snapshot(p)["prediction_inputs"]["bound_inputs"][0]["content_digest"] = "b" * 64
    _restamp_fingerprint(p)


def _change_a_bound_input_value_used(p):
    """The forgery that is invisible without the readings, built to be self-consistent.

    A bound input replays a value the reading it names does not hold. Everything else is
    made to agree: `values` moves with it (the record must agree with itself), the
    fingerprint is recomputed, and the claim is restamped to the score the predictor
    actually produces for the substituted series -- so the replay passes.

    Before the readings travelled there was nothing left to catch this. The aggregate
    digest covers the readings and was never compared to the bound values; the replay
    reproduces whatever the record supplies. The only thing that refuses this record is
    the reading itself saying otherwise.
    """
    from datetime import timedelta

    from cai.contract import PredictionClaim
    from cai.predictor import predict_degradation

    inputs = _snapshot(p)["prediction_inputs"]
    inputs["values"][0] = "70.000000"
    inputs["bound_inputs"][0]["value_used"] = "70.000000"
    _restamp_fingerprint(p)
    replayed = predict_degradation(
        metric=inputs["metric"],
        values=tuple(float(v) for v in inputs["values"]),
        horizon=timedelta(seconds=inputs["horizon_seconds"]),
        bound=tuple((b["observation_id"], b["content_digest"])
                    for b in inputs["bound_inputs"]),
    )
    claim = p["product"]["candidate"]["prediction_claim"]
    restamped = PredictionClaim.from_prediction(
        replayed, subject=claim["subject"]
    ).as_record()
    claim["score"] = restamped["score"]
    claim["evidence_strength"] = restamped["evidence_strength"]


def _add_a_conflict_about_unused_evidence(p):
    stranger = copy.deepcopy(_observations(p)[0])
    stranger["observation_id"] = "somebody-elses-problem"
    rival = copy.deepcopy(stranger)
    rival["value"] = "12.000000"
    p["product"]["release_evidence"]["integrity_conflicts"] = [
        {"kept": stranger, "rejected": rival}
    ]


@pytest.mark.parametrize("name,mutate,pattern", [
    (
        "snapshot cites readings that are not the carried ones",
        _replace_snapshot_ids,
        "the snapshot cites .* but the evidence carried is",
    ),
    (
        "a cited reading is missing from the bundle",
        _remove_a_cited_observation,
        "the snapshot cites .* but the evidence carried is",
    ),
    (
        "an unrelated reading is added to the bundle and the citation",
        _add_an_unrelated_observation,
        "evidence_content_digest is not the digest of the readings carried with it",
    ),
    (
        "the snapshot's declared subject is not the readings' subject",
        _snapshot_subject_disagrees_with_the_readings,
        "the snapshot says its readings are about .* but they are about",
    ),
    (
        "a reading's metric is changed",
        _change_an_observation_metric,
        "evidence_content_digest is not the digest of the readings carried with it",
    ),
    (
        "a reading's value is changed",
        _change_an_observation_value,
        "evidence_content_digest is not the digest of the readings carried with it",
    ),
    (
        "a reading's source system is changed",
        _change_an_observation_source_system,
        "the snapshot declares feeds .* but its readings came from",
    ),
    (
        "a bound input names a reading the bundle does not carry",
        _change_a_bound_input_observation_id,
        "is not among the readings carried",
    ),
    (
        "a bound input carries a digest that is not that reading's",
        _change_a_bound_input_content_digest,
        "carries a content digest that is not that reading's",
    ),
    (
        "a bound input replays a value that reading does not hold",
        _change_a_bound_input_value_used,
        "but that reading holds",
    ),
])
def test_a_forged_record_refuses_for_the_invariant_it_actually_violates(
    name, mutate, pattern
):
    """One mutation, one named arm.

    The `pattern` is the point. Ten of these would pass against a bare "integrity" match
    while reaching two arms between them, and the suite would look thorough while proving
    that eight invariants are never exercised.
    """
    with pytest.raises(ValueError, match=pattern):
        import_envelope(forged(mutate))


def test_a_reading_the_decision_had_not_received_is_refused_on_import():
    """Item 2, mutation 8, and it refuses on temporal grounds rather than on a digest.

    Moving a transaction time also moves the content digest, so the naive version of this
    test passes on the digest arm and proves nothing about point-in-time eligibility. The
    eligibility check runs BEFORE the assessment is recomputed, precisely so that this
    record is refused for the reason it is actually wrong: the decision-maker did not have
    this reading.
    """
    with pytest.raises(ValueError, match="after the knowledge cutoff"):
        import_envelope(forged(_change_a_transaction_time_to_after_the_cutoff))


def test_a_conflict_about_evidence_the_product_does_not_use_is_refused():
    """Item 2, mutation 13. A withholding for somebody else's problem is a refusal the
    operator cannot act on, so it must not be constructible either."""
    with pytest.raises(ValueError, match="not among the readings it contains"):
        import_envelope(forged(_add_a_conflict_about_unused_evidence))


def _conflicted_delivery() -> dict:
    """An honest ABSTAINED envelope whose refusal was caused by a real disagreement."""
    log = ObservationLog()
    for o in T.observations():
        log.record(o)
    first = T.observations()[0]
    log.record(Observation(first.observation_id, first.subject, first.metric, 999.9,
                           first.valid_time, first.transaction_time, "source-b"))
    payload = wire(observation_log=log)
    assert payload["product"]["determination"] == "ABSTAINED"
    assert payload["product"]["release_evidence"]["integrity_conflicts"]
    return payload


def test_the_conflicted_abstention_round_trips_honestly():
    """The twin for the mutation below. A refusal caused by a disagreement has to survive
    the wire as a refusal caused by that disagreement."""
    payload = _conflicted_delivery()
    rebuilt = import_envelope(payload)
    assert rebuilt.product.release_evidence.integrity_conflicts
    assert json.loads(rebuilt.canonical_json()) == payload


def test_dropping_an_integrity_conflict_from_the_wire_is_refused():
    """Item 2, mutation 12, and the single most valuable one in this file.

    The forgery is not to add something false. It is to REMOVE something true: take an
    honest abstention caused by two sources disagreeing about one reading, delete the
    disagreement, and ship a record whose evidence now looks clean. Before the conflicts
    travelled there was nothing to delete and nothing to notice, which is worse.
    """
    payload = _conflicted_delivery()
    payload["product"]["release_evidence"]["integrity_conflicts"] = []
    with pytest.raises(ValueError, match="the record names conflicts .* but the evidence"):
        import_envelope(payload)


def _relabel_everything_but_the_readings(p):
    """Item 2, mutation 14. The whole record consistently renamed onto another asset,
    with the carried telemetry left exactly as it was."""
    product = p["product"]
    claim = product["candidate"]["prediction_claim"]
    claim["subject"] = "asset-9999/battery-pack"
    product["evidence"]["subject"] = "asset-9999"
    basis = product["assurance"]["assurance_context"]
    basis["identity"]["resolved_entity"] = "asset-9999/battery-pack"
    basis["entitlement"]["subject"] = "asset-9999/battery-pack"
    for step in product["candidate"]["business_consequence"]["derivation"]["steps"]:
        if step["subject"] == "asset-4417":
            step["subject"] = "asset-9999"


def test_relabelling_the_whole_record_cannot_move_it_onto_another_asset():
    """The claim, the snapshot, both assertions and the derivation all agree with each
    other and all disagree with the telemetry. Before the readings travelled, every check
    that consumed a subject read it from the record, so this forgery was internally
    perfect and unfalsifiable from the artifact alone."""
    with pytest.raises(ValueError, match="but every reading it rests on is about"):
        import_envelope(forged(_relabel_everything_but_the_readings))


def test_an_imported_bundle_mixing_two_subjects_is_refused():
    """The refusal the release path no longer needs, at the boundary that still does.

    Release asks the log for the point-in-time view of ONE subject, so it cannot see a
    reading about another asset. Import receives whatever the artifact carries, so the
    multi-subject rule is live here -- and this is the test `test_formation` points at
    when it stopped being reachable there.
    """
    def mutate(p):
        stranger = copy.deepcopy(_observations(p)[0])
        stranger["observation_id"] = "z-1"
        stranger["subject"] = "asset-9999"
        _observations(p).append(stranger)
        _snapshot(p)["observation_ids"] = _snapshot(p)["observation_ids"] + ["z-1"]

    with pytest.raises(ValueError, match="a claim over several subjects"):
        import_envelope(forged(mutate))


def test_a_bundle_carrying_one_reading_twice_is_refused():
    """`ObservationLog` keeps one reading per id, so two is a state release cannot reach.
    On the wire it decides which reading a bound input resolves to."""
    def mutate(p):
        _observations(p).append(copy.deepcopy(_observations(p)[0]))

    with pytest.raises(ValueError, match="carries .* twice"):
        import_envelope(forged(mutate))


def test_a_fabricated_conflict_pairing_a_reading_with_itself_is_refused():
    """An identical redelivery is ordinary at-least-once traffic. A record that dressed
    one up as a disagreement would withhold a product nobody needed to withhold."""
    def mutate(p):
        same = copy.deepcopy(_observations(p)[0])
        p["product"]["release_evidence"]["integrity_conflicts"] = [
            {"kept": same, "rejected": copy.deepcopy(same)}
        ]

    with pytest.raises(ValueError, match="pairs a reading with itself"):
        import_envelope(forged(mutate))


def test_a_conflict_naming_a_different_version_of_a_carried_reading_is_refused():
    """The `kept` half of a conflict must BE the reading the bundle carries. A conflict
    recorded against one version of a reading and shipped beside another describes a
    contradiction nobody can reconcile -- and it lets a producer attach a real-looking
    disagreement to evidence that never had one."""
    def mutate(p):
        kept = copy.deepcopy(_observations(p)[0])
        kept["value"] = "77.000000"
        rejected = copy.deepcopy(kept)
        rejected["value"] = "88.000000"
        p["product"]["release_evidence"]["integrity_conflicts"] = [
            {"kept": kept, "rejected": rejected}
        ]

    with pytest.raises(ValueError, match="is not the reading the bundle carries"):
        import_envelope(forged(mutate))


# ---------------------------------------------------------------------------
# THE LIMIT. Stated in executable form so nobody has to take the docstring's word.
# ---------------------------------------------------------------------------


def test_the_carried_evidence_is_not_a_signature():
    """Tamper-EVIDENT, not tamper-proof, and the difference is worth demonstrating.

    A party who controls the whole artifact can alter a reading, recompute the aggregate
    digest, recompute the bound input's digest, recompute the fingerprint, and re-run the
    predictor to get a claim that replays. This test performs exactly that forgery and
    asserts it SUCCEEDS, because the alternative -- letting the README imply otherwise --
    is the overclaim this repository spends its time removing.

    What the carried evidence closes is drift between a record and its evidence. What it
    does not close is a party who controls both. That needs a signature over the pair,
    which is deliberately not implemented rather than implemented badly.
    """
    altered = T.observations()[:-1] + (
        Observation("a-4", "asset-4417", "battery_temp_c", 70.0, T.t(12, 6), T.t(12, 7),
                    "source-a"),
    )
    claim = T.claim_over(altered)
    product = T.deliver(
        candidate=T.candidate(claim=claim),
        evidence=T.evidence_over(claim, altered),
        observation_log=T.log_of(altered),
    )
    payload = json.loads(IntelligenceEnvelope(product=product).canonical_json())

    rebuilt = import_envelope(payload)

    assert rebuilt.product.determination.value == "DELIVERED"
    assert rebuilt.product.candidate.prediction_claim.score != T.claim().score, (
        "the forgery must actually change the number being sold"
    )


# ---------------------------------------------------------------------------
# STRUCTURAL EQUIVALENCE, asserted rather than described. These are the claims
# the handoff makes, in executable form.
# ---------------------------------------------------------------------------


def test_release_and_import_reach_their_assessment_through_the_same_function():
    """Not "they agree" -- they are the SAME call.

    A wire-side reimplementation that happened to agree today is the second semantics
    engine this package spends its time refusing, and the day it disagrees is the day the
    portable form stops meaning what the in-memory form means. So this asserts the call
    graph, not the answer: `formation.release` and
    `IntelligenceProduct._verify_the_assessment_follows_from_the_evidence` both invoke
    `release.assess_evidence`, and nothing else computes an `EvidenceAssessment`.
    """
    import ast
    import inspect
    import pathlib

    from cai import formation
    from cai.product import IntelligenceProduct

    assert "assess_release_evidence(" in inspect.getsource(formation.release)
    assert "assess_imported_evidence(" in inspect.getsource(
        IntelligenceProduct._verify_the_assessment_follows_from_the_evidence)

    # AST, not grep: nothing outside `assessment.py` may construct an EvidenceAssessment,
    # which is what stops a second projection appearing beside the first.
    builders = set()
    for path in pathlib.Path("src/cai").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "EvidenceAssessment"):
                builders.add(path.name)
    assert builders <= {"evidence.py", "assessment.py"}, builders


def test_the_two_boundaries_produce_the_identical_assessment_for_one_record():
    """The behavioural half. One product, assessed at release and re-assessed at import,
    compared dimension by dimension including the named missing evidence and conflicts."""
    from cai.binding import claim_is_replayable_here
    from cai.policy import ReleasePolicy
    from cai.assessment import assess_imported_evidence

    product = T.deliver()
    at_release = product.assurance.assessed.evidence_assessment
    assessed = product.assurance.assessed

    at_import = assess_imported_evidence(
        evidence=product.evidence,
        entitlement_assertion=assessed.context.entitlement_assertion,
        delivering_to=product.recipient,
        for_purpose=product.purpose,
        about_subject=product.candidate.prediction_claim.subject,
        for_tenant=product.tenant,
        release_decision_time=product.assurance.release_decision_time,
        confidence=product.candidate.prediction_claim.evidence_strength,
        model_applicable=assessed.context.applicability_assertion.valid,
        point_in_time_correct=assessed.context.temporal_assertion.valid,
        evidence_source=product.release_evidence,
        prediction_claim=product.candidate.prediction_claim,
        derivation=product.candidate.business_consequence.derivation,
        policy=ReleasePolicy(),
    )

    assert at_import == at_release
    assert at_import.release_decision() is at_release.release_decision()


def test_every_strictly_imported_envelope_satisfies_the_published_schema():
    """Both directions, because the interesting one is the second.

    Forwards is structural: validation runs before reconstruction, so anything that
    imports has already conformed. Backwards is the claim a conformance statement rests
    on -- that what this package EMITS is what its own published contract admits -- and it
    is checked by re-exporting the imported envelope and validating that.
    """
    from cai.envelope import validate_against_schema

    for payload in (wire(), _conflicted_delivery()):
        envelope = import_envelope(payload)
        re_exported = json.loads(envelope.canonical_json())
        validate_against_schema(re_exported)
        assert re_exported == payload


def test_a_reading_describing_an_event_that_had_not_happened_is_refused_on_import():
    """Item 17, attack 5. Valid time, not transaction time: the reading genuinely
    arrived, and the EVENT it describes had not occurred at the evaluation moment.

    `point_in_time_view` drops these at release. On the wire they arrive attached to a
    decision context that also arrives from outside, so the property is checked.
    """
    def mutate(p):
        context = p["product"]["candidate"]["context"]
        _observations(p)[0]["valid_time"] = T.t(20, 0).isoformat()
        del context  # the context is untouched; only the reading moves

    with pytest.raises(ValueError, match="after the evaluation time"):
        import_envelope(forged(mutate))


def test_a_reading_whose_two_clocks_contradict_each_other_is_refused_on_import():
    """Item 17, attack 5 again, from the other side: a device stamps a reading in the
    future and delivers it before the decision. `has_implausible_clock` names it, and
    `point_in_time_view` excludes it -- so one carried in the bundle is a reading release
    would never have assessed."""
    def mutate(p):
        observation = _observations(p)[0]
        observation["valid_time"] = T.t(12, 6, ).isoformat()
        observation["transaction_time"] = T.t(9, 0).isoformat()

    with pytest.raises(ValueError, match="claims an event that had not happened"):
        import_envelope(forged(mutate))


def test_a_reading_a_carried_correction_supersedes_is_refused_on_import():
    """Item 17, attack 8. The bundle carries both a reading and a correction to it that
    had already arrived -- so release would have dropped the superseded one, and a record
    carrying both is one release could not have produced.

    Reconstructable from the carried evidence alone, which is why it is checked: the
    correction is right there in the bundle claiming to supersede its neighbour.
    """
    def mutate(p):
        correction = copy.deepcopy(_observations(p)[0])
        correction["observation_id"] = "a-99"
        correction["supersedes"] = _observations(p)[0]["observation_id"]
        _observations(p).append(correction)
        _snapshot(p)["observation_ids"] = _snapshot(p)["observation_ids"] + ["a-99"]

    with pytest.raises(ValueError, match="was corrected by a later reading"):
        import_envelope(forged(mutate))


def test_values_bound_to_no_reading_at_all_cannot_reach_a_delivered_record():
    """THE HOSTILE PASS FOUND THIS, and it is the sharpest forgery in this file.

    `PredictionInput` exists because an evidence digest over observations and, separately,
    a tuple of values connects nothing: a producer can cite genuine readings, carry their
    perfectly valid digest, and put unrelated numbers in the inputs. One explicit join
    closed that -- and every check reading the join was written `if pi.bound_inputs:`, so
    an EMPTY tuple switched all three off. The field's own docstring blessed the state:
    "Empty means the values are unbound assertions."

    The attack below is internally perfect. Five fabricated values. The five genuine
    readings still cited. Their genuine aggregate digest. A fingerprint over the
    fabricated values, and a replay that reproduces the claim from them -- because both
    are computed over what the record supplied rather than over what it cited.

    It released as DELIVERED and imported cleanly, selling 0.0255 where the honest claim
    is 0.4942. Nothing in the bundle contradicted anything else; the number was simply
    about nothing. `PredictionInputs` now refuses the state at construction, which is why
    this test asserts a refusal rather than an abstention.
    """
    from cai.contract import PredictionInputs
    from cai.predictor import predict_degradation

    fabricated = (99.0, 99.5, 99.9, 100.4, 101.0)
    replayed = predict_degradation(metric="battery_temp_c", values=fabricated,
                                   horizon=T.context().horizon, bound=())
    assert round(replayed.risk, 4) != round(T.claim().score, 4), (
        "the fabricated series must actually produce a different claim"
    )
    with pytest.raises(ValueError, match="no bound observations are unbound assertions"):
        PredictionInputs(
            metric="battery_temp_c", values=fabricated,
            horizon_seconds=T.claim().horizon_seconds,
            model_version=T.claim().model_version,
            input_fingerprint=replayed.input_fingerprint,
        )


def test_every_value_the_claim_replays_is_bound_to_a_carried_reading():
    """The positive statement the refusal above protects: on an honest record, every
    number the predictor consumed names the reading it came from, and that reading is in
    the bundle."""
    product = T.deliver()
    inputs = product.evidence.prediction_inputs
    carried = {o.observation_id: o for o in product.release_evidence.observations}

    assert len(inputs.bound_inputs) == len(inputs.values)
    for bound, value in zip(inputs.bound_inputs, inputs.values):
        reading = carried[bound.observation_id]
        assert bound.value_used == value == reading.value
        assert bound.content_digest == reading.content_digest()


# ---------------------------------------------------------------------------
# THE RESIDUAL LIMITS, in executable form.
#
# A hostile pass that only records what it closed leaves the reader guessing about
# what it did not. These assert that specific forgeries ARE accepted, and say why
# that is the honest boundary rather than an oversight. If any of them starts
# failing, the boundary moved and this file should say so.
# ---------------------------------------------------------------------------


def test_a_step_claiming_it_held_outside_the_evaluated_window_is_refused():
    """The annotation that COULD be constrained, and now is.

    `valid_from`/`valid_to` say when a relationship held in the world. They crossed the
    wire and were checked against nothing, so a reader could be told an assignment held
    across 2099 and had no way to disagree -- a state the real walk could not emit,
    accepted by strict import.

    The rule that closed it is relation-specific rather than generic: an ASSIGNED_TO must
    be in force at the moment the evaluated window opens AND at the moment the carried
    loading window opens, which is exactly the pair of checks the graph makes. A 2099
    assignment fails the first of them.

    `tests/test_scope_and_applicability.py` holds the boundary cases, including the one a
    generic overlap rule admitted: an assignment that overlaps the evaluated window and
    has already ended by the time the loading window opens.
    """
    def forge_validity(p):
        step = p["product"]["candidate"]["business_consequence"]["derivation"]["steps"][1]
        step["valid_from"] = "2099-01-01T00:00:00+00:00"
        step["valid_to"] = "2099-06-01T00:00:00+00:00"

    with pytest.raises(ValueError, match="not in force when the evaluated window opens"):
        import_envelope(forged(forge_validity))


def test_the_reference_walks_own_validity_intervals_all_overlap_the_window():
    """The twin. A rule that refused the real walk would refuse everything, and SUPPORTS
    is the step that makes containment the wrong rule."""
    walk = import_envelope(wire()).product.candidate.business_consequence.derivation
    window = walk.evaluated_window

    scoped = [s for s in walk.steps if s.valid_from or s.valid_to]
    assert scoped, "the reference walk must actually carry some scoped steps"
    for step in scoped:
        assert step.valid_from is None or step.valid_from < window.end
        assert step.valid_to is None or step.valid_to > window.start


def test_injected_prerequisites_are_refused_because_they_are_now_attested():
    """CLOSED, not documented. Control Tower rejected stating this as a limit.

    `prerequisites` sat on the action, travelled in the record, and never reached the
    card -- so the delivered artifact, the only part of the bundle whose digest attests
    what a human was shown, omitted them while the record carried them. A forger could
    inject "skip the lockout" into a delivered record and nothing objected.

    Either they are internal metadata, in which case no reader may treat them as evidence
    of what an operator was told, or they are instructions. They are safety steps that
    must happen FIRST. So they render, which puts them inside the card, inside its digest,
    and inside the comparison the import boundary already performed.
    """
    def inject(p):
        p["product"]["candidate"]["action"]["prerequisites"] = ["skip the lockout"]

    with pytest.raises(ValueError, match="this is the text a human was shown"):
        import_envelope(forged(inject))


def test_honest_prerequisites_reach_the_card_and_its_digest():
    """The twin, and the point of the change: a prerequisite the operator never saw is
    not a prerequisite."""
    from cai.action import ActionRecommendation, ActionType, Priority
    from cai.decision import TimeInterval

    product = T.deliver(candidate=T.candidate(action=ActionRecommendation(
        "act-001", ActionType.INSPECT, "battery-pack-1", "maintenance", T.t(13, 3),
        TimeInterval(T.t(13, 5), T.t(13, 11)),
        "degradation signal over the commitment horizon", Priority.BEFORE_NEXT_USE,
        prerequisites=("isolate the pack", "lock out the charger"))))

    shown = product.rendered_delivery.card["what_should_i_do"]
    assert "isolate the pack" in shown and "lock out the charger" in shown
    # ...and it survives the wire, digest and all.
    payload = json.loads(IntelligenceEnvelope(product=product).canonical_json())
    rebuilt = import_envelope(payload)
    assert rebuilt.product.candidate.action.prerequisites == (
        "isolate the pack", "lock out the charger")
    assert json.loads(rebuilt.canonical_json()) == payload


def test_a_clearance_covering_more_than_the_product_uses_still_delivers():
    """NOT a limit -- the rule, from the permissive side.

    `permits()` requires the consumed sources to be a SUBSET of the licensed ones. A
    clearance covering a feed this product never touched is an ordinary commercial fact,
    and refusing it would refuse every real MSA.
    """
    def widen(p):
        p["product"]["assurance"]["assurance_context"]["entitlement"][
            "authorized_source_systems"] = sorted(
                set(T.CONSUMED_SOURCES) | {"a-feed-this-product-never-used"})

    assert import_envelope(forged(widen)).product.determination.value == "DELIVERED"
