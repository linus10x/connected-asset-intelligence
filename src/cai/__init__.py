"""A portable decision record for connected-asset intelligence products.

WHY THIS FILE EXISTS AT ALL
---------------------------
It did not, and the absence kept deciding design questions.

Twice in one audit the same fact was argued in opposite directions. Six names had been
deleted as "not part of the supported surface" and were restored, correctly, on the
grounds that this package declares no surface -- so every module-level name is importable
and therefore public. Then a verification seam was defended as "not a supported entry
point" on the grounds that no reasonable caller would reach it. Both arguments cannot be
right, and an auditor should not have to adjudicate which one applies today.

So the surface is written down. Everything named in `__all__` is the contract. Everything
else in `cai.*` is implementation, and a caller who imports it is on their own -- which is
now a structural statement about this file rather than an opinion in a review.

WHAT THIS IS NOT
----------------
Not an SDK, and deliberately small. No convenience wrappers, no facade objects, no
re-exported helpers "for completeness". Two things go in: what a producer needs to build
and release a product, and what a reader needs to import one and branch on what they find.

NOTHING IS REMOVED BY THIS FILE. Every name that was importable yesterday is importable
today from the module that defines it, including the six that were restored. `__all__`
says which of them this package will keep working, not which of them exist.

ONE NAME COLLIDES, AND IT IS WORTH KNOWING ABOUT
------------------------------------------------
`cai.assessment` is a module. `release()` is the entry point that produces a product, and it
lives in `cai.formation`. Exporting the function here binds the name `release` on the
package, so `from cai import release` gives you the FUNCTION.

That is the right way round -- the function is the documented entry point and the module
is implementation -- but a reader who wanted the module has to say `import cai.assessment` or
`from cai.assessment import ...`, both of which still work exactly as before. Written down
here rather than left to be discovered, because a silent shadowing is the sort of thing
that costs somebody an afternoon.

THE ONE RULE THAT IS ENFORCED RATHER THAN DOCUMENTED
-----------------------------------------------------
No public name accepts a verification waiver. `assess_evidence(..., replay_claim=False)`
was reachable while `replay_claim` sat on a public signature; the implementation is
underscored now and the two entry points below decide replay by construction.
`tests/test_historical_import.py` sweeps every public callable in every module for that
parameter and any other waiver, so the rule holds for names this file never mentions.
"""

from __future__ import annotations

# --- producing a product -------------------------------------------------
from .action import ActionRecommendation, ActionType, OutcomeObservation, OutcomeType, Priority
from .bitemporal import EvidenceBundle, Observation, ObservationLog, digest_observations
from .candidate import (
    ApplicabilityAssertion,
    AssuranceContext,
    EntitlementAssertion,
    IdentityAssertion,
    IntelligenceCandidate,
    TemporalAssertion,
)
from .consequence import (
    BusinessConsequence,
    CustomerCommitmentConsequence,
    DowntimeConsequence,
)
from .context import ContextGraph
from .contract import EvidenceSnapshot, PredictionClaim, PredictionInputs
from .decision import DecisionContext, TimeInterval, format_moment
from .delivery import AssuranceDecision, RenderedDelivery
from .derivation import ConsequenceDerivation, DerivationRelationship, DerivationStep
from .evidence import EvidenceAssessment
from .formation import release
from .lifecycle import DispositionEvent, DispositionState, ProductLifecycle
from .policy import ReleasePolicy
from .predictor import ModelEnvelope, declared_envelope, predict_degradation
from .product import Determination, IntelligenceProduct, ProductStatus, UnverifiableBasis

# --- reading one back ----------------------------------------------------
from .envelope import (
    HistoricalEnvelopeImport,
    IntelligenceEnvelope,
    MalformedEnvelopeText,
    SchemaViolation,
    StatusEvent,
    StatusEventType,
    import_envelope,
    import_historical_envelope,
    json_schema,
    parse_envelope,
    parse_historical_envelope,
    validate_against_schema,
)
from .verification import (
    DimensionVerification,
    VerificationDimension,
    VerificationReport,
    VerificationState,
)

__all__ = [
    # producing
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
    # reading back
    "Determination", "DimensionVerification", "DispositionEvent", "DispositionState",
    "HistoricalEnvelopeImport", "IntelligenceEnvelope", "MalformedEnvelopeText",
    "OutcomeObservation", "OutcomeType", "ProductLifecycle", "ProductStatus",
    "SchemaViolation", "StatusEvent", "StatusEventType", "UnverifiableBasis",
    "VerificationDimension", "VerificationReport", "VerificationState",
    "import_envelope", "import_historical_envelope", "json_schema", "parse_envelope",
    "parse_historical_envelope", "validate_against_schema",
]

# WHY THE TWO ASSESSMENT HELPERS ARE NOT ABOVE
# --------------------------------------------
# `assess_imported_evidence` and `assess_release_evidence` were exported here and were
# the one pair that could not honestly be. They return an ordinary `EvidenceAssessment`,
# and the imported one skips the claim replay when this build cannot reproduce the
# foreign model that produced the record. The distinction between "checked" and "could
# not be checked" is added AFTERWARDS, by the historical import operation, which wraps
# the answer in a `VerificationReport`.
#
# So a caller of the package-level helper received a verification-shaped object with the
# verification-state distinction stripped off -- the exact seam this package refuses
# everywhere else, reached through the front door rather than a keyword argument.
#
# Narrowing rather than changing them, because the functions are correct: they are
# implementation of the two boundaries, and the boundaries are what callers should hold.
# One producer entry point, `release`. Four reader entry points, `parse_envelope`,
# `parse_historical_envelope`, `import_envelope`, `import_historical_envelope`. Each of
# those either verifies fully or hands back a report saying what it could not verify, and
# neither is a thing a caller can accidentally do half of.
#
# Both names remain exactly where they are defined and are unchanged:
#
#     from cai.assessment import assess_release_evidence
#
# still works. What is gone is the promise that `cai.assess_release_evidence` is a stable
# package-level API. The package-level binding goes with it rather than being left in
# place, because a name bound on the package while `__all__` says it is not public
# recreates precisely the ambiguity this file was written to end.
