# connected-asset-intelligence

**A portable decision record for connected-asset intelligence — so a prediction can
become a product a customer can act on, and a provider can still defend six months
later.**

*Reference implementation on synthetic data, runnable on a laptop — not a production
system, and not connected to any real fleet, vehicle, or telemetry feed. The scenario
below is illustrative and did not happen.*

Forklift F-17 works an indoor loading yard. Not a truck on a highway — an on-site asset,
where there is no satellite positioning, the feed reconnects in bursts, and the machine
moves between bays hourly.

F-17 is running hot. Over five days its battery pack reports 41.0, 45.6, 51.4, 58.4,
66.6 °C — an acceleration, not a drift.

A sensor threshold says: *battery temperature high.* A model says: *degradation risk
0.49.* Neither is a product. Both are things a maintenance team already has too many of.

Now add four facts that live in four different systems. F-17 carries battery-pack-1.
F-17 is assigned to loading zone 3. Zone 3 loads shipment 22 tomorrow morning. Shipment
22 fulfils a next-day delivery commitment for customer A.

Connect them and the reading becomes something a customer would pay for:

> This asset is likely to be unavailable during tomorrow's loading window, which puts a
> next-day delivery commitment at risk. Inspect it before the next shift.

The moment that sentence is delivered it stops being an analytics output and becomes a
commercial claim — carrying an implied promise, an implied entitlement to the underlying
data, and an implied obligation to explain itself later. Most predictive-maintenance
stacks stop at the model score. This project is about the four stages that sit between a
score and a claim you can actually stand behind.

```
CONNECT → PREDICT → REASON → PRODUCTIZE → LEARN
```

| Stage | Answers | Representative modules |
|---|---|---|
| **CONNECT** | what physical thing, where, doing what, and what was knowable when | `bitemporal.py` |
| **PREDICT** | what is likely to happen next, within a declared envelope | `predictor.py` · `contract.py` |
| **REASON** | which business entities and commitments that affects | `context.py` · `derivation.py` · `consequence.py` |
| **PRODUCTIZE** | may this be delivered, to this recipient, and can it be defended later | `candidate.py` · `evidence.py` · `assessment.py` · `policy.py` · `formation.py` · `product.py` · `delivery.py` |
| **LEARN** | what the recipient did, what happened, what could improve the next one | `lifecycle.py` · `action.py` |
| *(TRUST)* | can the decision survive leaving the platform it was made on | `envelope.py` · `canonical.py` · `verification.py` |

Trust is not a sixth stage. It is a cross-cutting property — identity, evidence,
temporal integrity, rights, and reproducibility, threaded through all five — that this
project's argument treats as the precondition for running the loop above at enterprise
scale, rather than staying a research notebook. That is an architectural claim, not a
report that this reference implementation has been run at that scale — it has not, and
has never run outside a laptop on synthetic data. Trust is in parentheses above rather
than in the sequence for the same reason.

## What this demonstrates, and what it does not

This is a reference implementation on **synthetic data**, run on a laptop. It
demonstrates, end to end and by executable code rather than by prose:

- A prediction claim, a derived business consequence, and a release decision that are
  computed by the predictor and a context-graph walk — never typed in by hand.
- A six-dimension evidence algebra (432 enumerated states, exactly one releasing) that
  can refuse a technically perfect claim on **entitlement** alone, and does so in the
  scenario.
- Bitemporal reconstruction: what was knowable *at the decision*, distinct from what is
  believed in hindsight, computed and shown as different numbers (9 vs. 13 vs. 4
  observations in the scenario below).
- A portable envelope that exports, re-imports, and re-runs the recorded prediction
  outside the platform that produced it, reproducing the same score from a matching
  fingerprint.
- Outcome capture joined to the specific action it followed, by id — the data structure
  a learning loop needs, without claiming that loop has been run.

