# Schema / typed-domain reconciliation

Every invariant the typed domain enforces at construction, and what the
published JSON Schema does about it.

This file is GENERATED from `tests/test_schema_reconciliation.py`, which counts
the `raise` sites in every portable type's `__post_init__` and `_check*` helpers
and fails when the count and the table disagree. Adding a check to the domain
without classifying it breaks the test suite.

## Dispositions

| | Meaning | Where it is enforced |
|---|---|---|
| **A** | Expressible in JSON Schema | `json_schema()`, and reconstruction |
| **B** | Cross-field or recomputed | Typed reconstruction on import; published as an obligation in `x-semantic-validations` |
| **C** | Producer-only | Not part of portable conformance |

**157 invariants across 32 portable types** — 73 A, 64 B, 20 C.

A JSON Schema cannot compare two values in different subtrees, recompute a
digest, or replay a model. Everything in column B is one of those. Writing a
second wire-side validator to cover them would create two semantics engines,
and the day they disagree is the day the portable form stops meaning what the
in-memory form means — so they are enforced by rebuilding the typed objects,
which runs the domain's own rules.

## `cai.action.ActionRecommendation`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| action_id is stated | A | `/properties/product/properties/candidate/properties/action/properties/action_id` |
| due_by is timezone-aware | A | `/properties/product/properties/candidate/properties/action/properties/due_by` |
| due_by falls no later than the operational window closes | B | action.due_by falls no later than its operational window closes |

## `cai.action.OutcomeObservation`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| observed_at is timezone-aware | A | `/properties/outcome` |
| outcome_id is stated | A | `/properties/outcome` |
| subject is stated | A | `/properties/outcome` |
| the observation falls inside its own half-open window | B | outcome.subject is the claim's subject |

## `cai.bitemporal.EvidenceBundle`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| observation ids are unique in the bundle | B | observation ids are unique within the bundle |
| a declared conflict names a reading the bundle carries | B | an integrity conflict names two readings sharing an observation id |
| a declared conflict's kept reading is the one carried | B | an integrity conflict names two readings sharing an observation id |
| a conflict's two readings share an observation id | B | an integrity conflict names two readings sharing an observation id |
| a conflict's two readings genuinely differ | B | an integrity conflict names two readings sharing an observation id |

## `cai.bitemporal.Observation`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| observation_id is stated | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/observation_id` |
| subject is stated | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/subject` |
| metric is stated | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/metric` |
| source_system is stated | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/source_system` |
| value is a finite number | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/value` |
| value survives the six-decimal wire form | C | the wire carries a fixed six-decimal string; a conforming record is already quantized |
| both clocks are timezone-aware | A | `/properties/product/properties/release_evidence/properties/observations/items/properties/valid_time` |

## `cai.candidate.ApplicabilityAssertion`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| basis is stated | A | `/properties/product/properties/assurance/properties/assurance_context/properties/applicability/properties/basis` |
| subject_type is stated | A | `/properties/product/properties/assurance/properties/assurance_context/properties/applicability/properties/subject_type` |

## `cai.candidate.AssessedAssurance`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| the evidence assessment is typed | C | an in-memory type check; the wire carries an object the importer reconstructs through EvidenceAssessment, so no payload can substitute another type |
| the assurance context is typed | C | as above, for the context object |

## `cai.candidate.EntitlementAssertion`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| basis and policy_id are stated | A | `/properties/product/properties/assurance/properties/assurance_context/properties/entitlement/properties/basis` |
| policy_version is stated | A | `/properties/product/properties/assurance/properties/assurance_context/properties/entitlement/properties/policy_version` |
| valid_to postdates valid_from | B | entitlement scope is re-checked against the product's own recipient |
| recipient, purpose and tenant are non-empty | A | `/properties/product/properties/assurance/properties/assurance_context/properties/entitlement/properties/recipient` |
| its validity moments are timezone-aware | A | `/properties/product/properties/assurance/properties/assurance_context/properties/entitlement/properties/valid_from` |

## `cai.candidate.IdentityAssertion`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| confidence is in [0, 1] | A | `/properties/product/properties/assurance/properties/assurance_context/properties/identity/properties/confidence` |
| resolver is named | A | `/properties/product/properties/assurance/properties/assurance_context/properties/identity/properties/resolver` |
| confidence survives the six-decimal wire form | C | the wire carries a fixed six-decimal string; a conforming record is already quantized |

