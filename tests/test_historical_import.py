"""Strict import, historical import, and the line between them.

THE DEFECT
----------
`import_envelope(payload, accept_unverifiable_basis=True)` returned the same ordinary
`IntelligenceEnvelope` that a fully verified import returned. A caller who passed the flag
-- or a helper three layers down that passed it on their behalf -- held an object
indistinguishable from one checked end to end. The fact that a verification had not
happened disappeared at the API boundary.

The single boolean also conflated two independent trust conditions. "I cannot replay this
model" and "I do not have this policy's thresholds" are different facts about different
parts of the record, and one flag could not say which -- so accepting an unreplayable
model silently accepted an unreproducible policy too.

THE LINE THIS FILE DEFENDS
--------------------------
    a check that RUNS and PASSES   ->  VERIFIED
    a check that RUNS and FAILS    ->  REFUSED, in both modes
    a check that CANNOT BE RUN     ->  UNVERIFIABLE(reason), refused by strict import,
                                       reported by the historical one

Every test here is one of those three, and the ones that matter most are the middle row:
a forged score, a forged score_semantics, a forged evidence_strength and an entitlement
violation are refused whichever door the reader came in by.
"""

from __future__ import annotations

import json

import pytest

import test_formation as T
from cai.envelope import (
    HistoricalEnvelopeImport,
    IntelligenceEnvelope,
    import_envelope,
    import_historical_envelope,
)
from cai.product import UnverifiableBasis
from cai.verification import (
    DimensionVerification,
    VerificationDimension,
    VerificationReport,
    VerificationState,
)

D = VerificationDimension


def wire(**over) -> dict:
    return json.loads(IntelligenceEnvelope(product=T.deliver(**over)).canonical_json())


def broken(mutate, **over) -> dict:
    payload = wire(**over)
    mutate(payload)
    return payload


def foreign_model(p) -> None:
    """A claim naming a predictor build this process does not have.

    Self-consistent: the declared envelope's digest moves with the claim's, so the claim's
    own `__post_init__` still passes and the record is refused for the reason it is
    actually unverifiable rather than for an incidental contradiction.
    """
    digest = "e" * 64
    claim = p["product"]["candidate"]["prediction_claim"]
    claim["model_artifact_digest"] = digest
    claim["declared_envelope"]["model_artifact_digest"] = digest


def foreign_policy(p) -> None:
    p["product"]["assurance"]["policy_id"] = "acme.house-rules"


# ---------------------------------------------------------------------------
# 1. STRICT IMPORT HAS NO WAIVER.
# ---------------------------------------------------------------------------


def test_strict_import_has_no_general_waiver_flag():
    """STRUCTURAL. A signature that cannot express the waiver is a better guarantee than
    a check that refuses to honour one."""
    import inspect

    params = inspect.signature(import_envelope).parameters
    assert "accept_unverifiable_basis" not in params
    assert [p.name for p in params.values()] == ["payload"], (
        "strict import takes a payload and nothing that could relax it"
    )
    from cai.product import IntelligenceProduct

    assert "accept_unverifiable_basis" not in inspect.signature(
        IntelligenceProduct.from_record
    ).parameters, "and the flag is not merely hidden one layer down"


def test_an_unknown_model_artifact_refuses_strict_import():
    with pytest.raises(UnverifiableBasis, match="not the build running here"):
        import_envelope(broken(foreign_model))


def test_an_unknown_policy_refuses_strict_import():
    with pytest.raises(UnverifiableBasis, match="thresholds this package does not have"):
        import_envelope(broken(foreign_policy))


def test_the_honest_record_still_imports_strictly():
    """Non-triviality twin. Without it every refusal above passes against an importer
    that refuses everything."""
    envelope = import_envelope(wire())
    assert envelope.product.determination.value == "DELIVERED"


# ---------------------------------------------------------------------------
# 2. THE HISTORICAL API ADMITS, AND SAYS WHAT IT COULD NOT CHECK.
# ---------------------------------------------------------------------------


def test_historical_import_admits_a_foreign_model_and_names_the_gap():
    read = import_historical_envelope(broken(foreign_model))

    assert isinstance(read, HistoricalEnvelopeImport)
    assert read.envelope.product.product_id == "ip-001"
    assert read.verification_report.state_of(D.CLAIM_REPLAY) is (
        VerificationState.UNVERIFIABLE
    )
    assert "not the build running here" in read.verification_report[D.CLAIM_REPLAY].reason


