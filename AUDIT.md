# Audit

This is a public account of how this repository is verified, what that verification
covers, and — as important — what it does not. It is written for a reader deciding how
much to trust the claims in `README.md` and `docs/WHITEPAPER.md`, not as a transcript of
how the engineering got here.

All figures below describe what this project calls its **certified** baseline: the
commit at which every check in this document was run and its result independently
accepted as meeting this project's own precommitted acceptance standard, before any
further engineering change was made. That is a statement about this project's internal
process, not a third-party certification, security audit, or attestation of any kind —
see "What this assurance does not mean" below. `src/cai`, the schema, the tests, and the
measurement tooling have not changed since that baseline; only the documentation you are
reading has.

The test suite, the runnable scenario, and the schema/code equality check are re-run on
every push in CI (`.github/workflows/gates.yml`) and are pinned to a commit hash in
`RELEASE_EVIDENCE.md` / `release-evidence.json`. The mutation and guard-sweep figures
below (154 curated mutants, 2,101 source-derived mutations, 220 guards) are **not**
CI-gated — deliberately: `gates.yml` states the reason directly, that mutating on every
push is not a cost any contributor should pay and a check people learn to skip is worse
than one that is honestly run on demand. Those figures are reproducible by any reader
who runs the commands below against this commit, and are the accepted result of the most
recent such run; they are not yet pinned in a committed release-evidence artifact, because
`RELEASE_EVIDENCE.md` predates the guard-sweep and source-derived-mutation tooling and
regenerating it is scoped to this project's next release-evidence cycle, not to
narrative changes. Until then, treat the specific counts below as the accepted baseline
measurement, not as a number a clone of this repository can check against a committed
artifact by itself.

## Verification philosophy

Three rules run through everything below, because each one was learned by watching the
opposite fail:

**A measurement whose method is not shipped is a claim, not a measurement.** Every
number in this document comes from a script in this repository that a reader can run
themselves — not from a report pasted in after the fact. Earlier internal figures for
this project were produced by ad-hoc scripts written once and discarded; several were
wrong, and every error ran in the flattering direction. The tooling now lives in the
repository specifically so a claim and its method cannot separate.

**A safety property that only constrains one direction is usually satisfiable by doing
nothing.** A test suite that only checks "the system refuses when it should" passes for
a function that refuses unconditionally. So every refusal test in this codebase is
paired with a non-triviality test asserting the system does *not* over-refuse, and that
pairing is itself checked by mutation rather than trusted by inspection.

**A kill or a failure counts only when it is attributed.** A mutation that merely breaks
an import, or a test run that errors instead of failing, is not evidence the property
being tested actually caught anything — it can look identical to a real catch in a
summary line. The tooling described below distinguishes these explicitly rather than
folding them into a single pass/fail count.

## Primary evidence: the test suite

1,335 tests, organized by concern rather than by module — `tests/test_bitemporal.py`
and `tests/test_temporal_boundaries.py` (valid time vs. transaction time, clock
ordering), `tests/test_evidence_algebra.py` and `tests/test_guards.py` (the
six-dimension assessment and the refusal paths it drives), `tests/test_context.py` and
`tests/test_decision_boundaries.py` (the graph walk from asset to commitment),
`tests/test_predictor.py` and `tests/test_prediction_claim.py` (the model envelope and
its typed claim), `tests/test_formation.py` and `tests/test_determination_and_clocks.py`
(the release path and the three clocks a decision carries), `tests/test_lifecycle.py`
and `tests/test_rendering_parsing_outcome.py` (disposition, outcome, and rendered
delivery), `tests/test_portable_evidence.py`, `tests/test_wire.py`, and
`tests/test_schema_reconciliation.py` (the wire envelope and its schema),
`tests/test_hostile_states.py` and `tests/test_historical_import.py` (adversarial and
symmetry testing, below), `tests/test_firewall.py` (the naming firewall, below), and
`tests/test_public_surface.py` / `tests/test_public_bool_contracts.py` /
`tests/test_scope_and_applicability.py` / `tests/test_uncovered_branches.py` /
`tests/test_measurement_tooling.py` rounding out the public API surface, boolean
contracts, applicability boundaries, and the measurement tooling itself.

Run it: `.venv/bin/python -m pytest tests/ -q`.

## Adversarial evidence: two independent mutation techniques

Two tools ask different questions, and neither substitutes for the other.

**`mutation_harness.py` — a curated, named regression corpus.** Every mutant here was
written after a specific defect was found, and each declares which test must fail to
kill it. This is strong regression evidence — if a check that closed a known defect is
later removed, the corresponding named mutant reports exactly that. It is explicitly
**not** a completeness claim: the corpus was built from the tests that already exist, so
a clean run over it measures the corpus, not the suite. **154 curated mutants, all
killed, each verified against its own declared failure signature** — attribution
matters as much as the count, because a mutant that merely broke test collection would
otherwise read identically to one caught by the behavior it targets.