## `cai.candidate.IntelligenceCandidate`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| prediction_claim is a typed PredictionClaim, never prose | C | the structural refusal of author-supplied prose is a Python type check; the wire equivalent is the claim object's own required shape |
| candidate_id is stated | A | `/properties/product/properties/candidate/properties/candidate_id` |
| the consequence is actionable | B | derived values on the wire |
| the prediction window overlaps the exposure window | B | business_consequence.exposure_window overlaps the prediction window |
| the claim's horizon is the context's window duration | B | the claim's horizon equals the prediction window's duration |
| the walk's cutoff is the decision's | B | the derivation's cutoff and window are the decision context's |
| the walk's window is the decision's | B | the derivation's cutoff and window are the decision context's |
| the action is not due before the model decided | B | no product is actionable after action.due_by |
| the action's operational window overlaps the exposure | B | action.operational_window overlaps the consequence's exposure window |
| the action targets something the record names | B | the consequence's derivation terminates at the consequence's own subject |

## `cai.candidate.TemporalAssertion`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| a valid assertion's feature cutoff does not exceed its knowledge cutoff | B | knowledge_cutoff <= model_decision_time |
| basis is stated | A | `/properties/product/properties/assurance/properties/assurance_context/properties/temporal/properties/basis` |
| its three moments are timezone-aware | A | `/properties/product/properties/assurance/properties/assurance_context/properties/temporal/properties/model_decision_time` |

## `cai.consequence.BusinessConsequence`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| the derivation is a typed ConsequenceDerivation | C | an in-memory type check; the wire carries the walk as an object the importer reconstructs, so no payload can seat a hand-authored context here |
| the walk reaches the consequence's principal entity | B | the consequence's derivation terminates at the consequence's own subject |

## `cai.consequence.CustomerCommitmentConsequence`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| commitment_id is stated | A | `/properties/product/properties/candidate/properties/business_consequence/properties/detail` |
| the walk terminates at the commitment | B | the consequence's derivation terminates at the consequence's own subject |
| the walk carries the whole commercial chain | B | a CUSTOMER_COMMITMENT walk carries ASSIGNED_TO, SUPPORTS, LOADS and FULFILLS |

## `cai.consequence.DowntimeConsequence`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| expected_hours_lost is not negative | A | `/properties/product/properties/candidate/properties/business_consequence/properties/detail` |
| expected_hours_lost survives the two-decimal wire form | C | the wire carries a fixed two-decimal string; a conforming record is already quantized |
| the walk is rooted at the asset | B | the consequence's derivation terminates at the consequence's own subject |

## `cai.contract.EvidenceSnapshot`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| captured_at is present | A | `/properties/product/properties/evidence/properties/captured_at` |
| captured_at is timezone-aware | A | `/properties/product/properties/evidence/properties/captured_at` |
| identity_confidence is in [0, 1] | A | `/properties/product/properties/evidence/properties/identity_confidence` |
| evidence_content_digest is 64 lowercase hex | A | `/properties/product/properties/evidence/properties/evidence_content_digest` |
| every bound input is a cited observation | B | input_fingerprint is the fingerprint OF the recorded inputs |