def test_historical_import_admits_a_foreign_policy_and_names_the_gap():
    read = import_historical_envelope(broken(foreign_policy))

    assert read.verification_report.state_of(D.POLICY_REPLAY) is (
        VerificationState.UNVERIFIABLE
    )
    assert "acme.house-rules" in read.verification_report[D.POLICY_REPLAY].reason


def test_a_known_model_with_an_unknown_policy_still_reports_the_replay_verified():
    """The two conditions are independent, which one boolean could not express.

    This is the test that would have caught the conflation: a reader accepting an
    unreproducible policy used to accept an unreplayable model in the same breath.
    """
    report = import_historical_envelope(broken(foreign_policy)).verification_report

    assert report.state_of(D.CLAIM_REPLAY) is VerificationState.VERIFIED
    assert report.state_of(D.POLICY_REPLAY) is VerificationState.UNVERIFIABLE


def test_an_unknown_model_with_a_known_policy_still_reports_the_policy_verified():
    report = import_historical_envelope(broken(foreign_model)).verification_report

    assert report.state_of(D.POLICY_REPLAY) is VerificationState.VERIFIED
    assert report.state_of(D.CLAIM_REPLAY) is VerificationState.UNVERIFIABLE


def test_both_unknown_reports_both_and_the_rest_verified():
    def mutate(p):
        foreign_model(p)
        foreign_policy(p)

    report = import_historical_envelope(broken(mutate)).verification_report

    assert report.state_of(D.CLAIM_REPLAY) is VerificationState.UNVERIFIABLE
    assert report.state_of(D.POLICY_REPLAY) is VerificationState.UNVERIFIABLE
    for dimension in (D.STRUCTURAL_CONFORMANCE, D.EVIDENCE_RECONSTRUCTION,
                      D.ENTITLEMENT_SCOPE, D.RENDERED_ARTIFACT, D.LIFECYCLE):
        assert report.state_of(dimension) is VerificationState.VERIFIED, dimension


def test_an_honest_record_reports_every_dimension_verified():
    read = import_historical_envelope(wire())

    assert read.verification_report.fully_verified()
    assert not read.verification_report.unverifiable()
    assert len(read.verification_report.dimensions) == len(D)


def test_a_foreign_renderer_is_reported_rather_than_treated_as_a_forgery():
    """`RenderedDelivery.render` always stamps THIS build's renderer version, so a card
    produced by another renderer could never reproduce here.

    Refusing it read as "this record is forged" when the honest reading is "this record
    was rendered by software I do not have" -- the same mistake the claim replay made
    before it was separated out, on a different field.
    """
    def mutate(p):
        card = p["product"]["rendered_delivery"]
        card["renderer_version"] = "acme.renderer@9.9.9"
        card["content_digest"] = _restamped_card_digest(card)

    read = import_historical_envelope(broken(mutate))
    assert read.verification_report.state_of(D.RENDERED_ARTIFACT) is (
        VerificationState.UNVERIFIABLE
    )
    with pytest.raises(UnverifiableBasis, match="renderer"):
        import_envelope(broken(mutate))


def _restamped_card_digest(card: dict) -> str:
    """The digest the card's own content implies, so `RenderedDelivery.__post_init__`
    does not refuse it before the renderer-version branch is reached."""
    import hashlib
    from datetime import datetime

    from cai.canonical import canonicalize

    return hashlib.sha256(canonicalize({
        "renderer_version": card["renderer_version"],
        "locale": card["locale"],
        "rendered_text": card["rendered_text"],
        "card": dict(card["card"]),
        "rendered_at": datetime.fromisoformat(card["rendered_at"]).isoformat(),
    }).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 3. A FAILED CHECK IS NOT AN UNVERIFIABLE ONE. Both modes refuse.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,mutate,pattern", [
    (
        "forged score",
        lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
            "score", "0.990000"),
        "replays differently",
    ),
    (
        "forged score semantics",
        lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
            "score_semantics", "calibrated probability of real-world failure"),
        "replays differently",
    ),
    (
        "forged evidence strength",
        lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
            "evidence_strength", "0.990000"),
        "replays differently",
    ),
])
def test_a_replayable_forgery_refuses_in_both_modes(name, mutate, pattern):
    """The three fields the replay exists to bind, and the ones both independent audits
    reached DELIVERED by rewriting.

    `score_semantics` is the quiet one: leave the number alone and change what the number
    is said to MEAN, and every other signal stays green. "Relative degradation signal,
    ordering only" and "calibrated probability of real-world failure" are the same record
    with a different product sold off it.
    """
    with pytest.raises(ValueError, match=pattern):
        import_envelope(broken(mutate))
    with pytest.raises(ValueError, match=pattern):
        import_historical_envelope(broken(mutate))