**`mutation_generator.py` — mutations derived from the source, blind to the tests.**
This tool walks the AST of `src/cai` and mutates every load-bearing branch, comparison,
and refusal guard — negated conditions, forced `True`/`False` branches, swapped
comparisons and boolean operators, removed raise guards, and permissive/conservative
return substitutions — without any knowledge of which tests exist. That makes it the
tool that speaks to *coverage* rather than regression: a behavior nobody wrote a test
for gets mutated anyway, and the mutation either survives (a gap) or is killed. Run
independently at two levels of test-worker parallelism (`jobs=1` and `jobs=2`), the
source-derived generator produced **2,101 mutations, agreeing per mutation site between
both runs, with zero unexplained survivors, zero undeclared invalid mutants, zero
timeouts, and zero retries.**

Both tools mutate a scratch copy of the repository, never the live tree, and both
require the baseline suite to be green before scoring anything — an early version of
this class of tooling mutated source in place and scored a run against a baseline that
was moving underneath it, which produced false readings in both directions.

These counts answer one question each — "does removing a known-defect guard get caught"
and "does an arbitrary source-level mutation get caught" — and neither is a general
statement about code quality. Treat them as two narrow, reproducible measurements, not a
score.

## Guard sweep: which refusals are load-bearing

`guard_sweep.py` asks a narrower, complementary question: of every `raise` statement in
`src/cai` — discovered by AST, not by manual review — which ones can be deleted while
the suite stays green? A guard that nothing tests is dead protection: it reads as a
safeguard and enforces nothing.

