# Contributing

This is a reference implementation, not a platform. Contributions are welcome, but the
bar for a change is the same bar the codebase already holds itself to: does the code
enforce the invariant, or does the prose merely claim it does. Read that sentence twice
before opening a pull request — it is the single rule everything below expands on.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
.venv/bin/python -m pip install -e '.[test]'
```

Use the project's own interpreter (`.venv/bin/python`) for every command below, not
whatever `python3` resolves to on your system — a system interpreter with a different
`jsonschema` version, or none at all, will fail in ways that have nothing to do with
your change.

## Running the checks

```bash
.venv/bin/python -m pytest tests/ -q                  # the suite
.venv/bin/python scenarios/incident_reconstruction.py  # the hero path
.venv/bin/python verify_package.py                     # documents vs. running code
```

All three must pass before you open a pull request. `verify_package.py` passes clean as
of this revision — zero failures. It has failed before, and may again: this project's
release process sometimes freezes `README.md`, `docs/WHITEPAPER.md`, and
`docs/PRESENTATION.md` deliberately (their exact test-count references held stale)
between the moment a release-evidence artifact is generated and the moment those
documents are next regenerated, so that a committed evidence file always describes the
documents that existed when it was produced. If you find `verify_package.py` failing
only on test-count references inside those three files, check `AUDIT.md` and
`RELEASE_EVIDENCE.md` before assuming it's a bug — it may be that intentional freeze. If
it fails on anything else, treat that as a real defect: either the code changed in a way
the documents no longer describe accurately, or the documents assert something the code
does not do.

Mutation testing (`mutation_harness.py`), the guard sweep (`guard_sweep.py`), and
release-evidence generation (`generate_release_evidence.py`) exist and are documented in
`AUDIT.md`. They are slower and are not expected on every pull request — see that file
for what they check and how to run them if your change touches the release path, the
evidence algebra, or the wire schema.

## Schema generation and equality

`schema/envelope-1.json` is committed, but it is not hand-maintained. It is generated
from `cai.envelope.json_schema()` and CI fails the build if the two disagree:

```bash
.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "src")
from cai.envelope import json_schema
on_disk = json.loads(pathlib.Path("schema/envelope-1.json").read_text())
assert on_disk == json_schema(), "schema/envelope-1.json is stale — regenerate it"
PY
```

If your change touches any field the wire envelope carries, regenerate the file from
`json_schema()` and commit the result in the same pull request as the code change —
never hand-edit `schema/envelope-1.json` directly.

## Rebuilding the PDFs

`docs/WHITEPAPER.pdf` and `docs/PRESENTATION.pdf` are rendered from the committed
Markdown, not hand-maintained:

```bash
.venv/bin/python -m pip install -e '.[docs]'   # markdown + WeasyPrint, once
.venv/bin/python docs/build_pdfs.py
```

This is deterministic for a fixed Markdown input on a fixed machine — rebuilding without
changing `docs/WHITEPAPER.md` or `docs/PRESENTATION.md` reproduces byte-identical PDFs.
WeasyPrint itself binds against system Pango/Cairo/GDK-Pixbuf via `cffi`; that native
dependency is real, is not declared in `pyproject.toml` (Python packaging has no way to
express it), and has to already be present on whatever machine regenerates these files —
see `docs/build_pdfs.py`'s own docstring for the exact packages by platform. Regenerate
both PDFs in the same pull request as any change to the underlying Markdown, and commit
the result.

## Design constraints — read before adding a parameter

These are not style preferences; each one is enforced by a test or a `verify_package.py`
check, and a pull request that reintroduces one will fail CI:

- **No prose parameters on the release path.** `cai.formation.release` does not, and
  must not, accept a hand-typed `business_context`, `economic_consequence`, or
  `recommended_action` string. Business context is derived from `ContextGraph`, not
  supplied by a caller.
- **No verification waivers on a public name.** No public callable accepts a flag that
  skips replaying a claim or re-checking evidence. `tests/test_historical_import.py`
  sweeps every public callable for exactly this pattern; if your API needs to express
  "this could not be fully verified," return a typed report that says so
  (`VerificationReport`, `HistoricalEnvelopeImport`) rather than adding a boolean that
  turns verification off.
- **Derived values are re-derived and compared, not trusted from the wire.** If a field
  on the envelope can be computed from other fields (a rendered sentence, a release
  decision, a digest), the importer recomputes it and refuses a mismatch. Do not add a
  field that lets a producer assert a derived value without the means to check it.
- **Abstention needs a reason.** `ABSTAINED` without a stated reason is a bug, not a
  valid state — the type should make that unrepresentable, not rely on a caller
  remembering to fill in the string.
- **Six dimensions stay independent.** Do not collapse `Support`, `Completeness`,
  `Integrity`, `TemporalEligibility`, `Identity`, and `EntitlementState` back into a
  single provable/not-provable verdict, and do not add a seventh without updating every
  place that enumerates the state space (`verify_package.py`'s state-space check,
  `AUDIT.md`, and the schema).

## No silent weakening of invariants

If a change relaxes something the schema or the typed domain currently enforces — a
`required` field becomes optional, a `const` becomes an `enum`, an `additionalProperties:
false` gets removed — say so explicitly in the pull request description, including which
downstream guarantee gets weaker. A relaxation that is not called out in the description
is, on this codebase's own terms, exactly the kind of drift the verification tooling
exists to catch, and a reviewer should treat an unflagged one as a defect in the pull
request rather than approve it on trust.

## New public claims need a backer

If you add a sentence to `README.md`, `docs/WHITEPAPER.md`, `docs/PRESENTATION.md`, or
`AUDIT.md` that asserts a capability, back it with either:

1. a passing check that would fail if the claim were false (a test, a
   `verify_package.py` check, or a runnable command a reader can execute), or
2. an explicit label — `hypothesized` or `not demonstrated` — if the capability is
   architecturally plausible but has not actually been exercised against real
   operational data.

Do not write a sentence that reads as demonstrated fact when it is really a hope for
what the architecture *could* support. See `AUDIT.md` and `docs/WHITEPAPER.md` §19–20
for the standard this repository holds itself to.

## Generated artifacts

`RELEASE_EVIDENCE.md` and `release-evidence.json` are produced by
`generate_release_evidence.py`, which refuses to write either file if any command it
runs exits non-zero. Do not hand-edit them. If your change affects a figure they report
(a test count, a mutation count, a pinned artifact hash), regenerate them as part of the
release process that owns them — not as part of an unrelated pull request. Routine
pull requests should not touch these two files at all.

## Branching

Day to day, this project follows ordinary trunk-based development: a small change on a
short-lived branch, opened as a pull request against the default branch, reviewed, and
merged or fast-forwarded once CI is green. Delete the branch afterward.

This repository's git history includes an extended remediation branch that stayed open
far longer than that and carried its own internal audit process. That was a deliberate,
bounded response to a specific situation, documented in that branch's own history — it
is not the normal contribution model, and no new contribution should assume a
long-lived branch is the expected pattern.

## Commit messages

Write commit messages that explain *why*, not a restatement of the diff. A reviewer
should be able to read `git log --oneline` and understand the shape of the change
without opening it.
