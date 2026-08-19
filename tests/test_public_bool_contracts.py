"""Every public method declared `-> bool` must return an actual bool, both ways.

WHY THIS FILE EXISTS
--------------------
The source-derived mutation gate reported sixteen declared-equivalent survivors, and
two of them were declarations that `return False -> return None` is unobservable. The
reasoning was that every CURRENT caller consumes the result in a boolean context, where
False and None are the same answer.

That reasoning is about callers, not about the contract. These are importable methods
whose annotation says `bool`, and this package had already accepted -- when six deleted
names had to be restored -- that module-level importability is what makes something
public. A reader who writes

    assert entitlement.permits(...) is False

is using the declared API, and the mutant breaks them. False and None are both falsy;
they are not the same value, and a test suite that cannot tell them apart is not
asserting the contract the annotation states.

So the declarations are gone and the mutants are killed properly. `is True` / `is False`
throughout, deliberately -- `assert x` and `assert not x` would pass against the mutant
and leave this file as decoration.

WHAT IS NOT HERE
----------------
Private predicates whose only contract is truthiness. Writing `is False` tests for those
would pin an implementation detail and produce exactly the meaningless test this file is
arguing against.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import test_formation as T


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


TICK = timedelta(microseconds=1)


# --- the two the equivalence ledger wrongly excused ------------------------


def test_permits_returns_a_real_bool_in_both_directions():
    """`EntitlementAssertion.permits` is the clearance check. Its answer is the reason
    a delivery happens or does not, and the annotation says bool."""
    entitlement = T.entitlement()
    scope = dict(
        recipient="operations@customer", purpose="operational-advisory",
        subject="asset-4417/battery-pack", tenant="tenant-1",
        source_systems=T.CONSUMED_SOURCES, at=t(12, 7),
    )

    assert entitlement.permits(**scope) is True
    assert entitlement.permits(**{**scope, "tenant": "tenant-2"}) is False
    assert entitlement.permits(**{**scope, "recipient": "someone-else"}) is False


def test_covers_and_fitted_at_return_real_bools_at_their_boundaries():
    """The two graph predicates the portable derivation now delegates to. Both ends of
    the half-open interval, and the value as well as its truthiness."""
    from cai.context import Assignment, Component
    from cai.derivation import holds_at

    assignment = Assignment("asset-4417", "zone-3", t(8), t(8, 1),
                            source_system="yard", valid_to=t(13, 5))
    assert assignment.covers(t(12)) is True
    assert assignment.covers(t(13, 5)) is False, "valid_to is exclusive"
    assert assignment.covers(t(13, 5) - TICK) is True
    assert assignment.covers(t(7)) is False

    component = Component("battery-pack-1", "asset-4417", "battery-pack", t(8, 1),
                          source_system="asset-register",
                          installed_from=t(1), removed_at=t(13, 5))
    assert component.fitted_at(t(12)) is True
    assert component.fitted_at(t(13, 5)) is False
    assert component.fitted_at(t(1) - TICK) is False

    # And the one implementation both delegate to, including the doubly-open case that
    # `fitted_at` relies on meaning "always fitted".
    assert holds_at(valid_from=None, valid_to=None, moment=t(12)) is True
    assert holds_at(valid_from=t(13), valid_to=None, moment=t(12)) is False
    assert holds_at(valid_from=None, valid_to=t(13), moment=t(12)) is True


# --- and the rest of the declared-bool surface ----------------------------


def test_the_model_envelope_admission_predicates_return_real_bools():
    from cai.predictor import declared_envelope

    envelope = declared_envelope()
    metric, subject_type = (
        envelope.supported_applicability[0].metric,
        envelope.supported_applicability[0].subject_type,
    )
    assert envelope.admits_metric(metric) is True
    assert envelope.admits_metric("tyre_pressure_kpa") is False
    assert envelope.admits_subject_type(subject_type) is True
    assert envelope.admits_subject_type("crane/hoist") is False
    assert envelope.admits_pair(metric, subject_type) is True
    assert envelope.admits_pair(metric, "crane/hoist") is False
    assert envelope.admits_horizon(1) is True
    assert envelope.admits_horizon(envelope.max_horizon_seconds + 1) is False


def test_the_interval_predicates_return_real_bools():
    from cai.decision import TimeInterval

    window = TimeInterval(t(12, 7), t(15, 7))
    assert window.contains(t(13)) is True
    assert window.contains(t(15, 7)) is False, "half-open at the end"
    assert window.contains(t(12, 7)) is True, "closed at the start"
    assert window.overlaps(TimeInterval(t(14), t(16))) is True
    assert window.overlaps(TimeInterval(t(15, 7), t(16))) is False


def test_the_observation_clock_predicates_return_real_bools():
    from cai.bitemporal import Observation

    on_time = Observation("a-1", "asset-4417", "battery_temp_c", 41.0,
                          valid_time=t(10), transaction_time=t(10, 1),
                          source_system="source-a")
    assert on_time.is_late(timedelta(days=5)) is False
    assert on_time.is_late(timedelta(minutes=30)) is True
    assert on_time.has_implausible_clock() is False

    skewed = Observation("a-2", "asset-4417", "battery_temp_c", 41.0,
                         valid_time=t(20), transaction_time=t(10, 1),
                         source_system="source-a")
    assert skewed.has_implausible_clock() is True


def test_record_returns_a_real_bool_for_a_first_delivery_and_a_redelivery():
    """`ObservationLog.record` answers "was this new", and at-least-once delivery makes
    the False case ordinary traffic rather than an error path."""
    from cai.bitemporal import Observation, ObservationLog

    log = ObservationLog()
    reading = Observation("a-1", "asset-4417", "battery_temp_c", 41.0,
                          valid_time=t(10), transaction_time=t(10, 1),
                          source_system="source-a")
    assert log.record(reading) is True
    assert log.record(reading) is False


def test_known_at_and_was_known_at_return_real_bools():
    from cai.context import Assignment, known_at

    assignment = Assignment("asset-4417", "zone-3", t(8), t(8, 1), source_system="yard")
    assert assignment.was_known_at(t(8, 1)) is True, "inclusive at the instant"
    assert assignment.was_known_at(t(8, 1) - TICK) is False
    assert known_at(assignment, t(9)) is True
    assert known_at(assignment, t(7)) is False


def test_the_loading_window_overlap_returns_a_real_bool():
    from cai.context import LoadingWindow

    window = LoadingWindow("win-9", "zone-3", t(13, 5), t(13, 11), "ship-22",
                           recorded_at=t(9), source_system="dock-scheduler")
    assert window.overlaps(t(12, 7), t(15, 7)) is True
    assert window.overlaps(t(13, 11), t(15, 7)) is False
    assert window.overlaps(t(10), t(13, 5)) is False


def test_the_consequence_actionability_predicates_return_real_bools():
    """Two implementations, and the DOWNTIME one has a real threshold under it."""
    from cai.consequence import DowntimeConsequence
    from cai.decision import TimeInterval

    product = T.deliver()
    assert product.candidate.business_consequence.is_actionable() is True

    walk = product.candidate.business_consequence.derivation
    window = TimeInterval(t(13, 5), t(13, 11))
    below = DowntimeConsequence("DOWNTIME", window, walk, asset_id=walk.root_entity,
                                expected_hours_lost=0.5, affected_operation="loading")
    at_the_line = DowntimeConsequence("DOWNTIME", window, walk, asset_id=walk.root_entity,
                                      expected_hours_lost=1.0,
                                      affected_operation="loading")
    assert below.is_actionable() is False
    assert at_the_line.is_actionable() is True


def test_the_snapshot_and_lifecycle_predicates_return_real_bools():
    from cai.contract import EvidenceStatus, Reconstruction
    from cai.lifecycle import DispositionState, ProductLifecycle

    product = T.deliver()
    assert product.evidence.is_complete() is True

    lifecycle = ProductLifecycle(product_subject="asset-4417/battery-pack")
    lifecycle.advance(DispositionState.DELIVERED, at=t(12, 7), actor="system")
    assert lifecycle.is_closed() is False
    for state, hour in ((DispositionState.ACKNOWLEDGED, 8),
                        (DispositionState.ACCEPTED, 9),
                        (DispositionState.ACTION_COMPLETED, 14),
                        (DispositionState.OUTCOME_OBSERVED, 20)):
        lifecycle.advance(state, at=t(12, 7) + timedelta(hours=hour), actor="ops")
    assert lifecycle.is_closed() is True

    reachable = Reconstruction(EvidenceStatus.RECONSTRUCTABLE, (),
                               "asset-4417/battery-pack")
    gone = Reconstruction(EvidenceStatus.NOT_RECONSTRUCTABLE, ("observations",),
                          "asset-4417/battery-pack")
    assert reachable.is_reconstructable() is True
    assert gone.is_reconstructable() is False


def test_replayability_and_full_verification_return_real_bools():
    import json

    from cai.binding import claim_is_replayable_here
    from cai.envelope import IntelligenceEnvelope, import_historical_envelope

    product = T.deliver()
    assert claim_is_replayable_here(product.candidate.prediction_claim) is True

    payload = json.loads(IntelligenceEnvelope(product=product).canonical_json())
    report = import_historical_envelope(payload).verification_report
    assert report.fully_verified() is True

    # AND THE FALSE CASE, which nothing asserted.
    #
    # The corrected mutation gate found this: `return not self.unverifiable()` replaced
    # by `return True` survived the whole suite. Every test that read this method read it
    # on an honest record, so the method could have been a constant. That is the exact
    # shape of gap the return-direction correction was made to expose, found on the
    # first run of the corrected tool.
    claim = payload["product"]["candidate"]["prediction_claim"]
    claim["model_artifact_digest"] = "b" * 64
    claim["declared_envelope"]["model_artifact_digest"] = "b" * 64
    foreign = import_historical_envelope(payload).verification_report

    assert foreign.fully_verified() is False
    assert foreign.unverifiable() != ()


def test_every_public_bool_returning_callable_is_covered_here():
    """The sweep that stops this file going stale.

    A new public predicate added tomorrow gets no `is True`/`is False` test unless
    somebody remembers -- and its mutants would then survive and be declared equivalent
    on the same reasoning that was just rejected. So the list is derived, not written.
    """
    import ast
    import pathlib

    declared: set[str] = set()
    for path in sorted(pathlib.Path("src/cai").glob("*.py")):
        tree = ast.parse(path.read_text())

        def walk(node, scope: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{scope}.{child.name}" if scope else child.name
                    returns = child.returns
                    is_bool = (
                        isinstance(returns, ast.Name) and returns.id == "bool"
                    ) or (
                        isinstance(returns, ast.Constant) and returns.value == "bool"
                    )
                    if is_bool and not any(
                        part.startswith("_") for part in qualified.split(".")
                    ):
                        declared.add(qualified)
                    walk(child, qualified)
                elif isinstance(child, ast.ClassDef):
                    walk(child, f"{scope}.{child.name}" if scope else child.name)

        walk(tree, "")

    source = pathlib.Path(__file__).read_text()
    uncovered = sorted(
        name for name in declared if name.rsplit(".", 1)[-1] + "(" not in source
    )
    assert uncovered == [], (
        f"public bool-returning callables with no `is True`/`is False` test: {uncovered}"
    )
