# Normative non-schema canonicalization and digest contract

`schema/envelope-1.json` specifies structure and the cross-field invariants an envelope
must satisfy (see [`docs/SCHEMA_RECONCILIATION.md`](SCHEMA_RECONCILIATION.md) for the
full invariant-by-invariant table). It does not, on its own, tell an implementer in
another language how the eight digest fields on the wire are actually computed, or the
exact rules behind the `RFC8785-subset/1` canonicalization identifier it carries.

This document closes that gap. Every rule below is transcribed from the running
implementation — file and function named — not from a desired standard. Where the
implementation is heterogeneous, this document says so rather than presenting a false
uniformity.

## The headline fact: digests are not computed one uniform way

The schema requires eight fields matching `^[0-9a-f]{64}$` (a SHA-256 hex digest). All
eight are SHA-256. **They are not all SHA-256 over the same kind of input.** Four
distinct digest-input constructions are in use — canonical JSON, delimiter-joined field
strings, raw source-file bytes, and an order-independent aggregate of sorted child
digests — and which one applies depends on the field:

| Wire field | Scheme | Source |
|---|---|---|
| `product.rendered_delivery.content_digest` | canonical JSON | `cai.delivery._digest_of` |
| `product.assurance.policy_digest` | ad-hoc joined string | `cai.policy.ReleasePolicy.digest` |
| `product.candidate.prediction_claim.model_artifact_digest` | raw source-file bytes | `cai.predictor.model_artifact_digest` |
| `...prediction_claim.declared_envelope.model_artifact_digest` | raw source-file bytes | `cai.predictor.model_artifact_digest` |
| `product.candidate.prediction_claim.input_fingerprint` | ad-hoc joined string | `cai.predictor` (fingerprint function) |
| `product.evidence.prediction_inputs.input_fingerprint` | ad-hoc joined string | same as above |
| `...prediction_inputs.bound_inputs[].content_digest` | ad-hoc joined string | `cai.bitemporal.Observation.content_digest` |
| `product.evidence.evidence_content_digest` | ad-hoc joined string, order-independent | `cai.bitemporal.digest_observations` |

A ninth digest exists but is **not** a wire field: `IntelligenceEnvelope.digest()`, an
overall envelope digest a holder can compute for their own tamper-evidence check. It
uses the canonical-JSON scheme, over the full envelope record.

### Scheme 1 — canonical JSON

Used only for `rendered_delivery.content_digest` and the non-wire envelope digest.

```
SHA-256( UTF-8 bytes of canonicalize(payload) )
```

`canonicalize` is `cai.canonical.canonicalize` — see "Canonicalization identifier and
subset" below for exactly what it does. For `rendered_delivery.content_digest`, `payload`
is `{renderer_version, locale, rendered_text, card, rendered_at}` (`rendered_at` as its
ISO 8601 string). For the envelope digest, `payload` is the full envelope record
(`as_record()`), and the encoding is called `canonical_json()`.

### Scheme 2 — ad-hoc delimiter-joined strings

Used for `policy_digest`, `model_artifact_digest`'s sibling `input_fingerprint`, and the
per-observation `content_digest`. Each is:

```
SHA-256( UTF-8 bytes of a string built by joining specific fields with an ASCII
          delimiter that cannot appear inside any of them )
```

None of these go through `canonicalize()`. Field by field:

- **`policy_digest`** (`cai.policy.ReleasePolicy.digest`):
  `f"{policy_id}\x1f{policy_version}\x1f{identity_floor!r}\x1f{min_evidence_strength!r}"`
  — joined with `\x1f` (ASCII unit separator). The two threshold values use Python's
  `repr()` for a `float`, not the schema's fixed-decimal string form.
- **`input_fingerprint`** (the prediction-claim fingerprint function in `cai.predictor`):
  `\x1f`-joined `(model_version, metric, str(int(horizon_seconds)),
  ",".join(v.hex() for v in values), ";".join(f"{oid}={digest}" for oid, digest in
  bound))`. `v.hex()` is Python's `float.hex()` — an exact, round-trippable
  hexadecimal float representation, not the schema's fixed six-decimal string.
