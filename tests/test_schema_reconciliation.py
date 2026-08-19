"""Every constructor-level invariant, and what the published schema does about it.

WHY A TABLE RATHER THAN MORE EXAMPLES
--------------------------------------
The previous pass fixed six schema/domain mismatches by finding them one at a time. Six
were fixed and the seventh was found by the next reviewer, which is the signature of a
method that does not terminate: each round produces the mismatches somebody happened to
look for, and nothing says how many are left.

The set that matters is enumerable. Every rule the typed domain enforces at construction
is a `raise` inside a `__post_init__` or a `_check*` helper it calls, and those can be
counted from the AST. So this file counts them, requires a written disposition for each,
and fails when the count and the table disagree. Adding a check to the domain without
saying what the wire does about it now breaks a test.

THE THREE DISPOSITIONS
----------------------
A -- EXPRESSIBLE IN JSON SCHEMA, and therefore expressed. Types, nullability, closed
     vocabularies, minimum lengths, and conditionals over sibling keys of one object.
     These MUST be in `json_schema()`; a rule the schema could state and does not is a
     record another implementation will publish and this one will refuse.

B -- CROSS-FIELD OR RECOMPUTED, enforced by reconstructing the typed domain on import.
     Equality between two values in different subtrees, a digest recomputed over content,
     a claim replayed against a model. JSON Schema has no vocabulary for any of these,
     and writing a second hand-rolled validator to cover them would be the two-semantics-
     engines mistake this package refuses everywhere. Each names a rule in the schema's
     own `x-semantic-validations` list, so an implementer reading only the schema learns
     what they still owe.

C -- PRODUCER-ONLY, not part of portable conformance. Python type checks on objects that
     never cross the wire, and float-precision guards on values the wire form has already
     quantized. Putting these in the schema would describe constraints on a
     representation that does not exist.

WHAT THIS FILE DOES NOT CLAIM
-----------------------------
Not that the schema ENFORCES every A rule correctly -- that is what the STRUCTURAL corpus
in `test_wire.py` is for, and it carries a negative example per rule it covers. This one
asserts that every invariant has been classified, that no A rule points at a location the
schema does not describe, and that no B rule names a semantic obligation the schema fails
to publish. It is a completeness check over the classification, not a proof of the
implementation.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from cai.envelope import json_schema

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "src" / "cai"

# The types whose portable form is part of the contract. `policy`, `binding`, `assessment`
# and `canonical` are absent because they define no portable dataclass -- they are the
# functions the boundaries call, and their rules land on the types below.
PORTABLE_MODULES = (
    "contract", "candidate", "decision", "action", "consequence", "derivation",
    "delivery", "evidence", "bitemporal", "product", "envelope", "predictor",
    "lifecycle", "verification",
)

P = "/properties/product"
CAND = f"{P}/properties/candidate"
CLAIM = f"{CAND}/properties/prediction_claim"
CTX = f"{CAND}/properties/context"
ACTION = f"{CAND}/properties/action"
CONSEQ = f"{CAND}/properties/business_consequence"
WALK = f"{CONSEQ}/properties/derivation"
STEP = f"{WALK}/properties/steps/items"
ASSUR = f"{P}/properties/assurance"
CONTEXT = f"{ASSUR}/properties/assurance_context"
ASSESS = f"{CONTEXT}/properties/evidence"
EVID = f"{P}/properties/evidence"
INPUTS = f"{EVID}/properties/prediction_inputs"
BUNDLE = f"{P}/properties/release_evidence"
OBS = f"{BUNDLE}/properties/observations/items"

# Shorthands for the semantic rules an entry may cite. Each must appear verbatim as a
# substring of some rule in the schema's own x-semantic-validations list.
S_CUTOFF = "knowledge_cutoff <= model_decision_time"
S_WINDOW = "prediction_window_end > prediction_window_start"
S_TZ = "all timestamps are timezone-aware"
S_HORIZON = "the claim's horizon equals the prediction window's duration"
S_EXPOSURE = "business_consequence.exposure_window overlaps the prediction window"
S_OPWINDOW = "action.operational_window overlaps the consequence's exposure window"
S_DUEBY = "action.due_by falls no later than its operational window closes"
S_ENVELOPE = "the claim's metric and horizon fall inside its own declared_envelope"
S_REPLAY = "the claim replays"
S_FINGERPRINT = "input_fingerprint is the fingerprint OF the recorded inputs"
S_TERMINAL = "the consequence's derivation terminates at the consequence's own subject"
S_WALKCLOCK = "the derivation's cutoff and window are the decision context's"
S_DELIVERED = "determination=DELIVERED requires assurance.permitted=true"
S_ABSTAINED = "determination=ABSTAINED requires at least one blocking reason"
S_PERMITTED = "assurance.permitted=true requires an empty blocking_reasons"
S_POLICY = "re-running the named release policy over the recorded assurance basis"
S_CAPTURED = "evidence.captured_at does not postdate delivery_time"
S_VALIDUNTIL = "valid_until, when present, postdates delivery_time"
S_DIGEST = "rendered_delivery.content_digest verifies against renderer_version"
S_SCOPE = "entitlement scope is re-checked against the product's own recipient"
S_DERIVED = "derived values on the wire"
S_TRAIL = "lifecycle events open at DELIVERED"
S_OUTCOME = "outcome.subject is the claim's subject"
S_STATUS = "status events are chronological"
S_EFFECT = "attributed_effect is NOT_ESTABLISHED"
S_DEADLINE = "no product is actionable after action.due_by"
S_CLOCKS = "model_decision_time <= release_decision_time for every determination"
S_WITHHELD = "an ABSTAINED product carries no lifecycle events"
S_ONEMOMENT = "the trail's opening event is timestamped exactly delivery_time"
S_CARDINALITY = "the walk carries at most one step per relationship"
S_CHAIN = "a CUSTOMER_COMMITMENT walk carries ASSIGNED_TO, SUPPORTS, LOADS and FULFILLS"
S_STEPCLOCK = "every derivation step was recorded by the knowledge cutoff"
S_STEPSCOPE = "a step's validity interval is in force when the loading window opens"
S_INTEGRITY = "an integrity conflict names two readings sharing an observation id"
S_UNIQUE = "observation ids are unique within the bundle"

# --- THE TABLE -----------------------------------------------------------
# (invariant, disposition, where)
#   A -> a JSON Pointer into json_schema() that must resolve
#   B -> a substring of one of the schema's x-semantic-validations rules
#   C -> a reason the wire form cannot express or cannot violate it
RECONCILIATION: dict[str, tuple[tuple[str, str, str], ...]] = {
    "cai.contract.PredictionClaim": (
        ("score is a finite number", "A", f"{CLAIM}/properties/score"),
        ("horizon_seconds is positive", "A", f"{CLAIM}/properties/horizon_seconds"),
        ("evidence_strength is in [0, 1]", "A", f"{CLAIM}/properties/evidence_strength"),
        ("declared_envelope is a typed ModelEnvelope", "A",
         f"{CLAIM}/properties/declared_envelope"),
        ("the envelope's model_version is the claim's", "B", S_ENVELOPE),
        ("the envelope's artifact digest is the claim's", "B", S_ENVELOPE),
        ("the envelope admits the claim's metric", "B", S_ENVELOPE),
        ("the envelope admits the claim's horizon", "B", S_ENVELOPE),
    ),
    "cai.contract.PredictionInputs": (
        ("bound_inputs is non-empty", "A", f"{INPUTS}/properties/bound_inputs"),
        ("the bound values are the values scored", "B", S_FINGERPRINT),
        ("values survive the six-decimal wire form", "C",
         "the wire carries fixed six-decimal strings, so a conforming record has already "
         "been quantized and cannot express the lossy float this refuses"),
    ),
    "cai.contract.EvidenceSnapshot": (
        ("captured_at is present", "A", f"{EVID}/properties/captured_at"),
        ("captured_at is timezone-aware", "A", f"{EVID}/properties/captured_at"),
        ("identity_confidence is in [0, 1]", "A",
         f"{EVID}/properties/identity_confidence"),
        ("evidence_content_digest is 64 lowercase hex", "A",
         f"{EVID}/properties/evidence_content_digest"),
        ("every bound input is a cited observation", "B", S_FINGERPRINT),
    ),
    "cai.candidate.IdentityAssertion": (
        ("confidence is in [0, 1]", "A", f"{CONTEXT}/properties/identity/properties/confidence"),
        ("resolver is named", "A", f"{CONTEXT}/properties/identity/properties/resolver"),
        ("confidence survives the six-decimal wire form", "C",
         "the wire carries a fixed six-decimal string; a conforming record is already "
         "quantized"),
    ),
    "cai.candidate.ApplicabilityAssertion": (
        ("basis is stated", "A", f"{CONTEXT}/properties/applicability/properties/basis"),
        ("subject_type is stated", "A",
         f"{CONTEXT}/properties/applicability/properties/subject_type"),
    ),
    "cai.candidate.TemporalAssertion": (
        ("a valid assertion's feature cutoff does not exceed its knowledge cutoff", "B",
         S_CUTOFF),
        ("basis is stated", "A", f"{CONTEXT}/properties/temporal/properties/basis"),
        ("its three moments are timezone-aware", "A",
         f"{CONTEXT}/properties/temporal/properties/model_decision_time"),
    ),
    "cai.candidate.EntitlementAssertion": (
        ("basis and policy_id are stated", "A",
         f"{CONTEXT}/properties/entitlement/properties/basis"),
        ("policy_version is stated", "A",
         f"{CONTEXT}/properties/entitlement/properties/policy_version"),
        ("valid_to postdates valid_from", "B", S_SCOPE),
        ("recipient, purpose and tenant are non-empty", "A",
         f"{CONTEXT}/properties/entitlement/properties/recipient"),
        ("its validity moments are timezone-aware", "A",
         f"{CONTEXT}/properties/entitlement/properties/valid_from"),
    ),
    "cai.candidate.AssessedAssurance": (
        ("the evidence assessment is typed", "C",
         "an in-memory type check; the wire carries an object the importer reconstructs "
         "through EvidenceAssessment, so no payload can substitute another type"),
        ("the assurance context is typed", "C",
         "as above, for the context object"),
    ),
    "cai.candidate.IntelligenceCandidate": (
        ("prediction_claim is a typed PredictionClaim, never prose", "C",
         "the structural refusal of author-supplied prose is a Python type check; the "
         "wire equivalent is the claim object's own required shape"),
        ("candidate_id is stated", "A", f"{CAND}/properties/candidate_id"),
        ("the consequence is actionable", "B", S_DERIVED),
        ("the prediction window overlaps the exposure window", "B", S_EXPOSURE),
        ("the claim's horizon is the context's window duration", "B", S_HORIZON),
        ("the walk's cutoff is the decision's", "B", S_WALKCLOCK),
        ("the walk's window is the decision's", "B", S_WALKCLOCK),
        ("the action is not due before the model decided", "B", S_DEADLINE),
        ("the action's operational window overlaps the exposure", "B", S_OPWINDOW),
        ("the action targets something the record names", "B", S_TERMINAL),
    ),
    "cai.decision.TimeInterval": (
        ("the interval does not run backwards", "B", S_WINDOW),
        ("the interval is not zero-length", "B", S_WINDOW),
        ("both ends are timezone-aware", "A", f"{CTX}/properties/prediction_window_start"),
    ),
    "cai.decision.DecisionContext": (
        ("evaluation_time does not postdate the model decision", "B", S_CUTOFF),
        ("knowledge_cutoff does not postdate the model decision", "B", S_CUTOFF),
        ("its moments are timezone-aware", "A", f"{CTX}/properties/model_decision_time"),
    ),
    "cai.action.ActionRecommendation": (
        ("action_id is stated", "A", f"{ACTION}/properties/action_id"),
        ("due_by is timezone-aware", "A", f"{ACTION}/properties/due_by"),
        ("due_by falls no later than the operational window closes", "B", S_DUEBY),
    ),
    "cai.action.OutcomeObservation": (
        ("observed_at is timezone-aware", "A", "/properties/outcome"),
        ("outcome_id is stated", "A", "/properties/outcome"),
        ("subject is stated", "A", "/properties/outcome"),
        ("the observation falls inside its own half-open window", "B", S_OUTCOME),
    ),
    "cai.consequence.BusinessConsequence": (
        ("the derivation is a typed ConsequenceDerivation", "C",
         "an in-memory type check; the wire carries the walk as an object the importer "
         "reconstructs, so no payload can seat a hand-authored context here"),
        ("the walk reaches the consequence's principal entity", "B", S_TERMINAL),
    ),
    "cai.consequence.CustomerCommitmentConsequence": (
        ("commitment_id is stated", "A", f"{CONSEQ}/properties/detail"),
        ("the walk terminates at the commitment", "B", S_TERMINAL),
        ("the walk carries the whole commercial chain", "B", S_CHAIN),
    ),
    "cai.consequence.DowntimeConsequence": (
        ("expected_hours_lost is not negative", "A", f"{CONSEQ}/properties/detail"),
        ("expected_hours_lost survives the two-decimal wire form", "C",
         "the wire carries a fixed two-decimal string; a conforming record is already "
         "quantized"),
        ("the walk is rooted at the asset", "B", S_TERMINAL),
    ),
    "cai.derivation.DerivationStep": (
        ("subject and object are stated", "A", f"{STEP}/properties/subject"),
        ("source_system is stated", "A", f"{STEP}/properties/source_system"),
        ("the validity interval does not run backwards", "B", S_STEPSCOPE),
        ("the relationship is in the closed vocabulary", "A",
         f"{STEP}/properties/relationship"),
        ("its moments are timezone-aware", "A", f"{STEP}/properties/recorded_at"),
    ),
    "cai.derivation.ConsequenceDerivation": (
        ("rule_version is stated", "A", f"{WALK}/properties/rule_version"),
        ("knowledge_cutoff is timezone-aware", "A", f"{WALK}/properties/knowledge_cutoff"),
        ("the walk has at least one step", "A", f"{WALK}/properties/steps"),
        ("no step was recorded after the cutoff", "B", S_STEPCLOCK),
        ("at most one step per relationship", "B", S_CARDINALITY),
        ("every step continues from an entity the walk reached", "B", S_TERMINAL),
        ("every step continues from a relation that may precede it", "B", S_TERMINAL),
        ("an ASSIGNED_TO step says when the assignment began", "B", S_STEPSCOPE),
        ("an unscoped relation carries no validity interval", "B", S_STEPSCOPE),
        ("a SUPPORTS step is scoped at both ends", "B", S_STEPSCOPE),
        ("a SUPPORTS window overlaps the evaluated window", "B", S_STEPSCOPE),
        ("every scoped step holds when the loading window opens", "B", S_STEPSCOPE),
    ),
    "cai.delivery.RenderedDelivery": (
        ("rendered_at is present", "A", f"{P}/properties/rendered_delivery"),
        ("rendered_at is timezone-aware", "A", f"{P}/properties/rendered_delivery"),
        ("the digest verifies against the content it attests", "B", S_DIGEST),
    ),
    "cai.delivery.AssuranceDecision": (
        ("a permitted decision carries no blocking reasons", "A",
         f"{ASSUR}/properties/blocking_reasons"),
        ("a refusal states at least one reason", "A",
         f"{ASSUR}/properties/blocking_reasons"),
        ("the assessed basis is typed", "C",
         "an in-memory type check; the wire carries the basis as an object the importer "
         "reconstructs"),
        ("policy_digest is 64 lowercase hex", "A", f"{ASSUR}/properties/policy_digest"),
        ("release_decision_time is timezone-aware", "A",
         f"{ASSUR}/properties/release_decision_time"),
        ("policy_id and policy_version are stated", "A", f"{ASSUR}/properties/policy_id"),
    ),
    "cai.evidence.EvidenceAssessment": (
        ("MISSING names the missing evidence", "A",
         f"{ASSESS}/properties/missing_evidence"),
        ("COMPLETE names nothing missing", "A", f"{ASSESS}/properties/missing_evidence"),
        ("CONFLICTED names the conflicts", "A", f"{ASSESS}/properties/conflicts"),
    ),
    "cai.bitemporal.Observation": (
        ("observation_id is stated", "A", f"{OBS}/properties/observation_id"),
        ("subject is stated", "A", f"{OBS}/properties/subject"),
        ("metric is stated", "A", f"{OBS}/properties/metric"),
        ("source_system is stated", "A", f"{OBS}/properties/source_system"),
        ("value is a finite number", "A", f"{OBS}/properties/value"),
        ("value survives the six-decimal wire form", "C",
         "the wire carries a fixed six-decimal string; a conforming record is already "
         "quantized"),
        ("both clocks are timezone-aware", "A", f"{OBS}/properties/valid_time"),
    ),
    "cai.bitemporal.EvidenceBundle": (
        ("observation ids are unique in the bundle", "B", S_UNIQUE),
        ("a declared conflict names a reading the bundle carries", "B", S_INTEGRITY),
        ("a declared conflict's kept reading is the one carried", "B", S_INTEGRITY),
        ("a conflict's two readings share an observation id", "B", S_INTEGRITY),
        ("a conflict's two readings genuinely differ", "B", S_INTEGRITY),
    ),
    "cai.product.IntelligenceProduct": (
        ("release_evidence is a typed EvidenceBundle", "C",
         "an in-memory type check; the wire carries the readings as an object the "
         "importer reconstructs through EvidenceBundle"),
        ("product_id is stated", "A", f"{P}/properties/product_id"),
        ("claim_series_id is stated", "A", f"{P}/properties/claim_series_id"),
        ("a product does not supersede itself", "B", S_STATUS),
        ("the model decided no later than the gate, for every determination", "B",
         S_CLOCKS),
        ("recipient, purpose and tenant are non-empty", "A", f"{P}/properties/recipient"),
        ("DELIVERED records when it was delivered", "A", f"{P}/properties/delivery_time"),
        ("DELIVERED carries a validity horizon", "A", f"{P}/properties/valid_until"),
        ("DELIVERED preserves what the recipient saw", "A",
         f"{P}/properties/rendered_delivery"),
        ("DELIVERED requires a permitting assurance decision", "A",
         f"{ASSUR}/properties/permitted"),
        ("the release decision and the delivery are one moment", "B", S_DELIVERED),
        ("delivery falls strictly before the action's deadline", "B", S_DEADLINE),
        ("evidence does not postdate delivery", "B", S_CAPTURED),
        ("validity postdates delivery", "B", S_VALIDUNTIL),
        ("validity does not outlive the prediction window", "B", S_VALIDUNTIL),
        ("validity does not outlive the action's deadline", "B", S_DEADLINE),
        ("the rendering happened at delivery", "B", S_DIGEST),
        ("ABSTAINED contradicts a permitting decision", "A",
         f"{ASSUR}/properties/permitted"),
        ("ABSTAINED carries no card and no delivery time", "A",
         f"{P}/properties/rendered_delivery"),
        ("its moments are timezone-aware", "A", f"{P}/properties/delivery_time"),
    ),
    "cai.envelope.StatusEvent": (
        ("at is timezone-aware", "A", "/properties/status_events/items/properties/at"),
        ("actor is named", "A", "/properties/status_events/items/properties/actor"),
        ("a retraction states a reason", "A",
         "/properties/status_events/items/properties/reason"),
        ("a supersession names its replacement", "A",
         "/properties/status_events/items/properties/replacement_product_id"),
    ),
    "cai.envelope.IntelligenceEnvelope": (
        ("product is a typed IntelligenceProduct", "C",
         "an in-memory type check; the wire carries the product as an object the "
         "importer reconstructs"),
        ("lifecycle events are typed DispositionEvents", "C",
         "an in-memory type check; the wire carries typed records the importer rebuilds"),
        ("the outcome is a typed OutcomeObservation", "C",
         "an in-memory type check; the wire carries a typed record the importer rebuilds"),
        ("a withheld product carries no delivery history", "A",
         "/properties/lifecycle_events"),
        ("the trail opens at the delivery's own moment", "B", S_ONEMOMENT),
        ("an outcome requires the trail to have reached OUTCOME_OBSERVED", "B", S_OUTCOME),
        ("the trail's observation moment is the outcome's", "B", S_OUTCOME),
        ("the outcome observes the claim's subject", "B", S_OUTCOME),
        ("the outcome joins this product's action", "B", S_OUTCOME),
        ("the observation window opens no earlier than delivery", "B", S_OUTCOME),
        ("a trail reaching OUTCOME_OBSERVED carries an outcome", "B", S_OUTCOME),
        ("status events are typed StatusEvents", "C",
         "an in-memory type check; the wire carries typed records the importer rebuilds"),
        ("status events are chronological", "B", S_STATUS),
        ("no status event is recorded twice", "B", S_STATUS),
        ("nothing follows a retraction", "B", S_STATUS),
        ("no status event predates delivery", "B", S_STATUS),
        ("no supersession names the product itself", "B", S_STATUS),
        ("a product is superseded at most once", "B", S_STATUS),
    ),
    "cai.envelope.HistoricalEnvelopeImport": (
        ("the envelope is typed", "C",
         "a return-value type check on an object this package constructs; nothing about "
         "it crosses the wire"),
        ("the verification report is typed", "C",
         "as above; the report is produced by the importer, never read from a payload"),
    ),
    "cai.predictor.MetricApplicability": (
        ("metric and subject_type are both stated", "A",
         f"{CLAIM}/properties/declared_envelope/properties/supported_applicability"),
    ),
    "cai.predictor.ModelEnvelope": (
        ("the envelope declares at least one applicability pair", "A",
         f"{CLAIM}/properties/declared_envelope/properties/supported_applicability"),
        ("no applicability pair is declared twice", "A",
         f"{CLAIM}/properties/declared_envelope/properties/supported_applicability"),
        ("the horizon and observation bounds are positive", "A",
         f"{CLAIM}/properties/declared_envelope/properties/max_horizon_seconds"),
    ),
    "cai.lifecycle.DispositionEvent": (
        ("at is timezone-aware", "A", "/properties/lifecycle_events/items/properties/at"),
        ("actor is named", "A", "/properties/lifecycle_events/items/properties/actor"),
    ),
    "cai.verification.DimensionVerification": (
        ("UNVERIFIABLE states a reason", "C",
         "the verification report is produced by the importer and never travels; a "
         "payload cannot assert its own verification state"),
        ("VERIFIED states no reason", "C", "as above"),
    ),
    "cai.verification.VerificationReport": (
        ("no dimension is reported twice", "C",
         "produced by the importer, never read from a payload"),
        ("every dimension is reported", "C", "as above"),
    ),
}


# --- THE MECHANICS -------------------------------------------------------


def constructor_invariant_counts() -> dict[str, int]:
    """Count the `raise` sites the typed domain runs at construction.

    Per class: `__post_init__` plus every `_check*` helper defined ON that class. An
    inherited check counts against the class that defines it, which keeps the number
    stable when a subclass calls `super()`.
    """
    counts: dict[str, int] = {}
    for module in PORTABLE_MODULES:
        tree = ast.parse((SOURCE / f"{module}.py").read_text())
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = [
                n for n in cls.body
                if isinstance(n, ast.FunctionDef)
                and (n.name == "__post_init__" or n.name.startswith("_check"))
            ]
            total = sum(
                len([r for r in ast.walk(m) if isinstance(r, ast.Raise)])
                for m in methods
            )
            if total:
                counts[f"cai.{module}.{cls.__dict__.get('name', cls.name)}"] = total
    return counts


def resolve(pointer: str):
    """Walk a JSON Pointer into the generated schema, or raise KeyError."""
    node = json_schema()
    for part in pointer.strip("/").split("/"):
        node = node[part]
    return node


def semantic_rules() -> tuple[str, ...]:
    return tuple(json_schema()["x-semantic-validations"]["rules"])


COUNTS = constructor_invariant_counts()


def test_every_type_with_constructor_invariants_is_in_the_table():
    """A new portable type with checks cannot be added without a disposition."""
    assert set(COUNTS) == set(RECONCILIATION), {
        "in the code, missing from the table": sorted(set(COUNTS) - set(RECONCILIATION)),
        "in the table, missing from the code": sorted(set(RECONCILIATION) - set(COUNTS)),
    }


@pytest.mark.parametrize("qualified", sorted(COUNTS))
def test_every_constructor_invariant_has_a_disposition(qualified):
    """THE TRIPWIRE. Add a `raise` to a portable type and this fails until the table says
    what the wire does about it.

    Counting is what makes the completeness claim mean anything. A table that merely
    listed the invariants somebody remembered would be the previous method with more
    formatting.
    """
    assert len(RECONCILIATION[qualified]) == COUNTS[qualified], (
        f"{qualified} raises {COUNTS[qualified]} constructor invariants and the "
        f"reconciliation table classifies {len(RECONCILIATION[qualified])}"
    )


@pytest.mark.parametrize("qualified", sorted(RECONCILIATION))
def test_every_disposition_is_one_of_the_three(qualified):
    for invariant, disposition, where in RECONCILIATION[qualified]:
        assert disposition in ("A", "B", "C"), f"{qualified}: {invariant}"
        assert where, f"{qualified}: {invariant} has no stated location or reason"


@pytest.mark.parametrize("qualified", sorted(RECONCILIATION))
def test_every_schema_expressible_invariant_points_into_the_schema(qualified):
    """An A entry names a location the published schema actually describes.

    This is the check that would have caught `captured_at`: the type required it and the
    schema declared it nullable, and no test compared the two because none existed to
    compare them.
    """
    for invariant, disposition, where in RECONCILIATION[qualified]:
        if disposition != "A":
            continue
        try:
            node = resolve(where)
        except KeyError:
            pytest.fail(f"{qualified}: {invariant!r} points at {where}, which the "
                        f"generated schema does not describe")
        assert node, f"{qualified}: {invariant!r} points at an empty schema node"


@pytest.mark.parametrize("qualified", sorted(RECONCILIATION))
def test_every_semantic_invariant_is_published_as_an_obligation(qualified):
    """A B entry names a rule the schema TELLS an implementer they still owe.

    The point of `x-semantic-validations` is that somebody validating structurally and
    stopping has not enforced the contract. A cross-field rule the reference importer
    enforces and the schema never mentions is one they will not know to write.
    """
    rules = semantic_rules()
    for invariant, disposition, where in RECONCILIATION[qualified]:
        if disposition != "B":
            continue
        assert any(where in rule for rule in rules), (
            f"{qualified}: {invariant!r} is enforced by reconstruction and the schema "
            f"does not publish {where!r} as a semantic obligation"
        )


def test_the_table_covers_every_invariant_in_the_package():
    """One number, for the record, so the handoff can quote something derived."""
    assert sum(COUNTS.values()) == sum(len(v) for v in RECONCILIATION.values())


def test_the_committed_reconciliation_document_matches_the_table():
    """The Markdown is RENDERED from this table, never maintained beside it.

    A hand-written document describing a machine-checked table is a second authority for
    the same fact, and the divergence would be invisible: the tests would keep passing
    against the table while the published document said something else.
    """
    committed = (
        pathlib.Path(__file__).resolve().parent.parent
        / "docs" / "SCHEMA_RECONCILIATION.md"
    )
    assert committed.exists(), "docs/SCHEMA_RECONCILIATION.md is missing"
    assert committed.read_text() == render_markdown(), (
        "docs/SCHEMA_RECONCILIATION.md is stale -- regenerate it with "
        "`python -m tests.render_reconciliation` or the snippet in this test"
    )


def render_markdown() -> str:
    """The published table, derived from the same data the tests check."""
    by_disposition = {"A": 0, "B": 0, "C": 0}
    for entries in RECONCILIATION.values():
        for _, disposition, _ in entries:
            by_disposition[disposition] += 1
    total = sum(by_disposition.values())

    out = [
        "# Schema / typed-domain reconciliation",
        "",
        "Every invariant the typed domain enforces at construction, and what the",
        "published JSON Schema does about it.",
        "",
        "This file is GENERATED from `tests/test_schema_reconciliation.py`, which counts",
        "the `raise` sites in every portable type's `__post_init__` and `_check*` helpers",
        "and fails when the count and the table disagree. Adding a check to the domain",
        "without classifying it breaks the test suite.",
        "",
        "## Dispositions",
        "",
        "| | Meaning | Where it is enforced |",
        "|---|---|---|",
        "| **A** | Expressible in JSON Schema | `json_schema()`, and reconstruction |",
        "| **B** | Cross-field or recomputed | Typed reconstruction on import; published "
        "as an obligation in `x-semantic-validations` |",
        "| **C** | Producer-only | Not part of portable conformance |",
        "",
        f"**{total} invariants across {len(RECONCILIATION)} portable types** — "
        f"{by_disposition['A']} A, {by_disposition['B']} B, {by_disposition['C']} C.",
        "",
        "A JSON Schema cannot compare two values in different subtrees, recompute a",
        "digest, or replay a model. Everything in column B is one of those. Writing a",
        "second wire-side validator to cover them would create two semantics engines,",
        "and the day they disagree is the day the portable form stops meaning what the",
        "in-memory form means — so they are enforced by rebuilding the typed objects,",
        "which runs the domain's own rules.",
        "",
    ]
    for qualified in sorted(RECONCILIATION):
        out += [
            f"## `{qualified}`",
            "",
            "| Invariant | | Schema location / obligation / reason |",
            "|---|---|---|",
        ]
        for invariant, disposition, where in RECONCILIATION[qualified]:
            cell = f"`{where}`" if disposition == "A" else where
            out.append(f"| {invariant} | {disposition} | {cell} |")
        out.append("")
    return "\n".join(out)