## `cai.contract.PredictionClaim`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| score is a finite number | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/score` |
| horizon_seconds is positive | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/horizon_seconds` |
| evidence_strength is in [0, 1] | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/evidence_strength` |
| declared_envelope is a typed ModelEnvelope | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/declared_envelope` |
| the envelope's model_version is the claim's | B | the claim's metric and horizon fall inside its own declared_envelope |
| the envelope's artifact digest is the claim's | B | the claim's metric and horizon fall inside its own declared_envelope |
| the envelope admits the claim's metric | B | the claim's metric and horizon fall inside its own declared_envelope |
| the envelope admits the claim's horizon | B | the claim's metric and horizon fall inside its own declared_envelope |

## `cai.contract.PredictionInputs`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| bound_inputs is non-empty | A | `/properties/product/properties/evidence/properties/prediction_inputs/properties/bound_inputs` |
| the bound values are the values scored | B | input_fingerprint is the fingerprint OF the recorded inputs |
| values survive the six-decimal wire form | C | the wire carries fixed six-decimal strings, so a conforming record has already been quantized and cannot express the lossy float this refuses |

## `cai.decision.DecisionContext`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| evaluation_time does not postdate the model decision | B | knowledge_cutoff <= model_decision_time |
| knowledge_cutoff does not postdate the model decision | B | knowledge_cutoff <= model_decision_time |
| its moments are timezone-aware | A | `/properties/product/properties/candidate/properties/context/properties/model_decision_time` |

## `cai.decision.TimeInterval`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| the interval does not run backwards | B | prediction_window_end > prediction_window_start |
| the interval is not zero-length | B | prediction_window_end > prediction_window_start |
| both ends are timezone-aware | A | `/properties/product/properties/candidate/properties/context/properties/prediction_window_start` |

## `cai.delivery.AssuranceDecision`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| a permitted decision carries no blocking reasons | A | `/properties/product/properties/assurance/properties/blocking_reasons` |
| a refusal states at least one reason | A | `/properties/product/properties/assurance/properties/blocking_reasons` |
| the assessed basis is typed | C | an in-memory type check; the wire carries the basis as an object the importer reconstructs |
| policy_digest is 64 lowercase hex | A | `/properties/product/properties/assurance/properties/policy_digest` |
| release_decision_time is timezone-aware | A | `/properties/product/properties/assurance/properties/release_decision_time` |
| policy_id and policy_version are stated | A | `/properties/product/properties/assurance/properties/policy_id` |

## `cai.delivery.RenderedDelivery`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| rendered_at is present | A | `/properties/product/properties/rendered_delivery` |
| rendered_at is timezone-aware | A | `/properties/product/properties/rendered_delivery` |
| the digest verifies against the content it attests | B | rendered_delivery.content_digest verifies against renderer_version |

## `cai.derivation.ConsequenceDerivation`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| rule_version is stated | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/rule_version` |
| knowledge_cutoff is timezone-aware | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/knowledge_cutoff` |
| the walk has at least one step | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/steps` |
| no step was recorded after the cutoff | B | every derivation step was recorded by the knowledge cutoff |
| at most one step per relationship | B | the walk carries at most one step per relationship |
| every step continues from an entity the walk reached | B | the consequence's derivation terminates at the consequence's own subject |
| every step continues from a relation that may precede it | B | the consequence's derivation terminates at the consequence's own subject |
| an ASSIGNED_TO step says when the assignment began | B | a step's validity interval is in force when the loading window opens |
| an unscoped relation carries no validity interval | B | a step's validity interval is in force when the loading window opens |
| a SUPPORTS step is scoped at both ends | B | a step's validity interval is in force when the loading window opens |
| a SUPPORTS window overlaps the evaluated window | B | a step's validity interval is in force when the loading window opens |
| every scoped step holds when the loading window opens | B | a step's validity interval is in force when the loading window opens |

## `cai.derivation.DerivationStep`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| subject and object are stated | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/steps/items/properties/subject` |
| source_system is stated | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/steps/items/properties/source_system` |
| the validity interval does not run backwards | B | a step's validity interval is in force when the loading window opens |
| the relationship is in the closed vocabulary | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/steps/items/properties/relationship` |
| its moments are timezone-aware | A | `/properties/product/properties/candidate/properties/business_consequence/properties/derivation/properties/steps/items/properties/recorded_at` |

## `cai.envelope.HistoricalEnvelopeImport`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| the envelope is typed | C | a return-value type check on an object this package constructs; nothing about it crosses the wire |
| the verification report is typed | C | as above; the report is produced by the importer, never read from a payload |

## `cai.envelope.IntelligenceEnvelope`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| product is a typed IntelligenceProduct | C | an in-memory type check; the wire carries the product as an object the importer reconstructs |
| lifecycle events are typed DispositionEvents | C | an in-memory type check; the wire carries typed records the importer rebuilds |
| the outcome is a typed OutcomeObservation | C | an in-memory type check; the wire carries a typed record the importer rebuilds |
| a withheld product carries no delivery history | A | `/properties/lifecycle_events` |
| the trail opens at the delivery's own moment | B | the trail's opening event is timestamped exactly delivery_time |
| an outcome requires the trail to have reached OUTCOME_OBSERVED | B | outcome.subject is the claim's subject |
| the trail's observation moment is the outcome's | B | outcome.subject is the claim's subject |
| the outcome observes the claim's subject | B | outcome.subject is the claim's subject |
| the outcome joins this product's action | B | outcome.subject is the claim's subject |
| the observation window opens no earlier than delivery | B | outcome.subject is the claim's subject |
| a trail reaching OUTCOME_OBSERVED carries an outcome | B | outcome.subject is the claim's subject |
| status events are typed StatusEvents | C | an in-memory type check; the wire carries typed records the importer rebuilds |
| status events are chronological | B | status events are chronological |
| no status event is recorded twice | B | status events are chronological |
| nothing follows a retraction | B | status events are chronological |
| no status event predates delivery | B | status events are chronological |
| no supersession names the product itself | B | status events are chronological |
| a product is superseded at most once | B | status events are chronological |

