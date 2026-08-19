"""Tests for the bitemporal record.

The case that matters most is `test_reconstruction_must_not_benefit_from_hindsight`.
Everything else here supports it.

A reviewer with telematics experience will check exactly one thing first: whether a
90-day reconstruction can distinguish evidence that was available at decision time
from evidence that arrived afterwards. If it cannot, the reconstruction flatters the
decision-maker and misleads the investigator, and no amount of provenance elsewhere
repairs that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cai.bitemporal import Observation, ObservationLog


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def obs(
    oid: str,
    *,
    valid: datetime,
    txn: datetime,
    subject: str = "asset-4417",
    value: float = 1.0,
    source: str = "source-a",
) -> Observation:
    return Observation(
        observation_id=oid,
        subject=subject,
        metric="battery_temp_c",
        value=value,
        valid_time=valid,
        transaction_time=txn,
        source_system=source,
    )


def test_valid_time_and_transaction_time_are_independent():
    """The two clocks must not be conflated -- the whole module rests on this."""
    o = obs("o1", valid=t(10), txn=t(19))
    assert o.valid_time != o.transaction_time
    assert o.arrival_lag() == timedelta(days=9)
    assert o.is_late(timedelta(days=1))
    assert not o.is_late(timedelta(days=30))


def test_store_and_forward_backlog_is_ordinary_traffic():
    """A device out of coverage for a week delivers a burst on reconnect."""
    log = ObservationLog()
    reconnect = t(17, 8)
    for day in range(10, 17):
        assert log.record(obs(f"o{day}", valid=t(day), txn=reconnect))
    assert len(log) == 7
    # Nothing was known before the reconnect, despite the events being days old.
    assert log.decision_time_view(transaction_time=t(16)) == ()
    assert len(log.decision_time_view(transaction_time=reconnect)) == 7


def test_at_least_once_delivery_is_reported_not_raised():
    """Duplicates are normal in this transport and must not crash ingestion."""
    log = ObservationLog()
    o = obs("dup", valid=t(10), txn=t(11))
    assert log.record(o) is True
    assert log.record(o) is False, "duplicate should be reported, not accepted"
    assert len(log) == 1


def test_decision_time_view_excludes_late_arrivals():
    """The core distinction. Late evidence was not available, so it is excluded."""
    log = ObservationLog()
    log.record(obs("early", valid=t(10), txn=t(10, 1)))
    log.record(obs("late", valid=t(11), txn=t(20)))  # about day 11, arrived day 20

    known_on_day_12 = log.decision_time_view(transaction_time=t(12))
    ids = {o.observation_id for o in known_on_day_12}
    assert ids == {"early"}, "an observation that had not arrived was treated as known"


def test_current_best_known_view_includes_late_arrivals():
    """The retrospective view is a different, also-valid question."""
    log = ObservationLog()
    log.record(obs("early", valid=t(10), txn=t(10, 1)))
    log.record(obs("late", valid=t(11), txn=t(20)))

    believed_about_day_12 = log.current_best_known_view(valid_time=t(12))
    ids = {o.observation_id for o in believed_about_day_12}
    assert ids == {"early", "late"}


def test_the_two_views_genuinely_differ():
    """Non-triviality: if these ever return the same thing, the model is decorative."""
    log = ObservationLog()
    log.record(obs("early", valid=t(10), txn=t(10, 1)))
    log.record(obs("late", valid=t(11), txn=t(20)))

    known = log.decision_time_view(transaction_time=t(12))
    believed = log.current_best_known_view(valid_time=t(12))
    assert known != believed, "bitemporal model collapsed to a single timeline"


def test_reconstruction_must_not_benefit_from_hindsight():
    """A decision is judged on what was available when it was made.

    A recommendation is issued on day 12. On day 20, a reading about day 11 finally
    arrives. Any reconstruction that quietly folds that reading into the day-12
    picture makes the decision look better informed than it was.
    """
    log = ObservationLog()
    log.record(obs("seen", valid=t(10), txn=t(10, 1)))
    log.record(obs("arrived-later", valid=t(11), txn=t(20)))

    model_decision_time = t(12)
    gap = log.knowledge_gap(knowledge_cutoff=model_decision_time, subject="asset-4417")

    assert len(gap) == 1
    assert gap[0].observation_id == "arrived-later"
    # And the decision-time view must not contain it.
    at_decision = {
        o.observation_id
        for o in log.decision_time_view(transaction_time=model_decision_time)
    }
    assert "arrived-later" not in at_decision


def test_no_knowledge_gap_when_everything_arrived_on_time():
    """Anti-conservatism: the gap must be empty when it should be.

    Without this, `knowledge_gap` returning everything always would pass the test
    above -- the same vacuous-stub failure caught elsewhere in this suite.
    """
    log = ObservationLog()
    log.record(obs("a", valid=t(10), txn=t(10, 1)))
    log.record(obs("b", valid=t(11), txn=t(11, 1)))

    gap = log.knowledge_gap(knowledge_cutoff=t(12), subject="asset-4417")
    assert gap == (), "reported a knowledge gap where none existed"


def test_clock_skew_is_detectable():
    """A device claiming an event that had not yet happened on arrival.

    Not a paradox -- a skewed RTC. It matters because such a reading can otherwise
    slip into a knowledge window it does not belong to.
    """
    skewed = obs("skew", valid=t(15), txn=t(14))
    assert skewed.has_implausible_clock()
    assert not obs("ok", valid=t(14), txn=t(15)).has_implausible_clock()


def test_late_arrivals_about_a_closed_window_are_identifiable():
    """Which readings arrived after the window they describe had already closed."""
    log = ObservationLog()
    log.record(obs("inside", valid=t(10), txn=t(10, 2)))
    log.record(obs("straggler", valid=t(10), txn=t(25)))

    stragglers = log.late_arrivals(
        since=t(9), until=t(11), threshold=timedelta(days=1)
    )
    assert {o.observation_id for o in stragglers} == {"straggler"}


def test_subject_filter_does_not_leak_across_assets():
    """Multi-tenant and multi-asset hygiene, checked rather than assumed."""
    log = ObservationLog()
    log.record(obs("a1", valid=t(10), txn=t(10, 1), subject="asset-1"))
    log.record(obs("b1", valid=t(10), txn=t(10, 1), subject="asset-2"))

    only_a = log.decision_time_view(transaction_time=t(11), subject="asset-1")
    assert {o.observation_id for o in only_a} == {"a1"}


@pytest.mark.parametrize("lag_days", [0, 1, 7, 30, 90])
def test_arrival_lag_is_computed_across_realistic_ranges(lag_days):
    """Yard assets can be offline for a long time; the model must not assume hours."""
    o = obs("x", valid=t(1), txn=t(1) + timedelta(days=lag_days))
    assert o.arrival_lag() == timedelta(days=lag_days)


# ---------------------------------------------------------------------------
# INTEGRITY AND SKEW. Added after an audit found same-id-different-payload was
# silently discarded and skewed clocks leaked into the decision-time view.
# ---------------------------------------------------------------------------


def test_identical_redelivery_is_idempotent_and_not_a_conflict():
    """At-least-once delivery: an exact retry is ordinary traffic."""
    log = ObservationLog()
    o = obs("dup", valid=t(10), txn=t(11))
    assert log.record(o) is True
    assert log.record(obs("dup", valid=t(10), txn=t(11))) is False
    assert len(log) == 1
    assert log.integrity_conflicts() == ()


def test_same_id_different_payload_is_an_integrity_conflict():
    """The defect: two sources disagreeing was recorded as an ordinary retry.

    Deduplicating on the identifier alone kept the first version and never mentioned
    that the second disagreed. That is data loss disguised as idempotency.
    """
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(11), value=41.0))
    assert log.record(obs("a-1", valid=t(10), txn=t(11), value=88.0)) is False
    conflicts = log.integrity_conflicts()
    assert len(conflicts) == 1
    kept, rejected = conflicts[0]
    assert kept.value == 41.0 and rejected.value == 88.0
    assert len(log) == 1, "an append-only log must not rewrite the reading it kept"


def test_a_skewed_reading_does_not_enter_the_point_in_time_view():
    """Received before the decision, describing an event that had not happened.

    decision_time_view filters on arrival alone, so this reading passes it. The
    point-in-time view is the one a prediction should be computed from.
    """
    log = ObservationLog()
    log.record(obs("ok", valid=t(10), txn=t(10, 1)))
    # valid_time is inside the window and BEFORE the cutoff, so the ordinary filters
    # admit it. Only the two clocks contradicting each other -- claimed on day 11,
    # received on day 10 -- reveals the skew. A fixture dated past the cutoff would be
    # excluded for the wrong reason and the guard would go untested.
    log.record(obs("skewed", valid=t(11), txn=t(10)))

    arrived = {o.observation_id for o in log.decision_time_view(transaction_time=t(12))}
    usable = {
        o.observation_id for o in log.point_in_time_view(knowledge_cutoff=t(12))
    }
    assert "skewed" in arrived, "fixture no longer exercises the gap"
    assert usable == {"ok"}
    excluded = log.excluded_for_clock_skew(knowledge_cutoff=t(12))
    assert {o.observation_id for o in excluded} == {"skewed"}


def test_the_point_in_time_view_still_returns_good_evidence():
    """Non-triviality twin: it must filter, not refuse."""
    log = ObservationLog()
    for day in range(8, 12):
        log.record(obs(f"a-{day}", valid=t(day), txn=t(day, 1)))
    usable = log.point_in_time_view(knowledge_cutoff=t(12))
    assert len(usable) == 4


# ---------------------------------------------------------------------------
# RESTORED from test_integration_chain.py. See the note in test_context.py --
# the ledger claimed these were covered here and the mutation harness proved otherwise.
# ---------------------------------------------------------------------------


def test_substituting_a_reading_changes_the_evidence_digest():
    """Same id, different value. Pointers still resolve and the record still verifies,
    so without a digest over the evidence itself the reconstruction confidently
    describes a reading that no longer exists."""
    from cai.bitemporal import digest_observations

    original = (obs("a-1", valid=t(10), txn=t(11), value=41.0),
                obs("a-2", valid=t(11), txn=t(12), value=45.6))
    tampered = (obs("a-1", valid=t(10), txn=t(11), value=41.0),
                obs("a-2", valid=t(11), txn=t(12), value=12.0))
    assert digest_observations(original) != digest_observations(tampered)


def test_the_evidence_digest_ignores_storage_order():
    """Non-triviality twin: a digest that changes on everything compares nothing."""
    from cai.bitemporal import digest_observations

    a = obs("a-1", valid=t(10), txn=t(11), value=41.0)
    b = obs("a-2", valid=t(11), txn=t(12), value=45.6)
    assert digest_observations((a, b)) == digest_observations((b, a))


def test_the_retrospective_view_honours_supersession():
    """A correction and the reading it corrects must not both be current."""
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(11), value=41.0))
    log.record(Observation("a-1-rev2", "asset-4417", "battery_temp_c", 44.5,
                           t(10), t(12), "source-a", supersedes="a-1"))
    believed = log.current_best_known_view(valid_time=t(20))
    assert {o.observation_id for o in believed} == {"a-1-rev2"}
    assert len(log) == 2, "an evidence log must not delete what it superseded"


def test_the_decision_time_view_honours_supersession_known_by_then():
    """A correction already known at decision time supersedes; one arriving later
    must not reach back and rewrite the decision."""
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(11), value=41.0))
    log.record(Observation("a-1-rev2", "asset-4417", "battery_temp_c", 44.5,
                           t(10), t(12), "source-a", supersedes="a-1"))
    early = log.point_in_time_view(knowledge_cutoff=t(13), subject="asset-4417")
    assert {o.observation_id for o in early} == {"a-1-rev2"}

    late = ObservationLog()
    late.record(obs("a-1", valid=t(10), txn=t(11), value=41.0))
    late.record(Observation("a-1-rev2", "asset-4417", "battery_temp_c", 44.5,
                            t(10), t(25), "source-a", supersedes="a-1"))
    assert {o.observation_id for o in
            late.point_in_time_view(knowledge_cutoff=t(13), subject="asset-4417")} == {"a-1"}


def test_a_non_canonicalizable_number_is_refused_rather_than_approximated():
    """NaN and the infinities have no canonical JSON form, and a canonicalizer that
    emitted something for them would produce bytes another implementation cannot
    reproduce -- which is the one property the digest depends on."""
    import math

    import pytest

    from cai.canonical import NotCanonicalizable, canonicalize

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(NotCanonicalizable, match="no canonical JSON form"):
            canonicalize({"score": value})


# ===========================================================================
# A LATE CONFLICT MUST NOT REWRITE A DECISION THAT WAS HONEST WHEN IT WAS TAKEN.
#
# `point_in_time_view` filtered the readings on transaction time from the start.
# The conflicts attached to those readings went through no such filter -- the only
# test was whether the KEPT id was among the returned observations -- so a
# contradicting redelivery arriving on the 14th became part of the evidence for a
# decision taken on the 12th, and integrity went BROKEN two days after the fact.
#
# That is the hindsight this whole module exists to refuse, running backwards. The
# rejected reading carries its own transaction_time; a conflict belongs to a
# historical decision only if it had arrived by that decision's cutoff.
# ===========================================================================


TICK = timedelta(microseconds=1)
CUTOFF = t(12, 7)


def log_with_conflict_arriving_at(moment: datetime) -> ObservationLog:
    """One reading, and a second source disagreeing about it, landing at `moment`."""
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(10, 1), value=41.0))
    log.record(obs("a-1", valid=t(10), txn=moment, value=999.9, source="source-b"))
    return log


def conflicts_at(log: ObservationLog, cutoff: datetime) -> tuple[str, ...]:
    return log.evidence_for(knowledge_cutoff=cutoff, evaluation_time=cutoff)\
        .conflict_descriptions()


def test_a_conflict_that_had_arrived_before_the_cutoff_is_carried():
    """The twin. A filter that dropped everything would pass every test below it."""
    log = log_with_conflict_arriving_at(CUTOFF - TICK)

    assert len(conflicts_at(log, CUTOFF)) == 1


def test_a_conflict_arriving_exactly_at_the_cutoff_is_carried():
    """`transaction_time <= cutoff`, the same inclusive boundary `decision_time_view`
    uses for the readings themselves. Two clocks with different boundaries on one
    decision would be a bug nobody could find twice."""
    assert len(conflicts_at(log_with_conflict_arriving_at(CUTOFF), CUTOFF)) == 1


def test_a_conflict_arriving_a_microsecond_after_the_cutoff_is_not():
    """The defect, at its boundary. One microsecond on the wrong side of the cutoff and
    the decision-maker could not have known."""
    assert conflicts_at(log_with_conflict_arriving_at(CUTOFF + TICK), CUTOFF) == ()


def test_the_same_late_conflict_belongs_to_a_later_decision():
    """It is not deleted, and it is not a mistake -- it is simply not evidence about the
    12th. A decision taken on the 15th rests on a world that contains it.

    Without this the rule above could be satisfied by dropping every conflict, which is
    the failure mode that would make the whole integrity dimension decorative.
    """
    log = log_with_conflict_arriving_at(t(14))

    assert conflicts_at(log, CUTOFF) == ()
    assert len(conflicts_at(log, t(15, 7))) == 1
    assert len(log.integrity_conflicts()) == 1, "the log keeps it either way"


def test_reconstructing_a_past_decision_after_a_late_conflict_lands_is_unchanged():
    """The whole point, stated as the operation an investigator actually performs.

    Reconstruct the 12th before the 14th's redelivery exists, reconstruct it again
    afterwards, and compare. If those two differ, the record cannot defend a past
    decision -- which is the only thing it is for.
    """
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(10, 1), value=41.0))
    before = log.evidence_for(knowledge_cutoff=CUTOFF, evaluation_time=CUTOFF)

    log.record(obs("a-1", valid=t(10), txn=t(14), value=999.9, source="source-b"))
    after = log.evidence_for(knowledge_cutoff=CUTOFF, evaluation_time=CUTOFF)

    assert before.as_record() == after.as_record()


def test_a_late_conflict_does_not_break_the_integrity_of_a_past_decision():
    """The consequence in the dimension a reader actually looks at.

    The two tests above compare bundles. This one asks the question an operator asks:
    was this decision defensible on the evidence it had? A product that assessed
    integrity INTACT on the 12th must not re-assess as BROKEN because a second system
    finally sent its copy on the 14th.
    """
    log = ObservationLog()
    log.record(obs("a-1", valid=t(10), txn=t(10, 1), value=41.0))
    log.record(obs("a-1", valid=t(10), txn=t(14), value=999.9, source="source-b"))

    at_the_time = log.evidence_for(knowledge_cutoff=CUTOFF, evaluation_time=CUTOFF)
    today = log.evidence_for(knowledge_cutoff=t(15, 7), evaluation_time=t(15, 7))

    assert at_the_time.integrity_conflicts == ()
    assert today.integrity_conflicts != (), (
        "the disagreement is real and a decision taken today has to face it"
    )