- **Per-observation `content_digest`** (`cai.bitemporal.Observation.content_digest`):
  `\x1f`-joined `(observation_id, subject, metric, repr(value), valid_time.isoformat(),
  transaction_time.isoformat(), source_system, supersedes or "")`. Again `repr(value)`
  for the float, not the fixed six-decimal wire string that field carries elsewhere on
  the same record.

### Scheme 3 — raw file bytes

Used only for `model_artifact_digest`:

```
SHA-256( the exact bytes of src/cai/predictor.py on disk )
```

Not a JSON structure of any kind — it is a hash of this implementation's own source
file, used as a version fingerprint for the model that produced a claim.

### Scheme 4 — order-independent aggregate

Used only for `evidence_content_digest` (`cai.bitemporal.digest_observations`):

```
SHA-256( UTF-8 bytes of "\x1e".join(sorted(o.content_digest() for o in observations)) )
```

Every cited observation's own `content_digest` (scheme 2, above) is computed first, the
resulting hex strings are sorted lexicographically, then joined with `\x1e` (ASCII
record separator) and hashed again. Sorting makes the result independent of storage or
citation order — two holders of the same evidence set agree regardless of how they
stored it.

### What this means for portability

An independent implementation can reproduce `rendered_delivery.content_digest` and the
non-wire envelope digest byte-for-byte by implementing the canonical-JSON rules below
precisely. Reproducing `policy_digest`, `input_fingerprint`, or the observation-level
`content_digest`/`evidence_content_digest` fields byte-for-byte additionally requires
replicating two CPython-specific numeric formattings — `repr()` for `float` and
`float.hex()` — neither of which is a general cross-language standard. A conforming
reader in another language can still **carry these values opaquely and compare them for
equality** (the value on the wire either matches a value the reader independently holds,
or it does not); it cannot, without replicating CPython's float formatting exactly,
**independently compute** those specific fields from raw numeric inputs and expect a
byte-identical result. That is a real, current limit on cross-language interoperability,
not a claim this implementation makes and then quietly fails to support.

## Canonicalization identifier and subset

The wire's `canonicalization` field is a fixed constant: `RFC8785-subset/1`
(`cai.canonical.CANONICALIZATION`). It names a **subset** of RFC 8785 (the JSON
Canonicalization Scheme) — this implementation does not claim full RFC 8785 compliance,
and a reader should not assume it. `cai.canonical.canonicalize()` implements exactly:

- Output is UTF-8.
- Object keys are ordered by **UTF-16 code-unit** value, not Python's default code-point
  ordering (`cai.canonical._key_order`, which encodes each key as big-endian UTF-16 and
  compares the resulting code units). This is the one place RFC 8785 itself is followed
  precisely — RFC 8785 §3.2.3 specifies UTF-16 code-unit ordering, and Python's built-in
  string sort disagrees with it above the Basic Multilingual Plane.
