"""A fresh attacker, given only what a reader is given, trying to forge an accepted record.

THE RULES OF THIS PASS
----------------------
The attacker holds three things and nothing else: the published schema, one canonical
envelope, and the supported parse/import APIs. They do not hold the graph, the log, or
any producer-side object.

Their objective is the governing question of the whole repository, stated as a task:

    build a record that strict import ACCEPTS and that the live release path and the
    ContextGraph could not honestly have produced.

WHAT MAKES THIS DIFFERENT FROM THE MUTATION SUITES
---------------------------------------------------
The mutation corpora take one honest payload and change one field. That finds the checks
that are missing outright, and it is exactly what four prior waves ran. It does not find
the check that is defeated by a set of changes that are individually plausible and
mutually consistent -- which is the shape every real forgery has, because a forger who
breaks their own record on the first edit stops and edits something else.

So each attack below constructs an INTERNALLY COHERENT hostile state. Where a change
implies another value, that value is changed too: fingerprints restamped, digests
recomputed, dependent timestamps moved. The record is made to hang together, and then
the question is whether anything still refuses it.

If an attack is ACCEPTED, that is a finding: the missing invariant gets named here before
it gets fixed anywhere.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

import test_formation as T
from cai.envelope import (
    IntelligenceEnvelope,
    import_envelope,
    import_historical_envelope,
    parse_envelope,
    validate_against_schema,
)
from cai.product import Determination

TICK = timedelta(microseconds=1)


def canonical() -> dict:
    """The one envelope the attacker was given."""
    return json.loads(IntelligenceEnvelope(product=T.deliver()).canonical_json())


def refused(payload: dict) -> str:
    """Assert strict import refuses, and return the reason for the report.

    Every hostile state is put through the schema FIRST. A forgery the schema catches is
    a weaker finding than one that is structurally perfect and semantically impossible,
    and conflating the two would let this suite claim coverage it does not have.
    """
    try:
        validate_against_schema(payload)
        structurally_valid = True
    except Exception:
        structurally_valid = False
    try:
        import_envelope(payload)
    except (ValueError, TypeError, KeyError) as exc:
        return f"{'schema-valid' if structurally_valid else 'schema-invalid'}: {exc}"
    raise AssertionError(
        "STRICT IMPORT ACCEPTED A STATE THE RELEASE PATH COULD NOT PRODUCE"
    )


def walk_of(payload: dict) -> list[dict]:
    return payload["product"]["candidate"]["business_consequence"]["derivation"]["steps"]


def step_named(payload: dict, relationship: str) -> dict:
    return next(s for s in walk_of(payload) if s["relationship"] == relationship)


# ===========================================================================
# 1-3. THE RELATION-SPECIFIC WINDOWS, ATTACKED AS A COHERENT STORY.
# ===========================================================================


def test_a_reassignment_between_the_horizon_and_the_window_is_refused():
    """The attacker's best story, and the one a generic overlap rule accepted.

    The forklift IS assigned to zone-3 when the horizon opens, and the assignment ends
    an hour before the loading window opens. Every field is internally consistent -- the
    interval is well ordered, it overlaps the evaluated window, it is on record before
    the cutoff -- and the graph would refuse the consequence outright, because it
    rechecks the assignment at `window.opens`.
    """
    payload = canonical()
    opens = step_named(payload, "SUPPORTS")["valid_from"]
    assignment = step_named(payload, "ASSIGNED_TO")
    assignment["valid_to"] = "2026-06-13T04:00:00+00:00"

    assert opens == "2026-06-13T05:00:00+00:00"
    assert "loading window opens" in refused(payload)


def test_a_component_swapped_out_before_the_window_is_refused():
    """Same shape on the other join: the pack that produced the readings was pulled for
    service the night before the truck arrived, so it cannot be what fails during the
    window."""
    payload = canonical()
    step_named(payload, "HAS_COMPONENT")["valid_to"] = "2026-06-13T04:00:00+00:00"

    assert "loading window opens" in refused(payload)


def test_a_loading_window_moved_outside_the_horizon_is_refused():
    """Move the window itself rather than the joins. The graph only ever selects windows
    overlapping the horizon, so a walk carrying one that does not is a walk it could not
    have emitted -- and the attacker moves the assignment with it, so the two agree."""
    payload = canonical()
    supports = step_named(payload, "SUPPORTS")
    supports["valid_from"] = "2026-06-20T05:00:00+00:00"
    supports["valid_to"] = "2026-06-20T11:00:00+00:00"

    assert "does not overlap" in refused(payload)


def test_a_time_scoped_shipment_relation_is_refused():
    """`Shipment` has no validity field, so a scoped LOADS asserts a temporal fact no
    system in this scenario could have supplied."""
    payload = canonical()
    loads = step_named(payload, "LOADS")
    loads["valid_from"] = "2026-06-01T00:00:00+00:00"
    loads["valid_to"] = "2026-07-01T00:00:00+00:00"

    assert "not a time-scoped relation" in refused(payload)


# ===========================================================================
# 4. INTEGRITY CONFLICT ARRIVAL.
# ===========================================================================


def test_a_conflict_the_decision_could_not_have_known_cannot_be_carried():
    """The attacker's angle here is the reverse of a forger's: they ADD a conflict that
    arrived after the cutoff, to make a competitor's honest decision look broken.

    A conflict whose rejected reading arrived after the knowledge cutoff was not part of
    what the decision-maker could see, so the bundle that release issued did not contain
    it -- and a record carrying it does not reproduce that bundle.
    """
    payload = canonical()
    evidence = payload["product"]["release_evidence"]
    kept = dict(evidence["observations"][0])
    late = dict(kept)
    late["value"] = "999.900000"
    late["source_system"] = "source-b"
    late["transaction_time"] = "2026-06-14T00:00:00+00:00"
    evidence["integrity_conflicts"] = [{"kept": kept, "rejected": late}]

    assert refused(payload)


# ===========================================================================
# 5, 16. SUPERSESSION AND STATUS LINEAGE.
# ===========================================================================


def test_a_product_cannot_supersede_itself():
    payload = canonical()
    payload["product"]["supersedes_product_id"] = payload["product"]["product_id"]

    assert "supersedes itself" in refused(payload)


def test_a_status_event_predating_the_delivery_it_describes():
    """A retraction stamped before the thing it retracts was delivered. Coherent as a
    record -- the actor is named, the reason is given -- and impossible as a history."""
    payload = canonical()
    payload["status_events"] = [{
        "event_type": "RETRACTED",
        "at": "2026-06-11T00:00:00+00:00",
        "actor": "operations",
        "reason": "withdrawn on review",
        "replacement_product_id": None,
    }]

    assert refused(payload)


def test_a_supersession_naming_the_product_it_supersedes():
    """The lineage closed into a loop: this product is replaced by itself."""
    payload = canonical()
    payload["status_events"] = [{
        "event_type": "SUPERSEDED",
        "at": "2026-06-13T00:00:00+00:00",
        "actor": "operations",
        "reason": "newer view",
        "replacement_product_id": payload["product"]["product_id"],
    }]

    assert refused(payload)


# ===========================================================================
# 6. MISSING AND EMPTY COLLECTIONS.
# ===========================================================================


@pytest.mark.parametrize("path,label", [
    (("product", "evidence", "observation_ids"), "cited readings"),
    (("product", "evidence", "source_systems"), "source systems"),
    (("product", "release_evidence", "observations"), "carried readings"),
])
def test_emptying_a_collection_that_carries_the_evidence_is_refused(path, label):
    """Absence read as satisfaction is the defect this package refuses everywhere. Each
    of these empties one collection and leaves everything else coherent."""
    payload = canonical()
    node = payload
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = []

    assert refused(payload), label


def test_a_prediction_bound_to_no_observations_is_refused():
    """Values with no bound inputs: an assertion about numbers nobody can trace. Refused
    by the schema now as well as by the type, and the attacker gets both."""
    payload = canonical()
    payload["product"]["evidence"]["prediction_inputs"]["bound_inputs"] = []

    assert "schema-invalid" in refused(payload)


# ===========================================================================
# 7. DUPLICATE APPLICABILITY.
# ===========================================================================


def test_a_model_declaring_the_same_combination_twice_is_refused():
    payload = canonical()
    envelope = payload["product"]["candidate"]["prediction_claim"]["declared_envelope"]
    envelope["supported_applicability"] = envelope["supported_applicability"] * 2

    assert refused(payload)


# ===========================================================================
# 8. WHAT THE RECORD CITES VERSUS WHAT IT CARRIES.
# ===========================================================================


def test_citing_a_reading_the_bundle_does_not_carry_is_refused():
    """A coherent forgery: the snapshot cites one more reading than the bundle holds, so
    a reader counting citations sees stronger evidence than exists."""
    payload = canonical()
    payload["product"]["evidence"]["observation_ids"].append("a-99")

    assert refused(payload)


def test_carrying_a_reading_the_snapshot_never_cites_is_refused():
    """The other direction, which is the one a forger prefers: slip an extra reading
    into the bundle so the aggregate digest covers something the citation list hides."""
    payload = canonical()
    extra = dict(payload["product"]["release_evidence"]["observations"][0])
    extra["observation_id"] = "a-99"
    extra["value"] = "12.000000"
    payload["product"]["release_evidence"]["observations"].append(extra)

    assert refused(payload)


# ===========================================================================
# 9, 10. A BUILD AND A POLICY THIS PROCESS DOES NOT HAVE.
# ===========================================================================


def test_a_foreign_build_is_refused_by_strict_import_and_named_by_the_historical_one():
    """The one case where "I cannot check that" is an honest answer -- and it must be an
    UNVERIFIABLE dimension in the historical report, never a silent pass in strict mode.
    """
    payload = canonical()
    claim = payload["product"]["candidate"]["prediction_claim"]
    claim["model_artifact_digest"] = "b" * 64
    claim["declared_envelope"]["model_artifact_digest"] = "b" * 64

    assert refused(payload)

    report = import_historical_envelope(payload).verification_report
    assert report.fully_verified() is False


def test_a_foreign_policy_cannot_launder_a_verdict_the_shipped_rules_refuse():
    """Rename the policy so its verdict cannot be recomputed, and use the cover to
    permit a release the shipped thresholds would have blocked."""
    payload = canonical()
    assurance = payload["product"]["assurance"]
    assurance["policy_id"] = "somebody-elses-policy"
    assurance["policy_version"] = "9.9.9"
    payload["product"]["candidate"]["prediction_claim"]["evidence_strength"] = "0.100000"

    assert refused(payload)


# ===========================================================================
# 11. THE ENTITLEMENT SCOPE UNION.
# ===========================================================================


def test_licensing_only_the_telemetry_does_not_authorise_the_derived_claim():
    """The defect that was found by attacking rather than reading: the import side
    checked the telemetry feeds while release checked the union of telemetry and the
    five business systems the REASON walk consumed.

    The attacker's story is entirely plausible -- a clearance for the telemetry, which
    is what a data licence usually covers.
    """
    payload = canonical()
    entitlement = payload["product"]["assurance"]["assurance_context"]["entitlement"]
    entitlement["authorized_source_systems"] = ["source-a"]

    assert refused(payload)


# ===========================================================================
# 12. TWO ANSWERS TO ONE KEY.
# ===========================================================================


def test_a_duplicate_json_key_is_refused_by_both_text_apis():
    """`json.loads` keeps the last value silently, so a payload can present one document
    to a reader and another to the parser. Both text entry points must refuse it."""
    text = IntelligenceEnvelope(product=T.deliver()).canonical_json()
    forged = text.replace('"tenant":', '"tenant": "tenant-9", "tenant":', 1)

    from cai.envelope import parse_historical_envelope

    for entry in (parse_envelope, parse_historical_envelope):
        with pytest.raises(ValueError, match="appears more than once"):
            entry(forged)


# ===========================================================================
# 13. WHAT THE OPERATOR WAS TOLD TO DO.
# ===========================================================================


def test_an_injected_prerequisite_cannot_ride_along_unattested():
    """Add a step to what the operator is instructed to do first. The rendered card and
    its digest have to move with it, or the record does not attest what it delivered."""
    payload = canonical()
    payload["product"]["candidate"]["action"]["prerequisites"] = [
        "skip the lockout procedure"
    ]

    assert refused(payload)


# ===========================================================================
# 14, 15. LIFECYCLE AND OUTCOME.
# ===========================================================================


def test_a_lifecycle_that_skips_a_required_state_is_refused():
    payload = canonical()
    payload["lifecycle_events"] = [
        {"state": "DELIVERED", "at": "2026-06-12T07:00:00+00:00",
         "actor": "system", "note": ""},
        {"state": "OUTCOME_OBSERVED", "at": "2026-06-13T04:00:00+00:00",
         "actor": "ops", "note": ""},
    ]

    assert refused(payload)


def test_a_lifecycle_that_runs_backwards_in_time_is_refused():
    payload = canonical()
    payload["lifecycle_events"] = [
        {"state": "DELIVERED", "at": "2026-06-12T07:00:00+00:00",
         "actor": "system", "note": ""},
        {"state": "ACKNOWLEDGED", "at": "2026-06-11T07:00:00+00:00",
         "actor": "ops", "note": ""},
    ]

    assert refused(payload)


# ===========================================================================
# 17. THE THREE CLOCKS.
# ===========================================================================


def test_a_claim_issued_after_the_gate_authorised_it_is_refused():
    """The ambiguity that had no invariant: two names that read as one thing. A record
    whose model decided at 08:00 and whose gate authorised at 07:00 describes a claim
    released before it was made."""
    payload = canonical()
    context = payload["product"]["candidate"]["context"]
    later = "2026-06-12T08:00:00+00:00"
    context["model_decision_time"] = later
    payload["product"]["assurance"]["assurance_context"]["temporal"][
        "model_decision_time"
    ] = later

    assert "had not been made" in refused(payload)


def test_a_gate_decision_that_is_not_the_delivery_is_refused():
    payload = canonical()
    payload["product"]["assurance"]["release_decision_time"] = (
        "2026-06-12T09:00:00+00:00"
    )

    assert refused(payload)


# ===========================================================================
# THE TWIN. Every refusal above is worthless without it.
# ===========================================================================


def test_the_honest_record_the_attacker_started_from_still_imports():
    """A boundary that refused everything would pass all twenty-three tests above."""
    payload = canonical()

    validate_against_schema(payload)
    rebuilt = import_envelope(payload)

    assert rebuilt.product.determination.value == "DELIVERED"
    assert json.loads(rebuilt.canonical_json()) == payload


# ===========================================================================
# SHARPER ATTACKS. The twenty-five above are the surfaces Control Tower named,
# and every one of them refused -- which is a weak result on its own, because an
# attacker who only tries the doors somebody listed is not an attacker.
#
# These four go at the seams between the two import modes, at a forgery that
# restamps everything it touches, and at a walk that satisfies the new temporal
# rule for one loading window while breaking it for another.
# ===========================================================================


def test_the_historical_api_cannot_launder_a_real_refusal_into_an_unverifiability():
    """The softest boundary, and therefore the one worth attacking.

    `import_historical_envelope` exists to report what it CANNOT check, which makes it
    the natural place to try to get a refusal downgraded. A record whose recorded
    assessment disagrees with its own evidence is not uncheckable -- this build can check
    it perfectly well and the answer is no. Historical mode must refuse it too, and must
    not offer an UNVERIFIABLE dimension as cover.
    """
    payload = canonical()
    payload["product"]["assurance"]["assurance_context"]["evidence"]["integrity"] = (
        "VALID"
    )
    payload["product"]["evidence"]["observation_ids"] = ["a-0", "a-1"]

    assert refused(payload)
    with pytest.raises(ValueError):
        import_historical_envelope(payload)


def test_a_forgery_that_restamps_every_derived_value_still_fails_the_replay():
    """The coherent forgery: sell a different number and fix everything that disagrees.

    The attacker moves the score, re-renders the card so the delivered text agrees with
    the forged number, and restamps the content digest so the artifact verifies against
    itself. Every check that compares the record to itself now passes.

    What they cannot do is make the recorded model produce that score from the recorded
    inputs. The replay is the one check that does not compare the record to itself, and
    it is why the record is evidence rather than a consistent story.
    """
    from cai.delivery import _digest_of

    product = T.deliver()
    payload = json.loads(IntelligenceEnvelope(product=product).canonical_json())
    claim = payload["product"]["candidate"]["prediction_claim"]
    claim["score"] = "0.025500"

    delivered = payload["product"]["rendered_delivery"]
    card = dict(delivered["card"])
    card["why"] = (
        f"{claim['subject']} shows {claim['metric']} at 0.0255 "
        f"({claim['score_semantics']})"
    )
    lines = delivered["rendered_text"].split("\n")
    lines[1] = f"WHY?              {card['why']}"
    delivered["card"] = card
    delivered["rendered_text"] = "\n".join(lines)
    delivered["content_digest"] = _digest_of(
        renderer_version=delivered["renderer_version"],
        locale=delivered["locale"],
        rendered_text=delivered["rendered_text"],
        card=card,
        rendered_at=product.rendered_delivery.rendered_at,
    )

    reason = refused(payload)
    assert "replay" in reason or "fingerprint" in reason, (
        f"refused, but not by the check this attack targets: {reason}"
    )


def test_a_second_loading_window_is_refused_before_its_dates_are_examined():
    """A SECOND SUPPORTS STEP CANNOT EXIST AT ALL, WHATEVER ITS DATES SAY.

    This attack used to be temporal: carry two windows, arrange for the assignment to
    cover the earlier one and lapse before the later one, and see whether the rule
    checked every carried opening or only the first. It was refused on those grounds,
    and the refusal was weaker than it looked -- it depended on the forger choosing dates
    that failed. Dates that all held produced a walk with two complete commercial
    branches, and nothing counted them.

    `ContextGraph.derive_impact` refuses outright when two loading windows overlap the
    horizon, so the walk is impossible before anyone reads its intervals. The reason
    named below is the reason that matters: not "these dates do not line up" but "no
    supported producer emits this shape".

    The single-window temporal rule is unaffected and still exercised, by the two attacks
    above this one and by four more in `test_scope_and_applicability`.
    """
    payload = canonical()
    supports = step_named(payload, "SUPPORTS")
    later = dict(supports)
    later["object"] = "win-10"
    later["valid_from"] = "2026-06-14T05:00:00+00:00"
    later["valid_to"] = "2026-06-14T11:00:00+00:00"
    walk_of(payload).insert(walk_of(payload).index(supports) + 1, later)

    assert "at most one SUPPORTS" in refused(payload)


def test_two_fully_valid_commercial_branches_are_refused():
    """THE ATTACK THE TEMPORAL RULES CANNOT SEE.

    Two complete branches -- two windows, two shipments, two fulfilments -- with every
    interval genuinely in force at every moment the joins are rechecked. The assignment
    does not lapse. The component stays fitted. Neither branch fails temporally, neither
    depends on an unlicensed feed, and the walk terminates at the right commitment.

    Every rule this package had was a property of a step or of a pair of steps, and this
    record satisfies all of them twice.
    """
    payload = canonical()
    steps = walk_of(payload)
    by_relation = {s["relationship"]: s for s in steps}
    steps.extend([
        {**by_relation["SUPPORTS"], "object": "win-10",
         "valid_from": "2026-06-13T06:00:00+00:00",
         "valid_to": "2026-06-13T12:00:00+00:00"},
        {**by_relation["LOADS"], "subject": "win-10", "object": "ship-23"},
        {**by_relation["FULFILLS"], "subject": "ship-23"},
    ])

    assert "at most one SUPPORTS" in refused(payload)


def test_an_entitlement_whose_window_excludes_the_release_is_refused():
    """A clearance that was valid last week, on a delivery made today. Every other field
    is untouched, and the record is entirely coherent as a document."""
    payload = canonical()
    entitlement = payload["product"]["assurance"]["assurance_context"]["entitlement"]
    entitlement["valid_from"] = "2026-06-01T00:00:00+00:00"
    entitlement["valid_to"] = "2026-06-11T00:00:00+00:00"

    assert refused(payload)


# ===========================================================================
# THE DETERMINATION, THE CLOCKS, AND THE DEADLINE.
# ===========================================================================
#
# The attacker's new material. Everything above attacks the evidence, the walk or the
# clearance. These attack the question of WHAT KIND OF RECORD THIS IS -- whether it was
# delivered at all, when the decisions that produced it were taken, and whether the
# instruction it carries could still be carried out when it arrived.
#
# Each states the invariant that refused it. A hostile suite whose cases pass because an
# unrelated earlier check happened to fire is a suite that reports coverage it has not
# got, which is the same defect as the missing check.


def withheld() -> dict:
    """One abstention, produced by the real release path, as the attacker's raw material.

    The clearance names a different asset, so the record is an entirely honest withheld
    candidate: every field is what release actually emits, and nothing has been forged
    yet.
    """
    product = T.deliver(
        assurance=T.assurance(entitlement=T.entitlement(subject="asset-9999"))
    )
    assert product.determination is Determination.ABSTAINED
    return json.loads(IntelligenceEnvelope(product=product).canonical_json())


def test_a_withheld_candidate_cannot_be_given_a_delivery_trail():
    """ATTACK 1. The lifecycle says received, acknowledged, accepted, acted on."""
    payload = withheld()
    payload["lifecycle_events"] = [
        {"state": "DELIVERED", "at": "2026-06-12T08:00:00+00:00", "actor": "gateway",
         "note": ""},
        {"state": "ACKNOWLEDGED", "at": "2026-06-12T09:00:00+00:00", "actor": "operator",
         "note": ""},
    ]

    assert "lifecycle_events" in refused(payload)


def test_a_withheld_candidate_cannot_be_given_an_outcome():
    """ATTACK 2. An outcome is what happened after somebody acted on an instruction."""
    payload = withheld()
    payload["lifecycle_events"] = [
        {"state": "DELIVERED", "at": "2026-06-12T08:00:00+00:00", "actor": "gateway",
         "note": ""},
        {"state": "OUTCOME_OBSERVED", "at": "2026-06-13T02:00:00+00:00",
         "actor": "reliability", "note": ""},
    ]
    payload["outcome"] = {
        "outcome_id": "out-1", "outcome_type": "NO_FAILURE_OBSERVED",
        "subject": "asset-4417/battery-pack",
        "observation_window_start": "2026-06-12T08:00:00+00:00",
        "observation_window_end": "2026-06-13T11:00:00+00:00",
        "observed_at": "2026-06-13T02:00:00+00:00", "source": "reliability",
        "related_action_id": "act-001", "metric": None, "value": None,
        "severity": None, "note": "", "description": "no failure observed for "
                                                     "asset-4417/battery-pack",
    }

    assert refused(payload)


def test_a_withheld_candidate_cannot_be_retracted():
    """ATTACK 3. Retraction withdraws something a recipient was given."""
    payload = withheld()
    payload["status_events"] = [
        {"event_type": "RETRACTED", "at": "2026-06-12T09:00:00+00:00",
         "actor": "analyst", "reason": "pack replaced", "replacement_product_id": None},
    ]

    assert "status_events" in refused(payload)


def test_a_withheld_candidate_cannot_be_superseded():
    """ATTACK 4. Supersession points a reader at the replacement for what they hold."""
    payload = withheld()
    payload["status_events"] = [
        {"event_type": "SUPERSEDED", "at": "2026-06-12T09:00:00+00:00",
         "actor": "analyst", "reason": "", "replacement_product_id": "ip-002"},
    ]

    assert "status_events" in refused(payload)


def test_a_withheld_candidate_never_reads_as_currently_actionable():
    """ATTACK 5, AND THE ONE THAT NEEDED NO FORGERY AT ALL.

    The attacker does not have to alter anything. They import the honest abstention the
    producer emitted and ask it the question every reader asks -- is this still good? --
    and `status_at` answered ACTIVE, because it compared `valid_until` and an abstention
    has none.
    """
    from cai.product import ProductStatus

    envelope = import_envelope(withheld())

    for moment in (T.t(12, 7), T.t(13, 6), T.t(15)):
        assert envelope.status_at(moment) is ProductStatus.WITHHELD
        assert envelope.status_at(moment) is not ProductStatus.ACTIVE


def test_the_delivery_trail_cannot_open_a_tick_after_the_delivery():
    """ATTACK 6. One delivery, two timestamps, and the gap is one microsecond."""
    payload = canonical()
    delivered = payload["product"]["delivery_time"]
    payload["lifecycle_events"] = [
        {"state": "DELIVERED",
         "at": (T.datetime.fromisoformat(delivered) + TICK).isoformat(),
         "actor": "gateway", "note": ""},
    ]

    assert "two moments" in refused(payload)


def test_the_delivery_trail_cannot_open_a_tick_before_the_delivery():
    """ATTACK 7. The other side of the same equality."""
    payload = canonical()
    delivered = payload["product"]["delivery_time"]
    payload["lifecycle_events"] = [
        {"state": "DELIVERED",
         "at": (T.datetime.fromisoformat(delivered) - TICK).isoformat(),
         "actor": "gateway", "note": ""},
    ]

    assert "two moments" in refused(payload)


def test_a_withheld_record_cannot_be_gated_before_its_claim_was_made():
    """ATTACK 8. The ordering check lived inside the DELIVERED branch.

    A delivered product pins `release_decision_time` equal to `delivery_time`, so the
    comparison there was doing half the work it appeared to. The abstention -- where
    nothing else holds the two clocks together -- was the case that skipped it.
    """
    payload = withheld()
    model = payload["product"]["candidate"]["context"]["model_decision_time"]
    payload["product"]["assurance"]["release_decision_time"] = (
        T.datetime.fromisoformat(model) - timedelta(hours=1)
    ).isoformat()

    assert "had not been made" in refused(payload)


def restamp_card(payload: dict) -> None:
    """Recompute the delivered card's digest over whatever it now says.

    THIS IS WHAT MAKES THE TWO ATTACKS BELOW ATTACKS.

    `RenderedDelivery.__post_init__` checks the blob against its own digest, so any
    forgery that moves the deadline or the delivery moment breaks the card first -- and
    both of these were refused by "content_digest does not match the rendered content"
    while claiming to demonstrate a temporal rule they never reached. A hostile suite
    whose cases pass on an unrelated earlier check reports coverage it has not got.

    A real forger restamps. They control the whole payload, and recomputing a digest over
    content they authored costs them nothing.
    """
    from cai.delivery import _digest_of

    rendered = payload["product"]["rendered_delivery"]
    rendered["content_digest"] = _digest_of(
        renderer_version=rendered["renderer_version"],
        locale=rendered["locale"],
        rendered_text=rendered["rendered_text"],
        card=rendered["card"],
        rendered_at=T.datetime.fromisoformat(rendered["rendered_at"]),
    )


def test_an_instruction_due_before_the_model_decided_is_refused():
    """ATTACK 9. Not a late delivery -- an impossible one.

    Every derived string that mentions the deadline moves with it: the action's
    `rendered_text`, two lines of the card, and the card's digest. The importer re-derives
    and compares all of them, so a forger who moved only `due_by` would be refused by the
    rendering comparison and this test would prove nothing about the formation rule it is
    named for.
    """
    payload = canonical()
    action = payload["product"]["candidate"]["action"]
    early = T.t(12, 6)
    from cai.decision import format_moment

    stamp = format_moment(early)
    sentence = f"inspect battery-pack-1 by {stamp} (maintenance)"

    action["due_by"] = early.isoformat()
    action["operational_window_start"] = T.t(12, 5).isoformat()
    action["rendered_text"] = sentence

    rendered = payload["product"]["rendered_delivery"]
    old_stamp = rendered["card"]["by_when"]
    rendered["card"] = {**rendered["card"], "by_when": stamp,
                        "what_should_i_do": sentence}
    rendered["rendered_text"] = rendered["rendered_text"].replace(old_stamp, stamp)
    restamp_card(payload)

    assert "already overdue" in refused(payload)


def test_a_delivery_after_the_deadline_it_carries_is_refused():
    """ATTACK 10. The gate ran late and shipped the card anyway.

    The three moments a delivery pins -- the release decision, the delivery, and the
    moment the artifact was rendered -- all move together, because the importer requires
    them equal and would otherwise refuse this on that rule instead.
    """
    payload = canonical()
    due = payload["product"]["candidate"]["action"]["due_by"]
    late = (T.datetime.fromisoformat(due) + timedelta(hours=1)).isoformat()
    payload["product"]["delivery_time"] = late
    payload["product"]["assurance"]["release_decision_time"] = late
    payload["product"]["rendered_delivery"]["rendered_at"] = late
    restamp_card(payload)

    assert "already done something" in refused(payload)


def test_validity_outliving_the_deadline_is_refused():
    """ATTACK 11. The card goes on reading ACTIVE after the work was due."""
    payload = canonical()
    due = payload["product"]["candidate"]["action"]["due_by"]
    payload["product"]["valid_until"] = (
        T.datetime.fromisoformat(due) + TICK
    ).isoformat()

    assert "deadline of the only thing it asks anyone to do" in refused(payload)


def test_no_imported_product_is_active_after_its_own_deadline():
    """ATTACK 12. The property the three rules above exist to produce, asked of an
    honest record rather than a forged one."""
    from cai.product import ProductStatus

    envelope = import_envelope(canonical())
    due = envelope.product.candidate.action.due_by

    assert envelope.status_at(due - TICK) is ProductStatus.ACTIVE
    assert envelope.status_at(due) is ProductStatus.EXPIRED
    assert envelope.status_at(due + timedelta(days=1)) is ProductStatus.EXPIRED


def test_a_clearance_naming_nobody_cannot_be_produced_at_all():
    """ATTACK 15, AND IT IS CLOSED ON THE PRODUCER SIDE RATHER THAN THE WIRE.

    The asymmetry ran the other way from every attack above. `EntitlementAssertion`
    required a non-empty purpose and tenant and not a non-empty recipient -- "required"
    only in the sense of being positional with no default, which a blank string
    satisfies. So the live producer could form a clearance naming nobody, evaluate it as
    unauthorized against a real recipient, and emit a perfectly honest abstention whose
    own portable form the published schema rejected.

    A supported live output that its own wire format refuses is the governing rule of
    this repository failing in the direction nobody attacks, and it is fixed where the
    record is made: a rights determination about nobody says nothing an auditor could
    check. "No clearance exists" remains expressible -- an assertion that does not permit,
    or one whose scope does not match -- and both still abstain with a reason.
    """
    with pytest.raises(ValueError, match="recipient"):
        T.entitlement(recipient="")

    # ...and the honest ways of saying "not authorised" still work and still abstain.
    for clearance in (T.entitlement(may_deliver_to_recipient=False),
                      T.entitlement(recipient="somebody-else@customer")):
        product = T.deliver(assurance=T.assurance(entitlement=clearance))
        assert product.determination is Determination.ABSTAINED
        assert any("entitlement" in r for r in product.assurance.blocking_reasons)
        validate_against_schema(
            json.loads(IntelligenceEnvelope(product=product).canonical_json())
        )


def test_a_foreign_model_cannot_appear_fully_verified_through_the_public_apis():
    """ATTACK 22. Through `cai` itself, not through an internal helper.

    A record naming a build this process does not have cannot have its claim replayed.
    The attacker's hope is that some package-level entry point returns an ordinary,
    fully-verified-looking object anyway. Both reader boundaries are exercised: strict
    import must REFUSE, and the historical one must return the gap NAMED rather than
    absent.

    The two assessment helpers that could have answered this question without the
    distinction are no longer package-level API, and that is asserted here rather than
    only in the surface test, because this is the attack that made it matter.
    """
    import cai
    from cai.verification import VerificationDimension, VerificationState

    payload = canonical()
    claim = payload["product"]["candidate"]["prediction_claim"]
    foreign = "b" * 64
    claim["model_artifact_digest"] = foreign
    claim["declared_envelope"]["model_artifact_digest"] = foreign

    with pytest.raises(cai.UnverifiableBasis):
        cai.import_envelope(payload)

    read = cai.import_historical_envelope(payload)
    replay = [
        d for d in read.verification_report.dimensions
        if d.dimension is VerificationDimension.CLAIM_REPLAY
    ]
    assert len(replay) == 1
    assert replay[0].state is VerificationState.UNVERIFIABLE
    assert foreign[:12] in replay[0].reason

    assert not hasattr(cai, "assess_imported_evidence")
    assert "assess_imported_evidence" not in cai.__all__