@pytest.mark.parametrize("name,mutate", [
    ("unentitled recipient",
     lambda p: p["product"].__setitem__("recipient", "procurement@other-customer")),
    ("another tenant", lambda p: p["product"].__setitem__("tenant", "tenant-2")),
    ("another purpose", lambda p: p["product"].__setitem__("purpose", "benchmarking")),
])
def test_an_entitlement_violation_refuses_in_both_modes(name, mutate):
    """Rights are never waived. Not by a flag, not by a mode, not by naming a policy this
    package does not ship.

    The forger could not defeat this check, so they arranged for the branch that skipped
    it: the unknown-policy early return sat ABOVE the authorization, and `policy_id` is a
    free wire field. It is hoisted above that gate, and the gate is no longer a gate.
    """
    def with_foreign_policy(p):
        mutate(p)
        foreign_policy(p)

    for mutation in (mutate, with_foreign_policy):
        with pytest.raises(ValueError, match="does not authorise the delivery"):
            import_envelope(broken(mutation))
        with pytest.raises(ValueError, match="does not authorise the delivery"):
            import_historical_envelope(broken(mutation))


def test_the_entitlement_scope_dimension_can_never_be_unverifiable():
    """STRUCTURAL, and it is the executable form of "rights are never waived".

    Both halves of that comparison travel in full -- the clearance and the delivery it is
    supposed to authorise -- so there is no threshold to be missing and no build to be
    absent. "We could not check the rights question" is never an honest answer, and the
    only way to keep it that way is for no code path to be able to say it.
    """
    import ast
    import pathlib

    # AST rather than grep. A substring search matches the comment explaining why this
    # call is absent, which is the same false-positive trap `verify_package` documents.
    reported_unverifiable = set()
    for path in pathlib.Path("src/cai").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "unverifiable" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Attribute):
                reported_unverifiable.add(first.attr)
    assert reported_unverifiable, "the AST walk must actually find the reporting calls"
    assert "ENTITLEMENT_SCOPE" not in reported_unverifiable, (
        f"a code path can report the rights question as unverifiable: "
        f"{sorted(reported_unverifiable)}"
    )
    # And behaviourally, over a record with BOTH unverifiable bases: the dimension is
    # still reported verified, because it was still checked.
    def mutate(p):
        foreign_model(p)
        foreign_policy(p)

    report = import_historical_envelope(broken(mutate)).verification_report
    assert report.state_of(D.ENTITLEMENT_SCOPE) is VerificationState.VERIFIED


# ---------------------------------------------------------------------------
# 4. MALFORMED IS NOT UNVERIFIABLE.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("policy_id", ""),
    ("policy_version", ""),
    ("policy_digest", "not-a-digest"),
    ("policy_digest", ""),
])
def test_a_malformed_policy_identity_cannot_be_reclassified_as_unverifiable(field, value):
    """The most dangerous laundering available at this boundary.

    The importer branches on the policy identity: the policy this package ships gets its
    verdict recomputed, and any OTHER policy is reported as an unreproducible basis. A
    blank or malformed identifier must not be able to take the second branch -- "this
    record names no policy at all" would be reclassified as "this record names a policy I
    do not have", and a structurally broken record would be laundered into a merely
    unverifiable one that the historical API then admits.

    Refused by the schema on the wire and by `AssuranceDecision.__post_init__` in memory,
    so neither door is open.
    """
    payload = broken(lambda p: p["product"]["assurance"].__setitem__(field, value))
    for importer in (import_envelope, import_historical_envelope):
        with pytest.raises(ValueError) as caught:
            importer(payload)
        assert not isinstance(caught.value, UnverifiableBasis), (
            f"a malformed {field} was treated as merely unverifiable"
        )


