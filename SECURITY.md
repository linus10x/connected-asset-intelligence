# Security policy

## What this repository is

`connected-asset-intelligence` is a reference implementation of a decision-record
contract, built and verified against **synthetic data**. It does not ingest real
telemetry, does not connect to a production fleet or asset-management system, and does
not store customer data of any kind. Nothing here has been through a production security
review, and nothing here should be treated as a certification of production readiness.

If you are evaluating this project for use against real operational data, treat it as a
starting point for your own security review, not a substitute for one.

## Supported versions

This is a pre-1.0 reference implementation with a single active line of development.
Security fixes, like all other fixes, land on the current default branch. There is no
long-term-support branch and no backport policy. If you depend on a specific commit,
track that commit and re-evaluate before moving forward.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting for this repository (repository → Security
tab → "Report a vulnerability") if it is enabled. This opens a private advisory visible
only to the maintainer and lets a fix be developed and tested before public disclosure.
If private reporting is not available on this repository at the time you look, open a
minimal public issue that states a vulnerability exists without describing it, and ask
for a private channel — do not post exploit details or affected inputs in the open
issue.

Please include, as applicable: the module or file involved, a minimal reproduction, the
version or commit affected, and the impact you believe it has. A response should be
expected within a reasonable time for a project of this size; there is no SLA.

## Scope

In scope:

- The `cai` library (`src/cai/**`): the typed domain, the release path, the portable
  envelope, and schema validation.
- `scenarios/incident_reconstruction.py` and the packaged JSON Schema
  (`schema/envelope-1.json`).
- The measurement and verification tooling (`verify_package.py`,
  `mutation_harness.py`, `guard_sweep.py`, `mutation_generator.py`,
  `generate_release_evidence.py`) to the extent a defect in them would cause a false
  pass on a real safety property.

Out of scope:

- Findings that require a production deployment, real telemetry, or infrastructure this
  repository does not include — there is no server, no network listener, and no
  deployment target here to attack.
- Denial-of-service reports against local scripts you control on your own machine.
- The absence of features already disclosed as limitations in `README.md`,
  `docs/WHITEPAPER.md`, and `AUDIT.md` (for example: the evidence digest is
  tamper-evident, not tamper-proof; identity confidence is an input, not computed;
  release authority is a single global confidence floor). Those are documented
  boundaries, not undisclosed defects — but if you believe one of them is exploitable in
  a way the documentation does not make clear, that gap in the documentation is itself
  worth reporting.

## Data and privacy

All data shipped in this repository — observations, identifiers, timestamps, customer
and shipment references — is synthetic and was authored for the demonstration scenario.
None of it describes a real asset, fleet, customer, or telemetry feed. There is no
mechanism in this repository for ingesting or storing real personal data, and none
should be added without a corresponding review of what that would mean for this
project's security and privacy posture.

## Rights and entitlement modeling is not legal advice

`cai.candidate.EntitlementAssertion` and the six-dimension evidence algebra in
`cai.evidence` model whether an intelligence product *records* an entitlement
determination — they do not determine, interpret, or adjudicate real data-usage rights,
contracts, or regulatory obligations. Treating a `AUTHORIZED` value in this codebase as
a legal opinion about what you are entitled to do with real data would be a
misunderstanding of what the field represents. Obtain qualified legal advice for any
real entitlement question.

## Supply chain

The library depends at runtime on exactly one third-party package,
`jsonschema[format-nongpl]` (declared in `pyproject.toml`), used to validate the
published envelope schema. The test suite additionally depends on `pytest`. Both are
widely used, actively maintained packages. `verify_package.py` checks, on every run,
that the library's actual third-party imports match what `pyproject.toml` declares — a
dependency that appears without being declared, or a declared dependency the code no
longer uses, is a verification failure, not a silent drift.

If you add a dependency, prefer a well-maintained package over a hand-rolled
implementation of something that package already does correctly (see
`pyproject.toml`'s comment on why `jsonschema` was added), and be prepared to justify
the addition the same way.

## Secrets

This repository contains no credentials, API keys, or access tokens, and none should
ever be committed to it. A pre-commit naming firewall (`.githooks/pre-commit`,
authoritative form in `scan_history.sh`) blocks a list of prohibited terms from being
committed at all — the list itself lives outside the repository so that committing it
would not leak what it protects. If you believe you have found a secret already
committed to this repository's history, report it privately using the process above
rather than filing a public issue that names it.
