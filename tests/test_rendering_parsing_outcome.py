"""Three places where one fact had two representations, or one text had two meanings.

    A deadline rendered in the producer's local wall clock, with the offset dropped.
    A JSON document whose meaning depended on which parser read it.
    An outcome recorded twice -- once as prose, once as a typed observation.

None of the three was a missing check. Each was a check over the wrong thing.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

import test_formation as T
from cai.decision import format_moment
from cai.envelope import (
    IntelligenceEnvelope,
    MalformedEnvelopeText,
    import_envelope,
    parse_envelope,
    parse_historical_envelope,
)


# ===========================================================================
# OPERATOR-FACING DEADLINES ARE ONE INSTANT, RENDERED ONE WAY, IN UTC.
# ===========================================================================


def test_the_same_instant_in_different_source_offsets_renders_identically():
    """THE defect, and it is not the locale one.

    `f"{moment:%H:%M}"` renders the local wall-clock face of an offset-aware datetime and
    drops the offset. So one instant stamped +00:00 and stamped +01:00 rendered as two
    different deadlines, on two cards attesting the same moment, and neither said which
    zone it meant.
    """
    instant = datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)
    in_berlin = instant.astimezone(timezone(timedelta(hours=2)))
    in_denver = instant.astimezone(timezone(timedelta(hours=-6)))

    assert in_berlin == instant == in_denver, "the fixture must be one instant"
    assert format_moment(instant) == format_moment(in_berlin) == format_moment(in_denver)


def test_the_rendering_names_the_zone_it_means():
    """A timestamp with no zone invites the reader to supply one, and they will supply
    their own."""
    rendered = format_moment(datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc))

    assert rendered == "03:00 UTC on 13 Jun"
    assert "UTC" in rendered


def test_a_deadline_is_not_rendered_in_the_producers_offset():
    """The non-triviality half. A rule that merely rendered CONSISTENTLY could still have
    used whatever offset the producer sat in, which is exactly what makes a deadline
    unportable -- so this asserts the wall-clock face is the UTC one, not the local one.
    """
    in_denver = datetime(2026, 6, 12, 21, 0, tzinfo=timezone(timedelta(hours=-6)))

    assert format_moment(in_denver) == "03:00 UTC on 13 Jun"
    assert "21:00" not in format_moment(in_denver)


def test_the_process_locale_still_cannot_alter_the_result():
    """The earlier fix, kept under test. `%b` reads LC_TIME, so a producer under fr_FR
    stamped "13 juin" into the card while recording locale="en" beside it."""
    import locale as _locale

    reference = format_moment(datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc))
    for candidate in ("fr_FR.UTF-8", "de_DE.UTF-8"):
        try:
            _locale.setlocale(_locale.LC_TIME, candidate)
        except _locale.Error:
            continue
        try:
            assert format_moment(
                datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)) == reference, candidate
        finally:
            _locale.setlocale(_locale.LC_TIME, "C")


def test_a_naive_datetime_cannot_be_rendered_at_all():
    """There is no instant to normalise. Rendering the wall-clock face would put a
    deadline on an operator's card that means something different to each reader."""
    with pytest.raises(ValueError, match="refusing to render a naive datetime"):
        format_moment(datetime(2026, 6, 13, 3, 0))


def test_the_delivered_card_carries_the_utc_deadline():
    """Through the real public boundary rather than the helper alone."""
    product = T.deliver()

    assert product.rendered_delivery.card["by_when"] == "03:00 UTC on 13 Jun"
    assert "UTC" in product.rendered_delivery.rendered_text
    assert "UTC" in product.candidate.action.rendered_text()


def test_re_import_and_re_render_produce_identical_content():
    """The property that makes the rendering portable at all: the digest over the card is
    re-derived on import and compared, so a rendering that depended on the reader's zone
    would make every honest bundle fail its own round trip."""
    original = IntelligenceEnvelope(product=T.deliver())
    text = original.canonical_json()

    rebuilt = import_envelope(json.loads(text))

    assert rebuilt.canonical_json() == text
    assert rebuilt.product.rendered_delivery.content_digest == (
        original.product.rendered_delivery.content_digest
    )
    assert rebuilt.product.rendered_delivery.card == (
        original.product.rendered_delivery.card
    )


# ===========================================================================
# ONE TEXT, ONE RECORD.
# ===========================================================================


def canonical_text(**over) -> str:
    return IntelligenceEnvelope(product=T.deliver(**over)).canonical_json()


