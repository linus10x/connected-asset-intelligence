#!/usr/bin/env python3
"""Named regression mutants. Reproducible, curated, and NOT a completeness claim.

WHAT THIS IS FOR, NARROWED
--------------------------
Every mutant below was written after a specific defect was found, and each declares the
tests that must fail to kill it. That makes this excellent REGRESSION evidence: if the
check that closed a known defect is removed, a named mutant says so and names the test
that should have caught it.

What it is not, and used to be read as, is evidence that the suite is complete. The
corpus was built FROM the tests, so a green score over it measures the corpus. A mutation
nobody thought of is a mutation nobody wrote, and this file is silent about it. Wave 4
demonstrated the circularity rather than arguing it: fresh mutations against uncovered
behaviour survived while this corpus was fully green.

`mutation_generator.py` is the other half -- candidates derived from the AST of
`src/cai`, knowing nothing about the tests -- and it is the gate that speaks to coverage.
This one remains the gate that speaks to regression. Both run; neither substitutes for
the other.

A NOTE ON RE-ANCHORING
----------------------
Twenty anchors moved in the increment that introduced portable evidence, and every one
was re-pointed at where its rule now lives rather than deleted. One rule had genuinely
become unreachable at its old site -- `formation`'s "readings the decision had not
received", which release now gets by construction from the point-in-time query -- and its
mutant moved to the import boundary, which is where that rule still has to be checked. A
mutant dropped because its anchor moved is coverage silently lost, and this file's whole
purpose is not losing things silently.

WHY A SCRIPT RATHER THAN A CLAIM
--------------------------------
"We tried a mutation and it failed" is prose. Prose is not evidence -- it cannot be
re-run by a reviewer, and it degrades silently as the code changes underneath it.

This applies each mutation to a copy of the source, runs the suite, restores the
original, and reports. A reviewer runs it and sees for themselves.

BIDIRECTIONAL BY DESIGN
-----------------------
Killing only conservative mutants (always refuse, always NOT_RECONSTRUCTABLE) proves the
system is cautious, not that it is correct. A system that refuses everything is safe
and useless. So every conservative mutant is paired with its permissive opposite --
always release, always provable, ignore entitlement -- and both must die.

WHAT COUNTS AS A KILL, AND WHY THAT NEEDED FIXING
-------------------------------------------------
An earlier version of this harness counted *any* pytest failure as a kill. That is a
false-pass generator, and it was fair criticism:

  * a mutant that breaks the import produces a collection error, pytest reports
    failures, and the harness records a behavioural kill that never happened;
  * a mutant might be killed by a test unrelated to the property it targets, which
    proves the suite is noisy rather than that the property is guarded;
  * nothing verified the source was actually restored afterwards, so a failed restore
    would silently poison every subsequent mutant and the final suite run.

A kill is now valid only when the suite still collected the baseline number of tests,
reported no collection errors, and the failures include the specific tests the mutant
is declared to break. `expect_failing` is the load-bearing part: it turns "something
went red" into "the property I claimed to guard is the thing that caught this."

Source files are hashed before mutation and re-hashed after restore. A mismatch aborts
the run rather than continuing on a corrupted tree.

Usage:  python3 mutation_harness.py
Exit 0 when every mutant is killed by its declared tests.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent

# THE HARNESS MUTATES SOURCE IN PLACE, SO IT DOES NOT DO IT HERE.
#
# It used to rewrite `src/cai/*.py` in the live repository and restore each file
# afterwards. That is correct in isolation and hostile in practice: anyone editing the
# tree while it runs gets non-deterministic test failures from a source file that is
# mutated for a few hundred milliseconds at a time, and the harness gets a baseline that
# moves under it. Both happened -- a run marked twelve mutants INVALID because the test
# count changed from 748 to 754 mid-flight, then declared the tree had not returned to
# baseline. Neither report was true, and both looked like real findings.
#
# `guard_sweep.py` has the same property and carries the same warning in prose. Prose did
# not prevent it. Working on a scratch copy does: the live tree is never touched, so the
# failure mode is not available regardless of who is editing what.
def _workspace() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="cai-mutants-")) / "repo"
    shutil.copytree(_REPO, scratch, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache",
        ".mypy_cache", "*.egg-info", "build", "dist", ".ruff_cache",
    ))
    return scratch


ROOT = _workspace()
SRC = ROOT / "src" / "cai"


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    find: str
    replace: str
    direction: str          # "conservative" | "permissive"
    must_fail_because: str
    expect_failing: tuple[str, ...] = ()
    """Test names that MUST be among the failures for this kill to count.

    Empty means unverified, and the harness reports that as a weakness rather than
    quietly accepting it.
    """


MUTANTS: list[Mutant] = [
    Mutant(
        "always RELEASE", "evidence.py",
        "        if self.support is not Support.SUPPORTED:",
        "        if False:  # mutant",
        "permissive", "unsupported evidence must withhold",
        ("test_release_predicate_holds_over_the_entire_state_space",
         "test_all_blocking_reasons_are_reported_not_just_the_first"),
    ),
    Mutant(
        "ignore entitlement", "evidence.py",
        "        if self.entitlement is not EntitlementState.AUTHORIZED:",
        "        if False:  # mutant",
        "permissive", "an unauthorized claim must withhold",
        ("test_unknown_entitlement_is_never_treated_as_permission",
         "test_release_predicate_holds_over_the_entire_state_space"),
    ),
    Mutant(
        "ignore transaction time", "bitemporal.py",
        "            if o.transaction_time <= transaction_time",
        "            if o.valid_time <= transaction_time  # mutant",
        "permissive", "late evidence must not enter the original decision",
        ("test_decision_time_view_excludes_late_arrivals",),
    ),
    Mutant(
        "ignore valid time", "bitemporal.py",
        "            if o.valid_time <= valid_time",
        "            if o.transaction_time <= valid_time  # mutant",
        "permissive", "the wrong temporal view must not be selected",
        ("test_the_two_views_genuinely_differ",
         "test_current_best_known_view_includes_late_arrivals"),
    ),
    Mutant(
        "constant predictor", "predictor.py",
        "    risk = max(0.0, min(1.0, raw))", "    risk = 0.5  # mutant",
        "conservative", "a degrading series must outscore a stable one",
        ("test_degrading_series_scores_higher_than_stable_one",),
    ),
    Mutant(
        "unenforced applicability envelope", "predictor.py",
        "    if horizon > MAX_HORIZON:", "    if False:  # mutant",
        "permissive", "the model must refuse beyond its declared envelope",
        ("test_refuses_horizon_beyond_declared_maximum",),
    ),
    Mutant(
        "ignore assignment validity", "context.py",
        "            if a.asset_id == asset_id and a.covers(horizon_start)",
        "            if a.asset_id == asset_id  # mutant",
        "permissive", "a stale zone assignment must not produce an impact",
        ("test_missing_or_late_relationship_prevents_business_impact_claim",),
    ),
    Mutant(
        "context always derives", "context.py",
        "        if not live:", "        if False:  # mutant",
        "permissive", "a missing relationship must prevent the claim",
        ("test_missing_or_late_relationship_prevents_business_impact_claim",),
    ),
    Mutant(
        "causal overclaim", "lifecycle.py",
        '    NOT_ESTABLISHED = "NOT_ESTABLISHED"',
        '    NOT_ESTABLISHED = "NOT_ESTABLISHED"\n    PREVENTED = "PREVENTED"  # mutant',
        "permissive", "outcome capture must never imply causation",
        ("test_no_code_path_can_claim_the_intervention_worked",),
    ),
    # ---- the joins between modules. Untested until the integration suite existed,
    # ---- which is exactly how the docs came to describe a chain the code did not walk.
    Mutant(
        "relationships ignore recording time", "context.py",
        "        live = [a for a in covering if a.was_known_at(transaction_time_cutoff)]",
        "        live = list(covering)  # mutant",
        "permissive", "a backdated relationship must not enter a past decision",
        ("test_an_assignment_recorded_after_the_cutoff_is_not_used",),
    ),
    Mutant(
        "component binding ignores the owning asset", "context.py",
        "            if component.asset_id != asset_id:",
        "            if False:  # mutant",
        "permissive", "a claim must not bind to a part on a different machine",
        ("test_a_component_on_another_asset_is_refused",),
    ),
    Mutant(
        # Anchored on the line ABOVE as well: the bare
        # "and o.observation_id not in superseded" is a strict PREFIX of
        # "…not in superseded_by_then" in `point_in_time_view`, and patched the intended
        # line only because it happens to appear first. A reordering of the two methods
        # would have silently mutated the decision-time view while reporting a kill
        # attributed to a retrospective-view test, and the harness's
        # "anchor not found -> survivor" net cannot fire on a prefix collision.
        "retrospective view ignores supersession", "bitemporal.py",
        "            if o.valid_time <= valid_time\n"
        "            and o.observation_id not in superseded",
        "            if o.valid_time <= valid_time\n"
        "            and True  # mutant",
        "permissive", "a correction and its target must not both be current",
        ("test_the_retrospective_view_honours_supersession",),
    ),
    Mutant(
        "context facts ignore knowledge time", "context.py",
        "    return fact.recorded_at <= transaction_time",
        "    return True  # mutant",
        "permissive", "a day-14 schedule must not justify a day-12 conclusion",
        ("test_a_context_fact_recorded_after_the_cutoff_is_not_used",),
    ),
    Mutant(
        "overlapping windows resolved by list order", "context.py",
        "        if len(overlapping) > 1:", "        if False:  # mutant",
        "permissive", "insertion order must not decide the economic consequence",
        ("test_two_overlapping_windows_refuse_rather_than_taking_the_first",),
    ),
    Mutant(
        "decision-time view ignores supersession", "bitemporal.py",
        "            and o.observation_id not in superseded_by_then",
        "            and True  # mutant",
        "permissive", "a corrected reading and its correction must not both be used",
        ("test_the_decision_time_view_honours_supersession_known_by_then",),
    ),
    Mutant(
        "validity not rechecked at the window", "context.py",
        "            a.zone_id == zone_id and a.covers(window.opens)",
        "            a.zone_id == zone_id  # mutant",
        "permissive", "an asset gone before the window is not a risk to it",
        ("test_an_asset_reassigned_before_the_window_is_not_a_risk_to_it",),
    ),
    Mutant(
        "policy refuses everything", "policy.py",
        "        return AssuranceDecision(\n            permitted=not reasons,",
        "        return AssuranceDecision(\n            permitted=False,  # mutant",
        "conservative", "a well-formed claim must actually be released",
        ("test_a_verified_claim_is_delivered",),
    ),
    Mutant(
        "candidate refuses every consequence", "candidate.py",
        "        if not self.business_consequence.is_actionable():",
        "        if True:  # mutant",
        "conservative", "an actionable consequence must form a candidate",
        ("test_an_actionable_downtime_consequence_does_form",),
    ),
    Mutant(
        "canonicalizer refuses everything", "canonical.py",
        "    if isinstance(value, str):\n        return value",
        "    if isinstance(value, str):\n        raise NotCanonicalizable('mutant')",
        "conservative", "a valid record must canonicalise",
        ("test_the_envelope_canonicalises_and_digests",),
    ),
    Mutant(
        "context never derives", "context.py",
        "        return result(True, commitment)", "        return result(False, None)",
        "conservative", "a complete graph walk must produce an impact",
        ("test_the_same_facts_recorded_in_time_do_derive",),
    ),
    Mutant(
        "release skips digest verification", "assessment.py",
        "    elif digest_observations(evidence_source.observations) != digest:",
        "    elif False:  # mutant",
        "permissive", "a digest unrelated to the evidence must not verify",
        ("test_an_unverifiable_digest_abstains",),
    ),
    Mutant(
        "entitlement checked against itself", "assessment.py",
        "        recipient=delivering_to,",
        "        recipient=entitlement_assertion.recipient,  # mutant",
        "permissive", "a clearance for one recipient must not authorise another",
        ("test_a_clearance_for_one_recipient_does_not_authorise_another",),
    ),
    Mutant(
        "candidate accepts a non-actionable consequence", "candidate.py",
        "        if not self.business_consequence.is_actionable():",
        "        if False:  # mutant",
        "permissive", "no actionable consequence means no product to form",
        ("test_a_non_actionable_consequence_forms_no_candidate",),
    ),
    Mutant(
        "permit DELIVERED with a refusing assurance", "product.py",
        "            if not self.assurance.permitted:",
        "            if False:  # mutant",
        "permissive", "a delivered product must carry a decision that permitted it",
        ("test_a_delivered_payload_carrying_a_refusing_assurance_is_refused",),
    ),
    # ---- the cross-object bindings. Every one of these fields existed, travelled in the
    # ---- record and printed in the hero while binding to nothing.
    Mutant(
        "skip subject binding", "binding.py",
        "    if assurance.identity_assertion.resolved_entity != claim.subject:",
        "    if False:  # mutant",
        "permissive", "identity must be resolved for the asset the claim is about",
        ("test_an_identity_assertion_about_another_entity_is_refused",),
    ),
    Mutant(
        "decouple applicability model version", "binding.py",
        "    if assurance.applicability_assertion.model_version != claim.model_version:",
        "    if False:  # mutant",
        "permissive", "the envelope checked must belong to the model that ran",
        ("test_an_applicability_assertion_about_another_model_is_refused",),
    ),
    Mutant(
        "decouple temporal assertion decision time", "binding.py",
        "        assurance.temporal_assertion.model_decision_time != context.model_decision_time",
        "        False  # mutant",
        "permissive", "DecisionContext is the single temporal authority",
        ("test_a_temporal_assertion_naming_another_decision_time_is_refused",),
    ),
    Mutant(
        "decouple temporal assertion knowledge cutoff", "binding.py",
        "        or assurance.temporal_assertion.knowledge_cutoff != context.knowledge_cutoff",
        "        or False  # mutant",
        "permissive", "an assertion about a different cutoff checked different evidence",
        ("test_a_temporal_assertion_naming_another_knowledge_cutoff_is_refused",),
    ),
    Mutant(
        "skip evidence-to-claim model comparison", "binding.py",
        "    if evidence.model_version is not None and evidence.model_version != claim.model_version:",
        "    if False:  # mutant",
        "permissive", "the snapshot must describe the computation the claim came from",
        ("test_evidence_produced_by_another_model_is_refused",),
    ),
    # ---- the wire boundary. Untested until the import suite existed, which is how the
    # ---- portable bundle came to omit the evidence and the entitlement scope entirely.
    Mutant(
        "bypass envelope reconstruction validation", "envelope.py",
        "    validate_envelope_payload(payload)",
        "    pass  # mutant",
        "permissive", "structural refusals must run before reconstruction",
        ("test_an_unknown_schema_version_is_refused",
         "test_a_payload_claiming_the_intervention_worked_is_refused"),
    ),
    Mutant(
        "accept an unknown canonicalization", "envelope.py",
        "    if canonicalization != CANONICALIZATION:",
        "    if False:  # mutant",
        "permissive", "a digest is meaningless against an unnamed algorithm",
        ("test_an_unfamiliar_canonicalization_is_refused_before_the_schema_sees_it",),
    ),
    Mutant(
        "evidence is dropped from the portable bundle", "product.py",
        '            "evidence": self.evidence.as_record(),',
        '            "evidence": {},  # mutant',
        "permissive", "a bundle without its evidence cannot be checked by any reader",
        ("test_the_evidence_snapshot_actually_crosses_the_wire",),
    ),
    Mutant(
        "entitlement scope is summarised away on export", "candidate.py",
        '                "subject": self.entitlement_assertion.subject,',
        '                # mutant -- subject dropped',
        "permissive", "an importer must be able to re-run the authorization",
        ("test_the_entitlement_scope_crosses_the_wire",),
    ),
    Mutant(
        "rendered action text is read back as an input", "action.py",
        '            prerequisites=tuple(r.get("prerequisites") or ()),  # type: ignore[arg-type]',
        '            prerequisites=tuple(r.get("prerequisites") or ()),  # type: ignore[arg-type]\n        ) if r.get("rendered_text") is None else cls(\n            action_id=str(r["action_id"]), action_type=ActionType(r["action_type"]),\n            target=str(r["rendered_text"]), responsible_role=str(r["responsible_role"]),\n            due_by=datetime.fromisoformat(str(r["due_by"])),\n            operational_window=TimeInterval(\n                datetime.fromisoformat(str(r["operational_window_start"])),\n                datetime.fromisoformat(str(r["operational_window_end"])),\n            ),\n            reason=str(r["reason"]), priority=Priority(r["priority"]),\n            prerequisites=tuple(r.get("prerequisites") or ()),  # mutant',
        "permissive", "an exported rendering must never become an input on the way back",
        ("test_a_delivered_product_survives_the_wire_intact",),
    ),
    Mutant(
        "skip subject comparison", "candidate.py",
        "        if subject != self.subject or tenant != self.tenant:",
        "        if tenant != self.tenant:  # mutant",
        "permissive", "a clearance for one asset must not release a claim about another",
        ("test_a_clearance_for_one_subject_does_not_authorise_another",),
    ),
    Mutant(
        "skip tenant comparison", "candidate.py",
        "        if subject != self.subject or tenant != self.tenant:",
        "        if subject != self.subject:  # mutant",
        "permissive", "a clearance for one tenant must not release another's data",
        ("test_a_clearance_for_one_tenant_does_not_authorise_another",),
    ),
    Mutant(
        "skip product/use comparison", "candidate.py",
        "        if recipient != self.recipient or purpose != self.purpose:",
        "        if recipient != self.recipient:  # mutant",
        "permissive", "a clearance for one purpose must not authorise another use",
        ("test_a_clearance_for_one_purpose_does_not_authorise_another_use",),
    ),
    Mutant(
        "skip source-data comparison", "candidate.py",
        "        if not source_systems or not set(source_systems).issubset(\n"
        "            self.authorized_source_systems\n"
        "        ):",
        "        if False:  # mutant",
        "permissive", "a claim must rest only on feeds the licence actually names",
        ("test_evidence_from_an_unlicensed_source_system_is_not_cleared",),
    ),
    Mutant(
        "substitute assertion tenant for the actual tenant", "assessment.py",
        "        tenant=for_tenant,",
        "        tenant=entitlement_assertion.tenant,  # mutant",
        "permissive", "checking an assertion against itself makes the scope decorative",
        ("test_a_clearance_for_one_tenant_does_not_authorise_another",),
    ),
    Mutant(
        "substitute assertion subject for the claim subject", "assessment.py",
        "        subject=about_subject,",
        "        subject=entitlement_assertion.subject,  # mutant",
        "permissive", "the entitlement must bind to the asset the claim is about",
        ("test_a_clearance_for_one_subject_does_not_authorise_another",),
    ),
    Mutant(
        "candidate accepts prose as the claim", "candidate.py",
        "        if not isinstance(self.prediction_claim, PredictionClaim):",
        "        if False:  # mutant",
        "permissive", "arbitrary prediction prose must not reach the aggregate root",
        ("test_the_candidate_refuses_prose_in_place_of_a_typed_claim",),
    ),
    Mutant(
        "assurance accepts an asserted evidence assessment", "candidate.py",
        "        if not isinstance(self.evidence_assessment, EvidenceAssessment):",
        "        if False:  # mutant",
        "permissive", "an assessment a caller asserts is one nobody performed",
        ("test_an_untyped_evidence_assessment_is_refused",),
    ),
    Mutant(
        "envelope accepts an untyped product", "envelope.py",
        "        if not isinstance(self.product, IntelligenceProduct):",
        "        if False:  # mutant",
        "permissive", "the envelope must carry the typed product, not a loose record",
        ("test_the_envelope_refuses_anything_but_a_typed_product",),
    ),
    Mutant(
        "delivery digest is not verified", "delivery.py",
        "        if self.content_digest != self.recomputed_digest():",
        "        if False:  # mutant",
        "permissive", "a delivery record must not attest content it does not carry",
        ("test_a_rendered_delivery_cannot_carry_a_digest_of_other_content",),
    ),
    Mutant(
        "trust line is appended without restamping the digest", "delivery.py",
        "            content_digest=_digest_of(\n"
        "                renderer_version=self.renderer_version,\n"
        "                locale=self.locale,\n"
        "                rendered_text=text,\n"
        "                card=card,\n"
        "                rendered_at=self.rendered_at,\n"
        "            ),",
        "            content_digest=self.content_digest,  # mutant",
        "permissive", "the digest must bind the text the recipient actually received",
        ("test_the_delivered_text_is_what_the_digest_attests",),
    ),
    Mutant(
        "candidate accepts a mismatched exposure window", "candidate.py",
        "        if not self.context.prediction_window.overlaps(",
        "        if False and self.context.prediction_window.overlaps(",
        "permissive", "the consequence must belong to this decision",
        ("test_a_consequence_outside_the_prediction_window_forms_no_candidate",),
    ),
    Mutant(
        "knowledge may postdate the decision", "decision.py",
        "        if self.knowledge_cutoff > self.model_decision_time:",
        "        if False:  # mutant",
        "permissive", "a decision cannot rest on evidence that had not arrived",
        ("test_knowledge_cannot_postdate_the_decision",),
    ),
    Mutant(
        "action may fall after its window", "action.py",
        "        if self.due_by > self.operational_window.end:",
        "        if False:  # mutant",
        "permissive", "an action after the window cannot change the outcome",
        ("test_an_action_due_after_its_window_closes_is_refused",),
    ),
    Mutant(
        "envelope accepts a causal claim", "envelope.py",
        "        AttributedEffect(effect)", "        pass  # mutant",
        "permissive", "an imported envelope must not assert PREVENTED",
        ("test_an_envelope_claiming_the_intervention_worked_is_refused",),
    ),
    Mutant(
        "canonicalizer approximates floats", "canonical.py",
        "        if value != int(value):", "        if False:  # mutant",
        "permissive", "two implementations must not produce two digests for one record",
        ("test_a_non_integer_float_is_refused_rather_than_approximated",),
    ),
    Mutant(
        # RE-ANCHORED. `status_at` now returns WITHHELD for a non-delivered product
        # before it reaches the expiry comparison, and the `is not None` half of the old
        # condition went with it: a DELIVERED product always has a validity horizon.
        # Same mutation, same defect, same killer.
        "expired product still reads active", "product.py",
        "        if moment >= self.valid_until:",
        "        if False:  # mutant",
        "permissive", "an operator must not act on stale intelligence",
        ("test_status_is_derived_from_lineage_events_and_time",),
    ),
    Mutant(
        "dedupe ignores payload", "bitemporal.py",
        "            if existing.content_digest() != observation.content_digest():",
        "            if False:  # mutant",
        "permissive", "two sources disagreeing must not read as an ordinary retry",
        ("test_same_id_different_payload_is_an_integrity_conflict",),
    ),
    Mutant(
        "point-in-time view ignores clock skew", "bitemporal.py",
        "            and not o.has_implausible_clock()",
        "            and True  # mutant",
        "permissive", "a reading claiming the future must not enter the decision",
        ("test_a_skewed_reading_does_not_enter_the_point_in_time_view",),
    ),
    Mutant(
        "lifecycle opens at any state", "lifecycle.py",
        "            if to is not DispositionState.DELIVERED:",
        "            if False:  # mutant",
        "permissive", "a product cannot be acknowledged before it is delivered",
        ("test_a_lifecycle_cannot_open_at_acknowledged",),
    ),
    Mutant(
        "lifecycle accepts backwards time", "lifecycle.py",
        "        if at < last:", "        if False:  # mutant",
        "permissive", "an unreplayable trail is not a record",
        ("test_events_cannot_go_backwards_in_time",),
    ),
    Mutant(
        "fingerprint ignores the metric", "predictor.py",
        "            metric,\n            str(int(horizon.total_seconds())),",
        "            str(int(horizon.total_seconds())),  # mutant",
        "permissive", "identical values under different metrics must not collide",
        ("test_fingerprint_distinguishes_metrics_with_identical_values",),
    ),
    Mutant(
        "evidence digest ignores values", "bitemporal.py",
        '        parts = (\n            self.observation_id,',
        '        parts = (  # mutant\n            self.observation_id,)\n        _unused = (\n            self.observation_id,',
        "permissive", "substituting a reading must change the evidence digest",
        ("test_substituting_a_reading_changes_the_evidence_digest",),
    ),
    # =====================================================================
    # THE CONTROL TOWER RE-AUDIT OF a28f8e4. One integration mutation at the
    # JOIN per finding -- not a constructor test. Each is declared against the
    # test that claims to guard it, so a kill by some unrelated assertion
    # counts as a survivor rather than as evidence.
    # =====================================================================

    # ---- P0-1. The claim bound to its input fingerprint and to none of the values the
    # ---- predictor produced, so a legitimate fingerprint could carry a substituted score.
    Mutant(
        "P0-1 claim output is never replayed", "assessment.py",
        "        reason = predictor_output_mismatch(evidence, prediction_claim)",
        "        reason = None  # mutant",
        "permissive", "a substituted score or meaning must not reach DELIVERED",
        ("test_a_substituted_predictor_output_field_is_refused_by_replay",
         "test_a_substituted_model_artifact_digest_is_refused_by_replay"),
    ),
    Mutant(
        "P0-1 imported claim is not bound to its inputs", "product.py",
        "        reason = input_fingerprint_mismatch(product.evidence, claim)",
        "        reason = None  # mutant",
        "permissive", "a wire claim citing one set of readings must not carry another",
        ("test_a_payload_whose_claim_does_not_match_its_recorded_inputs_is_refused",),
    ),
    Mutant(
        "P0-1 replay is skipped on import", "product.py",
        "        elif claim_is_replayable_here(claim):",
        "        elif False:  # mutant",
        "permissive", "a replayable imported claim must still replay",
        ("test_a_payload_whose_claim_replays_to_a_different_score_is_refused",),
    ),

    # ---- P0-2. DecisionContext was the temporal authority everywhere except where a
    # ---- second one could disagree with it.
    Mutant(
        "P0-2 zero-length interval permitted", "decision.py",
        "        if self.end == self.start:", "        if False:  # mutant",
        "permissive", "an instant is not a prediction window",
        ("test_a_zero_length_interval_is_refused",),
    ),
    Mutant(
        "P0-2 claim horizon may disagree with the window", "candidate.py",
        "        if self.prediction_claim.horizon_seconds != derived_horizon:",
        "        if False:  # mutant",
        "permissive", "two horizons that can disagree are two temporal authorities",
        ("test_a_claim_whose_horizon_disagrees_with_the_window_forms_no_candidate",),
    ),
    Mutant(
        "P0-2 action need not touch the exposure", "candidate.py",
        "        if not self.action.operational_window.overlaps(",
        "        if False and self.action.operational_window.overlaps(",
        "permissive", "an action for a different operational event must not attach",
        ("test_an_action_for_a_different_operational_event_is_refused",),
    ),

    # ---- P0-3. Assurance stopped being typed at the wire, so the import boundary applied
    # ---- none of the guarantees that apply at live release.
    Mutant(
        "P0-3 import skips the cross-bindings", "product.py",
        "        verify_bindings(product.candidate, assessed.context, product.evidence)",
        "        pass  # mutant",
        "permissive", "a payload altering the recorded assurance basis must be refused",
        ("test_a_payload_altering_the_recorded_assurance_basis_is_refused",),
    ),
    Mutant(
        "P0-3 import does not recompute the decision", "product.py",
        "        findings.append(product._verify_recorded_decision_follows_from_its_basis())",
        "        findings.append(verified(VerificationDimension.POLICY_REPLAY))  # mutant",
        "permissive", "a verdict the named policy does not reproduce must be refused",
        ("test_a_payload_altering_the_policy_digest_is_refused",
         "test_a_payload_naming_a_policy_this_package_does_not_have_is_refused"),
    ),
    Mutant(
        "P0-3 entitlement is not re-run against the delivery", "product.py",
        "            if not entitlement.permits(",
        "            if False and entitlement.permits(",
        "permissive", "the clearance must authorise the delivery this record describes",
        ("test_an_entitlement_violation_refuses_in_both_modes",),
    ),
    Mutant(
        "P0-3 the assessment need not follow from its dimensions", "evidence.py",
        '        if "release" in r and r["release"] != rebuilt.release_decision().value:',
        "        if False:  # mutant",
        "permissive", "a stated conclusion must follow from the record's own dimensions",
        ("test_a_payload_rewriting_a_dimension_under_its_own_verdict_is_refused",),
    ),

    # ---- P0-4. The five-link derivation was computed, used, and discarded.
    Mutant(
        "P0-4 the derivation is dropped on export", "consequence.py",
        '            "derivation": self.derivation.as_record(),',
        "            # mutant -- derivation dropped",
        "permissive", "the portable consequence must carry why the facts justify it",
        ("test_the_reason_path_survives_the_wire",),
    ),
    Mutant(
        "P0-4 the path need not TERMINATE at the conclusion", "consequence.py",
        "        if self.derivation.terminal_entity != self.commitment_id:",
        "        if False:  # mutant",
        "permissive", "a walk concluding elsewhere argues for something else",
        ("test_a_consequence_naming_an_intermediate_step_is_refused",),
    ),
    Mutant(
        "P0-4 the path need not reach the conclusion at all", "consequence.py",
        "        if principal not in self.derivation.entities():",
        "        if False:  # mutant",
        "permissive", "a real path attached to somebody else's conclusion must be refused",
        ("test_a_downtime_consequence_whose_path_never_mentions_its_asset_is_refused",),
    ),
    Mutant(
        "P0-4 the walk may use facts recorded after the cutoff", "derivation.py",
        "        late = [s.label() for s in self.steps if s.recorded_at > self.knowledge_cutoff]",
        "        late = []  # mutant",
        "permissive", "a walk cannot use a fact the decision-maker had not received",
        ("test_a_payload_whose_derivation_used_a_fact_recorded_after_the_cutoff_is_refused",),
    ),
    Mutant(
        "P0-4 the derivation need not answer to this decision's clock", "candidate.py",
        "        if path.knowledge_cutoff != self.context.knowledge_cutoff:",
        "        if False:  # mutant",
        "permissive", "a walk performed at another cutoff knew a different amount",
        ("test_a_derivation_from_another_decision_forms_no_candidate",),
    ),

    # ---- P0-5. The typed LEARN boundary did not survive the wire.
    Mutant(
        "P0-5 the outcome is not bound to this subject", "envelope.py",
        "        if self.outcome.subject != subject:", "        if False:  # mutant",
        "permissive", "an outcome about another asset must not attach to this product",
        ("test_an_outcome_that_does_not_bind_to_this_product_is_refused",),
    ),
    Mutant(
        "P0-5 the outcome is not joined to the action", "envelope.py",
        "        if self.outcome.related_action_id != action_id:",
        "        if False:  # mutant",
        "permissive", "without the join, acted and ignored are the same row",
        ("test_an_outcome_that_does_not_bind_to_this_product_is_refused",),
    ),
    Mutant(
        "P0-5 trail rules are not run on import", "envelope.py",
        "        check_trail(self.lifecycle_events)", "        pass  # mutant",
        "permissive", "an imported trail must obey the rules an in-memory one obeys",
        ("test_an_imported_lifecycle_trail_out_of_order_is_still_refused",
         "test_an_imported_lifecycle_trail_skipping_acknowledgement_is_refused"),
    ),
    Mutant(
        # RE-ANCHORED. An outcome on a withheld product is refused one check earlier now,
        # so `delivery is not None` could no longer be false and was removed.
        "P0-5 an outcome may be observed before delivery", "envelope.py",
        "        if self.outcome.observation_window.start < delivery:",
        "        if False:  # mutant",
        "permissive", "nothing can be the outcome of a recommendation not yet sent",
        ("test_an_outcome_observed_before_delivery_is_refused",),
    ),

    # ---- P0-6. Status came from the caller on the one question that must have a single
    # ---- authority.
    Mutant(
        "P0-6 status ignores retraction events", "envelope.py",
        "        if any(e.event_type is StatusEventType.RETRACTED for e in effective):",
        "        if False:  # mutant",
        "permissive", "a retracted claim must not read as active",
        ("test_status_derives_retraction_and_supersession_from_envelope_events",),
    ),
    Mutant(
        "P0-6 status events apply retroactively", "envelope.py",
        "        effective = [e for e in self.status_events if e.at <= moment]",
        "        effective = list(self.status_events)  # mutant",
        "permissive", "an event must not change what was believable before it happened",
        ("test_a_status_event_has_not_taken_effect_before_it_happened",),
    ),
    Mutant(
        "P0-6 a product may supersede itself", "envelope.py",
        "                if event.replacement_product_id == self.product.product_id:",
        "                if False:  # mutant",
        "permissive", "self-supersession terminates no lineage",
        ("test_a_product_cannot_supersede_itself",),
    ),
    Mutant(
        # RE-ANCHORED, same cause as P0-5: a status event on a withheld product is
        # refused earlier, so only a DELIVERED product reaches this loop.
        "P0-6 a claim may be retracted before it was made", "envelope.py",
        "            if event.at < delivery:",
        "            if False:  # mutant",
        "permissive", "a status event cannot predate the delivery it is about",
        ("test_a_status_event_predating_delivery_is_refused",),
    ),

    # ---- P0-7. Detected by the log, consumable by the assessment, never once carried
    # ---- into a real release. Two independent audits found this one.
    Mutant(
        "P0-7 conflicts dropped at the release join", "assessment.py",
        "    conflicts = evidence_source.conflict_descriptions()",
        "    conflicts = ()  # mutant",
        "permissive", "two sources disagreeing must reach the actual release path",
        ("test_an_integrity_conflict_reaches_the_release_path_and_withholds",),
    ),
    Mutant(
        "P0-7 the bundle omits the log's conflicts", "bitemporal.py",
        "                if kept.observation_id in ids",
        "                if False  # mutant",
        "permissive", "the bundle a log produces must carry what the log found",
        ("test_an_integrity_conflict_reaches_the_release_path_and_withholds",),
    ),

    # ---- P0-8. The legacy scalar rights representation. Also found independently.
    Mutant(
        "P0-8 the legacy boolean Entitlement returns", "contract.py",
        "@dataclass(frozen=True)\nclass PredictionClaim:",
        "@dataclass(frozen=True)\nclass Entitlement:  # mutant\n"
        "    may_use_source_data: bool = False\n"
        "    may_deliver_to_recipient: bool = False\n\n\n"
        "@dataclass(frozen=True)\nclass PredictionClaim:",
        "permissive", "exactly one rights representation may exist",
        ("test_the_legacy_boolean_entitlement_representation_is_gone",
         "test_no_module_reintroduces_a_scalar_rights_representation"),
    ),

    # ---- P1-1 / P1-2. Assertion provenance, and the envelope it is asserted against.
    Mutant(
        "P1-1 identity evidence refs are summarised away", "candidate.py",
        '                "evidence_refs": list(self.identity_assertion.evidence_refs),',
        '                "evidence_refs": [],  # mutant',
        "permissive", "a confidence with no evidence behind it cannot be challenged",
        ("test_the_assertion_provenance_survives_rather_than_degrading_to_a_verdict",),
    ),
    Mutant(
        "P1-2 subject type is asserted against nothing", "binding.py",
        "        if not envelope.admits_subject_type(asserted_type):",
        "        if False:  # mutant",
        "permissive", "applicability must be checked against the declared envelope",
        ("test_an_unknown_subject_type_refuses_on_the_envelope_not_on_the_pair",),
    ),
    Mutant(
        "P1-2 a claim may exceed its own declared envelope", "contract.py",
        "        if not self.declared_envelope.admits_metric(self.metric):",
        "        if False:  # mutant",
        "permissive", "a claim outside its own envelope contradicts itself",
        ("test_a_claim_whose_metric_is_outside_its_declared_envelope_is_refused",),
    ),

    # ---- P1-3. The schema audit that only detected the one shape somebody had fixed.
    Mutant(
        "P1-3 a load-bearing wire object is reopened", "envelope.py",
        '                                    "input_fingerprint", "declared_envelope",\n'
        "                                ],\n"
        '                                "additionalProperties": False,',
        '                                    "input_fingerprint", "declared_envelope",\n'
        "                                ],  # mutant",
        "permissive", "an object open to unspecified properties must be caught",
        ("test_no_load_bearing_structure_is_left_unconstrained",
         "test_the_schema_rejects_an_unspecified_extra_property"),
    ),
    Mutant(
        "P1-3 a structurally mandatory field stops being required", "envelope.py",
        '"assurance", "evidence", "release_evidence", "recipient", "purpose",',
        '"assurance", "recipient", "purpose",  # mutant',
        "permissive", "the published contract must not permit a bundle with no evidence",
        ("test_the_schema_requires_every_field_a_real_payload_carries",),
    ),

    # ---- P1-4. Derived values re-derived AND compared, never silently normalised.
    Mutant(
        "P1-4 a tampered instruction is silently re-derived", "action.py",
        '        if "rendered_text" in r and r["rendered_text"] != rebuilt.rendered_text():',
        "        if False:  # mutant",
        "permissive", "the sentence a human was shown must not be quietly replaced",
        ("test_a_derived_value_contradicting_its_source_is_refused_not_normalised",),
    ),
    Mutant(
        "P1-4 product-level derived values are not compared", "product.py",
        "        product._verify_derived_wire_values(r)", "        pass  # mutant",
        "permissive", "a derived value disagreeing with its source is a second authority",
        ("test_a_derived_value_contradicting_its_source_is_refused_not_normalised",),
    ),

    # ---- P1-5. The explicit design invariants that were simply absent.
    Mutant(
        "P1-5 the rendering need not be the one delivered", "product.py",
        "            if self.rendered_delivery.rendered_at != self.delivery_time:",
        "            if False:  # mutant",
        "permissive", "a later re-render must not pass as what the recipient received",
        ("test_a_rendering_timestamped_away_from_its_delivery_is_refused",),
    ),
    Mutant(
        "P1-5 rendered_at is outside the digest", "delivery.py",
        '            "rendered_at": rendered_at.isoformat(),',
        "            # mutant -- rendered_at left outside the digest",
        "permissive", "a timestamp the digest does not cover is decoration",
        ("test_the_rendering_timestamp_is_inside_the_digest",),
    ),
    Mutant(
        "P1-5 a clearance may cover no time at all", "candidate.py",
        "        if self.valid_to is not None and self.valid_to <= self.valid_from:",
        "        if False:  # mutant",
        "permissive", "an entitlement valid over no interval authorises nothing",
        ("test_an_entitlement_valid_over_no_interval_is_refused",),
    ),
    Mutant(
        "P1-5 a temporal verdict needs no basis", "candidate.py",
        "        if not self.basis:\n            raise ValueError(\n"
        '                "a temporal verdict with no basis is a naked valid flag; say on what "',
        "        if False:\n            raise ValueError(\n"
        '                "a temporal verdict with no basis is a naked valid flag; say on what "',
        "permissive", "a bare valid=True gives a reader nothing to challenge",
        ("test_a_temporal_verdict_with_no_basis_is_refused",),
    ),
    # =====================================================================
    # WAVE 2 -- the fresh-context adversarial pass. Three independent auditors
    # attacked the wave-1 remediation. Every P0 they found was on the IMPORT
    # side: each finding had been closed on the live release path and left open
    # at the boundary where "portable, reconstructable outside the platform"
    # actually lives. Two of them independently forged a DELIVERED record.
    # =====================================================================
    # RETIRED: "W2 the record chooses whether the replay runs".
    #
    # The defect was that a record's own artifact digest decided whether the strongest
    # check ran. Two mutants now cover that decision point from both sides, and this one
    # sat between them expressing neither:
    #
    #   P0-1 "replay is skipped on import"  mutates `elif claim_is_replayable_here(claim)`
    #   CT3  "strict import accepts an unverifiable basis"  mutates the strict gate
    #
    # Every replacement that expressed the original defect against the current branch
    # structure failed to COMPILE, and the harness correctly reported INVALID -- a mutant
    # that breaks collection proves nothing about behaviour. Manufacturing a syntactically
    # valid mutant that expresses a defect two others already cover would be padding the
    # corpus, which is the opposite of what it is for.
    #
    # Retired here rather than deleted silently, because a mutant that disappears without
    # a reason is indistinguishable from coverage quietly lost.
    Mutant(
        "W2 an unreproducible policy verdict is accepted", "product.py",
        "        blocked = [f for f in findings if f.state is VerificationState.UNVERIFIABLE]",
        "        blocked = []  # mutant",
        "permissive", "a policy whose thresholds we lack cannot reproduce its verdict",
        ("test_the_strict_reconstruction_api_refuses_an_unverifiable_record_directly",),
    ),
    Mutant(
        "W2 the assessment need not follow from the evidence", "product.py",
        "        for dimension in (\"completeness\", \"temporal_eligibility\", \"entitlement\"):",
        "        for dimension in ():  # mutant",
        "permissive", "COMPLETE over an incomplete snapshot is a record contradicting itself",
        ("test_a_payload_whose_assessment_contradicts_its_own_evidence_is_refused",),
    ),
    Mutant(
        "W2 identity confidence may differ from the assertion", "binding.py",
        "        and evidence.identity_confidence != assurance.identity_assertion.confidence",
        "        and False  # mutant",
        "permissive", "two numbers for one question is graded on one, reported on the other",
        ("test_a_payload_whose_identity_confidence_contradicts_its_assertion_is_refused",),
    ),
    Mutant(
        "W2 the delivered artifact is not re-derived", "product.py",
        "        if rendered.content_digest != expected.content_digest:",
        "        if False:  # mutant",
        "permissive", "the text a human was shown must match the claim beside it",
        ("test_a_payload_whose_delivered_card_was_rewritten_is_refused",),
    ),
    Mutant(
        "W2 a bundle may import as other than what arrived", "envelope.py",
        "    if canonicalize(reserialized) != canonicalize(payload):",
        "    if False:  # mutant",
        "permissive", "deleting a derived key must not bypass what contradicting it catches",
        ("test_a_payload_that_does_not_reconstruct_as_itself_is_refused",),
    ),
    Mutant(
        "W2 the cited observation ids bind to nothing", "assessment.py",
        "    if cited != verified:",
        "    if False:  # mutant",
        "permissive", "a record must not cite readings the release never verified",
        ("test_a_snapshot_citing_readings_the_release_never_saw_is_refused",),
    ),
    Mutant(
        "W2 the identity floor is a second copy", "assessment.py",
        "    elif evidence.identity_confidence < policy.identity_floor:",
        "    elif evidence.identity_confidence < 0.85:  # mutant",
        "permissive", "the policy digest must cover the number that actually decides",
        ("test_the_policy_digest_covers_the_thresholds_that_actually_decide",),
    ),
    Mutant(
        "W2 two supersessions may name two replacements", "envelope.py",
        "                if seen_supersession:",
        "                if False:  # mutant",
        "permissive", "a lineage with two current replacements cannot be followed",
        ("test_two_supersessions_naming_different_replacements_are_refused",),
    ),
    Mutant(
        "W2 a status event may follow a retraction", "envelope.py",
        "            if seen_retraction:\n                raise ValueError(\n"
        '                    f"a {event.event_type.value} event follows a retraction; a claim "',
        "            if False:\n                raise ValueError(\n"
        '                    f"a {event.event_type.value} event follows a retraction; a claim "',
        "permissive", "a withdrawn claim has no standing left to change",
        ("test_an_event_after_a_retraction_is_refused",),
    ),
    Mutant(
        "W2 the schema audit stops being normative", "envelope.py",
        '            "valid_from", "valid_to",\n        ],',
        "        ],  # mutant",
        "permissive", "a field a real payload carries must be required by the contract",
        ("test_the_schema_requires_every_field_a_real_payload_carries",),
    ),
    Mutant(
        "W2 the derivation window need not be this decision's", "candidate.py",
        "        if path.evaluated_window != self.context.prediction_window:",
        "        if False:  # mutant",
        "permissive", "a walk over another window describes a different exposure",
        ("test_a_derivation_over_a_different_window_forms_no_candidate",),
    ),
    Mutant(
        "W2 ABSTAINED may carry a permitting decision", "product.py",
        "            if self.assurance.permitted:\n                raise ValueError(\n"
        '                    "ABSTAINED contradicts an assurance decision that permitted release"',
        "            if False:\n                raise ValueError(\n"
        '                    "ABSTAINED contradicts an assurance decision that permitted release"',
        "permissive", "both directions of the contradiction must be refused",
        ("test_an_abstained_product_carrying_a_permitting_decision_is_refused",),
    ),
    Mutant(
        "W2 the predictor's upper clamp is removed", "predictor.py",
        "    risk = max(0.0, min(1.0, raw))", "    risk = max(0.0, raw)  # mutant",
        "permissive", "a runaway series must saturate rather than score above 1.0",
        ("test_the_upper_clamp_actually_binds",),
    ),
    Mutant(
        "W2 the HAS_COMPONENT step is not recorded", "context.py",
        '                relationship=DerivationRelationship.HAS_COMPONENT,',
        '                relationship=DerivationRelationship.ASSIGNED_TO,  # mutant',
        "permissive", "the walk must bind the claim to the part that degrades",
        ("test_the_full_walk_traverses_all_five_relationships_including_has_component",),
    ),
    # =====================================================================
    # WAVE 3 -- a fourth fresh-context auditor, attacking the wave-2 result.
    # Two more P0s, and both were reachable with the flag OFF or with a flag
    # whose scope was wider than its own documentation claimed.
    # =====================================================================
    Mutant(
        "W3 the unverifiable-basis flag waives the rights question", "product.py",
        "            entitlement = assessed.context.entitlement_assertion",
        "            entitlement = assessed.context.entitlement_assertion.__class__(**{**assessed.context.entitlement_assertion.__dict__, \"authorized_source_systems\": (\"*\",)})  # mutant",
        "permissive", "an accepted unverifiable basis must not waive entitlement",
        ("test_a_claim_that_cannot_be_replayed_here_is_refused_by_default",),
    ),
    Mutant(
        "W3 the claim's subject is a free variable", "binding.py",
        "    if claim.subject != observed and not claim.subject.startswith(observed + \"/\"):",
        "    if False:  # mutant",
        "permissive", "a claim must be about the thing its readings are about",
        ("test_a_relabelled_asset_is_refused_on_import",
         "test_a_relabelled_asset_is_refused_on_the_live_release_path_too"),
    ),
    Mutant(
        "W3 the walk need not mention the observed subject", "binding.py",
        "    if walk.root_entity != observed:",
        "    if False:  # mutant",
        "permissive", "evidence and reasoning must describe the same thing",
        ("test_a_claim_whose_subject_the_walk_never_mentions_is_refused",),
    ),
    Mutant(
        "W3 a claim may rest on readings about several subjects", "binding.py",
        "    if len(observed_subjects) > 1:",
        "    if False:  # mutant",
        "permissive", "a claim over several subjects needs a combining rule",
        ("test_an_imported_bundle_mixing_two_subjects_is_refused",),
    ),
    Mutant(
        "W3 the snapshot need not say what it observed", "assessment.py",
        "    elif frozenset({evidence.subject}) != observed:",
        "    elif False:  # mutant",
        "permissive", "the snapshot must record the subject its readings are about",
        ("test_a_forged_record_refuses_for_the_invariant_it_actually_violates",),
    ),
    Mutant(
        "W3 a claim may outlive the window it describes", "product.py",
        "            if self.valid_until is not None and self.valid_until > window_end:",
        "            if False:  # mutant",
        "permissive", "perishability must answer to the prediction window",
        ("test_a_claim_cannot_outlive_the_window_it_describes",),
    ),
    Mutant(
        "W3 release emits what its own importer refuses", "assessment.py",
        "    reason = input_fingerprint_mismatch(evidence, prediction_claim)",
        "    reason = None  # mutant",
        "permissive", "the two boundaries must not disagree about the same record",
        ("test_release_does_not_emit_a_record_its_own_importer_would_refuse",),
    ),
    Mutant(
        "W3 lossy telemetry precision is accepted", "contract.py",
        "        lossy = [v for v in self.values if float(f\"{v:.6f}\") != v]",
        "        lossy = []  # mutant",
        "permissive", "a record must survive its own round trip",
        ("test_telemetry_finer_than_the_wire_form_is_refused_at_the_boundary",),
    ),
    Mutant(
        "W3 the operator timestamp reads the process locale", "decision.py",
        '    return f"{utc:%H:%M} UTC on {utc.day:02d} {_MONTHS[utc.month - 1]}"',
        '    return f"{moment:%H:%M} UTC on {moment.day:02d} {_MONTHS[moment.month - 1]}"  # mutant',
        "permissive", "a portable record cannot depend on the reader's locale",
        ("test_the_same_instant_in_different_source_offsets_renders_identically",
         "test_a_deadline_is_not_rendered_in_the_producers_offset"),
    ),
    # =====================================================================
    # WAVE 4. Four auditors on the wave-3 result. These three are the joins
    # a walk, a claim's part and an instruction were each free of.
    # =====================================================================
    Mutant(
        "W4 a walk need not join up", "derivation.py",
        "            if arrived is None:",
        "            if False:  # mutant",
        "permissive", "a path with a hole in it is a conclusion with a hole in it",
        ("test_a_walk_whose_links_do_not_join_is_refused",),
    ),
    Mutant(
        "W4 the walk may start anywhere it likes", "derivation.py",
        "        reached_by: dict[str, set[object]] = {root: {_ROOTED}}",
        "        reached_by: dict[str, set[object]] = {s.subject: {_ROOTED} for s in self.steps}  # mutant",
        "permissive", "seeding from every step makes the reachability check vacuous",
        ("test_a_walk_whose_links_do_not_join_is_refused",),
    ),
    Mutant(
        "W4 the claim's part is asserted by nobody", "binding.py",
        "        if part != asserted_part:",
        "        if False:  # mutant",
        "permissive", "the part of a subject must be the part somebody asserted",
        ("test_a_claim_about_a_part_nobody_asserted_is_refused",),
    ),
    Mutant(
        "W4 the instruction may name a different machine", "candidate.py",
        "        if self.action.target not in named:",
        "        if False:  # mutant",
        "permissive", "the field an operator acts on must be one the record names",
        ("test_an_action_aimed_at_something_the_record_never_mentions_is_refused",),
    ),
    Mutant(
        "W4 a digest need not be a digest", "contract.py",
        "        if digest is not None and (",
        "        if False and (  # mutant",
        "permissive", "a value that cannot be a SHA-256 is not an integrity field",
        ("test_a_snapshot_whose_digest_is_not_a_digest_is_refused",),
    ),
    Mutant(
        "W4 the cited readings need not be the ones used", "contract.py",
        "            if uncited:",
        "            if False:  # mutant",
        "permissive", "the pointers a reader follows must be the readings replayed",
        ("test_a_snapshot_citing_readings_it_did_not_use_is_refused",),
    ),
    Mutant(
        # RE-ANCHORED and WIDENED. `recipient` joined the loop, so the construct is now
        # five lines and the anchor has to span all of them: replacing the opening line
        # alone would orphan the tuple entries and produce invalid Python.
        "W4 a clearance may match by emptiness", "candidate.py",
        '        for label, value in (\n'
        '            ("recipient", self.recipient),\n'
        '            ("purpose", self.purpose),\n'
        '            ("tenant", self.tenant),\n'
        '        ):',
        "        for label, value in ():  # mutant",
        "permissive", "blank recipient, purpose and tenant satisfy permits() vacuously",
        ("test_an_entitlement_with_a_blank_purpose_or_tenant_is_refused",),
    ),
    Mutant(
        "W4 a product may supersede itself", "product.py",
        "        if self.supersedes_product_id == self.product_id:",
        "        if False:  # mutant",
        "permissive", "a lineage cycle returns the reader to where they started",
        ("test_a_product_that_supersedes_itself_is_refused",),
    ),
    Mutant(
        "W4 perishability may be expressed by omission", "product.py",
        "            if self.valid_until is None:\n"
        "                raise ValueError(",
        "            if False:  # mutant\n"
        "                raise ValueError(",
        "permissive", "a delivered claim with no horizon never expires",
        ("test_a_delivered_claim_with_no_validity_horizon_is_refused",),
    ),
    Mutant(
        "W4 a withheld product may carry delivery prose", "product.py",
        "            if self.rendered_delivery is not None or self.delivery_time is not None:",
        "            if False:  # mutant",
        "permissive", "prose belongs to a delivery that happened",
        ("test_a_withheld_product_carrying_delivery_prose_is_refused",),
    ),
    Mutant(
        "W4 a decision may be taken at any time", "product.py",
        "            if self.assurance.release_decision_time != self.delivery_time:",
        "            if False:  # mutant",
        "permissive", "the rules in force are the ones in force at delivery",
        ("test_a_decision_taken_at_another_time_than_the_delivery_is_refused",),
    ),
    Mutant(
        "W4 identity conflicts wait behind the policy gate", "product.py",
        "        if conflicts and self.assurance.permitted:",
        "        if False:  # mutant",
        "permissive", "a conflict is not a threshold and blocks under any policy",
        ("test_a_payload_permitting_release_over_unresolved_identity_conflicts_is_refused",),
    ),
    Mutant(
        "W4 the snapshot may understate which feeds it used", "assessment.py",
        "    if declared != actual:",
        "    if False:  # mutant",
        "permissive", "the tuple the rights check tests must come from the readings",
        ("test_a_snapshot_understating_which_feeds_it_used_is_refused",),
    ),
    Mutant(
        # RE-ANCHORED. The rule lived in `formation.release` as an explicit refusal, and
        # that refusal is now unreachable: release takes the point-in-time view FROM the
        # log, so a reading the decision-maker had not received cannot be in the bundle.
        # The rule itself did not go away -- it moved to the import boundary, where
        # readings do still arrive from outside -- so the mutant moved with it rather than
        # being retired. A mutant deleted because its anchor moved is coverage silently
        # lost.
        "W4/CT2 a decision may rest on readings it had not received", "binding.py",
        "        if observation.transaction_time > context.knowledge_cutoff:",
        "        if False:  # mutant",
        "permissive", "point-in-time correctness is not a matter of assertion",
        ("test_a_reading_the_decision_had_not_received_is_refused_on_import",),
    ),
    Mutant(
        "W4 the evidence-strength floor does not project", "assessment.py",
        "    elif confidence < policy.min_evidence_strength:\n"
        "        support = Support.UNSUPPORTED",
        "    elif False:  # mutant\n"
        "        support = Support.UNSUPPORTED",
        "permissive", "release question five must reach the support dimension",
        ("test_a_claim_below_the_release_authority_floor_abstains",),
    ),
    Mutant(
        "W4 the evidence-strength floor gives no reason", "policy.py",
        "        if strength < self.min_evidence_strength:",
        "        if False:  # mutant",
        "permissive", "release question five must reach the policy's reasons",
        ("test_a_claim_below_the_release_authority_floor_abstains",),
    ),
    Mutant(
        "W4 bound inputs need not match the readings", "assessment.py",
        "            if source.value != b.value_used:",
        "            if False:  # mutant",
        "permissive", "fabricated inputs beside genuine readings must not deliver",
        ("test_bound_inputs_fabricated_beside_genuine_readings_are_refused",),
    ),
    Mutant(
        "W4 a confidence may be finer than its wire form", "candidate.py",
        '        if float(f"{self.confidence:.6f}") != self.confidence:',
        "        if False:  # mutant",
        "permissive", "release must not emit a record its own importer refuses",
        ("test_a_confidence_finer_than_the_wire_form_is_refused",),
    ),
    Mutant(
        "W4 downtime hours may be finer than their wire form", "consequence.py",
        '        if float(f"{self.expected_hours_lost:.2f}") != self.expected_hours_lost:',
        "        if False:  # mutant",
        "permissive", "the described value and the carried value must be one value",
        ("test_downtime_hours_finer_than_the_wire_form_are_refused",),
    ),
    Mutant(
        "W4 two rule versions for one walk", "binding.py",
        "        and evidence.semantic_rule_version != walk.rule_version",
        "        and False  # mutant",
        "permissive", "one question must not have two answers in one bundle",
        ("test_evidence_naming_different_semantic_rules_than_the_walk_is_refused",),
    ),
    Mutant(
        "W4 facts may be evaluated after the decision", "decision.py",
        "        if self.evaluation_time > self.model_decision_time:",
        "        if False:  # mutant",
        "permissive", "a decision cannot evaluate a moment that had not happened",
        ("test_facts_cannot_be_evaluated_as_true_after_the_decision_was_taken",),
    ),
    Mutant(
        "W4 the inputs need not be about the claim's metric", "binding.py",
        "    if pi.metric != claim.metric:",
        "    if False:  # mutant",
        "permissive", "the discriminators below the fingerprint must decide",
        ("test_a_fingerprint_that_matches_while_its_inputs_disagree_is_still_refused",),
    ),
    Mutant(
        "W4 the inputs need not cover the claim's horizon", "binding.py",
        "    if pi.horizon_seconds != claim.horizon_seconds:",
        "    if False:  # mutant",
        "permissive", "the discriminators below the fingerprint must decide",
        ("test_a_fingerprint_that_matches_while_its_inputs_disagree_is_still_refused",),
    ),
    # -----------------------------------------------------------------------
    # THIS INCREMENT. Each closes a defect the previous corpus could not express,
    # because the code it would have mutated did not exist yet.
    # -----------------------------------------------------------------------
    Mutant(
        "CT1 the log-to-release join is removed", "bitemporal.py",
        "        return EvidenceBundle(",
        "        return EvidenceBundle(observations=observations) or EvidenceBundle(  # mutant",
        "permissive", "release must see the contradictions the log found in its readings",
        ("test_an_integrity_conflict_reaches_the_release_path_and_withholds",
         "test_the_conflict_a_hand_built_bundle_would_have_hidden_still_withholds"),
    ),
    Mutant(
        "CT2 the carried evidence is not compared to the assessment", "product.py",
        "        if recorded.integrity is not recomputed.integrity:",
        "        if False:  # mutant",
        "permissive", "a record whose evidence contradicts its verdict must be refused",
        ("test_a_forged_record_refuses_for_the_invariant_it_actually_violates",),
    ),
    Mutant(
        "CT3 strict import accepts an unverifiable basis", "envelope.py",
        "    blocked = report.unverifiable()",
        "    blocked = []  # mutant",
        "permissive", "absence of a verification is not a verification",
        ("test_an_unknown_model_artifact_refuses_strict_import",
         "test_an_unknown_policy_refuses_strict_import"),
    ),
    Mutant(
        "CT4 the REASON sources leave the entitlement union", "assessment.py",
        "        | set(derivation.source_systems())",
        "        | set()  # mutant",
        "permissive", "a product must be licensed for every source that forms it",
        ("test_a_product_using_an_unlicensed_reason_source_is_refused",),
    ),
    Mutant(
        "CT4b the import union drops the REASON sources", "product.py",
        "                source_systems=material_source_systems(",
        "                source_systems=tuple(self.evidence.source_systems) or "
        "material_source_systems(  # mutant",
        "permissive", "both boundaries must check the same entitlement scope",
        ("test_historical_import_re_runs_the_same_entitlement_source_union",),
    ),
    Mutant(
        "CT5 the deadline is rendered in the producer's offset", "decision.py",
        "    utc = moment.astimezone(timezone.utc)",
        "    utc = moment  # mutant",
        "permissive", "one instant must render as one deadline for every reader",
        ("test_the_same_instant_in_different_source_offsets_renders_identically",),
    ),
    Mutant(
        # THIS MUTANT WAS PATCHING A DIFFERENT SITE FROM THE ONE IT NAMED.
        #
        # The anchor was the bare `if key in seen:`, which occurs twice in envelope.py:
        # once in `_check_status_events` at line 365, and once in `no_duplicate_keys` at
        # line 763. `str.replace(find, replace, 1)` takes the FIRST, so CT6 mutated the
        # duplicate STATUS EVENT check while its name, its rationale ("one text must
        # denote one record") and the JSON path it claimed to guard all described the
        # second site.
        #
        # It reported killed every time, because its declared killer is the status-event
        # test, which does fail when the status-event check is removed. Internally
        # consistent, correctly green, and covering something other than what the corpus
        # said. That is the stale-attribution class this harness already carries scar
        # tissue from: green in aggregate, guarding a different thing.
        #
        # The JSON path was never uncovered in fact -- the suite asserts it directly and
        # the source-derived generator mutates that condition too. What was wrong was the
        # corpus's own bookkeeping. Split into the two mutants the two sites deserve.
        "CT6 duplicate JSON keys are resolved rather than refused", "envelope.py",
        "        for key, _ in pairs:\n"
        "            if key in seen:",
        "        for key, _ in pairs:\n"
        "            if False:  # mutant",
        "permissive", "one text must denote one record",
        ("test_a_duplicate_json_key_is_refused_by_both_text_apis",),
    ),
    Mutant(
        # The site CT6 was actually hitting, now declared on its own terms.
        "CT6b a duplicate status event is folded rather than refused", "envelope.py",
        "            key = (event.event_type.value, event.at.isoformat(), event.replacement_product_id)\n"
        "            if key in seen:",
        "            key = (event.event_type.value, event.at.isoformat(), event.replacement_product_id)\n"
        "            if False:  # mutant",
        "permissive", "a sequence that records one fact twice is not one history",
        ("test_a_duplicate_status_event_is_refused",),
    ),
    Mutant(
        "CT7 the published schema is not run", "envelope.py",
        "    validate_against_schema(payload)",
        "    pass  # mutant",
        "permissive", "a schema called normative and never run is a second universe",
        ("test_a_structurally_malformed_payload_is_refused_by_the_published_schema",),
    ),
    Mutant(
        "CT8 the trail and the outcome may disagree about when", "envelope.py",
        "        if observed_state.at != self.outcome.observed_at:",
        "        if False:  # mutant",
        "permissive", "one event cannot have happened at two moments",
        ("test_the_lifecycle_moment_and_the_outcome_moment_cannot_disagree",),
    ),
    Mutant(
        "CT8b the outcome window is open at the far end", "action.py",
        "        if not self.observation_window.contains(self.observed_at):",
        "        if self.observed_at < self.observation_window.start:  # mutant",
        "permissive", "an outcome outside its window is counted against the wrong period",
        ("test_an_outcome_outside_its_half_open_window_is_refused",),
    ),
    Mutant(
        "CT9 the metric/subject pair is not validated", "binding.py",
        "        if not envelope.admits_pair(claim.metric, asserted_type):",
        "        if False:  # mutant",
        "permissive", "the cross-product is not the declaration",
        ("test_an_individually_valid_metric_and_subject_type_can_still_be_an_invalid_pair",
         "test_import_enforces_the_same_pair_semantics"),
    ),
    Mutant(
        "CT10 the walk's relations need not follow one another", "derivation.py",
        "            if not arrived & set(permitted):",
        "            if False:  # mutant",
        "permissive", "a connected walk whose relations do not follow justifies nothing",
        ("test_a_relabelled_but_connected_walk_is_refused",
         "test_each_relation_may_only_continue_from_where_it_belongs"),
    ),
    Mutant(
        "CT10b the walk need only mention the observed asset", "binding.py",
        "    if walk.root_entity != observed:",
        "    if observed not in walk.entities():  # mutant",
        "permissive", "a walk about one asset that mentions another is not about it",
        ("test_the_walk_must_be_rooted_at_the_observed_asset_not_merely_mention_it",),
    ),
]



@dataclass
class SuiteResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    collected: int = 0
    failing: set[str] = field(default_factory=set)

    @property
    def is_well_formed(self) -> bool:
        """The suite ran as a suite, rather than falling over during collection."""
        return self.errors == 0 and self.collected > 0


def _purge_bytecode() -> None:
    """Remove every `__pycache__` under the tree.

    WHY THIS IS NOT PARANOIA
    ------------------------
    CPython decides a cached `.pyc` is current from the source's mtime and SIZE. A mutant
    that replaces a line with one of the same length, applied and restored inside the same
    second, leaves a `.pyc` that looks current and is not -- so the NEXT run imports the
    mutated bytecode from a pristine source file.

    That is not a hypothetical: it produced a false surviving mutant and then a false
    "the tree did not return to its baseline state" on a tree `git status` reported clean,
    with the correct source visible in the file. A harness whose whole purpose is
    producing evidence cannot have a failure mode that manufactures both false negatives
    and false alarms from nothing.
    """
    for cache in ROOT.rglob("__pycache__"):
        if ".git" not in cache.parts:
            shutil.rmtree(cache, ignore_errors=True)


def run_suite() -> SuiteResult:
    """Run the suite and parse enough to tell a real kill from an accident."""
    _purge_bytecode()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "-p", "no:randomly"],
        capture_output=True, text=True, cwd=ROOT,
        # Belt and braces with the purge above: nothing written, nothing to go stale.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    out = proc.stdout + proc.stderr
    result = SuiteResult()
    if m := re.search(r"(\d+) failed", out):
        result.failed = int(m.group(1))
    if m := re.search(r"(\d+) passed", out):
        result.passed = int(m.group(1))
    if m := re.search(r"(\d+) errors?", out):
        result.errors = int(m.group(1))
    # "collected N items" appears on a clean run; on a collection failure pytest says
    # "collected N items / M errors", which the errors capture above picks up.
    if m := re.search(r"collected (\d+) item", out):
        result.collected = int(m.group(1))
    else:
        # -q suppresses the collected line on success; total tests is the sum.
        result.collected = result.passed + result.failed
    # "FAILED tests/test_x.py::test_name[param]" -> "test_name[param]"
    result.failing = set(re.findall(r"^FAILED \S+?::(\S+)", out, re.M))
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_failures(
    *,
    survivors: list[str],
    invalid: list[str],
    unverified: list[str],
    baseline_restored: bool,
) -> list[str]:
    """Every reason this curated run fails the Phase-5 criterion. Empty means it passes.

    WHAT A ZERO EXIT FROM THIS HARNESS USED TO MEAN, AND WHAT IT NOW MEANS.

    A killed mutant with no declared `expect_failing` was appended to `unverified`,
    printed under the heading "weaker evidence", and the process then returned 0 anyway.
    So the output said one thing to a reader and the exit status said a stronger thing to
    every automated caller, and the exit status is what a gate consumes.

    `expect_failing` is the whole difference between "something went red" and "this named
    test caught this specific mutation". Phase 5 requires the curated corpus to pass WITH
    that attribution, so an unattributed kill cannot be a sentence in a report while the
    process reports success.

    A pure function over the four collected facts, so both polarities are testable without
    running the corpus. `baseline_restored` is a parameter rather than an assumption
    because a run that leaves the tree dirty has not demonstrated anything about the
    package, however the mutants scored.
    """
    reasons: list[str] = []
    if not baseline_restored:
        reasons.append("the tree did not return to its baseline state")
    for name in survivors:
        reasons.append(f"SURVIVED, nothing caught it: {name}")
    for name in invalid:
        reasons.append(f"INVALID, no verdict was reached: {name}")
    for name in unverified:
        reasons.append(f"KILLED BUT UNATTRIBUTED, no declared signature: {name}")
    return reasons


def main() -> int:
    baseline = run_suite()
    print(f"baseline: {baseline.passed} passed, {baseline.failed} failed, "
          f"{baseline.collected} collected\n")
    if baseline.failed or not baseline.is_well_formed:
        print("suite is not green; fix that before mutating.")
        return 1

    survivors: list[str] = []
    invalid: list[str] = []
    unverified: list[str] = []

    print(f"{'mutant':<38} {'direction':<13} {'killed':<8} {'tests':<7} verified")
    print("-" * 84)

    for mutant in MUTANTS:
        target = SRC / mutant.file
        original = target.read_text()
        before_hash = sha(target)

        if mutant.find not in original:
            print(f"{mutant.name:<38} {mutant.direction:<13} {'SKIP':<8} "
                  f"{'-':<7} anchor not found")
            survivors.append(f"{mutant.name} (anchor missing -- harness is stale)")
            continue

        # AN ANCHOR THAT MATCHES TWICE PATCHES WHICHEVER COMES FIRST, SILENTLY.
        #
        # `replace(..., 1)` takes the first occurrence, so a `find` string that is not
        # unique mutates a site the declaration may not be describing. CT6 did exactly
        # that for the life of this corpus: named for the JSON duplicate-key path, it
        # patched a duplicate status-event check four hundred lines earlier, and reported
        # killed every run because its declared killer matched the site it hit rather than
        # the site it named.
        #
        # The file already carried a hand-written warning about a prefix collision on one
        # specific mutant. A comment guards one case; this guards the class.
        occurrences = original.count(mutant.find)
        if occurrences > 1:
            print(f"{mutant.name:<38} {mutant.direction:<13} {'SKIP':<8} "
                  f"{'-':<7} anchor matches {occurrences} sites")
            invalid.append(
                f"{mutant.name} (anchor is not unique: {occurrences} matches in "
                f"{mutant.file}; it would patch whichever comes first)"
            )
            continue

        try:
            target.write_text(original.replace(mutant.find, mutant.replace, 1))
            result = run_suite()
        finally:
            target.write_text(original)

        after_hash = sha(target)
        if after_hash != before_hash:
            print(f"\nFATAL: {mutant.file} was not restored "
                  f"({before_hash[:12]} -> {after_hash[:12]}). Aborting.")
            return 2

        # A mutant that breaks collection did not demonstrate anything about behaviour.
        if not result.is_well_formed or result.collected != baseline.collected:
            print(f"{mutant.name:<38} {mutant.direction:<13} {'INVALID':<8} "
                  f"{result.failed:<7} collection changed "
                  f"({baseline.collected} -> {result.collected}, "
                  f"{result.errors} errors)")
            invalid.append(
                f"{mutant.name} -- broke collection rather than behaviour; "
                f"this proves nothing"
            )
            continue

        killed = result.failed > 0
        if not killed:
            print(f"{mutant.name:<38} {mutant.direction:<13} {'NO':<8} "
                  f"{result.failed:<7} -")
            survivors.append(f"{mutant.name} -- {mutant.must_fail_because}")
            continue

        if not mutant.expect_failing:
            print(f"{mutant.name:<38} {mutant.direction:<13} {'yes':<8} "
                  f"{result.failed:<7} (signature not declared)")
            unverified.append(f"{mutant.name} -- killed, but by unspecified tests")
            continue

        expected = set(mutant.expect_failing)
        # ANCHORED, not substring. `any(e in f for f in failing)` let a DIFFERENT test
        # satisfy a declared signature merely by containing its name, which is the one
        # failure mode a harness reporting "verified against a declared failure signature"
        # must not have. A live collision already existed:
        # `test_an_unknown_schema_version_is_refused` is a substring of
        # `test_an_unknown_schema_version_is_refused_not_guessed`. It happened not to fire.
        #
        # The split strips a parametrised case id, so a mutant declared against a
        # parametrised test is still attributed to it.
        failing_names = {f.split("[")[0] for f in result.failing}
        matched = expected & failing_names
        if matched != expected:
            missing = ", ".join(sorted(expected - matched))
            print(f"{mutant.name:<38} {mutant.direction:<13} {'WRONG':<8} "
                  f"{result.failed:<7} expected {missing}")
            survivors.append(
                f"{mutant.name} -- died, but not to the test that claims to guard it "
                f"(missing: {missing})"
            )
            continue

        print(f"{mutant.name:<38} {mutant.direction:<13} {'yes':<8} "
              f"{result.failed:<7} {len(expected)} declared")

    final = run_suite()
    print("-" * 84)
    print(f"restored: {final.passed} passed, {final.failed} failed, "
          f"{final.collected} collected")
    if final.failed or final.collected != baseline.collected:
        print("\nFATAL: the tree did not return to its baseline state.")
        return 2

    conservative = sum(1 for m in MUTANTS if m.direction == "conservative")
    permissive = sum(1 for m in MUTANTS if m.direction == "permissive")
    verified = sum(1 for m in MUTANTS if m.expect_failing)
    if not survivors and not invalid:
        print(f"\nall {len(MUTANTS)} mutants killed "
              f"({conservative} conservative, {permissive} permissive); "
              f"{verified} verified against a declared failure signature")

    failures = gate_failures(
        survivors=survivors, invalid=invalid, unverified=unverified,
        baseline_restored=True,
    )
    if failures:
        print(f"\nGATE FAILED: {len(failures)} condition(s) unmet")
        for reason in failures:
            print(f"  - {reason}")
        if unverified:
            print("\nDeclare the killing test(s) in each mutant's `expect_failing`. Do "
                  "not remove a mutant to make this pass.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
