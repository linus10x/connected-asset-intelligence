"""What the package promises, pinned to a literal list.

WHY THIS FILE EXISTS
--------------------
`cai/__init__.py` says `__all__` is the contract and everything else is implementation.
Nothing enforced that. The list could gain a name in a refactor, lose one in a rename,
or -- as it did -- carry a pair whose semantics did not belong on a public boundary at
all, and no test would have noticed any of the three.

A structural test over a declared surface is the one place where writing the answer down
twice is correct. Everywhere else in this package a second copy of a fact is the drift
surface being removed; here the second copy IS the check, because the property under test
is "this list changed", and a rule derived from the list cannot detect that.

WHAT THIS DOES NOT CLAIM
------------------------
Not that every name is well designed, and not that the implementation is hidden. Python
has no private modules and this package does not pretend otherwise: `cai.assessment`,
`cai.binding` and the rest remain importable and always will. The claim is narrower and
checkable -- that the set of names this package undertakes to keep working is exactly
this set, and that changing it is a deliberate edit to a test rather than a side effect.
"""

from __future__ import annotations

import inspect

import pytest

import cai

# The producer surface: what a caller needs to build a candidate, assemble the four
# assertions, and release. One entry point actually produces a product.
PRODUCING = {
    "ActionRecommendation", "ActionType", "Priority",
    "ApplicabilityAssertion", "AssuranceContext", "AssuranceDecision",
    "BusinessConsequence", "ConsequenceDerivation", "ContextGraph",
    "CustomerCommitmentConsequence", "DecisionContext", "DerivationRelationship",
    "DerivationStep", "DowntimeConsequence", "EntitlementAssertion",
    "EvidenceAssessment", "EvidenceBundle", "EvidenceSnapshot", "IdentityAssertion",
    "IntelligenceCandidate", "IntelligenceProduct", "ModelEnvelope", "Observation",
    "ObservationLog", "PredictionClaim", "PredictionInputs", "ReleasePolicy",
    "RenderedDelivery", "TemporalAssertion", "TimeInterval",
    "declared_envelope", "digest_observations", "format_moment",
    "predict_degradation", "release",
}

# The reader surface: four entry points, plus the types needed to branch on what they
# return.
READING = {
    "Determination", "DimensionVerification", "DispositionEvent", "DispositionState",
    "HistoricalEnvelopeImport", "IntelligenceEnvelope", "MalformedEnvelopeText",
    "OutcomeObservation", "OutcomeType", "ProductLifecycle", "ProductStatus",
    "SchemaViolation", "StatusEvent", "StatusEventType", "UnverifiableBasis",
    "VerificationDimension", "VerificationReport", "VerificationState",
    "import_envelope", "import_historical_envelope", "json_schema", "parse_envelope",
    "parse_historical_envelope", "validate_against_schema",
}

# Defined in `cai.assessment`, deliberately not promised on the package.
INTERNAL_ASSESSMENT_HELPERS = (
    "assess_release_evidence",
    "assess_imported_evidence",
    "imported_integrity_findings",
    "material_source_systems",
)


def test_the_declared_surface_is_exactly_this():
    """A literal inventory. Any addition or removal fails here first."""
    assert set(cai.__all__) == PRODUCING | READING


def test_every_promised_name_actually_resolves():
    """`__all__` entries are strings, so a typo or a deleted name is silent until a
    caller hits it -- or until `from cai import *` raises somewhere else entirely."""
    missing = [name for name in cai.__all__ if not hasattr(cai, name)]
    assert not missing, f"promised but not importable: {missing}"


def test_the_declared_surface_has_no_duplicates():
    assert len(cai.__all__) == len(set(cai.__all__))


@pytest.mark.parametrize("name", INTERNAL_ASSESSMENT_HELPERS)
def test_the_assessment_helpers_are_not_package_level_api(name):
    """THE FINDING, PINNED.

    `assess_imported_evidence` returns an ordinary `EvidenceAssessment` and skips the
    claim replay when this build cannot reproduce the model that produced the record.
    The verification-state distinction is added afterwards by the historical import
    operation -- so a caller of the helper alone got an object that looks like a
    completed verification and is not one.

    Both halves are asserted. Absent from the promise, and absent from the package
    namespace too: a name bound on `cai` while `__all__` denies it is the ambiguity that
    made this necessary, restated one level down.
    """
    assert name not in cai.__all__
    assert not hasattr(cai, name)


@pytest.mark.parametrize("name", INTERNAL_ASSESSMENT_HELPERS)
def test_the_assessment_helpers_are_still_importable_from_their_module(name):
    """TWIN. Narrowing the promise, not deleting the functions.

    The restored compatibility names stay exactly where they are defined. A build that
    achieved the test above by deleting them would pass it and would have removed working
    implementation to satisfy a surface question.
    """
    import cai.assessment

    assert callable(getattr(cai.assessment, name))


def test_no_promised_callable_accepts_a_verification_waiver():
    """The rule `cai/__init__.py` says is enforced rather than documented.

    `tests/test_historical_import.py` sweeps every module for this. Repeated over the
    declared surface specifically, because that is the set this package undertakes to
    keep working -- and a waiver reachable through a promised name is worse than one
    reachable through an implementation detail.
    """
    offenders = []
    for name in cai.__all__:
        obj = getattr(cai, name)
        for attribute in (obj, *(
            getattr(obj, m) for m in dir(obj)
            if not m.startswith("_") and callable(getattr(obj, m, None))
        )):
            try:
                parameters = inspect.signature(attribute).parameters
            except (TypeError, ValueError):
                continue
            for waiver in ("replay_claim", "accept_unverifiable_basis", "skip_replay",
                           "trust_record", "verify"):
                if waiver in parameters:
                    offenders.append(f"{name}: {waiver}")
    assert not offenders, f"public names accepting a verification waiver: {offenders}"


def test_the_four_reader_entry_points_are_promised():
    """Named individually, because the narrowing above is only honest if the boundaries
    it points callers at are themselves guaranteed."""
    for entry in ("parse_envelope", "parse_historical_envelope",
                  "import_envelope", "import_historical_envelope"):
        assert entry in cai.__all__
        assert callable(getattr(cai, entry))


def test_release_is_the_function_not_the_module():
    """`cai.assessment` is a module and `release` is a function in `cai.formation`.
    Exporting the function binds the name on the package, which is the right way round
    and is the sort of shadowing that costs somebody an afternoon when it is not written
    down."""
    assert inspect.isfunction(cai.release)
    assert cai.release.__module__ == "cai.formation"