## `cai.envelope.StatusEvent`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| at is timezone-aware | A | `/properties/status_events/items/properties/at` |
| actor is named | A | `/properties/status_events/items/properties/actor` |
| a retraction states a reason | A | `/properties/status_events/items/properties/reason` |
| a supersession names its replacement | A | `/properties/status_events/items/properties/replacement_product_id` |

## `cai.evidence.EvidenceAssessment`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| MISSING names the missing evidence | A | `/properties/product/properties/assurance/properties/assurance_context/properties/evidence/properties/missing_evidence` |
| COMPLETE names nothing missing | A | `/properties/product/properties/assurance/properties/assurance_context/properties/evidence/properties/missing_evidence` |
| CONFLICTED names the conflicts | A | `/properties/product/properties/assurance/properties/assurance_context/properties/evidence/properties/conflicts` |

## `cai.lifecycle.DispositionEvent`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| at is timezone-aware | A | `/properties/lifecycle_events/items/properties/at` |
| actor is named | A | `/properties/lifecycle_events/items/properties/actor` |

## `cai.predictor.MetricApplicability`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| metric and subject_type are both stated | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/declared_envelope/properties/supported_applicability` |

## `cai.predictor.ModelEnvelope`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| the envelope declares at least one applicability pair | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/declared_envelope/properties/supported_applicability` |
| no applicability pair is declared twice | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/declared_envelope/properties/supported_applicability` |
| the horizon and observation bounds are positive | A | `/properties/product/properties/candidate/properties/prediction_claim/properties/declared_envelope/properties/max_horizon_seconds` |

## `cai.product.IntelligenceProduct`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| release_evidence is a typed EvidenceBundle | C | an in-memory type check; the wire carries the readings as an object the importer reconstructs through EvidenceBundle |
| product_id is stated | A | `/properties/product/properties/product_id` |
| claim_series_id is stated | A | `/properties/product/properties/claim_series_id` |
| a product does not supersede itself | B | status events are chronological |
| the model decided no later than the gate, for every determination | B | model_decision_time <= release_decision_time for every determination |
| recipient, purpose and tenant are non-empty | A | `/properties/product/properties/recipient` |
| DELIVERED records when it was delivered | A | `/properties/product/properties/delivery_time` |
| DELIVERED carries a validity horizon | A | `/properties/product/properties/valid_until` |
| DELIVERED preserves what the recipient saw | A | `/properties/product/properties/rendered_delivery` |
| DELIVERED requires a permitting assurance decision | A | `/properties/product/properties/assurance/properties/permitted` |
| the release decision and the delivery are one moment | B | determination=DELIVERED requires assurance.permitted=true |
| delivery falls strictly before the action's deadline | B | no product is actionable after action.due_by |
| evidence does not postdate delivery | B | evidence.captured_at does not postdate delivery_time |
| validity postdates delivery | B | valid_until, when present, postdates delivery_time |
| validity does not outlive the prediction window | B | valid_until, when present, postdates delivery_time |
| validity does not outlive the action's deadline | B | no product is actionable after action.due_by |
| the rendering happened at delivery | B | rendered_delivery.content_digest verifies against renderer_version |
| ABSTAINED contradicts a permitting decision | A | `/properties/product/properties/assurance/properties/permitted` |
| ABSTAINED carries no card and no delivery time | A | `/properties/product/properties/rendered_delivery` |
| its moments are timezone-aware | A | `/properties/product/properties/delivery_time` |

## `cai.verification.DimensionVerification`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| UNVERIFIABLE states a reason | C | the verification report is produced by the importer and never travels; a payload cannot assert its own verification state |
| VERIFIED states no reason | C | as above |

## `cai.verification.VerificationReport`

| Invariant | | Schema location / obligation / reason |
|---|---|---|
| no dimension is reported twice | C | produced by the importer, never read from a payload |
| every dimension is reported | C | as above |
