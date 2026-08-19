"""What a determination permits, and which clock answers to which.

TWO QUESTIONS THAT LOOKED SETTLED AND WERE NOT
----------------------------------------------
The package already refuses an abstention that carries a rendered card or a delivery
time: `IntelligenceProduct.__post_init__` names that state and raises. What it did not
refuse was everything recorded BESIDE the product. The envelope's join to delivery was

    if delivery is None or not self.lifecycle_events:
        return

and an abstention has `delivery_time is None` by construction -- so the guard skipped
itself on precisely the records it exists to constrain. An abstention could open a
lifecycle at DELIVERED, run it to OUTCOME_OBSERVED, carry the outcome, and be retracted
afterwards. Every individual event was well-formed. The sequence described a delivery
that never happened.

The second question is the clocks. Three moments travel with every decision --
`model_decision_time`, `release_decision_time`, `delivery_time` -- and the ordering
between the first two was checked inside the DELIVERED branch, which is the one branch
where the third moment pins them anyway. So the ordering was enforced where it was
redundant and absent where it was load-bearing: an abstention could claim its release
gate decided before the model it was gating had issued a claim.

Allowing the model and the gate to differ is correct -- they are different domain events
-- but it opens a gap the package had no rule for. A gate that runs at 09:00 over a model
that decided at 07:00 can deliver a card instructing an operator to act by 08:00. The
instruction is already impossible when it arrives, and nothing refused it.

WHAT THIS FILE IS FOR
---------------------
Each defect gets an adversarial reproduction, an honest twin that must keep working, and
the boundary either side of the moment where the answer changes. The twins are not
decoration: every refusal below could be satisfied by a build that refuses everything,
and a suite that only proves refusals cannot tell those two apart.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

import test_formation as T
from cai.action import OutcomeObservation, OutcomeType
from cai.decision import TimeInterval
from cai.envelope import (
    IntelligenceEnvelope,
    StatusEvent,
    StatusEventType,
    import_envelope,
    import_historical_envelope,
)
from cai.lifecycle import DispositionEvent, DispositionState
from cai.product import Determination, ProductStatus

TICK = timedelta(microseconds=1)


# ---------------------------------------------------------------------------
# BUILDERS. An abstention produced by the real release path, never hand-built.
# ---------------------------------------------------------------------------


def abstained(**over):
    """A rights abstention: the clearance covers a different asset.

    Produced by `release`, so this is a record the supported live system genuinely
    emits. A hand-constructed `IntelligenceProduct(determination=ABSTAINED, ...)` would
    prove nothing about what the producer can put on the wire.
    """
    product = T.deliver(
        assurance=T.assurance(entitlement=T.entitlement(subject="asset-9999")), **over
    )
    assert product.determination is Determination.ABSTAINED
    return product


def evidence_abstained():
    """The other honest abstention: the evidence itself does not support release."""
    c = T.candidate()
    product = T.deliver(
        candidate=c, evidence=T.evidence(c.prediction_claim, digest="a" * 64)
    )
    assert product.determination is Determination.ABSTAINED
    return product


def delivered_trail(product, at):
    """The opening of a delivery trail, at a chosen moment."""
    return (DispositionEvent(DispositionState.DELIVERED, at, "gateway"),)


# ===========================================================================
# 1. AN ABSTENTION IS NOT A DELIVERY, AND NOTHING RECORDED BESIDE IT MAY SAY SO
# ===========================================================================


def test_an_honest_rights_abstention_still_forms():
    """TWIN FIRST. Everything below refuses; this is what must not be refused."""
    product = abstained()
    assert product.delivery_time is None
    assert product.rendered_delivery is None
    assert any("entitlement" in r for r in product.assurance.blocking_reasons)
    IntelligenceEnvelope(product=product)


def test_an_honest_evidence_abstention_still_forms():
    """The second twin, on a different blocking dimension.

    Two twins rather than one because §1's constraints are enforced on the
    determination, and a build that broke abstention formation for a reason specific to
    the rights path would still satisfy a single-twin suite.
    """
    product = evidence_abstained()
    assert product.delivery_time is None
    IntelligenceEnvelope(product=product)


def test_an_abstained_product_cannot_open_a_delivery_trail():
    """THE DEFECT. `delivery is None` returned early, so this state was constructible.

    The lifecycle says the operator received the card, acknowledged it and accepted it.
    The product says nothing was ever delivered. Both are in the same envelope.
    """
    with pytest.raises(ValueError, match="abstained|withheld|not delivered"):
        IntelligenceEnvelope(
            product=abstained(),
            lifecycle_events=delivered_trail(abstained(), T.t(12, 8)),
        )


def test_an_abstained_product_cannot_carry_an_outcome():
    """An outcome is what happened AFTER somebody acted on a delivered instruction."""
    product = abstained()
    trail = (
        DispositionEvent(DispositionState.DELIVERED, T.t(12, 8), "gateway"),
        DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 9), "operator"),
        DispositionEvent(DispositionState.ACCEPTED, T.t(12, 10), "operator"),
        DispositionEvent(DispositionState.ACTION_COMPLETED, T.t(13, 1), "technician"),
        DispositionEvent(DispositionState.OUTCOME_OBSERVED, T.t(13, 6), "reliability"),
    )
    outcome = OutcomeObservation(
        outcome_id="out-1",
        outcome_type=OutcomeType.NO_FAILURE_OBSERVED,
        subject=product.candidate.prediction_claim.subject,
        observation_window=TimeInterval(T.t(13, 5), T.t(13, 11)),
        observed_at=T.t(13, 6),
        source="reliability",
        related_action_id=product.candidate.action.action_id,
    )
    with pytest.raises(ValueError, match="abstained|withheld|not delivered"):
        IntelligenceEnvelope(
            product=product, lifecycle_events=trail, outcome=outcome
        )


def test_an_abstained_product_cannot_be_retracted():
    """Retraction withdraws a claim that was made. Nothing was delivered to withdraw."""
    with pytest.raises(ValueError, match="abstained|withheld|not delivered"):
        IntelligenceEnvelope(
            product=abstained(),
            status_events=(
                StatusEvent(StatusEventType.RETRACTED, T.t(12, 9), "analyst",
                            reason="pack replaced"),
            ),
        )


def test_an_abstained_product_cannot_be_superseded():
    """Supersession points a reader at the replacement for something they were given."""
    with pytest.raises(ValueError, match="abstained|withheld|not delivered"):
        IntelligenceEnvelope(
            product=abstained(),
            status_events=(
                StatusEvent(StatusEventType.SUPERSEDED, T.t(12, 9), "analyst",
                            replacement_product_id="ip-002"),
            ),
        )


def test_an_abstained_product_never_reports_active():
    """`status_at` fell through to ACTIVE for every product with no `valid_until`.

    An abstention has none by construction, so the one determination that was never
    delivered reported the status that means "delivered and still actionable".
    """
    product = abstained()
    for moment in (T.t(12, 7), T.t(13), T.t(30)):
        assert product.status_at(moment) is ProductStatus.WITHHELD
        assert IntelligenceEnvelope(product=product).status_at(moment) is (
            ProductStatus.WITHHELD
        )


def test_a_delivered_product_still_reports_active_and_expired():
    """TWIN for the status change. WITHHELD must not swallow the delivered answers."""
    product = T.deliver()
    assert product.determination is Determination.DELIVERED
    assert product.status_at(product.valid_until - TICK) is ProductStatus.ACTIVE
    assert product.status_at(product.valid_until) is ProductStatus.EXPIRED


# ---- the same four states, arriving from outside rather than built in process


@pytest.mark.parametrize("mutate", [
    pytest.param(
        lambda p: {"lifecycle_events": [
            {"state": "DELIVERED", "at": T.t(12, 8).isoformat(), "actor": "gateway",
             "note": ""}]},
        id="delivery-trail"),
    pytest.param(
        lambda p: {"status_events": [
            {"event_type": "RETRACTED", "at": T.t(12, 9).isoformat(),
             "actor": "analyst", "reason": "pack replaced",
             "replacement_product_id": None}]},
        id="retraction"),
    pytest.param(
        lambda p: {"status_events": [
            {"event_type": "SUPERSEDED", "at": T.t(12, 9).isoformat(),
             "actor": "analyst", "reason": "",
             "replacement_product_id": "ip-002"}]},
        id="supersession"),
])
def test_strict_import_refuses_an_abstention_dressed_as_a_delivery(mutate):
    """The same states, forged onto the wire, refused by BOTH authorities separately.

    The schema now expresses this constraint, so `import_envelope` refuses these payloads
    structurally and never reaches the typed rule. That is the right order and it makes a
    single-assertion test dishonest: it would report the domain invariant working while
    only ever exercising the validator.

    So both halves are asserted. The structural refusal names the collection that violated;
    the typed refusal is reached by reconstructing the product FROM THE PAYLOAD -- the same
    `from_record_with_findings` the importer calls -- and assembling the envelope directly,
    which is the path a caller takes when they hold a record rather than a file.

    `tests/test_wire.py` holds the schema corpus for the same three states. This one exists
    for the second assertion.
    """
    from cai.envelope import SchemaViolation
    from cai.product import IntelligenceProduct

    payload = IntelligenceEnvelope(product=abstained()).as_record()
    payload.update(mutate(payload))

    with pytest.raises(SchemaViolation):
        import_envelope(payload)

    rebuilt, _ = IntelligenceProduct.from_record_with_findings(payload["product"])
    assert rebuilt.determination is Determination.ABSTAINED
    with pytest.raises(ValueError, match="was ABSTAINED and carries"):
        IntelligenceEnvelope(
            product=rebuilt,
            lifecycle_events=tuple(
                DispositionEvent.from_record(e)
                for e in payload.get("lifecycle_events") or ()
            ),
            status_events=tuple(
                StatusEvent.from_record(e) for e in payload.get("status_events") or ()
            ),
        )


def test_historical_import_does_not_downgrade_an_abstention_contradiction():
    """UNVERIFIABLE means "this reader could not check". This reader can check it.

    The historical path exists for facts that genuinely cannot be re-derived here -- a
    foreign model, a policy whose thresholds are not on the wire. A determination that
    contradicts the events recorded beside it needs no absent build to detect, so
    reporting it as a verification gap would launder a refusal into a caveat.
    """
    payload = IntelligenceEnvelope(product=abstained()).as_record()
    payload["lifecycle_events"] = [
        {"state": "DELIVERED", "at": T.t(12, 8).isoformat(), "actor": "gateway",
         "note": ""}
    ]
    with pytest.raises((ValueError, TypeError)):
        import_historical_envelope(payload)


# ===========================================================================
# 2. ONE DELIVERY, ONE MOMENT
# ===========================================================================


def test_the_trail_opens_at_the_moment_of_delivery():
    """TWIN. Equal moments accept, which is what release actually produces."""
    product = T.deliver()
    envelope = IntelligenceEnvelope(
        product=product,
        lifecycle_events=delivered_trail(product, product.delivery_time),
    )
    assert envelope.lifecycle_events[0].at == product.delivery_time


def test_a_trail_opening_after_delivery_is_refused():
    """THE DEFECT. The check was `>=`, so one delivery could carry two timestamps.

    The product says 07:00 and the trail says 09:00. The package already refused this
    exact shape for OUTCOME_OBSERVED -- "one event cannot have happened at two moments"
    -- and left the opening event free.
    """
    product = T.deliver()
    with pytest.raises(ValueError, match="two moments|one event|delivered at"):
        IntelligenceEnvelope(
            product=product,
            lifecycle_events=delivered_trail(product, product.delivery_time + TICK),
        )


def test_a_trail_opening_before_delivery_is_refused():
    """The other side. Already refused; asserted here so the pair is symmetric."""
    product = T.deliver()
    with pytest.raises(ValueError):
        IntelligenceEnvelope(
            product=product,
            lifecycle_events=delivered_trail(product, product.delivery_time - TICK),
        )


def test_a_trail_that_does_not_open_at_delivered_is_refused():
    """The first thing that happens to a delivered product is that it is delivered."""
    product = T.deliver()
    with pytest.raises(ValueError):
        IntelligenceEnvelope(
            product=product,
            lifecycle_events=(
                DispositionEvent(
                    DispositionState.ACKNOWLEDGED, product.delivery_time, "operator"
                ),
            ),
        )


def test_strict_import_carries_the_one_moment_rule():
    product = T.deliver()
    payload = IntelligenceEnvelope(
        product=product,
        lifecycle_events=delivered_trail(product, product.delivery_time),
    ).as_record()
    payload["lifecycle_events"][0]["at"] = (product.delivery_time + TICK).isoformat()
    with pytest.raises((ValueError, TypeError)):
        import_envelope(payload)


def test_the_canonical_round_trip_preserves_the_opening_moment():
    product = T.deliver()
    envelope = IntelligenceEnvelope(
        product=product,
        lifecycle_events=delivered_trail(product, product.delivery_time),
    )
    reimported = import_envelope(envelope.as_record())
    assert reimported.lifecycle_events[0].at == product.delivery_time
    assert reimported.canonical_json() == envelope.canonical_json()


# ===========================================================================
# 3. THE ORDERING IS A PROPERTY OF THE DECISION, NOT OF A SUCCESSFUL DELIVERY
# ===========================================================================


def test_an_abstention_cannot_be_gated_before_its_claim_was_made():
    """THE DEFECT. The model<=release check sat inside the DELIVERED branch.

    A withheld candidate carries both clocks and neither is pinned by a delivery time,
    so the one determination where the ordering is not implied by anything else was the
    one where it went unchecked.
    """
    payload = IntelligenceEnvelope(product=abstained()).as_record()
    gate = payload["product"]["assurance"]
    model = payload["product"]["candidate"]["context"]["model_decision_time"]
    gate["release_decision_time"] = (
        T.datetime.fromisoformat(model) - timedelta(hours=1)
    ).isoformat()
    with pytest.raises((ValueError, TypeError), match="had not been made|issued|gate"):
        import_envelope(payload)


def test_an_abstention_gated_after_its_claim_is_accepted():
    """TWIN. The gate running later than the model is the ordinary case, not a defect."""
    product = abstained()
    assert (
        product.candidate.context.model_decision_time
        <= product.assurance.release_decision_time
    )
    IntelligenceEnvelope(product=product)


# ===========================================================================
# 4. A DELAYED GATE MUST NOT DELIVER AN ALREADY-STALE INSTRUCTION
# ===========================================================================


def test_an_action_due_before_the_model_decided_cannot_form():
    """Formation, not release. The candidate is incoherent before anyone grades it."""
    stale = T.ActionRecommendation(
        "act-001", T.ActionType.INSPECT, "battery-pack-1", "maintenance",
        T.t(12, 6),  # one hour BEFORE model_decision_time
        TimeInterval(T.t(13, 5), T.t(13, 11)),
        "degradation signal", T.Priority.BEFORE_NEXT_USE,
    )
    with pytest.raises(ValueError, match="due|deadline|decided"):
        T.candidate(action=stale)


def test_an_action_due_exactly_when_the_model_decided_forms():
    """THE BOUNDARY, DECIDED DELIBERATELY.

    Equality is permitted at formation and can never reach a delivery: delivery is
    strictly before `due_by`, and delivery is at or after the release decision, which is
    at or after the model's. So such a candidate forms, can be honestly withheld, and
    cannot be delivered. That is a coherent pair, and it is stated here rather than left
    to be discovered from whichever comparison happened to be written first.
    """
    at_the_moment = T.ActionRecommendation(
        "act-001", T.ActionType.INSPECT, "battery-pack-1", "maintenance",
        T.t(12, 7),  # exactly model_decision_time
        TimeInterval(T.t(13, 5), T.t(13, 11)),
        "degradation signal", T.Priority.BEFORE_NEXT_USE,
    )
    T.candidate(action=at_the_moment)


def test_a_delivery_one_tick_before_the_deadline_is_accepted():
    """TWIN. Late but still actionable is a delivery, not a defect."""
    due = T.action().due_by
    product = T.deliver(release_decision_time=due - TICK, valid_until=due)
    assert product.determination is Determination.DELIVERED
    assert product.delivery_time == due - TICK


def test_a_delivery_exactly_at_the_deadline_is_refused():
    """EXCLUSIVE, and consistent with every other interval end in this package.

    `TimeInterval.contains` is `start <= m < end`, `valid_until` expires AT its moment,
    and an observation window closes half-open. A card handed to an operator at the
    instant the work was due leaves no interval in which the work could be done.
    """
    due = T.action().due_by
    with pytest.raises(ValueError, match="due|deadline|stale"):
        T.deliver(release_decision_time=due, valid_until=due)


def test_a_delivery_after_the_deadline_is_refused():
    due = T.action().due_by
    with pytest.raises(ValueError, match="due|deadline|stale"):
        T.deliver(release_decision_time=due + timedelta(hours=1),
                  valid_until=due + timedelta(hours=2))


def test_validity_outliving_the_action_deadline_is_refused():
    """THE RULING. `valid_until` answers "is this still actionable", so it answers to
    the deadline of the action it is asking for."""
    due = T.action().due_by
    with pytest.raises(ValueError, match="due|deadline|actionable"):
        T.deliver(valid_until=due + TICK)


def test_validity_exactly_at_the_action_deadline_is_accepted():
    """TWIN and boundary. Expiring AT the deadline is the longest honest horizon."""
    due = T.action().due_by
    product = T.deliver(valid_until=due)
    assert product.valid_until == due


def test_no_product_is_active_after_the_deadline_of_its_own_action():
    """The property the three rules above exist to produce, asserted directly.

    Stated over the boundary rather than over a convenient interior moment: the
    interesting instant is the deadline itself.
    """
    product = T.deliver(valid_until=T.action().due_by)
    due = product.candidate.action.due_by
    assert product.status_at(due - TICK) is ProductStatus.ACTIVE
    assert product.status_at(due) is ProductStatus.EXPIRED
    assert product.status_at(due + TICK) is ProductStatus.EXPIRED


def test_status_immediately_before_validity_is_active():
    product = T.deliver(valid_until=T.action().due_by)
    assert product.status_at(product.valid_until - TICK) is ProductStatus.ACTIVE


def test_status_exactly_at_validity_is_expired():
    product = T.deliver(valid_until=T.action().due_by)
    assert product.status_at(product.valid_until) is ProductStatus.EXPIRED


def test_a_delayed_but_still_actionable_release_survives_the_round_trip():
    """The whole point of allowing the gate to lag the model, exercised end to end."""
    due = T.action().due_by
    late = due - timedelta(hours=1)
    product = T.deliver(release_decision_time=late, valid_until=due)
    envelope = IntelligenceEnvelope(
        product=product, lifecycle_events=delivered_trail(product, late)
    )
    reimported = import_envelope(envelope.as_record())
    assert reimported.canonical_json() == envelope.canonical_json()
    assert reimported.product.delivery_time == late
    assert reimported.product.candidate.context.model_decision_time < late


# ===========================================================================
# THE PUBLIC RELEASE INPUT IS A RELEASE-DECISION CLOCK AND NOW SAYS SO.
# ===========================================================================
#
# `release()` took a parameter called `delivery_time` and passed it, unchanged, into
# `assess_release_evidence(release_decision_time=...)` and
# `policy.evaluate(release_decision_time=...)`. Both are right about what it is: the
# moment the system decides whether the intelligence may go out. Delivery is what happens
# AFTERWARDS, and only if the decision permits.
#
# So on the abstained path the caller had to pass a `delivery_time` to reach an outcome in
# which `product.delivery_time` is None -- correctly, because nothing was delivered. The
# package documents a three-clock model in `Appendix C` terms and contradicted it at the
# public entry point, which is the one place an implementer in another language reads
# first.
#
# No fourth clock and no delivery-delay abstraction: this implementation delivers the
# instant it decides to, so on the delivered path all three moments coincide. That is a
# property of THIS reference build, asserted below, not a law about release gates.


def test_the_public_release_signature_takes_a_release_decision_time():
    """(1) The name the parameter should always have had."""
    import inspect

    from cai.formation import release

    assert "release_decision_time" in inspect.signature(release).parameters


def test_the_public_release_signature_no_longer_takes_a_delivery_time():
    """(2) And the name it should not. A deprecated alias kept quietly accepting the old
    keyword would leave the contradiction in place for every caller who never re-read the
    signature, which is most of them."""
    import inspect

    from cai.formation import release

    assert "delivery_time" not in inspect.signature(release).parameters


def test_an_honest_delivery_stamps_one_instant_on_all_three_clocks():
    """(3) Immediate delivery, stated as an assertion rather than left as a comment."""
    product = T.deliver()

    assert product.determination is Determination.DELIVERED
    assert product.assurance.release_decision_time == product.delivery_time
    assert product.rendered_delivery.rendered_at == product.delivery_time


def test_an_honest_abstention_keeps_its_release_clock_and_delivers_nothing():
    """(4) THE CASE THE OLD NAME GOT WRONG.

    The release gate ran and decided; that moment is real and is recorded. Nothing was
    delivered, so there is no delivery time and no card. Under the old signature the
    caller reached this state by passing an argument named after the event that did not
    occur.
    """
    product = T.deliver(recipient="procurement@other-customer", purpose="benchmarking")

    assert product.determination is Determination.ABSTAINED
    assert product.assurance.release_decision_time is not None
    assert product.delivery_time is None
    assert product.rendered_delivery is None


def test_a_model_deciding_after_the_gate_is_refused_for_a_delivered_product():
    """(5) A gate cannot authorise a claim that did not exist when it ran."""
    with pytest.raises(ValueError, match="a gate cannot"):
        T.deliver(release_decision_time=T.t(12, 7) - timedelta(hours=1))


def test_a_model_deciding_after_the_gate_is_refused_for_an_abstention_too():
    """(6) The same inversion, on the branch where the ordering used to go unchecked.

    `model_decision_time <= release_decision_time` was enforced inside the DELIVERED
    branch, which is the one branch where the third clock pins it anyway. Renaming the
    parameter must not quietly move that check back inside.
    """
    with pytest.raises(ValueError, match="a gate cannot"):
        T.deliver(recipient="procurement@other-customer", purpose="benchmarking",
                  release_decision_time=T.t(12, 7) - timedelta(hours=1))


def test_a_gate_running_after_the_model_still_delivers_while_the_action_is_reachable():
    """(7) The twin for 5 and 6, and it carries real weight.

    A build that refused every model-to-gate gap would satisfy both refusals above and
    make the two clocks one clock. A delay is legitimate; what is not is a delay that
    outlives the instruction the card carries.
    """
    later = T.t(12, 7) + timedelta(minutes=30)

    product = T.deliver(release_decision_time=later)

    assert product.determination is Determination.DELIVERED
    assert product.candidate.context.model_decision_time < product.delivery_time
    assert product.delivery_time < product.candidate.action.due_by, (
        "the fixture no longer exercises a reachable action deadline"
    )


def test_the_canonical_round_trip_survives_the_rename():
    """(8) Bytes in, same bytes out, and both clocks intact across the wire."""
    from cai.envelope import parse_envelope

    product = T.deliver()
    text = IntelligenceEnvelope(product=product).canonical_json()

    rebuilt = parse_envelope(text)

    assert rebuilt.product.delivery_time == product.delivery_time
    assert (rebuilt.product.assurance.release_decision_time
            == product.assurance.release_decision_time)
    assert rebuilt.canonical_json() == text


def test_the_wire_format_is_untouched_by_a_python_parameter_rename():
    """(9) THE BOUNDARY OF THE CHANGE.

    A keyword argument is an internal detail of one Python entry point. The record is a
    published format that other implementations build against and that already-persisted
    products are stored in. If the rename had reached the wire, every archived envelope
    would have silently changed meaning -- which is a migration, not a rename.
    """
    import json

    product = T.deliver()
    record = json.loads(IntelligenceEnvelope(product=product).canonical_json())["product"]

    assert "delivery_time" in record, "the wire lost its delivery clock"
    assert record["delivery_time"] is not None
    assert "release_decision_time" in json.dumps(record["assurance"]), (
        "the wire lost its release-decision clock"
    )
    # The renamed keyword must not have appeared as a new product-level key.
    assert "release_decision_time" not in record, (
        "a Python parameter rename leaked into the published record"
    )

    # And the abstained record still carries an explicit null delivery clock rather than
    # dropping the key, which is what a reader distinguishes "not delivered" by.
    abstained = T.deliver(recipient="procurement@other-customer", purpose="benchmarking")
    other = json.loads(
        IntelligenceEnvelope(product=abstained).canonical_json())["product"]
    assert "delivery_time" in other and other["delivery_time"] is None
