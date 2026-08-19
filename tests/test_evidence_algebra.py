"""Tests for the bounded evidence algebra.

The algebra is finite and small, so correctness here is established by *enumeration*
rather than by sampling. There are 4 x 2 x 2 x 3 x 3 x 3 = 432 reachable states, which
is cheap to walk exhaustively.

That is the honest form of the claim: proven over this bounded rule set, not for
arbitrary queries. A general result about incomplete-information semantics would be a
different and much larger undertaking, and is not attempted.
"""

from __future__ import annotations

import itertools

import pytest

from cai.evidence import (
    Completeness,
    EntitlementState,
    EvidenceAssessment,
    Identity,
    Integrity,
    Release,
    Support,
    TemporalEligibility,
    fully_satisfied,
)


def build(**overrides) -> EvidenceAssessment:
    base = dict(
        support=Support.SUPPORTED,
        completeness=Completeness.COMPLETE,
        integrity=Integrity.VALID,
        temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
        identity=Identity.RESOLVED,
        entitlement=EntitlementState.AUTHORIZED,
    )
    base.update(overrides)
    if base["completeness"] is Completeness.MISSING and "missing_evidence" not in base:
        base["missing_evidence"] = ("model_version",)
    if base["support"] is Support.CONFLICTED and "conflicts" not in base:
        base["conflicts"] = ("source-a vs source-b",)
    return EvidenceAssessment(**base)


# ---------------------------------------------------------------------------
# EXHAUSTIVE: the release predicate over the entire state space.
# ---------------------------------------------------------------------------


def test_release_predicate_holds_over_the_entire_state_space():
    """Exactly one combination releases; all 431 others withhold.

    This is the proof. Because the algebra is bounded, "we checked every case" is a
    literal statement rather than a figure of speech.
    """
    released = 0
    total = 0
    for combo in itertools.product(
        Support, Completeness, Integrity, TemporalEligibility, Identity, EntitlementState
    ):
        support, completeness, integrity, temporal, identity, entitlement = combo
        kwargs = dict(
            support=support,
            completeness=completeness,
            integrity=integrity,
            temporal_eligibility=temporal,
            identity=identity,
            entitlement=entitlement,
        )
        if completeness is Completeness.MISSING:
            kwargs["missing_evidence"] = ("x",)
        if support is Support.CONFLICTED:
            kwargs["conflicts"] = ("c",)
        assessment = EvidenceAssessment(**kwargs)
        total += 1
        if assessment.release_decision() is Release.RELEASE:
            released += 1
            # The only releasable state is the all-permitting one.
            assert support is Support.SUPPORTED
            assert completeness is Completeness.COMPLETE
            assert integrity is Integrity.VALID
            assert temporal is TemporalEligibility.ELIGIBLE_AS_OF_DECISION
            assert identity is Identity.RESOLVED
            assert entitlement is EntitlementState.AUTHORIZED

    assert total == 432, f"state space changed size: {total}"
    assert released == 1, f"expected exactly one releasable state, got {released}"


def test_the_permitting_state_actually_releases():
    """Non-triviality. Without this, 'withhold everything' passes the test above."""
    assert fully_satisfied().release_decision() is Release.RELEASE
    assert fully_satisfied().blocking_reasons() == ()


# ---------------------------------------------------------------------------
# Each dimension must be independently sufficient to block.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override, expected_fragment",
    [
        ({"support": Support.UNSUPPORTED}, "support=UNSUPPORTED"),
        ({"support": Support.REFUTED}, "support=REFUTED"),
        ({"support": Support.CONFLICTED}, "support=CONFLICTED"),
        ({"completeness": Completeness.MISSING}, "completeness=MISSING"),
        ({"integrity": Integrity.BROKEN}, "integrity=BROKEN"),
        ({"temporal_eligibility": TemporalEligibility.LATE}, "temporal_eligibility=LATE"),
        (
            {"temporal_eligibility": TemporalEligibility.OUTSIDE_VALID_WINDOW},
            "temporal_eligibility=OUTSIDE_VALID_WINDOW",
        ),
        ({"identity": Identity.AMBIGUOUS}, "identity=AMBIGUOUS"),
        ({"identity": Identity.CONFLICTED}, "identity=CONFLICTED"),
        ({"entitlement": EntitlementState.UNAUTHORIZED}, "entitlement=UNAUTHORIZED"),
        ({"entitlement": EntitlementState.UNKNOWN}, "entitlement=UNKNOWN"),
    ],
)
def test_each_dimension_blocks_independently_and_names_itself(
    override, expected_fragment
):
    """A blocked release must say which dimension blocked it.

    This is the whole reason for keeping six dimensions rather than one verdict: a
    rights refusal and a broken hash chain need different people to act.
    """
    assessment = build(**override)
    assert assessment.release_decision() is Release.WITHHOLD
    reasons = " ".join(assessment.blocking_reasons())
    assert expected_fragment in reasons