@pytest.mark.parametrize("field,value,pattern", [
    ("policy_id", "", "names no rules at all"),
    ("policy_version", "", "names no rules at all"),
    ("policy_digest", "not-a-digest", "cannot be a policy digest"),
])
def test_a_malformed_policy_identity_is_refused_in_memory_too(field, value, pattern):
    """The in-memory twin of the case above.

    On the wire the schema refuses these by pattern. That is the right place for the wire
    to refuse them, and it would leave the DOMAIN rule proved only by the schema -- so a
    decision object could still be constructed in process naming no policy at all, and the
    branch that reclassifies an unknown policy as unverifiable would be reachable from
    inside. Two boundaries, two tests, one rule.
    """
    from cai.delivery import AssuranceDecision

    honest = T.deliver().assurance
    with pytest.raises(ValueError, match=pattern):
        AssuranceDecision(
            permitted=True,
            blocking_reasons=(),
            policy_id=value if field == "policy_id" else honest.policy_id,
            policy_version=value if field == "policy_version" else honest.policy_version,
            policy_digest=value if field == "policy_digest" else honest.policy_digest,
            assessed=honest.assessed,
            release_decision_time=honest.release_decision_time,
        )


def test_a_policy_digest_that_is_not_this_policys_refuses_in_both_modes():
    """Naming the rules everybody trusts while carrying a digest that is not theirs."""
    payload = broken(lambda p: p["product"]["assurance"].__setitem__(
        "policy_digest", "c" * 64))
    with pytest.raises(ValueError, match="carries a digest that is not that policy's"):
        import_envelope(payload)
    with pytest.raises(ValueError, match="carries a digest that is not that policy's"):
        import_historical_envelope(payload)


# ---------------------------------------------------------------------------
# 5. THE REPORT ITSELF. It is a value, and it refuses to be a vague one.
# ---------------------------------------------------------------------------


def test_a_report_that_says_nothing_about_a_dimension_cannot_exist():
    """A reader reads silence as "fine". Requiring the full set is what stops a dimension
    being quietly dropped by a code path that forgets it."""
    from cai.verification import verified

    with pytest.raises(ValueError, match="says nothing about"):
        VerificationReport(dimensions=(verified(D.LIFECYCLE),))


def test_a_report_cannot_answer_one_dimension_twice():
    from cai.verification import unverifiable, verified

    with pytest.raises(ValueError, match="more than once"):
        VerificationReport(dimensions=tuple(
            [verified(d) for d in D] + [unverifiable(D.LIFECYCLE, "why not")]
        ))


def test_an_unverifiable_dimension_must_say_why():
    """A reader told a check did not happen, and not why, cannot decide what to do about
    it -- which is the whole difference between this and the boolean it replaced."""
    with pytest.raises(ValueError, match="with no reason given"):
        DimensionVerification(D.CLAIM_REPLAY, VerificationState.UNVERIFIABLE)


def test_a_verified_dimension_cannot_carry_an_excuse():
    """The other direction, and it is not symmetry for its own sake: a reader skimming
    states would never see a caveat parked beside a VERIFIED."""
    with pytest.raises(ValueError, match="carries the reason"):
        DimensionVerification(D.CLAIM_REPLAY, VerificationState.VERIFIED, "mostly")


def test_the_report_is_not_stamped_into_the_historical_product():
    """It describes THIS reader on THIS build at THIS moment -- whether the predictor
    artifact happens to be present, whether this package ships the policy named. Welding
    that into an immutable historical record is the reconstruction-of-a-reconstruction
    this codebase names as its worst failure elsewhere.
    """
    read = import_historical_envelope(broken(foreign_model))

    assert "verification" not in json.dumps(read.envelope.as_record())
    assert not hasattr(read.envelope.product, "verification_report")
    # And the envelope a historical read returns is byte-identical to the payload, so a
    # record read historically today and strictly tomorrow is the same record.
    assert json.loads(read.envelope.canonical_json()) == broken(foreign_model)


# ===========================================================================
# THE `replay_claim` SEAM, CLOSED STRUCTURALLY RATHER THAN BY CONVENTION.
#
# The boundaries always chose it honestly -- release passed a literal True, import
# derived it from the record. That was checked here and it was not enough, because
# `assess_evidence` and `integrity_findings` were public module-level names WITH the
# boolean on their signature, and this package declares no surface, so every
# module-level name is importable. The project had already accepted exactly that
# reasoning once, when six deleted names had to be restored on it. Using the opposite
# standard for the seam would have been an argument rather than a rule.
#
# The implementations are now `_assess_evidence` / `_integrity_findings`. What is
# public is named for its boundary and decides replay by construction:
#
#     assess_release_evidence      replay is mandatory
#     assess_imported_evidence     replay derived from claim_is_replayable_here
#     imported_integrity_findings  same, for the named diagnostics
# ===========================================================================


