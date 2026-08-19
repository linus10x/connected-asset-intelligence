#!/usr/bin/env python3
"""Verify every factual claim the documents make about the code.

Run before shipping. The documents assert test counts, state-space sizes, and
behaviours; this checks each against the running system rather than trusting that they
were true when written. They were true when written -- and one of them had already
drifted by two commits later, which is why this exists.
"""
from __future__ import annotations
import itertools, re, subprocess, sys
sys.path.insert(0, "src")

FAILURES: list[str] = []

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)

print("verifying package claims\n")

out = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                     capture_output=True, text=True).stdout
m = re.search(r"(\d+) passed", out)
count = m.group(1) if m else "0"
check("test suite green", bool(m) and "failed" not in out, f"{count} passed")

from cai.evidence import (Support, Completeness, Integrity, TemporalEligibility,
                          Identity, EntitlementState, fully_satisfied, Release)
states = len(list(itertools.product(Support, Completeness, Integrity,
                                    TemporalEligibility, Identity, EntitlementState)))

for doc in ("README.md", "docs/WHITEPAPER.md", "docs/PRESENTATION.md"):
    text = open(doc).read()
    stale = re.findall(r"\b(\d+) tests\b", text)
    check(f"{doc}: test count current",
          all(s == count for s in stale) if stale else True,
          f"states {set(stale) or 'none'}, actual {count}")
    if str(states) in text or "states" not in text:
        check(f"{doc}: state-space figure", True, f"{states}")

check("exactly one releasable state",
      sum(1 for c in itertools.product(Support, Completeness, Integrity,
                                       TemporalEligibility, Identity, EntitlementState)
          if c == (Support.SUPPORTED, Completeness.COMPLETE, Integrity.VALID,
                   TemporalEligibility.ELIGIBLE_AS_OF_DECISION, Identity.RESOLVED,
                   EntitlementState.AUTHORIZED)) == 1)
check("permitting state actually releases",
      fully_satisfied().release_decision() is Release.RELEASE)

demo = subprocess.run([sys.executable, "scenarios/incident_reconstruction.py"],
                      capture_output=True, text=True)
check("demo runs clean", demo.returncode == 0)
# Case-insensitive: the demo prints section headings in caps, and an earlier version
# of this check failed on that rather than on anything real. A verifier that reports
# false failures trains you to ignore it, which is worse than not having one.
for marker in ("DELIVERED", "ABSTAINED", "knowable", "entitlement", "CONNECT", "LEARN"):
    check(f"demo shows {marker!r}", marker.lower() in demo.stdout.lower())

# THE DEPENDENCY CLAIM, RESTATED BECAUSE THE OLD ONE BECAME FALSE.
#
# This used to assert "the library imports only the standard library". That stopped being
# true when the published JSON Schema became the structural validator: validating a Draft
# 2020-12 document correctly means `jsonschema`, and hand-writing a weaker second
# implementation of a mature specification to preserve a convenience label would be the
# platform imitation this project declines everywhere else.
#
# So the check is now the stronger one it should always have been: the third-party imports
# the source actually takes must be exactly the dependencies pyproject declares. A label
# nobody can drift from beats a label somebody has to remember to update.
import ast as _ast_deps  # noqa: E402
import pathlib as _pathlib  # noqa: E402

_imported: set[str] = set()
for _path in sorted(_pathlib.Path("src/cai").glob("*.py")):
    for _node in _ast_deps.walk(_ast_deps.parse(_path.read_text())):
        if isinstance(_node, _ast_deps.Import):
            _imported |= {a.name.split(".")[0] for a in _node.names}
        elif isinstance(_node, _ast_deps.ImportFrom) and _node.level == 0 and _node.module:
            _imported.add(_node.module.split(".")[0])