- No insignificant whitespace (`json.dumps(..., separators=(",", ":"))`).
- Standard JSON string escaping (Python's `json.dumps` default).
- Supported value types: `null`, boolean, integer, string, array, object. Python tuples
  are treated identically to lists and normalize as JSON arrays.
- A `float` that is finite and integer-valued (e.g. `5.0`) normalizes to a JSON integer
  (`5`).
- A `float` that is **not** integer-valued is **refused outright** — `canonicalize()`
  raises rather than emit a value two implementations might format differently.
- `NaN` and infinite values are refused outright, for the same reason.

**Consequence:** every precision-sensitive numeric value this contract carries on the
wire — prediction scores, confidences, observation values, and similar — travels as an
explicitly formatted fixed-decimal **string** (six decimal places for the
score/confidence-shaped fields, two for `expected_hours_lost`; see the schema's own
`pattern` constraints), never as a raw JSON float. That is how the domain avoids ever
needing `canonicalize()` to handle a non-integer float in practice: by the time a value
reaches a canonicalized payload, it has already been quantized to an integer-compatible
representation or moved into a string field the schema pattern-constrains.

This is the complete rule set. There is no additional canonicalization behavior beyond
what is listed above — do not assume RFC 8785 features (e.g. its full number
serialization algorithm for arbitrary floats) apply here merely because the identifier
references RFC 8785.

## REASON relationship vocabulary and topology

`cai.derivation.DerivationRelationship` is a closed, five-member enum:

```
HAS_COMPONENT · ASSIGNED_TO · SUPPORTS · LOADS · FULFILLS
```

No sixth relationship exists in this reference implementation, and a step naming
anything else is refused at construction (`DerivationStep.__post_init__`).

### Continuation rule

A derivation is a sequence of steps, each relating a subject to an object. Reachability
alone (every step's subject appeared as an earlier step's object) is not sufficient —
the relation each step names must also be one the walk's `_MAY_CONTINUE_FROM` table
(`cai.derivation`) permits at that point:

```
HAS_COMPONENT   may leave the walk's ROOT only
ASSIGNED_TO     may leave the walk's ROOT only
SUPPORTS        may continue only from a step reached via ASSIGNED_TO
LOADS           may continue only from a step reached via SUPPORTS
FULFILLS        may continue only from a step reached via LOADS
```

The walk's root is its first step's subject — the asset a derivation is about.
`HAS_COMPONENT` and `ASSIGNED_TO` are the two relations permitted to leave that root
directly; the remaining three form a single chain, each picking up exactly where the
previous one left off. A step that is otherwise reachable but names a relation the table
does not permit at that point is refused — this is what stops a forged-but-connected
walk that keeps every real entity and interval but relabels the relations into a
sequence that happens to stay joined while meaning nothing.

### Cardinality

**At most one step per relationship, per walk.** A second step naming a relationship
already present is refused outright — regardless of which entities it names or whether
the walk would otherwise be well-formed. This reference implementation's own graph walk
(`cai.context.ContextGraph.derive_impact`) never emits a second step for the same
relationship in the first place: it treats "two zones at horizon start" or "two loading
windows overlapping the horizon" as data defects and refuses to derive an impact at all,
rather than picking one.

### Temporal scoping, per relationship

- **`LOADS`** and **`FULFILLS`** are **unscoped**: both `valid_from` and `valid_to` must
  be absent. Their underlying facts (a shipment loading a window, a shipment fulfilling a
  commitment) have no validity-interval field to source one from, and a scoped step here
  asserts a temporal fact no source system could have supplied.
- **`SUPPORTS`** must be scoped at **both** ends, copied directly from the loading
  window's own `opens`/`closes`, and that interval must overlap the walk's evaluated
  window.
- **`ASSIGNED_TO`** must state `valid_from` (required on the underlying assignment
  record); `valid_to` may be absent (still in force).
- Where **`HAS_COMPONENT`** or **`ASSIGNED_TO`** carry an interval, that interval must
  hold — not merely overlap, but contain — two specific instants the walk checks
  explicitly: the evaluated window's own start, and the opening instant of every
  `SUPPORTS` step's loading window. A component or assignment that covered the general
  window but had already lapsed by the moment the loading window actually opened does
  not satisfy this.

### Additional path requirements by consequence type

The topology above is necessary but not sufficient on its own — a consequence type
states which relations its walk must additionally contain. In this reference
implementation:

- A `CUSTOMER_COMMITMENT` consequence's derivation must carry `ASSIGNED_TO`, `SUPPORTS`,
  `LOADS`, and `FULFILLS`. `HAS_COMPONENT` is optional: the graph walk emits it only when
  a component was named to the walk, so requiring it unconditionally would refuse an
  otherwise-honest record that never claimed one.

No entity ontology beyond the six concepts and five relationships above exists in this
reference implementation, and none should be inferred. `DerivationStep` deliberately
records only that one named thing stood in a named relation to another, on some system's
authority, known by a given moment — it is not told, and this document does not assert,
what any relation *means* beyond its position in the adjacency table above.

## What this document does not claim

- It does not claim full RFC 8785 compliance — only the stated subset.
- It does not claim that every digest field can be independently recomputed,
  byte-for-byte, from another language without replicating two CPython-specific float
  formattings (see "What this means for portability" above).
- It does not claim this closed, five-relationship vocabulary generalizes to a different
  asset class or business domain without extension — see `docs/WHITEPAPER.md` §20 for
  that as an explicit hypothesis, not a demonstrated fact.
- It is not a claim of unrestricted cross-language interoperability beyond the specific
  contract stated here. A structurally valid, semantically valid envelope produced by
  another implementation is possible without ever reading this repository's Python
  source; byte-identical reproduction of every digest field on it is not, for the reasons
  stated above.