def test_unknown_entitlement_is_never_treated_as_permission():
    """An unrecorded right is not a right.

    Worth its own test because "we never checked" is the most tempting thing to treat
    as a soft pass, and it is the one most likely to matter in a dispute.
    """
    assert build(entitlement=EntitlementState.UNKNOWN).release_decision() is Release.WITHHOLD


def test_all_blocking_reasons_are_reported_not_just_the_first():
    """Fixing one blocker only to rediscover the next wastes a cycle each time."""
    assessment = build(
        support=Support.UNSUPPORTED,
        integrity=Integrity.BROKEN,
        entitlement=EntitlementState.UNAUTHORIZED,
    )
    reasons = assessment.blocking_reasons()
    assert len(reasons) >= 3
    joined = " ".join(reasons)
    assert "support=" in joined and "integrity=" in joined and "entitlement=" in joined


# ---------------------------------------------------------------------------
# The representations must not drift apart.
# ---------------------------------------------------------------------------


def test_missing_without_naming_what_is_missing_is_rejected():
    with pytest.raises(ValueError, match="requires naming"):
        EvidenceAssessment(
            support=Support.SUPPORTED,
            completeness=Completeness.MISSING,
            integrity=Integrity.VALID,
            temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
            identity=Identity.RESOLVED,
            entitlement=EntitlementState.AUTHORIZED,
        )


def test_complete_with_a_missing_list_is_rejected():
    with pytest.raises(ValueError, match="contradicts"):
        EvidenceAssessment(
            support=Support.SUPPORTED,
            completeness=Completeness.COMPLETE,
            integrity=Integrity.VALID,
            temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
            identity=Identity.RESOLVED,
            entitlement=EntitlementState.AUTHORIZED,
            missing_evidence=("model_version",),
        )


def test_conflicted_without_naming_conflicts_is_rejected():
    with pytest.raises(ValueError, match="requires naming"):
        EvidenceAssessment(
            support=Support.CONFLICTED,
            completeness=Completeness.COMPLETE,
            integrity=Integrity.VALID,
            temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
            identity=Identity.RESOLVED,
            entitlement=EntitlementState.AUTHORIZED,
        )


def test_record_is_exportable_and_complete():
    """The record must carry every dimension -- it has to survive leaving the system."""
    record = build(entitlement=EntitlementState.UNAUTHORIZED).as_record()
    for key in (
        "support",
        "completeness",
        "integrity",
        "temporal_eligibility",
        "identity",
        "entitlement",
        "release",
        "blocking_reasons",
    ):
        assert key in record
    assert record["release"] == "WITHHOLD"


def test_conflicted_support_is_distinct_from_unsupported():
    """Evidence on both sides is a worse position than no evidence, and must look it."""
    conflicted = build(support=Support.CONFLICTED)
    unsupported = build(support=Support.UNSUPPORTED)
    assert conflicted.conflicts, "CONFLICTED must carry its conflicts"
    assert not unsupported.conflicts
    assert conflicted.as_record()["support"] != unsupported.as_record()["support"]


def test_the_wire_blocking_reasons_must_be_the_reasons_the_dimensions_produce():
    """The `release` half of the derived-value comparison was guarded by a mutant; the
    reasons half was not, so a record could name a different set of blockers than its own
    dimensions imply and be accepted."""
    import pytest

    from cai.evidence import EvidenceAssessment

    withheld = EvidenceAssessment(
        support=Support.UNSUPPORTED,
        completeness=Completeness.COMPLETE,
        integrity=Integrity.VALID,
        temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
        identity=Identity.RESOLVED,
        entitlement=EntitlementState.AUTHORIZED,
    )
    record = withheld.as_record()
    record["blocking_reasons"] = ["entitlement=UNAUTHORIZED"]
    with pytest.raises(ValueError, match="not the reasons its dimensions produce"):
        EvidenceAssessment.from_record(record)


def test_an_honest_assessment_round_trips():
    """Non-triviality twin for both derived-value comparisons."""
    from cai.evidence import EvidenceAssessment, fully_satisfied

    original = fully_satisfied()
    assert EvidenceAssessment.from_record(original.as_record()) == original