def test_no_public_name_in_the_package_accepts_a_replay_argument():
    """STRUCTURAL, and swept over the WHOLE package rather than a list of five.

    The previous version of this test enumerated the five entry points a caller was
    expected to use, which proves nothing about the ones they might reach instead --
    and `assess_evidence(..., replay_claim=False)` was reachable the entire time it
    passed.

    So: every public callable in every module, and none of them may take this
    parameter or any other waiver. A function that wants the boolean has to be
    underscored, which is what makes "supported entry point" a fact about the code
    instead of a claim in a docstring.
    """
    import importlib
    import inspect
    import pkgutil

    import cai

    offenders = []
    for module in pkgutil.iter_modules(cai.__path__):
        mod = importlib.import_module(f"cai.{module.name}")
        for name, obj in vars(mod).items():
            if name.startswith("_") or getattr(obj, "__module__", None) != mod.__name__:
                continue
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            targets = [(name, obj)] if inspect.isfunction(obj) else [
                (f"{name}.{m}", f) for m, f in vars(obj).items()
                if inspect.isfunction(f) and not m.startswith("_")
            ]
            for label, fn in targets:
                try:
                    params = set(inspect.signature(fn).parameters)
                except (TypeError, ValueError):
                    continue
                waivers = params & {
                    "replay_claim", "skip_replay", "accept_unverifiable_basis",
                    "verify", "strict", "waive", "trust",
                }
                if waivers:
                    offenders.append(f"cai.{module.name}.{label}{sorted(waivers)}")

    assert offenders == [], (
        f"a public name exposes the verification seam: {offenders}"
    )


def test_the_wrappers_refuse_the_argument_smuggled_through_kwargs():
    """The rename alone would not have closed it.

    Both wrappers forward `**kwargs`, so `assess_release_evidence(replay_claim=False,
    ...)` reached the private implementation with two values for the argument -- which
    fails, but as a TypeError from a function the caller never named. That is an
    accident, and an accident is not an invariant. It is now refused by name.
    """
    from cai.assessment import (
        assess_imported_evidence,
        assess_release_evidence,
        imported_integrity_findings,
    )

    for entry in (assess_release_evidence, assess_imported_evidence,
                  imported_integrity_findings):
        with pytest.raises(TypeError, match="does not accept replay_claim"):
            entry(replay_claim=False)


def test_live_release_always_replays_and_cannot_be_told_not_to():
    """Release passes True unconditionally, and that is the correct asymmetry.

    A claim reaching release was produced moments earlier by this process, so one naming
    another build is incoherent THERE and must FAIL the replay rather than be excused from
    it. The import boundary is the only place where "this build cannot check that" is a
    real answer.
    """
    import ast
    import inspect

    from cai.formation import release

    tree = ast.parse(inspect.getsource(release))
    called = [
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id.startswith("assess_")
    ]
    assert called == ["assess_release_evidence"], (
        f"release must assess through the mandatory-replay entry point, not {called}"
    )
    # And that entry point has no way to be told otherwise -- checked here rather than
    # trusted, because the whole finding was that the honest call site was not the
    # invariant.
    from cai.assessment import assess_release_evidence

    assert "replay_claim" not in inspect.signature(assess_release_evidence).parameters
    assert "replay_claim=True" in inspect.getsource(assess_release_evidence)


def test_the_import_boundary_derives_the_flag_from_the_record_alone():
    """`claim_is_replayable_here` is a pure function of the claim's artifact digest and
    this build's. No caller input reaches it."""
    import inspect

    from cai.binding import claim_is_replayable_here
    from cai.product import IntelligenceProduct

    from cai.assessment import assess_imported_evidence, imported_integrity_findings

    assert list(inspect.signature(claim_is_replayable_here).parameters) == ["claim"]
    source = inspect.getsource(IntelligenceProduct._verify_the_assessment_follows_from_the_evidence)
    assert "assess_imported_evidence(" in source
    assert "replay_claim" not in source, (
        "the import boundary must not name the flag at all; the wrapper derives it"
    )
    for wrapper in (assess_imported_evidence, imported_integrity_findings):
        body = inspect.getsource(wrapper)
        assert "claim_is_replayable_here(kwargs[\"prediction_claim\"])" in body
        assert "replay_claim" not in inspect.signature(wrapper).parameters