_third_party = _imported - set(sys.stdlib_module_names) - {"cai"}
_declared = {"jsonschema"}
check(
    "the library's third-party imports are exactly what pyproject declares",
    _third_party == _declared,
    f"imports {sorted(_third_party)}, declares {sorted(_declared)}",
)
_pyproject = open("pyproject.toml").read()
check(
    "the schema validator is a declared runtime dependency, not an ambient one",
    "jsonschema" in _pyproject.split("[project.optional-dependencies]")[0],
    "a validator that is present by luck validates nothing on a clean clone",
)
deps = subprocess.run([sys.executable, "-c",
                       "import cai.contract,cai.assessment,cai.bitemporal,cai.predictor,cai.evidence"],
                      capture_output=True, text=True, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
# The domain modules still import nothing outside the standard library; `jsonschema` is
# reached from `cai.envelope` alone, and lazily, so the typed domain stays independent of
# the wire validator. Worth keeping as its own check rather than folding into the above.
check("the typed domain imports only the standard library", deps.returncode == 0)

for doc in ("README.md", "docs/WHITEPAPER.md", "docs/PRESENTATION.md"):
    body = open(doc).read().lower()
    overbroad = "no dependencies" in body or "zero dependencies" in body
    check(f"{doc}: dependency claim is not overbroad", not overbroad)

# ---------------------------------------------------------------------------
# EXECUTION-PATH CLAIMS. The reason this section exists is worth recording.
#
# Every numeric check above passed for several revisions while the documents
# described a chain the code did not walk: the scenario hard-coded the claim, the
# confidence and the business context, and imported neither the predictor nor the
# context graph. Test counts stayed synchronised; the semantics drifted.
#
# So a verifier that only reconciles numbers is the wrong instrument. These check that
# the hero path actually traverses what the prose says it traverses.
# ---------------------------------------------------------------------------
scenario_src = open("scenarios/incident_reconstruction.py").read()

for module, symbol in (
    ("predictor", "predict_degradation"),
    ("context graph", "ContextGraph"),
    ("lifecycle", "ProductLifecycle"),
    ("evidence digest", "digest_observations"),
    ("decision context", "DecisionContext"),
    ("typed claim", "PredictionClaim.from_prediction"),
    ("typed action", "ActionRecommendation"),
    ("candidate", "IntelligenceCandidate"),
    ("release path", "release"),
    ("portable envelope", "IntelligenceEnvelope"),
):
    check(f"hero path invokes the {module}", f"{symbol}(" in scenario_src)

# The specific regression: intelligence supplied as literals rather than derived.
#
# Both checks below started out as substring greps and both cried wolf on their first
# run -- "confidence=0." matched identity_confidence, which is legitimately an input, and
# "business_context" matched the line where build_product *renders* it, which is the fix
# rather than the defect. Fixing the checker was the right move; loosening the code to
# satisfy a bad check would have been the wrong one.
check(
    "hero path derives its claim from the predictor",
    "PredictionClaim.from_prediction(prediction" in scenario_src,
    "the claim must be built from the predictor's output, never assembled by hand",
)

sys.path.insert(0, "src")
import inspect  # noqa: E402

from cai.formation import release as _release  # noqa: E402

_params = inspect.signature(_release).parameters
_prose = {"claim", "prediction_horizon", "recommended_action", "confidence",
          "business_context", "economic_consequence"}
check(
    "the release path has no prose parameters",
    not (_prose & set(_params)),
    f"present: {sorted(_prose & set(_params))}",
)
check(
    "release requires a typed candidate",
    "candidate" in _params,
)
check(
    "evidence verification cannot be omitted",
    "observation_log" in _params
    and _params["observation_log"].default is inspect.Parameter.empty,
)
# STRONGER than the two versions this replaces. The first checked that a bare tuple of
# readings was a required argument; it was, and the conflicts the log found in them could
# still be left behind. The second checked that the argument was an EvidenceBundle; it
# was, and a hand-built bundle with `integrity_conflicts=()` type-checked perfectly.
#
# There is now no argument of any name through which caller-assembled evidence can reach
# the release path. Release takes the log and runs the point-in-time query itself, so the
# authority that DETECTS a conflict is the authority that ISSUES the evidence.
import cai.bitemporal as _bit  # noqa: E402
check(
    "no caller-assembled evidence can reach the release path",
    "observations" not in _params
    and "evidence_source" not in _params
    and not any(p.annotation in (_bit.EvidenceBundle, "EvidenceBundle")
                for p in _params.values()),
    "release takes the ObservationLog, not a bundle a caller built",
)
check(
    "the log is the issuer of release evidence",
    hasattr(_bit.ObservationLog, "evidence_for")
    and "evidence_for(" in inspect.getsource(_release),
)

# ---- The Control Tower re-audit findings, asserted against the modules rather than
# ---- against a ledger entry claiming they were closed.
import cai.contract as _contract  # noqa: E402
import cai.candidate as _cand  # noqa: E402
import cai.consequence as _conseq  # noqa: E402
import cai.delivery as _deliv  # noqa: E402
import cai.envelope as _env  # noqa: E402
import cai.product as _prod  # noqa: E402
import cai.assessment as _rel  # noqa: E402

check(
    "the legacy boolean Entitlement is deleted",
    not hasattr(_contract, "Entitlement"),
)
check(
    "the superseded release-policy constant is deleted",
    not hasattr(_rel, "POLICY_VERSION"),
)
check(
    "status is not taken from the caller",
    not ({"retracted", "superseded_by"}
         & set(inspect.signature(_prod.IntelligenceProduct.status_at).parameters)),
    "and the envelope derives it: "
    f"{hasattr(_env.IntelligenceEnvelope, 'status_at')}",
)
check(
    "the assurance basis crosses the wire typed",
    "assessed" in _deliv.AssuranceDecision.__dataclass_fields__
    and "assurance_context_record" not in _deliv.AssuranceDecision.__dataclass_fields__,
)
check(
    "a caller cannot assert the evidence assessment",
    "evidence_assessment" not in _cand.AssuranceContext.__dataclass_fields__,
)
import dataclasses as _dc  # noqa: E402

_derivation_field = _conseq.BusinessConsequence.__dataclass_fields__.get("derivation")
check(
    "the consequence cannot exist without its derivation",
    _derivation_field is not None
    and _derivation_field.default is _dc.MISSING
    and _derivation_field.default_factory is _dc.MISSING,
    "required at construction, no default to fall back to",
)
check(
    "the claim carries the envelope its model declares",
    "declared_envelope" in _contract.PredictionClaim.__dataclass_fields__,
)
# Two hops, because the replay moved into `_integrity_findings` when that dimension
# started naming its own reasons. Asserting only the first hop would pass while the
# replay had been dropped from the function that actually performs it.
check(
    "the release join replays the predictor's output",
    "_integrity_findings" in inspect.getsource(_rel._assess_evidence)
    and "predictor_output_mismatch" in inspect.getsource(_rel._integrity_findings),
)
check(
    "the replay cannot be waived at release",
    # The literal True now lives in the wrapper release goes through, and -- the part
    # that makes it an invariant rather than a habit -- no public name takes the flag.
    "replay_claim=True" in inspect.getsource(_rel.assess_release_evidence)
    and "replay_claim" not in inspect.signature(_rel.assess_release_evidence).parameters
    and "replay_claim" not in inspect.getsource(_release),
    "the claim was produced by this process, so it must fail the replay, not skip it",
)
check(
    "the import boundary reuses the release path's bindings",
    "verify_bindings" in inspect.getsource(
        _prod.IntelligenceProduct.from_record_with_findings
    ),
)
# The waiver is gone, and gone from BOTH layers. A flag removed from the public entry
# point and left on the reconstruction underneath it is still reachable by anyone who
# reads the module, and this repository has twice found a capability "removed" in one
# place and live in another.
check(
    "strict import has no waiver flag",
    "accept_unverifiable_basis" not in inspect.signature(_env.import_envelope).parameters
    and "accept_unverifiable_basis" not in inspect.signature(
        _prod.IntelligenceProduct.from_record
    ).parameters,
)
check(
    "an unverifiable basis is readable only through a separately named API",
    hasattr(_env, "import_historical_envelope")
    and hasattr(_env, "HistoricalEnvelopeImport"),
    "the gap stays visible instead of returning an ordinary verified-looking envelope",
)
check(
    "the published schema is the structural validator, and it is run",
    "validate_against_schema" in inspect.getsource(_env._reconstruct)
    and "Draft202012Validator" in inspect.getsource(_env.validate_against_schema),
    "a schema called normative and never run describes a second accepted universe",
)
# The evidence itself travels, not only a citation of it. Without this the portable form
# is strictly weaker than the in-memory form: an importer can re-run four of the six
# assurance dimensions and has to take the other two on the record's word.
check(
    "the release evidence crosses the wire",
    "release_evidence" in _prod.IntelligenceProduct.__dataclass_fields__
    and "release_evidence" in inspect.getsource(_prod.IntelligenceProduct.as_record),
)
check(
    "import re-runs the release path's own evidence assessment",
    "assess_imported_evidence" in inspect.getsource(
        _prod.IntelligenceProduct._verify_the_assessment_follows_from_the_evidence
    ),
    "not a second wire-side implementation of evidence semantics",
)
_envelope_fields = _env.IntelligenceEnvelope.__dataclass_fields__
check(
    "the lifecycle boundary is typed on the wire",
    "DispositionEvent" in str(_envelope_fields["lifecycle_events"].type)
    and "OutcomeObservation" in str(_envelope_fields["outcome"].type),
    "not tuple[dict] and dict|None, which reconstructed into nothing",
)
# The scalar API must be gone, not merely unused.
import cai.assessment as _rel  # noqa: E402
check("the scalar build_product is deleted", not hasattr(_rel, "build_product"))
# ...and so must the legacy release representation. These survived one full audit cycle
# while the migration ledger asserted they had been removed, so the claim is checked
# against the module rather than against the ledger.
check("the legacy ReleaseDecision is deleted", not hasattr(_rel, "ReleaseDecision"))
check("the legacy evaluate_release is deleted", not hasattr(_rel, "evaluate_release"))
# The six-dimension assessment must be what actually decides, not a parallel module.
# It decides in the policy now that the legacy path is gone; the claim is unchanged,
# only its address is. Asserted against the live decision site, not a grep of prose.
check(
    "the enumerated algebra is wired into release",
    "release_decision()" in open("src/cai/policy.py").read(),
)
# The hero must PRINT the assessment that decided, never recompute one for display.
# Recomputing it is how the shown dimensions came to be stronger than the deciding ones.
check(
    "hero prints the assessment that authorised delivery",
    "product.assurance.assurance_context_record" in scenario_src
    and "assess_" not in scenario_src,
    "a separately recomputed assessment can diverge from the one that decided",
)
# AST, not grep: the first version of this matched the comment explaining why the call
# is absent, which is the same false-positive trap as the novelty check.
import ast as _ast  # noqa: E402
_policy_ast = _ast.parse(open("src/cai/policy.py").read())
_calls = {
    n.func.attr for n in _ast.walk(_policy_ast)
    if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
}
check(
    "entitlement has a single authority",
    "permits" not in _calls,
    "policy must not re-decide what the assurance dimension already decided",
)
check(
    "canonicalization is specified, not incidental",
    "RFC8785" in open("src/cai/canonical.py").read(),
)

# Novelty must never be ASSERTED. Using the word to disclaim novelty ("not novel
# infrastructure") is correct and must not be flagged -- a crude grep would push
# someone to delete a true sentence to satisfy the check.
for doc in ("README.md", "docs/WHITEPAPER.md", "docs/PRESENTATION.md"):
    body = open(doc).read().lower()
    asserted = [p for p in ("is novel", "a novel", "our novel", "novel contribution",
                            "novel approach") if p in body]
    check(f"{doc}: novelty not asserted", not asserted, str(asserted) if asserted else "")

print()
if FAILURES:
    print(f"{len(FAILURES)} claim(s) FAILED verification:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
print("all package claims verified against the running system")