Each guard is classified into exactly one of four categories: **behaviorally
load-bearing** (removing it makes a specific, named test fail, reproducibly, both in the
full suite and when that test is re-run alone); **removable** (the suite stays green
without it — nothing depends on the guard existing); **inconclusive** (the suite goes
red but no single failure reproduces attributably — for example the named failure passes
when re-run in isolation); or **invalid** (removing it breaks compilation or collection
outright, which proves nothing about the guard's behavioral value).

Run at both `jobs=1` and `jobs=2`, the sweep covered **all 220 guards discovered in
`src/cai`, agreeing per guard and per attributed killer between both runs, with zero
removable, zero inconclusive, and zero invalid results** — every guard in the codebase
is both real and currently exercised by a specific, named test.

## Temporal integrity

Every observation carries valid time and transaction time; every derived relationship
(an asset's zone assignment, a loading window, a shipment) carries the same pair.
`tests/test_bitemporal.py` and `tests/test_temporal_boundaries.py` cover: point-in-time
reconstruction against an arbitrary knowledge cutoff, correction handling (a correction
must name the reading it supersedes), out-of-order and backlogged arrival, and the clock
ordering invariant the schema states explicitly — `knowledge_cutoff <= model_decision_time
<= release_decision_time` — holding for both delivered and abstained determinations.
`tests/test_determination_and_clocks.py` exercises the three-clock model end to end
(model decision time bounds the evidence; release decision time selects the rules;
delivery time is when the recipient received it). CI additionally re-runs the scenario
under a second locale (`fr_FR.UTF-8`) and diffs the output byte-for-byte against the
`en` run, because a rendered timestamp is a common place for locale-dependent formatting
to silently change what a reader is shown.

## Hostile-state and release/import symmetry testing

`tests/test_hostile_states.py` constructs adversarial inputs directly — a digest that
matches the SHA-256 format but does not match the cited readings, a recorded correction
that names the wrong prior reading, and similar deliberately malformed states — and
checks that the system refuses them for the correct, specific reason rather than merely
failing to crash.

`tests/test_historical_import.py` and the import path in `cai.envelope` test the
symmetry between producing a product and reading one back: an imported envelope
re-derives every value the schema marks as derived (a rendered sentence, a release
decision, blocking reasons, a digest) and refuses on any disagreement with what the
record claims, rather than trusting the wire copy. A record produced by a model this
build cannot replay is importable only through a separately named path
(`import_historical_envelope`, returning a typed `HistoricalEnvelopeImport`) that keeps
the "could not verify" state visible instead of returning an ordinary-looking, silently
unverified envelope. Separately, `tests/test_public_surface.py` sweeps every name in the
package's declared public surface (`cai.__all__`, defined and explained in
`src/cai/__init__.py`) for a verification-waiver parameter — nothing in the promised
public API can turn evidence replay off.

## Portability and schema verification

`schema/envelope-1.json` is a normative Draft 2020-12 JSON Schema, generated from
`cai.envelope.json_schema()`. CI checks the committed file against a freshly generated
one on every push and fails the build on any disagreement — the schema a reader
validates against and the schema the code actually enforces cannot drift apart silently.
Canonicalization (`cai.canonical`, RFC 8785 subset) fixes exactly how a record serializes
to bytes before it is digested, so two implementations that agree on the record agree on
its digest. `tests/test_wire.py`, `tests/test_portable_evidence.py`, and
`tests/test_schema_reconciliation.py` cover round-tripping, digest stability, and
schema/code equality directly.

## Firewall

A pre-commit hook (`.githooks/pre-commit`) and an authoritative pre-push scanner
(`scan_history.sh`) block a list of prohibited terms from entering any commit, staged
content, or the full repository history, on the working assumption that this repository's
entire history eventually becomes visible outside the current small group of people
working on it. The term list itself is deliberately kept **outside** this repository —
committing an opportunity-specific list would leak exactly what it exists to protect —
so this document describes the mechanism, not the contents. `tests/test_firewall.py`
covers the matching logic; the certified baseline records a clean pass across all ten
configured scan passes.

## Clean-clone, exact-SHA reproduction

`.github/workflows/gates.yml` runs on every push: a fresh `actions/checkout`, installing
strictly from `pyproject.toml` (no undocumented local setup step), the full test suite,
the scenario run under two locales with a byte-for-byte diff, the schema equality check
above, and `verify_package.py`. The certified engineering baseline ran this way: a clean
clone, at an exact commit SHA, with no reruns.

## `verify_package.py`

`verify_package.py` checks the documents' factual claims against the code that is
actually running — test counts, the enumerated state-space size, dependency claims, and
specific execution-path assertions (for example, that the runnable scenario genuinely
invokes the predictor and the context graph rather than having the numbers typed in by
hand). As of this revision it passes with zero failures.

That was not always true within this project's history, and the reason is worth stating
plainly rather than only fixing quietly. Between an engineering change and a narrative
regeneration, this project has previously let `README.md`, `docs/WHITEPAPER.md`, and
`docs/PRESENTATION.md` hold stale test-count references on purpose — specifically so a
committed `RELEASE_EVIDENCE.md` continues to describe the exact documents that existed
when it was generated, rather than being silently invalidated by an unrelated doc edit.
`.github/workflows/gates.yml`, unchanged by this narrative pass, currently hardcodes an
expectation that `verify_package.py` fails on exactly those three specific
test-count checks. Now that the checks genuinely pass, that hardcoded expectation in
`gates.yml` is itself stale and will fail CI on the next push unless updated to expect
zero failures — a one-line change to release/CI tooling, which is outside what this
narrative-only pass is authorized to touch. This is recorded here rather than fixed
silently; see the return packet's open items for the same note directed at the process
that owns `gates.yml`.

## What this assurance means

- Every number above was produced by running the tool it describes, against this
  repository, and can be reproduced by anyone who clones it.
- The refusal paths this project's argument depends on — entitlement, evidence
  integrity, temporal eligibility, identity — are each independently, adversarially
  tested, not merely asserted by a docstring.
- The wire contract a reader validates against is verified identical to the contract
  the code enforces, on every push in CI, rather than trusted to stay in sync. That
  covers structure and the cross-field invariants the schema states. The non-schema
  digest and canonicalization contract those invariants rest on — precisely which
  digest fields hash canonical JSON versus an ad-hoc string versus this
  implementation's own source bytes, and exactly what an independent implementation
  can and cannot reproduce byte-for-byte — is stated in full in
  [`docs/PORTABILITY_CONTRACT.md`](docs/PORTABILITY_CONTRACT.md).

## What this assurance does not mean

- It is not evidence of predictive accuracy, calibration, or any property of a model
  applied to real telemetry — every input in this repository is synthetic.
- Passing mutation and guard measurements demonstrate that specific, named refusal
  behaviors are exercised by specific, named tests. They are not a general completeness
  claim, a code-quality score, or evidence that no untested behavior exists anywhere in
  the codebase.
- A tamper-evident digest is not a tamper-proof one: a party controlling both a record
  and the readings behind it can alter them together and recompute a consistent digest.
  See `README.md`'s Honest limitations section for the full list of boundaries this
  repository states about itself.
- None of the above is a security certification, a legal opinion on data rights, or a
  statement about production readiness. See `SECURITY.md`.

Further detail on the schema-to-code reconciliation process specifically is in
[`docs/SCHEMA_RECONCILIATION.md`](docs/SCHEMA_RECONCILIATION.md).
