#!/usr/bin/env python3
"""Generate the release-evidence card: `release-evidence.json` + `RELEASE_EVIDENCE.md`.

WHY GENERATED, AND WHY FAIL-CLOSED
----------------------------------
A results section written by hand is accurate on the day it is written. This project
proved that twice: the white paper's test count was right when drafted and wrong two
commits later, both times caught by a check rather than by a reader.

The generator it replaces had a worse version of the same disease. It captured only
stdout and discarded every exit code and stderr, so a pytest run that died during
collection still yielded a parse of whatever partial output existed, and the document
was written anyway -- with "?" where a number belonged and a confident heading above it.
A generator that cannot fail cannot be trusted to report failure.

So: every command's exit status is checked, and anything unexpected aborts before a
single byte is written. A missing card is a legible state. A card describing a run that
did not happen is not.

FAIL CLOSED MEANS ONE SUCCESSFUL STATE, NOT A BEST-EFFORT ONE
---------------------------------------------------------------
Every required release-evidence precondition below has exactly one successful shape:
present, installed, unchanged, passed, equal, byte-identical. There is no tri-state
"unavailable" or "not checked here" that this generator will still write a card around.
A required condition that is not satisfied raises `EvidenceUnavailable` before anything
is written -- a missing pinned artifact, an absent dependency, a diverged engineering
surface, an unreachable firewall policy, a failed history scan, a schema mismatch, a
locale that is not installed on this machine, or output that is not byte-identical
across locales. The checks run cheapest-first (see `collect()`) so a run that is going
to refuse does so before it pays for the expensive commands.

THE TWO-COMMIT EVIDENCE CONVENTION
-----------------------------------
This file describes a commit -- `subject_commit` -- that it cannot itself be part of: a
commit cannot contain a byte-accurate description of its own resulting tree without
already knowing bytes it has not yet produced. So the convention is two commits, not one:

    subject_commit    every code/doc/artifact frozen and clean; what this evidence is ABOUT
    (subject_parent)  subject_commit's own parent, so a reader can see what changed INTO it
    EVIDENCE_SHA       a direct CHILD of subject_commit, created afterward, changing only
                       RELEASE_EVIDENCE.md and release-evidence.json

This generator runs while `HEAD == subject_commit` and refuses on a dirty tree --
evidence about an uncommitted state is not evidence about a commit. The evidence-only
commit that follows is not the subject being measured, and this file never guesses its
own eventual SHA. A later phase verifies `parent(EVIDENCE_SHA) == subject_commit` and
that `diff(subject_commit, EVIDENCE_SHA)` touches only the two evidence artifacts --
this generator does not perform that check on itself, because at generation time
EVIDENCE_SHA does not exist yet.

WHAT THE CARD IS FOR
--------------------
Binding public claims to an exact state. It is not a test dump. Someone reading the
white paper should be able to open this, see the commit, and re-run the commands.

ALL THREE PHASE-5 MEASUREMENTS ARE CARRIED FORWARD, NEVER RE-RUN HERE
-----------------------------------------------------------------------
Curated mutation (`mutation_harness.py`), source-derived mutation
(`mutation_generator.py`), and the guard sweep (`guard_sweep.py`) were each already
independently accepted by Control Tower at `CERTIFIED_ENGINEERING_BASELINE`. The latter
two take on the order of ten hours between them; re-running any of the three merely
because this card is being generated would make every release-evidence run as expensive
as the one before it, forever, and it would silently re-authorize an unrelated,
out-of-band remeasurement this generator has no business triggering.

So this generator NEVER invokes `mutation_harness.py`, `mutation_generator.py`, or
`guard_sweep.py`. It carries forward the already Control-Tower-accepted Phase-5 result
(`ACCEPTED_PHASE5_EVIDENCE` below) ONLY if `engineering_surface_unchanged()` confirms, by
`git diff`, that every file all three measurements actually cover -- including the three
harness files themselves -- is still byte-identical to the certified baseline commit.
If anything on that surface has changed, carry-forward is impossible and this generator
raises `EvidenceUnavailable` rather than writing a card that says so: a final release
card without accepted engineering evidence behind it is not a weaker release card, it is
no release card, and fresh Control Tower authorization is required before one can exist.

Usage:
    python3 generate_release_evidence.py             # write both evidence files
    python3 generate_release_evidence.py --dry-run    # collect and print; write nothing
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The commit Control Tower independently accepted the Phase-5 evidence packet at. Not a
# claim about the current candidate -- a fixed historical fact, checked against.
CERTIFIED_ENGINEERING_BASELINE = "a413f85ec50c5edb0fb67eeb2af68ae3f34f39b9"

# Every path any of the three accepted Phase-5 measurements actually covers. If any of
# these differ from CERTIFIED_ENGINEERING_BASELINE, none of the three measurements still
# describes what it would be carried forward onto, and carry-forward must refuse.
ENGINEERING_SURFACE = (
    "src/cai",
    "schema",
    "tests",
    "scenarios",
    "mutation_harness.py",
    "mutation_generator.py",
    "guard_sweep.py",
    "scan_history.sh",
)

# The Phase-5 evidence Control Tower independently accepted at CERTIFIED_ENGINEERING_BASELINE.
# A historical record, not a live measurement -- see engineering_surface_unchanged(). All
# three sub-records (curated mutation, source-derived mutation, guard sweep) are expensive
# or adversarial measurements accepted once and bound to this one certified SHA; none of
# them is re-run by this generator.
ACCEPTED_PHASE5_EVIDENCE = {
    "baseline_commit": CERTIFIED_ENGINEERING_BASELINE,
    "curated_mutation": {
        "total": 154,
        "killed": 154,
        "conservative": 5,
        "permissive": 149,
        "attributed": 154,
        "surviving": 0,
        "invalid": 0,
        "unattributed": 0,
        "baseline_restored": True,
    },
    "source_derived_mutation": {
        "total": 2101,
        "killed": 2092,
        "declared_equivalent": 1,
        "diagnostic_only": 6,
        "declared_invalid": 2,
        "unexplained": 0,
        "undeclared_invalid": 0,
        "timeout": 0,
        "retry": 0,
        "jobs1_jobs2_per_site_json_sha256": (
            "401accc0dddc2a46bebec29673ae6fe868aae24ac68806d6aff39c712803f769"
        ),
    },
    "guard_sweep": {
        "discovered": 220,
        "load_bearing": 220,
        "removable": 0,
        "inconclusive": 0,
        "invalid": 0,
        "retry": 0,
        "jobs1_jobs2_per_site_json_sha256": (
            "ffefbc654d22043b3483a452bb3f7049ad75c0b962e32c96c09987c7cc431fa1"
        ),
    },
}

# The commands this generator actually runs itself, in reproduction order. Curated
# mutation testing is NOT here -- like source-derived mutation and the guard sweep, it is
# carried forward from ACCEPTED_PHASE5_EVIDENCE rather than re-run; see the module
# docstring and phase5_evidence_section().
REVIEWER_COMMANDS = (
    ("tests", (sys.executable, "-m", "pytest", "tests/", "-q")),
    ("verifier", (sys.executable, "verify_package.py")),
    ("scenario", (sys.executable, "scenarios/incident_reconstruction.py")),
)

# The public artifact set this card pins by content hash. A claim in a document is only
# as bound as the document, so the document is hashed too. This covers the full
# public-narrative and reproduction-tooling surface, AND the methodology that produced
# this evidence and enforces it on every push -- this generator, the CI gate definition,
# and the two firewall scripts -- so the process that produced the evidence is pinned
# alongside the artifacts it evidences. PINNED is a required set: see
# required_artifacts_present(). A missing entry aborts generation by name; it is never
# silently dropped from the hashed set.
PINNED = (
    "README.md",
    "AUDIT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "pyproject.toml",
    "docs/WHITEPAPER.md",
    "docs/WHITEPAPER.pdf",
    "docs/PRESENTATION.md",
    "docs/PRESENTATION.pdf",
    "docs/SCHEMA_RECONCILIATION.md",
    "docs/PORTABILITY_CONTRACT.md",
    "schema/envelope-1.json",
    "scenarios/incident_reconstruction.py",
    "verify_package.py",
    "mutation_harness.py",
    "mutation_generator.py",
    "guard_sweep.py",
    "scan_history.sh",
    "docs/build_pdfs.py",
    "generate_release_evidence.py",
    ".github/workflows/gates.yml",
    ".githooks/firewall_match.sh",
    ".githooks/pre-commit",
)

# Dependencies whose installed version is worth recording verbatim, rather than as a
# hand-maintained sentence that goes stale the moment the dependency set changes. All
# four are required for FINAL evidence generation -- see dependency_versions().
DEPENDENCY_NAMES = ("jsonschema", "pytest", "markdown", "weasyprint")

# The release-machine locale check in locale_byte_identity() runs the scenario under this
# locale and requires it to be installed. Not a CI-only convenience: final evidence is
# generated on a real release machine, and this generator checks that machine directly.
ALT_LOCALE = "fr_FR.UTF-8"


class EvidenceUnavailable(Exception):
    """Raised rather than writing a card describing a run that did not happen."""


def run(name: str, args: tuple[str, ...]) -> tuple[str, float]:
    """Run a reviewer command, or refuse to report on it."""
    started = time.monotonic()
    proc = subprocess.run(list(args), capture_output=True, text=True, cwd=ROOT)
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        raise EvidenceUnavailable(
            f"{name} exited {proc.returncode}; refusing to generate a card.\n"
            f"--- stdout ---\n{proc.stdout[-2000:]}\n"
            f"--- stderr ---\n{proc.stderr[-2000:]}"
        )
    return proc.stdout, elapsed


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise EvidenceUnavailable(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(pattern: str, text: str, what: str) -> str:
    """Extract a figure, or refuse. A '?' in a results card is a silent failure."""
    match = re.search(pattern, text)
    if not match:
        raise EvidenceUnavailable(f"could not read {what} from command output")
    return match.group(1)


def required_artifacts_present() -> None:
    """PINNED is a required set, not a best-effort one.

    Checked before any expensive measurement starts. A missing required path is named
    explicitly and generation refuses -- it is never silently omitted from the hashed
    artifact set the way `if path.exists()` would omit it.
    """
    missing = [name for name in PINNED if not (ROOT / name).exists()]
    if missing:
        raise EvidenceUnavailable(
            "missing required pinned artifact(s); refusing before any measurement "
            "starts:\n" + "\n".join(f"  - {name}" for name in missing)
        )


def dependency_versions() -> dict[str, str]:
    """Installed versions of the direct reproducibility dependencies -- a hard gate.

    `importlib.metadata.version` rather than a package's own (often deprecated or
    absent) `__version__` attribute: it works uniformly across every dependency here
    without importing each one, and it reads exactly what `pip` installed. For FINAL
    evidence generation all four are required; any absence means this machine cannot
    actually reproduce what the card is about to claim, so generation refuses rather
    than recording an absence as if it were a fact about the release.
    """
    versions: dict[str, str] = {}
    missing = []
    for name in DEPENDENCY_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        raise EvidenceUnavailable(
            "required dependency(ies) not installed for final evidence generation: "
            + ", ".join(missing)
        )
    return versions


def firewall_policy_digest() -> str:
    """The naming firewall's term list, fingerprinted without being read or published.

    The list lives outside this repository by design (see `.githooks/pre-commit`).
    `firewall_list_digest` is the one existing implementation
    (`.githooks/firewall_match.sh`); this shells out to it rather than re-hashing the
    policy file a second way that could disagree with the pre-commit hook's own answer.
    A digest with no full scan behind it proves only which policy file existed, so this
    is one half of firewall_gate() below, not the whole gate.
    """
    proc = subprocess.run(
        ["bash", "-c", "source .githooks/firewall_match.sh && firewall_list_digest"],
        capture_output=True, text=True, cwd=ROOT,
    )
    digest = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise EvidenceUnavailable(
            "firewall policy digest unavailable or malformed; refusing to generate a "
            "card without a verified policy input."
        )
    return digest


def firewall_gate() -> dict[str, str]:
    """Firewall is a hard gate, not just a hash.

    Requires both: the external policy digest (firewall_policy_digest(), above) AND a
    successful `scan_history.sh` run under that policy. Output is captured only to prove
    PASS in the exception message on failure -- the policy's own contents are never
    printed by scan_history.sh on a passing run, and this does not publish them either.
    """
    digest = firewall_policy_digest()
    proc = subprocess.run(
        ["bash", "scan_history.sh"], capture_output=True, text=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise EvidenceUnavailable(
            "scan_history.sh did not pass; refusing to generate a card.\n"
            f"--- stdout (tail) ---\n{proc.stdout[-2000:]}\n"
            f"--- stderr (tail) ---\n{proc.stderr[-1000:]}"
        )
    return {"result": "passed", "policy_sha256": digest}


def schema_equality_gate() -> bool:
    """Schema equality is a hard gate: the only value ever recorded is True.

    A failed check process, or a parsed result other than True, raises rather than
    letting `schema_equality: false` or `schema_equality: null` reach a written card.
    """
    proc = subprocess.run(
        [sys.executable, "-c",
         "import json, pathlib, sys; sys.path.insert(0, 'src')\n"
         "from cai.envelope import json_schema\n"
         "d = json.loads(pathlib.Path('schema/envelope-1.json').read_text())\n"
         "print(d == json_schema())"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise EvidenceUnavailable(
            "schema equality check process failed; refusing to generate a card.\n"
            f"--- stderr ---\n{proc.stderr[-2000:]}"
        )
    if proc.stdout.strip() != "True":
        raise EvidenceUnavailable(
            "schema/envelope-1.json does not equal cai.envelope.json_schema(); "
            "refusing to generate a card that would assert schema equality."
        )
    return True


def locale_byte_identity() -> dict[str, object]:
    """Release-machine gate: ALT_LOCALE must be installed HERE, and the scenario must
    produce byte-identical output under it and under the default locale.

    Not best-effort: final release evidence is generated on a real release machine, and
    this checks that machine directly rather than substituting CI's own locale job for
    it. An unavailable locale, a nonzero exit under either locale, or non-identical
    output all raise -- the only value ever recorded is a successful, checked,
    byte-identical result.
    """
    available = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout
    if ALT_LOCALE.split(".")[0] not in available and ALT_LOCALE not in available:
        raise EvidenceUnavailable(
            f"{ALT_LOCALE} is not installed on this release machine; final evidence "
            "requires a live release-machine locale check, not CI prose standing in "
            "for it."
        )
    default = subprocess.run(
        [sys.executable, "scenarios/incident_reconstruction.py"],
        capture_output=True, text=True, cwd=ROOT,
    )
    alt = subprocess.run(
        [sys.executable, "scenarios/incident_reconstruction.py"],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "LC_ALL": ALT_LOCALE},
    )
    if default.returncode != 0 or alt.returncode != 0:
        raise EvidenceUnavailable(
            "the scenario did not exit 0 under the default locale and/or "
            f"{ALT_LOCALE}; refusing to generate a card."
        )
    if default.stdout != alt.stdout:
        raise EvidenceUnavailable(
            f"scenario output differs between the default locale and {ALT_LOCALE}; "
            "refusing to generate a card that would assert byte identity."
        )
    return {"checked": True, "locale": ALT_LOCALE, "byte_identical": True}


def engineering_surface_unchanged(baseline: str) -> tuple[bool, list[str]]:
    """Whether every path any Phase-5 measurement covers is still byte-identical to
    `baseline`.

    A `git diff --stat` with output is a change; empty output is none. This is the
    fail-closed gate for ACCEPTED_PHASE5_EVIDENCE -- carry-forward requires this to
    return (True, []).
    """
    diff = git("diff", "--stat", baseline, "--", *ENGINEERING_SURFACE)
    if not diff:
        return True, []
    changed = sorted({line.split("|")[0].strip() for line in diff.splitlines() if "|" in line})
    return False, changed


def phase5_evidence_section() -> dict[str, object]:
    """The Phase-5 carry-forward hard gate.

    If the engineering surface has diverged from CERTIFIED_ENGINEERING_BASELINE, this
    raises rather than returning a "not carried forward" record: a final release card
    without accepted engineering evidence behind it is not a weaker card, it is no card,
    and fresh Control Tower authorization is required before one can exist.
    """
    unchanged, diverged = engineering_surface_unchanged(CERTIFIED_ENGINEERING_BASELINE)
    if not unchanged:
        raise EvidenceUnavailable(
            "the engineering surface this measurement covers has changed since the "
            f"certified baseline {CERTIFIED_ENGINEERING_BASELINE}; carrying the old "
            "Phase-5 evidence (curated mutation, source-derived mutation, guard sweep) "
            "forward would describe a tree that no longer exists. Fresh Control Tower "
            "authorization is required before any of the three can be regenerated or "
            "carried forward for this candidate. Diverged paths: " + ", ".join(diverged)
        )
    return {
        "carried_forward": True,
        "basis": (
            f"engineering surface byte-identical to certified baseline "
            f"{CERTIFIED_ENGINEERING_BASELINE}; not re-measured here"
        ),
        **ACCEPTED_PHASE5_EVIDENCE,
    }


def collect() -> dict:
    # Cheap, structural checks first, so a run that is going to refuse does not first
    # pay for pytest, the scenario, or anything else expensive. See the module
    # docstring's "FAIL CLOSED MEANS ..." section for why every one of these has exactly
    # one successful shape.

    # 1. clean working tree
    dirty = git("status", "--porcelain")
    if dirty:
        raise EvidenceUnavailable(
            "working tree is dirty; evidence must describe a committed, clean state:\n"
            + dirty
        )

    # 2. what this evidence is about
    subject_commit = git("rev-parse", "HEAD")
    try:
        subject_parent = git("rev-parse", f"{subject_commit}^")
    except EvidenceUnavailable:
        subject_parent = None  # a root commit has none; unlikely here, not fatal

    # 3. required pinned artifacts
    required_artifacts_present()

    # 4. required reproducibility dependencies
    dependencies = dependency_versions()

    # 5. engineering-surface equality to the certified baseline -- also carries forward
    #    the curated, source-derived, and guard-sweep mutation evidence
    phase5 = phase5_evidence_section()

    # 6. firewall policy availability + scan_history.sh PASS
    firewall = firewall_gate()

    # 7. schema equality
    schema_equal = schema_equality_gate()

    # 8. locale byte identity, live, on this machine
    locale = locale_byte_identity()

    # 9-11. pytest, verify_package, the normal scenario run -- in that order
    outputs: dict[str, str] = {}
    timings: dict[str, float] = {}
    for name, args in REVIEWER_COMMANDS:
        outputs[name], timings[name] = run(name, args)

    tests_out = outputs["tests"]
    scenario_out = outputs["scenario"]

    # 12. artifact hashing -- every path already confirmed present in step 3
    artifacts = {name: sha256(ROOT / name) for name in PINNED}

    return {
        "subject_commit": subject_commit,
        "subject_parent": subject_parent,
        "working_tree": "clean",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "dependencies": dependencies,
        "tests": {
            "passed": int(need(r"(\d+) passed", tests_out, "passed count")),
            "failed": int(m.group(1)) if (m := re.search(r"(\d+) failed", tests_out)) else 0,
        },
        "curated_mutation": phase5["curated_mutation"],
        "verifier": "passed",
        "scenario": {
            "delivered": len(re.findall(r"determination\s*:\s*DELIVERED", scenario_out)),
            "abstained": len(re.findall(r"determination\s*:\s*ABSTAINED", scenario_out)),
            "abstention_reasons": re.findall(r"reason\s*:\s*(.+)", scenario_out),
            "decision_time_observations": int(
                need(r"available on day 12\s*:\s*(\d+)", scenario_out, "decision-time count")
            ),
            "hindsight_observations": int(
                need(r"believed in hindsight\s*:\s*(\d+)", scenario_out, "hindsight count")
            ),
            "learned_later": int(
                need(r"learned only later\s*:\s*(\d+)", scenario_out, "knowledge gap count")
            ),
            "output_sha256": hashlib.sha256(scenario_out.encode("utf-8")).hexdigest(),
        },
        "locale_byte_identity": locale,
        "schema_equality": schema_equal,
        "accepted_engineering_baseline": CERTIFIED_ENGINEERING_BASELINE,
        "phase5_source_derived_and_guard_evidence": phase5,
        "firewall": firewall,
        "artifacts": artifacts,
        "timings_seconds": {k: round(v, 2) for k, v in timings.items()},
        "limitations": [
            "All data is synthetic. No result generalises to production telemetry.",
            "Risk scores are relative orderings, not calibrated failure probabilities.",
            "Outcome capture records what was observed, never what was caused.",
            "Identity confidence is an input, not computed here.",
            "The observation log is append-only in-process, not cryptographically chained.",
            "A correction must name the reading it supersedes; unannounced corrections "
            "arriving under a new id are not inferred.",
            "Entitlement records a rights determination made elsewhere; this code does not "
            "interpret contracts or determine legal rights.",
            "Release authority is a single global confidence floor, not scaled to the "
            "economic consequence of the claim.",
            "Digests are SHA-256 throughout but computed by four different digest-input "
            "constructions depending on the field -- see docs/PORTABILITY_CONTRACT.md.",
        ],
    }


def render(data: dict) -> str:
    d = data
    scenario = d["scenario"]
    phase5 = d["phase5_source_derived_and_guard_evidence"]
    cm = d["curated_mutation"]
    locale = d["locale_byte_identity"]
    firewall = d["firewall"]
    deps = d["dependencies"]
    dep_lines = ", ".join(f"{name} {version}" for name, version in deps.items())

    lines = [
        "# Release evidence",
        "",
        "*Generated by `generate_release_evidence.py`. Do not hand-edit — every figure was",
        "produced by running the system it describes, at the commit named below.*",
        "",
        f"- **subject_commit:** `{d['subject_commit']}`",
        f"- **subject_parent:** `{d['subject_parent'] or 'none (root commit)'}`",
        f"- **Working tree:** {d['working_tree']}",
        f"- **Generated:** {d['generated_utc']}",
        f"- **Python:** {d['python']} on {d['platform']}",
        f"- **Dependencies:** {dep_lines}",
        "",
        "This card describes `subject_commit` only. It is written while `subject_commit`",
        "is `HEAD` and the tree is clean, and it is never itself part of the commit it",
        "describes — a later, separate commit adds this file and `release-evidence.json`",
        "as the only two changes on top of `subject_commit`.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "PY=.venv/bin/python",
        "$PY -m pytest tests/ -q                    # the suite",
        "$PY verify_package.py                       # docs vs code",
        "$PY scenarios/incident_reconstruction.py    # the hero path",
        "```",
        "",
        "Curated mutation testing (`mutation_harness.py`), source-derived mutation, and",
        "the guard sweep are NOT re-run by this generator — see the carried-forward",
        "sections below.",
        "",
        "| command | seconds |",
        "|---|---|",
    ]
    for name, secs in d["timings_seconds"].items():
        lines.append(f"| {name} | {secs} |")

    lines += [
        "",
        "## Tests",
        "",
        f"**{d['tests']['passed']} passed, {d['tests']['failed']} failed.**",
        "",
        "## Curated mutation testing",
        "",
        f"**Carried forward from the certified engineering baseline** "
        f"`{phase5['baseline_commit']}` — {phase5['basis']}.",
        "",
        f"**{cm['total']} mutants, all killed** — {cm['conservative']} conservative, "
        f"{cm['permissive']} permissive; {cm['attributed']} verified against a declared "
        f"failure signature; {cm['invalid']} invalid, {cm['unattributed']} unattributed; "
        f"baseline restored: {cm['baseline_restored']}.",
        "",
        "This is the hand-authored regression corpus (`mutation_harness.py`), not a",
        "completeness claim — see the section below for the source-derived generator and",
        "the guard sweep, which are equally carried forward and not re-run by this",
        "generator.",
        "",
        "## Source-derived mutation and guard-sweep evidence",
        "",
    ]
    sdm = phase5["source_derived_mutation"]
    gs = phase5["guard_sweep"]
    lines += [
        f"**Carried forward from the certified engineering baseline** "
        f"`{phase5['baseline_commit']}` — {phase5['basis']}.",
        "",
        f"- Source-derived mutation: {sdm['total']} total, {sdm['killed']} killed, "
        f"{sdm['declared_equivalent']} declared equivalent, "
        f"{sdm['diagnostic_only']} diagnostic-only, {sdm['declared_invalid']} "
        f"declared invalid, {sdm['unexplained']} unexplained, "
        f"{sdm['undeclared_invalid']} undeclared invalid, {sdm['timeout']} timeout, "
        f"{sdm['retry']} retry. jobs=1/jobs=2 per-site JSON SHA-256: "
        f"`{sdm['jobs1_jobs2_per_site_json_sha256']}`.",
        f"- Guard sweep: {gs['discovered']} discovered, {gs['load_bearing']} "
        f"load-bearing, {gs['removable']} removable, {gs['inconclusive']} "
        f"inconclusive, {gs['invalid']} invalid, {gs['retry']} retry. jobs=1/jobs=2 "
        f"per-site JSON SHA-256: `{gs['jobs1_jobs2_per_site_json_sha256']}`.",
    ]

    lines += [
        "",
        "## Package verifier",
        "",
        f"`verify_package.py`: **{d['verifier']}**.",
        "",
        "## Schema equality",
        "",
        f"`schema/envelope-1.json` matches `cai.envelope.json_schema()`: "
        f"**{d['schema_equality']}**.",
        "",
        "## Locale byte-identity",
        "",
        f"Scenario output under `{locale['locale']}` vs. the default locale: "
        f"**byte-identical: {locale['byte_identical']}**.",
    ]

    lines += [
        "",
        "## Hero scenario",
        "",
        f"Delivered **{scenario['delivered']}** · Abstained **{scenario['abstained']}**",
        f"Output digest (SHA-256): `{scenario['output_sha256']}`",
        "",
        "Abstention reasons, exactly as emitted:",
        "",
    ]
    for reason in scenario["abstention_reasons"]:
        lines.append(f"- `{reason.strip()}`")

    lines += [
        "",
        "### Decision time versus hindsight",
        "",
        f"- Available at the decision: **{scenario['decision_time_observations']}** observations",
        f"- Believed in hindsight: **{scenario['hindsight_observations']}** observations",
        f"- Learned only afterwards: **{scenario['learned_later']}**",
        "",
        "The claim is judged on the first number. Folding the third into it would flatter the",
        "decision-maker and mislead an investigator.",
        "",
        "## Firewall",
        "",
        f"Result: **{firewall['result']}**. Policy SHA-256: `{firewall['policy_sha256']}`.",
        "",
        "## Pinned artifacts",
        "",
        "| file | sha256 |",
        "|---|---|",
    ]
    for name, digest in d["artifacts"].items():
        lines.append(f"| `{name}` | `{digest}` |")

    lines += ["", "## What these results do not show", ""]
    for limitation in d["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="collect and print evidence; write neither RELEASE_EVIDENCE.md nor "
             "release-evidence.json",
    )
    args = parser.parse_args()

    try:
        data = collect()
    except EvidenceUnavailable as exc:
        print(f"REFUSING TO GENERATE:\n{exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(data, indent=2))
        print(
            f"\n[dry run: wrote nothing. {data['tests']['passed']} tests, "
            f"{data['curated_mutation']['total']} curated mutants, "
            f"{data['subject_commit'][:9]}, tree {data['working_tree']}]",
            file=sys.stderr,
        )
        return 0

    (ROOT / "release-evidence.json").write_text(json.dumps(data, indent=2) + "\n")
    (ROOT / "RELEASE_EVIDENCE.md").write_text(render(data))
    print(
        f"wrote release-evidence.json + RELEASE_EVIDENCE.md "
        f"({data['tests']['passed']} tests, {data['curated_mutation']['total']} "
        f"curated mutants, {data['subject_commit'][:9]}, tree {data['working_tree']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