def test_a_replayable_mismatch_is_a_failure_and_never_an_unverifiability():
    """The third proof, and the one that matters most.

    The seam must not become a route by which a claim this build CAN check gets reported
    as merely uncheckable. A forged score on a replayable record refuses in BOTH modes,
    and the historical report never carries an UNVERIFIABLE claim_replay for it.
    """
    forged = broken(lambda p: p["product"]["candidate"]["prediction_claim"].__setitem__(
        "score", "0.990000"))

    for importer in (import_envelope, import_historical_envelope):
        with pytest.raises(ValueError, match="replays differently"):
            importer(forged)


# ===========================================================================
# ITEM 6 — CT's CONDITION. Absent inputs may make the REPLAY dimension
# unverifiable and nothing else, and every check not needing those inputs must
# still run.
# ===========================================================================


def inputless(**over) -> dict:
    from cai.contract import EvidenceSnapshot

    snapshot = EvidenceSnapshot(**{
        **T.evidence(T.claim()).__dict__, "prediction_inputs": None})
    return broken(over.pop("mutate", lambda p: None),
                  evidence=snapshot, **over)


def test_absent_inputs_make_only_the_replay_dimension_unverifiable():
    read = import_historical_envelope(inputless())

    assert read.verification_report.state_of(D.CLAIM_REPLAY) is (
        VerificationState.UNVERIFIABLE)
    for dimension in (D.STRUCTURAL_CONFORMANCE, D.EVIDENCE_RECONSTRUCTION,
                      D.POLICY_REPLAY, D.ENTITLEMENT_SCOPE, D.RENDERED_ARTIFACT,
                      D.LIFECYCLE):
        assert read.verification_report.state_of(dimension) is (
            VerificationState.VERIFIED), dimension


def test_absent_inputs_still_require_the_assessment_to_agree_with_them():
    """CT's explicit condition: the historical path must independently verify that the
    recorded assessment agrees with the missing inputs. A record claiming COMPLETE over
    evidence that is missing its prediction inputs is refused, not read."""
    def claim_complete(p):
        # The forgery has to be internally consistent, or the POLICY re-run refuses it
        # first and this test passes on a different check. The recorded assessment, the
        # decision's own reasons and the derived abstention reason all move together --
        # which is what a real forger would do, and what leaves completeness as the only
        # thing left wrong with the record.
        dimensions = p["product"]["assurance"]["assurance_context"]["evidence"]
        dimensions["completeness"] = "COMPLETE"
        dimensions["missing_evidence"] = []
        dimensions["release"] = "WITHHOLD"
        dimensions["blocking_reasons"] = ["integrity=BROKEN"]
        p["product"]["assurance"]["blocking_reasons"] = ["integrity=BROKEN"]
        p["product"]["abstention_reason"] = "integrity=BROKEN"

    with pytest.raises(ValueError, match="completeness=COMPLETE"):
        import_historical_envelope(inputless(mutate=claim_complete))


@pytest.mark.parametrize("name,mutate,pattern", [
    (
        "entitlement scope",
        lambda p: p["product"]["assurance"]["assurance_context"]["entitlement"].__setitem__(
            "authorized_source_systems", []),
        "entitlement",
    ),
    (
        "identity confidence binding",
        lambda p: p["product"]["evidence"].__setitem__(
            "identity_confidence", "0.020000"),
        "two numbers for one question",
    ),
    (
        "the policy verdict the record does not reproduce",
        lambda p: (
            p["product"]["assurance"].__setitem__(
                "blocking_reasons",
                p["product"]["assurance"]["blocking_reasons"] + ["identity: invented"]),
            p["product"].__setitem__(
                "abstention_reason",
                "; ".join(p["product"]["assurance"]["blocking_reasons"]))),
        "over the recorded assurance basis produces",
    ),
])
def test_absent_inputs_do_not_switch_off_any_other_verification(name, mutate, pattern):
    """Absence of a replay basis must not become a general amnesty. Every check that does
    not need those inputs still runs, and still refuses."""
    with pytest.raises(ValueError, match=pattern):
        import_historical_envelope(inputless(mutate=mutate))