def with_duplicate(text: str, key: str, second_value: str) -> str:
    """Insert a second occurrence of `key` immediately after the first.

    Textual surgery rather than dict manipulation, deliberately: a dict cannot hold the
    defect. That is the whole point -- by the time a payload is a dict the duplicate is
    already gone, and whichever value survived is the one every downstream check verifies.
    """
    marker = f'"{key}":'
    at = text.index(marker)
    end = _value_end(text, at + len(marker))
    return text[:end] + f',"{key}":{second_value}' + text[end:]


def _value_end(text: str, start: int) -> int:
    """Where the JSON value beginning at `start` ends."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0:
            return i
    return len(text)


def test_an_honest_canonical_document_parses_and_imports():
    """The twin. Every refusal below is worthless against a parser that refuses
    everything, and this is also the proof that the surgery helper above works on a real
    document rather than only on a contrived one."""
    envelope = parse_envelope(canonical_text())

    assert envelope.product.product_id == "ip-001"
    assert envelope.product.determination.value == "DELIVERED"


def test_canonical_json_parse_envelope_canonical_json_is_stable():
    """text -> record -> text, byte-identical. Any field the parser or the importer
    silently drops, coerces or reorders shows up as a diff."""
    text = canonical_text()

    assert parse_envelope(text).canonical_json() == text


@pytest.mark.parametrize("name,key,second_value", [
    ("top-level product", "product", "null"),
    ("nested prediction_claim field", "score", '"0.990000"'),
    ("evidence field", "evidence_content_digest", '"' + "b" * 64 + '"'),
    ("product_id with two different values", "product_id", '"ip-999"'),
    ("schema version", "schema_version", '"who-knows/9"'),
    ("attributed effect", "attributed_effect", '"PREVENTED"'),
])
def test_a_duplicate_object_key_is_refused_before_a_dict_can_hide_it(
    name, key, second_value
):
    """JSON does not define what a duplicate key means.

    `json.loads` keeps the last, some parsers keep the first, some collect both, some
    error. So one textual artifact denoted different semantic records to different
    readers, and no amount of domain checking closed it because the domain never saw the
    ambiguity -- by the time the importer received a dict, the duplicate was gone.

    `object_pairs_hook` sees the pairs in document order, which is the only point at which
    "this key appeared twice" is still a fact.
    """
    text = with_duplicate(canonical_text(), key, second_value)

    with pytest.raises(MalformedEnvelopeText, match=f"key '{key}' appears more than once"):
        parse_envelope(text)


def test_the_duplicate_would_otherwise_have_changed_the_record():
    """The polarity check for the whole section.

    Without it, every case above would pass against a parser that refused duplicates it
    did not need to refuse. This shows the SAME text, parsed by the standard library,
    silently becomes a different record -- a product id nobody delivered -- and imports as
    though nothing had happened.
    """
    text = with_duplicate(canonical_text(), "product_id", '"ip-999"')

    permissive = json.loads(text)
    assert permissive["product"]["product_id"] == "ip-999", (
        "the standard library keeps the last occurrence; that is the reading this "
        "contract must not silently accept"
    )
    with pytest.raises(MalformedEnvelopeText):
        parse_envelope(text)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_standard_numeric_constant_is_refused(literal):
    """Python extensions to JSON, not JSON. The canonicalizer has no form for them, so a
    document containing one could not be re-serialized as the record it arrived as."""
    text = canonical_text().replace('"score":', f'"unused":{literal},"score":', 1)

    with pytest.raises(MalformedEnvelopeText, match="extension to JSON"):
        parse_envelope(text)


def test_a_float_literal_is_refused():
    """Every decimal in this contract travels as a string carrying its own precision, so
    that two implementations cannot format one value two ways and produce two
    valid-looking digests. A float literal on the wire is either a mistake or an attempt
    to exploit exactly that."""
    text = canonical_text().replace('"horizon_seconds":259200', '"horizon_seconds":259200.0')

    with pytest.raises(MalformedEnvelopeText, match="is a float"):
        parse_envelope(text)


def test_only_json_is_parsed():
    for text in ("not json at all", "", "[1,2,3]", "null"):
        with pytest.raises(MalformedEnvelopeText):
            parse_envelope(text)


def test_the_parser_does_not_create_a_second_interpretation_of_the_domain():
    """STRUCTURAL. `parse_envelope` decides what structure the bytes denote and hands it
    to the same import path every other caller uses.

    A text entry point that re-implemented any domain rule would be the second semantics
    engine this package spends its time refusing, arrived at through a new door.
    """
    import inspect

    source = inspect.getsource(parse_envelope)
    assert "import_envelope(" in source
    assert len([line for line in source.splitlines() if line.strip().startswith("return")]) == 1
    # The parser is PRIVATE, and the historical reader reaches it through its own entry
    # point rather than through a public dict-returning function. That is what stops a
    # caller taking the duplicate-key safety and skipping the domain reconstruction.
    from cai import envelope as envelope_module

    assert not hasattr(envelope_module, "parse_envelope_payload"), (
        "a public payload parser lets a caller stop before the domain sees the record"
    )
    assert "_parse_envelope_payload(" in inspect.getsource(parse_historical_envelope)


def test_the_historical_text_entry_point_refuses_duplicate_keys_too():
    """The records least able to defend themselves get the same parse.

    Without this entry point a historical reader falls back to `json.loads`, and one
    textual artifact denotes different records to different readers -- reopening the hole
    for precisely the archive nobody can re-derive.
    """
    honest = parse_historical_envelope(canonical_text())
    assert honest.envelope.product.product_id == "ip-001"
    assert honest.verification_report.fully_verified() is True

    with pytest.raises(MalformedEnvelopeText, match="appears more than once"):
        parse_historical_envelope(
            with_duplicate(canonical_text(), "product_id", '"ip-999"'))


# ===========================================================================
# ONE OUTCOME AUTHORITY.
# ===========================================================================


def test_the_lifecycle_has_no_scalar_outcome_field():
    """STRUCTURAL. Deleted, not deprecated -- a field that exists teaches every caller
    that filling it means something."""
    import dataclasses

    from cai.lifecycle import ProductLifecycle

    fields = {f.name for f in dataclasses.fields(ProductLifecycle)}
    assert "observed_outcome" not in fields
    assert not hasattr(ProductLifecycle("asset-4417"), "observed_outcome")
    assert "observed_outcome" not in ProductLifecycle("asset-4417").as_record()


def test_the_lifecycle_has_no_string_outcome_method():
    """The other half. A method that stores prose is the same authority as a field that
    holds it."""
    from cai.lifecycle import ProductLifecycle

    assert not hasattr(ProductLifecycle, "record_outcome")


def test_the_lifecycle_still_records_the_transition():
    """Twin: removing the second authority must not remove the first. The trail records
    STATE TRANSITIONS, and OUTCOME_OBSERVED is one."""
    from cai.lifecycle import DispositionState, ProductLifecycle

    lifecycle = ProductLifecycle("asset-4417/battery-pack", product_id="ip-001")
    lifecycle.advance(DispositionState.DELIVERED, at=T.t(12, 7), actor="system")
    lifecycle.advance(DispositionState.IGNORED, at=T.t(12, 9), actor="ops")
    lifecycle.advance(DispositionState.OUTCOME_OBSERVED, at=T.t(13, 4), actor="system",
                      note="no failure observed")

    assert lifecycle.is_closed()
    assert lifecycle.events[-1].note == "no failure observed"


def outcome_over(**over):
    from cai.action import OutcomeObservation, OutcomeType

    return OutcomeObservation(**{
        "outcome_id": "out-1",
        "outcome_type": OutcomeType.DEFECT_FOUND_ON_INSPECTION,
        "subject": "asset-4417/battery-pack",
        "observation_window": T.TimeInterval(T.t(13, 2), T.t(13, 5)),
        "observed_at": T.t(13, 4),
        "source": "maintenance-system",
        "related_action_id": "act-001",
        **over,
    })


def test_an_outcome_inside_its_half_open_window_is_accepted():
    """Twin for the three refusals below."""
    assert outcome_over().observed_at == T.t(13, 4)
    assert outcome_over(observed_at=T.t(13, 2)).observed_at == T.t(13, 2), (
        "the window's opening instant is INSIDE it; half-open means [start, end)"
    )


@pytest.mark.parametrize("name,observed_at", [
    ("before the window opens", T.t(13, 1)),
    ("exactly at the window's end", T.t(13, 5)),
    ("after the window closes", T.t(13, 9)),
])
def test_an_outcome_outside_its_half_open_window_is_refused(name, observed_at):
    """Only the opening half was enforced, so an outcome could be observed after its own
    window closed -- or exactly at the boundary where it belongs to the NEXT window. An
    observation outside the period it claims to describe is a row an evaluation dataset
    counts against the wrong interval."""
    with pytest.raises(ValueError, match="outside the half-open observation window"):
        outcome_over(observed_at=observed_at)


def learned_envelope(**over):
    from cai.action import OutcomeObservation, OutcomeType
    from cai.lifecycle import DispositionEvent, DispositionState

    observed_at = over.get("observed_at", T.t(13, 4))
    event_at = over.get("event_at", observed_at)
    product = T.deliver()
    return IntelligenceEnvelope(
        product=product,
        lifecycle_events=(
            DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
            DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 9), "ops"),
            DispositionEvent(DispositionState.ACCEPTED, T.t(12, 14), "ops"),
            DispositionEvent(DispositionState.ACTION_COMPLETED, T.t(13, 2), "tech"),
            DispositionEvent(DispositionState.OUTCOME_OBSERVED, event_at, "tech"),
        ),
        outcome=OutcomeObservation(
            "out-1", over.get("outcome_type", OutcomeType.DEFECT_FOUND_ON_INSPECTION),
            product.candidate.prediction_claim.subject,
            T.TimeInterval(T.t(13, 2), T.t(13, 6)), observed_at,
            source="maintenance-system",
            related_action_id=product.candidate.action.action_id,
        ),
    )


def test_the_lifecycle_moment_and_the_outcome_moment_cannot_disagree():
    """One event, one moment. The trail said when the outcome was observed and the typed
    outcome said when it was observed, and nothing compared them.

    No separate `recorded_at` is introduced. There is one event here, and a second
    timestamp for it would need a reason and a name -- which is the two-authorities
    pattern the scalar outcome field was just deleted for, one layer down.
    """
    with pytest.raises(ValueError, match="one event cannot have happened at two moments"):
        learned_envelope(event_at=T.t(13, 5))


def test_the_agreeing_moments_still_form():
    assert learned_envelope().outcome.observed_at == T.t(13, 4)


# ===========================================================================
# THE THREE DISPOSITION PATHS, ACTUALLY WALKED.
#
# `test_honest_outcomes_of_every_disposition_survive_the_wire` varied `OutcomeType`
# across three values while its helper built the ACCEPTED path every time. Its name
# and docstring said accepted, overridden and ignored recommendations all reach a
# recorded outcome and all three survive export. It tested one of them, three times.
#
# The non-adoption paths are the ones worth protecting -- OVERRIDDEN and IGNORED are
# the rows a learning loop needs most and the easiest to lose, precisely because
# nothing downstream consumes them the way an accepted recommendation is consumed.
# So each path is constructed, exported, strict-imported, and compared field by
# field: the exact trail, the typed outcome, the action binding, the observed moment.
# ===========================================================================


DISPOSITION_PATHS = {
    "accepted": (
        ("DELIVERED", 7), ("ACKNOWLEDGED", 9), ("ACCEPTED", 14),
        ("ACTION_COMPLETED", 26), ("OUTCOME_OBSERVED", 28),
    ),
    # A human saw it and decided against it. The outcome still happens and is still
    # observed, and it is the most informative row in the file.
    "overridden": (
        ("DELIVERED", 7), ("ACKNOWLEDGED", 9), ("OVERRIDDEN", 14),
        ("OUTCOME_OBSERVED", 28),
    ),
    # Nobody engaged with it at all. Four states shorter, and the one a trail that only
    # ever exercised the happy path would silently stop supporting.
    "ignored": (
        ("DELIVERED", 7), ("IGNORED", 9), ("OUTCOME_OBSERVED", 28),
    ),
}


def envelope_along(path_name: str, *, outcome_type=None):
    """Build a learned envelope whose lifecycle actually walks the named path."""
    from cai.action import OutcomeObservation, OutcomeType
    from cai.lifecycle import DispositionEvent, DispositionState

    steps = DISPOSITION_PATHS[path_name]
    observed_at = T.t(12, 7) + timedelta(hours=steps[-1][1] - 7)
    product = T.deliver()
    return IntelligenceEnvelope(
        product=product,
        lifecycle_events=tuple(
            DispositionEvent(DispositionState(state),
                             T.t(12, 7) + timedelta(hours=hour - 7),
                             "system" if state == "DELIVERED" else "ops")
            for state, hour in steps
        ),
        outcome=OutcomeObservation(
            "out-1", outcome_type or OutcomeType.DEFECT_FOUND_ON_INSPECTION,
            product.candidate.prediction_claim.subject,
            T.TimeInterval(T.t(13, 2), T.t(13, 6)), observed_at,
            source="maintenance-system",
            related_action_id=product.candidate.action.action_id,
        ),
    )


@pytest.mark.parametrize("path_name", sorted(DISPOSITION_PATHS))
def test_each_disposition_path_survives_the_wire_intact(path_name):
    """Construct, export, strict-import, and compare every field that carries meaning.

    `canonical_json() == canonical_json()` alone would pass against an importer that
    dropped the trail and re-derived it, so the trail is compared state by state.
    """
    from cai.lifecycle import DispositionState

    envelope = envelope_along(path_name)
    text = envelope.canonical_json()

    rebuilt = parse_envelope(text)

    assert rebuilt.canonical_json() == text
    assert [e.state for e in rebuilt.lifecycle_events] == [
        DispositionState(state) for state, _ in DISPOSITION_PATHS[path_name]
    ], "the trail is not the trail that went in"
    assert [e.at for e in rebuilt.lifecycle_events] == [
        e.at for e in envelope.lifecycle_events
    ]
    assert rebuilt.outcome.outcome_type is envelope.outcome.outcome_type
    assert rebuilt.outcome.related_action_id == "act-001"
    assert rebuilt.outcome.observed_at == envelope.outcome.observed_at
    assert rebuilt.outcome.observation_window == envelope.outcome.observation_window


@pytest.mark.parametrize("path_name", sorted(DISPOSITION_PATHS))
@pytest.mark.parametrize("outcome_type", [
    "DEFECT_FOUND_ON_INSPECTION",
    "NO_FAILURE_OBSERVED",
    "FAILURE_OCCURRED",
])
def test_every_outcome_type_survives_on_every_disposition_path(path_name, outcome_type):
    """The cross-product the old test's name implied and its helper did not build.

    Nine cases rather than three. A recommendation that was overridden and then failed
    anyway is a different row from one that was accepted and then failed, and the record
    has to be able to hold both.
    """
    from cai.action import OutcomeType

    envelope = envelope_along(path_name, outcome_type=OutcomeType(outcome_type))
    text = envelope.canonical_json()

    rebuilt = parse_envelope(text)

    assert rebuilt.canonical_json() == text
    assert rebuilt.outcome.outcome_type is OutcomeType(outcome_type)
    assert rebuilt.lifecycle_events[-2].state.value == (
        DISPOSITION_PATHS[path_name][-2][0]
    ), "the disposition that reached the outcome is not the one built"


def test_the_three_paths_really_are_three_different_trails():
    """The twin for the parametrisation itself.

    The defect being corrected here was a parametrised test whose cases were identical
    under the hood, so the parametrisation proved nothing. This asserts the cases differ
    -- which is the check whose absence let the old version pass for four waves.
    """
    trails = {
        name: tuple(e.state.value for e in envelope_along(name).lifecycle_events)
        for name in DISPOSITION_PATHS
    }
    assert len(set(trails.values())) == 3, trails
    assert "ACCEPTED" in trails["accepted"]
    assert "OVERRIDDEN" in trails["overridden"] and "ACCEPTED" not in trails["overridden"]
    assert "IGNORED" in trails["ignored"] and "ACKNOWLEDGED" not in trails["ignored"]


def test_a_trail_that_skips_a_required_state_is_still_refused():
    """The paths above are the LEGAL ones. Widening the fixture must not have widened
    the transition table with it -- an accepted recommendation cannot reach an observed
    outcome without the action being completed."""
    from cai.lifecycle import DispositionEvent, DispositionState, IllegalTransition

    product = T.deliver()
    with pytest.raises(IllegalTransition, match="not a permitted transition"):
        IntelligenceEnvelope(
            product=product,
            lifecycle_events=(
                DispositionEvent(DispositionState.DELIVERED, T.t(12, 7), "system"),
                DispositionEvent(DispositionState.ACKNOWLEDGED, T.t(12, 9), "ops"),
                DispositionEvent(DispositionState.ACCEPTED, T.t(12, 14), "ops"),
                DispositionEvent(DispositionState.OUTCOME_OBSERVED, T.t(13, 4), "ops"),
            ),
        )


def test_the_causal_boundary_holds_however_the_outcome_arrives():
    """`attributed_effect` has exactly one member and no code path sets another. Deleting
    the scalar outcome must not have opened a door to one."""
    from cai.lifecycle import AttributedEffect

    assert len(list(AttributedEffect)) == 1
    assert learned_envelope().attributed_effect is AttributedEffect.NOT_ESTABLISHED
    assert json.loads(learned_envelope().canonical_json())["attributed_effect"] == (
        "NOT_ESTABLISHED"
    )