It does **not** demonstrate production predictive accuracy, causal operational or
financial benefit, real fleet telemetry, commercial adoption, or that retraining on
captured outcomes actually improves anything. Those distinctions are not a footnote —
see [Honest limitations](#honest-limitations) below and the fuller
**Demonstrated / Hypothesized / Not demonstrated** breakdown in
[`docs/WHITEPAPER.md`](docs/WHITEPAPER.md).

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
.venv/bin/python -m pip install -e '.[test]'

.venv/bin/python -m pytest tests/ -q                      # 1335 tests
.venv/bin/python verify_package.py                        # documents vs. running code
.venv/bin/python scenarios/incident_reconstruction.py     # the hero path, five stages, four outcomes
```

The **typed domain** — the modules that decide what happens — imports only the standard
library. The **wire boundary** depends on one third-party package,
[`jsonschema`](https://pypi.org/project/jsonschema/) (declared in `pyproject.toml`), used
to validate the published envelope schema on import; the test suite additionally
requires `pytest`. `verify_package.py` checks, on every run, that the library's actual
imports are exactly what `pyproject.toml` declares — no cloud account, no configuration,
nothing ambient.

Figures above are bound to a commit in [`RELEASE_EVIDENCE.md`](RELEASE_EVIDENCE.md),
regenerated by `generate_release_evidence.py`, which refuses to write anything if any
command it runs exits non-zero. That file currently describes an earlier commit than the
code you are reading, by deliberate policy — see [Verification and
reproducibility](#verification-and-reproducibility).

## Anatomy of the intelligence product

`scenarios/incident_reconstruction.py` runs the chain above end to end and prints, in
order: what was knowable on day 12 versus in hindsight (CONNECT); the bounded 72-hour
claim (PREDICT); the graph walk from component to commitment (REASON); the release
decision, the six dimensions that decided it, and three refusal cases — wrong recipient,
tampered evidence, no reachable commitment — that show the system does not merely rubber
stamp (PRODUCTIZE); the disposition trail and observed outcome joined to the action that
caused it (LEARN); and an export/re-import/replay of the whole bundle outside the
process that produced it (TRUST).

Four outcomes are reachable, and all four matter:

| Outcome | Meaning |
|---|---|
| **Delivered** | The chain completed and the claim is defensible. |
| **Abstained — rights** | Technically sound, but no right to deliver it to this recipient. |
| **Abstained — evidence** | The claim could not support itself, and the gap is named. |
| **Abstained — no commitment** | A correct prediction with no path to a customer consequence. An alert, not a product. |

A system that only refuses is safe and useless. One that never refuses is dangerous.

The wire form (`schema/envelope-1.json`, a normative Draft 2020-12 JSON Schema) carries,
per product: the typed prediction claim and its declared applicability envelope; the
business consequence and the full derivation path that produced it, not just the
conclusion; the six-dimension assurance basis and the policy that decided on it; the
evidence bundle the release path actually consumed, including any conflicting readings
it found and rejected; what was rendered and shown to the recipient; and, once
delivered, the typed lifecycle trail and outcome. In plain terms, a product carries:

```
subject · claim · prediction_horizon · business_context · economic_consequence
recommended_action · confidence · abstention_reason · evidence_snapshot
model_version · semantic_rule_version · release_policy_version
customer_entitlement · recipient · delivery_time · disposition
observed_outcome · expiry
```

## Four ideas worth arguing with

**1. The context must be derived, not asserted.** `release()` will not accept a
hand-typed `business_context` string. It takes a candidate whose business consequence
was produced by walking component → zone → loading window → shipment → commitment, and
the delivered prose is rendered from that walk. A claim with no reachable commitment is
refused. That is the difference between selling intelligence and forwarding an alert.

**2. Abstention is a product outcome, not an error.** A claim withheld for a stated
reason is a valid result. `ABSTAINED` without a reason raises, because a silent
abstention is indistinguishable from a crash six months later in a log.

**3. Entitlement is a field, not a policy document.** Cross-customer intelligence is a
rights question before a technical one. The scenario refuses a claim with complete
evidence, high confidence, and resolved identity — purely because the operator had no
right to deliver it to that recipient. To be precise about the boundary: this *records*
a determination made by counsel or a policy engine; it does not interpret contracts.

**4. A decision is judged on what was knowable when it was made.** Connected assets
buffer while out of coverage and deliver backlogs on reconnect. Every observation
carries **valid time** and **transaction time**; a day-12 claim is reconstructed against
the day-12 view. So do relationships — a zone reassignment entered after the decision
cannot be used to justify it.

## Verification and reproducibility

- `.venv/bin/python -m pytest tests/ -q` — 1335 tests. Every refusal test is paired
  with one asserting the system does *not* over-refuse, because a property like "missing
  evidence must yield NOT_PROVABLE" is satisfied perfectly by a function that refuses
  unconditionally — that pairing is what makes the suite mean something.
- `.venv/bin/python verify_package.py` — checks the documents' factual claims (test
  counts, state-space size, dependency claims, and specific execution-path assertions
  such as "the hero path actually invokes the predictor") against the running code,
  rather than trusting they stayed true after they were written. As of this revision it
  passes clean, with zero failures — see `AUDIT.md` for what it checks and why a stale
  claim in this exact README has failed it before.
- Mutation testing and a guard sweep exist and are described, correctly bounded, in
  [`AUDIT.md`](AUDIT.md) — not summarized here as a headline number, because a count by
  itself proves nothing about direction or attribution.
- CI (`.github/workflows/gates.yml`) re-clones the exact commit, installs strictly from
  `pyproject.toml`, runs the suite, runs the scenario under two different locales and
  diffs the output byte-for-byte, and checks the committed schema against the one the
  code generates.

## Honest limitations

- All data is synthetic. No result generalizes to production telemetry.
- Identity confidence is an **input**, not computed.
- No positioning semantics for indoor assets (UWB/BLE/RTLS) — only the arrival pattern
  of position-denied sources is modeled.
- The observation log is append-only in-process, not cryptographically chained.
- A correction must name the reading it supersedes; the log does not detect an
  unannounced correction that merely arrives with a different id.
- The evidence digest is tamper-**evident**, not tamper-proof.
- Release authority is a single global confidence floor, **not** scaled to economic
  consequence.
- `attributed_effect` has exactly one value, `NOT_ESTABLISHED` — outcome capture is not
  evidence that a recommendation caused a good outcome, and one test fails if anyone
  adds a second value.
- No watermarking or windowing policy — those belong to the ingesting engine.
- `abstention_reason` is carried on the product record for audit and for whatever
  downstream system consumes it — the reference implementation does not render or send
  an abstention notice to a human recipient. Only a `DELIVERED` product gets a rendered
  card; a delivery channel that surfaces the reason for a refusal to the person who would
  otherwise have received the claim is outside this repository's scope.
- The rendered delivery card shows raw scores (a risk value, an identity confidence) with
  the plain-language recommendation, but without a stated scale or severity anchor next
  to the numbers themselves — a reader has to already know what the number range means to
  judge urgency from the card alone.

## What this is not

- **Not a platform.** A specification with a working conformance demonstration. A team
  on any mature data platform could implement this contract; that is the intent.
- **Not novel infrastructure.** Provenance, lineage, entity resolution, and
  certain-answer semantics over incomplete data are established fields. The contribution
  is the composition and the product boundary.
- **Not a predictive-maintenance product.** The bundled model is a monotonic degradation
  fit, deliberately simple enough to verify by hand.
- **Not calibrated.** All data is synthetic. Risk scores are relative orderings, not
  probabilities of real-world failure.
- **Not a proof of causation.** `attributed_effect` names what was observed, never what
  was caused.
- **Not integrated with any named commercial telematics, fleet-management, or
  connected-vehicle vendor or platform.** Every identifier in this repository was
  authored for the scenario.

## Documentation

- [`docs/WHITEPAPER.md`](docs/WHITEPAPER.md) — the full technical and business argument,
  including the Demonstrated / Hypothesized / Not-demonstrated boundary in detail, and a
  sequencing view of what real-world validation would require.
- [`docs/PRESENTATION.md`](docs/PRESENTATION.md) — the same argument as an executive
  deck.
- [`AUDIT.md`](AUDIT.md) — what was verified, how, and what that verification does and
  does not mean.
- [`docs/PORTABILITY_CONTRACT.md`](docs/PORTABILITY_CONTRACT.md) — the exact digest,
  canonicalization, and relationship-topology rules the schema itself doesn't state, for
  an implementer building a compatible reader or writer in another language.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — design constraints, invariants a change must
  not weaken silently, and how to run the checks.
- [`SECURITY.md`](SECURITY.md) — reporting process, scope, and data/privacy posture.

## Repository

```
src/cai/bitemporal.py    CONNECT — valid vs. transaction time; late arrival as the normal case
src/cai/predictor.py     PREDICT — illustrative degradation baseline, declared applicability envelope
src/cai/contract.py      PREDICT — the typed prediction claim and its evidence snapshot
src/cai/context.py       REASON — the ontology walk from component to commitment
src/cai/derivation.py    REASON — the recorded derivation path, not just its conclusion
src/cai/consequence.py   REASON — typed business consequences (customer commitment, downtime)
src/cai/evidence.py      PRODUCTIZE — the six-dimension algebra, 432 states, exactly one releasing
src/cai/candidate.py     PRODUCTIZE — the assurance context a release decision is assessed against
src/cai/assessment.py    PRODUCTIZE — assesses release and imported evidence against that context
src/cai/policy.py        PRODUCTIZE — the release policy the six-dimension algebra is wired into
src/cai/formation.py     PRODUCTIZE — release(): the single producer entry point
src/cai/delivery.py      PRODUCTIZE — the typed assurance decision and rendered delivery
src/cai/action.py        PRODUCTIZE/LEARN — recommended actions and typed outcome observations
src/cai/product.py       PRODUCTIZE — the intelligence product and its determination
src/cai/lifecycle.py     LEARN — disposition and outcome, with the causal boundary enforced
src/cai/envelope.py      TRUST — the portable, schema-validated wire envelope; import/export
src/cai/canonical.py     TRUST — RFC 8785 canonical JSON, so a digest means the same thing twice
src/cai/verification.py  TRUST — typed verification reports for what could and could not be checked
tests/                   1335 tests, each refusal paired with a non-triviality check
scenarios/               the runnable end-to-end demonstration
schema/envelope-1.json   the normative wire contract, generated from and checked against the code
```

## A note on the tests

An earlier specification stated the central property as *"missing evidence must yield
NOT_PROVABLE"* and *"removing evidence must never increase provability."*

Both are satisfied perfectly by a function that refuses unconditionally. The property was
vacuous and a stub would have passed the suite while doing nothing.

Every refusal test is therefore paired with one asserting the system does **not**
over-refuse, verified by mutation rather than assertion. A kill counts only when the
suite still collected the same number of tests and the failures include the specific
test declared to guard that property — otherwise a mutant that broke the import reads
exactly like one caught by behaviour.

That rule paid for itself immediately: it caught a clock-skew test passing for the wrong
reason, because the fixture was dated past the cutoff and an ordinary filter excluded it
before the guard was ever reached.

Licensed MIT.
