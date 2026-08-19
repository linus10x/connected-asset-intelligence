#!/usr/bin/env python3
"""Which refusal guards can be deleted with the suite still green?

WHY THIS EXISTS
---------------
A `raise` nothing tests is a guard that reads as protection and proves nothing. Wave 1
found 73 of 137 removable; wave 4 found 61 of 170 still removable after three rounds of
remediation. Both numbers were produced by a script somebody wrote, used once, and threw
away -- so the next reader had to take the figure on trust or rebuild the tool.

That is the same defect this repository keeps finding in its own evidence: a measurement
whose method is not shipped is a claim, not a measurement.

WHY IT WAS REBUILT
------------------
The version that reported "0 removable of 208" had four defects, and every one of them
biased the answer towards zero -- towards the flattering direction, like every other
defect this tooling has had:

  1. It mutated the LIVE source tree. A concurrent edit and this sweep can each undo the
     other, and a crash between write and restore leaves the repository altered.
  2. It never checked that the suite was green BEFORE it started. On a red baseline every
     guard reads as load-bearing and the sweep reports zero removable, which looks like
     the best possible result.
  3. It ignored pytest's return code entirely.
  4. It decided the suite had passed by testing `"failed" not in stdout`. A guard whose
     removal breaks COLLECTION prints no "failed" line -- so a mutant that stopped the
     suite from running at all was scored as "the guard is load-bearing".

So the number was not evidence. This version borrows the discipline the mutation tools
were corrected into: a scratch copy of the repository, a baseline that must pass in a
worker-shaped workspace, the same collected test universe, and a kill that requires an
actual FAILING test rather than the absence of a word in a log.

WHAT IT REPORTS
---------------
  guards discovered      every `raise` in src/cai, by AST
  behaviourally load-bearing   removing it makes a named test FAIL, and that named test
                         fails again when re-run ALONE against the same removed-guard tree
  removable              removing it leaves the suite green -- nothing holds this guard
  inconclusive           the suite went red but nothing attributable reproduced: the named
                         failure passed when re-run alone, or the run only ERRORED, or it
                         did not terminate. NOT counted as load-bearing
  invalid                removing it breaks compilation or collection: not proof of
                         anything, and NOT counted as load-bearing

A FIFTH DEFECT, FOUND AFTER THE FOUR ABOVE WERE FIXED
-----------------------------------------------------
The rebuilt sweep still credited ANY `FAILED` line in the full-suite output to the guard it
had just removed. Under a pool of workers each running a full pytest, a test can fail for
reasons that have nothing to do with the removal -- the same machine saturation the retry
existed for -- so an unrelated failure was silently accepted as proof that a guard was
covered. Like the first four, it biased towards the flattering answer.

`mutation_generator.py` had already closed this exact failure class for mutants. The rule is
now shared rather than restated: a named failure counts only once it reproduces alone.

  python3 guard_sweep.py            # summary
  python3 guard_sweep.py --list     # every removable guard, with its own message
  python3 guard_sweep.py --sites    # per-site classification, human readable
  python3 guard_sweep.py --json     # per-site records on stdout, progress on stderr
  python3 guard_sweep.py --gate     # DECIDES: nonzero unless every condition below holds

MEASURING AND DECIDING ARE DIFFERENT JOBS
-----------------------------------------
The default mode exits 0 whatever it finds, on purpose: a sweep that failed the build
would be reverse-engineered into a number somebody tunes. That is right for a measurement
and useless as a gate, because process success then carried no claim at all -- a run
holding INCONCLUSIVE results, INVALID results, a load-bearing verdict with nothing to
re-run, or a removable guard nobody had decided about, all exited 0.

`--gate` adds the decision without removing the measurement. Its exit status comes from
`gate_failures`, a pure function over the result objects that can be unit-tested in both
directions against hand-built results. It fails on any of: an INCONCLUSIVE result, an
INVALID result, a load-bearing result with no named reproduced killer, any full-suite
retry, a REMOVABLE guard absent from `ACCEPTED_REMOVABLE`, or an empty result set.

Read-only in effect on this repository: nothing here writes inside `src/`.
"""
from __future__ import annotations

import ast
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Overridable for the same reason `mutation_generator`'s are: a measurement tool cannot
# be checked only against the suite it measures. `tests/test_measurement_tooling.py`
# points this at a miniature repository holding one guard the tests assert and one they
# do not, and requires it to tell them apart.
ROOT = Path(os.environ.get("CAI_GUARD_ROOT") or Path(__file__).resolve().parent)
PACKAGE = os.environ.get("CAI_GUARD_PACKAGE", "cai")
SRC = ROOT / "src" / PACKAGE

# Same denylist as the mutant workspace, and for the same reason: an allowlist of
# "everything the suite reads" is a list somebody forgets to update, and the failure mode
# when they forget is a measurement that always agrees with itself.
WORKSPACE_EXCLUDES = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache",
    "*.egg-info", "build", "dist", ".ruff_cache",
)

COLLECTED = re.compile(r"^(\d+) tests? collected", re.MULTILINE)
# Same correction as `mutation_generator.py`: `\S+` truncates a parametrized nodeid at
# the first space inside its brackets, and this package's parametrize ids are sentences.
# Here it only ever mis-named the test in a report, and a report naming
# `test_x[a` instead of `test_x[a required key is deleted]` is a reader sent to look for
# a test that does not exist.
FAILED = re.compile(r"^FAILED (.+?)(?: - |\s*$)", re.MULTILINE)
ERROR = re.compile(r"^ERROR (.+?)(?: - |\s*$)", re.MULTILINE)


class Verdict(str, Enum):
    LOAD_BEARING = "load-bearing"
    """Removing it made a named test FAIL, AND that test failed again when re-run alone
    against the same guard-removed tree. Something holds this guard up, and the something
    has been named and reproduced."""
    REMOVABLE = "removable"
    """Removing it left the suite green. Nothing does."""
    INCONCLUSIVE = "inconclusive"
    """The suite went red and nothing attributable to this guard could be reproduced.

    Three ways in: the named failure passed when re-run alone, so it belonged to the load
    and not to the guard; the run ERRORED without any test FAILING; or the run did not
    terminate. All three used to be worth something. The first two were scored
    LOAD_BEARING, which is the flattering direction -- an unrelated failure became
    evidence that a guard was covered, silently. The third was scored INVALID.

    None of them is evidence in either direction, so none of them is counted as either."""
    INVALID = "invalid"
    """Removing it broke compilation or collection. No test ran, so this says nothing
    about whether the guard is tested -- and scoring it as load-bearing, which the old
    sweep did, is how 208 guards came to look fully covered."""


@dataclass(frozen=True)
class Guard:
    file: str
    line: int
    scope: str
    message: str
    span: tuple[int, int]
    indent: int

    @property
    def site_id(self) -> str:
        return f"{self.file}:{self.line} [{self.scope}]"


@dataclass
class Result:
    guard: Guard
    verdict: Verdict
    detail: str = ""
    retried: bool = False
    """Whether any verdict here depended on repeating a full-suite run.

    A field rather than a phrase inside `detail`, because the release protocol asks a
    yes/no question of the whole run -- did any result depend on a re-run? -- and
    answering it by grepping prose is how the answer stops being checked.

    It is now STRUCTURALLY false. The full-suite retry that could set it was removed: a
    repeated suite run cannot turn an inconclusive result into a verdict, because the
    failure it was fishing for was as likely to be the machine as the guard. The field and
    its printed line stay so that "retries exercised 0" remains a stated fact rather than
    a line that quietly disappeared along with the mechanism, which is how a reader loses
    the ability to tell the two apart.

    The targeted single-test re-run in `_evaluate` is not a retry in this sense. It does
    not repeat the suite and it cannot manufacture a verdict; it can only withhold one.
    """


def guards() -> list[Guard]:
    found: list[Guard] = []
    for path in sorted(SRC.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)

        def walk(node: ast.AST, scope: str) -> None:
            for child in ast.iter_child_nodes(node):
                inner = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef)):
                    inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
                if isinstance(child, ast.Raise):
                    raw = lines[child.lineno - 1]
                    found.append(Guard(
                        file=path.name, line=child.lineno, scope=scope,
                        message=" ".join(
                            (ast.get_source_segment(source, child) or "").split()
                        ),
                        span=(child.lineno, child.end_lineno),
                        indent=len(raw) - len(raw.lstrip()),
                    ))
                walk(child, inner)

        walk(tree, "<module>")
    return found


def _build_workspace() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cai-guards-"))
    workspace = root / "repo"
    shutil.copytree(ROOT, workspace, ignore=WORKSPACE_EXCLUDES, symlinks=True)
    return workspace


def _purge(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


# The same exclusion, for the same reason: `tests/test_measurement_tooling.py` spawns
# this sweep and the mutation generator, so running it inside every guard's workspace is
# a nested pool per guard, and it asserts nothing about `src/cai` that could kill one.
# Applied to the baseline and to every guard identically.
# ONE EXCLUSION LIST, IMPORTED RATHER THAN RESTATED.
#
# This held its own copy naming a single file, and `mutation_generator.py` held another.
# Both tools do the same thing to the tree -- they change `src/cai` and re-run the suite
# -- so a test module that cannot survive a mutated source tree cannot survive a
# guard-removed one either, and keeping the two lists in step was a promise somebody had
# to remember to keep.
#
# It was already broken when this was written: the reconciliation test parametrizes over
# an inventory parsed from the live `src/cai`, and removing the sole raise in
# `MetricApplicability.__post_init__` -- which is precisely what this sweep does to every
# guard in turn -- drops that class from the inventory and collects one fewer test. The
# generator found it first because it ran first, and the same site would have been
# reported INVALID here.
#
# This is the shared-matcher argument from `firewall_match.sh`, one directory over: two
# copies of one policy disagree eventually, and the disagreement surfaces as a tooling
# defect at the worst moment.
#
# `reproduces_alone` arrives by the same argument and for the same reason. A removed guard
# and an applied mutant are the same kind of change to the tree, so "a named failure only
# counts once it reproduces alone" is one rule, not two. It lived only in the mutation tool
# while this one still promoted any FAILED line straight to LOAD_BEARING.
from mutation_generator import EXCLUDED_FROM_THE_MUTATED_UNIVERSE, reproduces_alone

_IGNORE = [arg for path in EXCLUDED_FROM_THE_MUTATED_UNIVERSE
           for arg in ("--ignore", path)]


def _pytest(workspace: Path, *args: str, timeout: int = 300):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", *args, *_IGNORE,
         "-p", "no:cacheprovider"],
        cwd=workspace, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=timeout,
    )


def _collected(workspace: Path) -> int | None:
    completed = _pytest(workspace, "--co", "-q", timeout=180)
    if completed.returncode != 0:
        return None
    match = COLLECTED.search(completed.stdout + completed.stderr)
    return int(match.group(1)) if match else None


def check_baseline() -> tuple[int | None, str]:
    """The suite must pass in a workspace built exactly as the workers build theirs.

    On a red baseline every guard looks load-bearing, and the sweep reports zero
    removable -- which reads as the best possible outcome. That is the single most
    dangerous failure available to a measurement, and it is the one the previous version
    had no defence against.
    """
    workspace = _build_workspace()
    try:
        count = _collected(workspace)
        if count is None:
            return None, "the baseline workspace cannot collect the suite"
        completed = _pytest(workspace, "-q", "--no-header", "--tb=no", "-rf")
        if completed.returncode != 0:
            return None, (completed.stdout + completed.stderr).strip()[-1500:]
        return count, ""
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


_WORKSPACE: Path | None = None
_COLLECTED: int = 0


def _init_worker(collected: int) -> None:
    global _WORKSPACE, _COLLECTED
    _WORKSPACE = _build_workspace()
    _COLLECTED = collected


def _evaluate(guard: Guard) -> Result:
    assert _WORKSPACE is not None
    target = _WORKSPACE / "src" / PACKAGE / guard.file
    original = target.read_text()
    lines = original.splitlines(keepends=True)
    without = "".join(
        lines[: guard.span[0] - 1] + [" " * guard.indent + "pass\n"] + lines[guard.span[1]:]
    )
    try:
        compile(without, guard.file, "exec")
    except SyntaxError as exc:
        return Result(guard, Verdict.INVALID, f"does not compile: {exc.msg}")

    target.write_text(without)
    _purge(_WORKSPACE)
    try:
        count = _collected(_WORKSPACE)
        if count is None:
            return Result(guard, Verdict.INVALID, "collection or import failure")
        if count != _COLLECTED:
            return Result(guard, Verdict.INVALID,
                          f"changed the test universe: {count} vs {_COLLECTED}")
        # `-rfE`, not `-rf`: the latter reports failures only, so a test that ERRORS in
        # setup gives rc=1 with no FAILED and no ERROR line and nothing to diagnose.
        #
        # ONE RUN, THEN ATTRIBUTION. THE SECOND FULL-SUITE ATTEMPT IS GONE.
        #
        # What stood here was a `for attempt in (1, 2)` loop, and it answered the wrong
        # question. It re-ran the WHOLE SUITE hoping a FAILED line would appear, and the
        # first one that did -- from any test, for any reason -- promoted the guard to
        # LOAD_BEARING. Under a pool of workers each running a full pytest, a test can fail
        # for reasons that have nothing to do with the guard being removed. That is the same
        # saturation the retry was added for. So the retry did not defend against the
        # transient; it laundered it into evidence.
        #
        # And it laundered it in the flattering direction. An unrelated failure became proof
        # that a guard was covered, silently, which is the exact shape of the other
        # seventeen tooling defects found on this programme.
        #
        # The rule now matches `mutation_generator`, which is where it was already correct:
        # the named failure is re-run ALONE against the same guard-removed tree, and only a
        # failure that reproduces counts. A verdict can no longer be reached by repeating an
        # inconclusive full-suite run, which is what the release protocol means when it asks
        # for zero retries in the final evidence.
        completed = _pytest(_WORKSPACE, "-x", "-q", "--no-header", "--tb=no", "-rfE")
        if completed.returncode == 0:
            return Result(guard, Verdict.REMOVABLE)
        output = completed.stdout + completed.stderr
        failures = FAILED.findall(output)
        errors = ERROR.findall(output)
        if failures:
            killer = failures[0]
            if reproduces_alone(_WORKSPACE, killer):
                return Result(guard, Verdict.LOAD_BEARING, killer)
            return Result(
                guard, Verdict.INCONCLUSIVE,
                f"{killer} failed in the full run and passed when re-run alone against "
                f"the same guard-removed tree; not attributable to this guard",
            )
        # An ERROR is not an assertion. Nothing caught the removal.
        if errors:
            return Result(
                guard, Verdict.INCONCLUSIVE,
                f"no test FAILED; {len(errors)} test(s) ERRORED: {list(errors[:3])}",
            )
        tail = " ".join(output.strip().splitlines()[-2:])[:200]
        return Result(
            guard, Verdict.INCONCLUSIVE,
            f"rc={completed.returncode}, no FAILED and no ERROR line. "
            f"Last output: {tail!r}",
        )
    except subprocess.TimeoutExpired:
        # A guard whose removal hangs the suite may well matter, but no test asserted it.
        # Calling that load-bearing would be inferring coverage from a stall.
        return Result(guard, Verdict.INCONCLUSIVE,
                      "did not terminate without the guard; no assertion caught it")
    finally:
        target.write_text(original)
        if target.read_text() != original:
            raise AssertionError(f"worker source not restored: {guard.file}")
        _purge(_WORKSPACE)


def attribution_summary(results: list[Result]) -> tuple[int, int]:
    """(named, unnamed) among the LOAD_BEARING verdicts.

    DERIVED, BECAUSE THE FIRST VERSION OF THIS WAS A SENTENCE.

    The summary printed "every load-bearing guard names a killer that failed again when
    re-run alone" as an unconditional line. It was true of the code path -- LOAD_BEARING is
    only returned immediately after `reproduces_alone` agrees -- and it was still a claim
    rather than a measurement. It would have printed unchanged over a result set that
    contradicted it.

    That is the defect this whole programme keeps finding in its own evidence, committed
    inside the fix for another instance of it: a banner asserting a property nobody
    computed. So the number comes from the results, an unnamed load-bearing verdict is
    reported as a defect in this tool, and both directions are unit-tested.
    """
    load_bearing = [r for r in results if r.verdict is Verdict.LOAD_BEARING]
    named = sum(1 for r in load_bearing if r.detail)
    return named, len(load_bearing) - named


ACCEPTED_REMOVABLE: dict[str, str] = {}
"""Site id -> the human-readable reason that removable guard is accepted anyway.

EMPTY, AND THAT IS THE CURRENT TRUTH RATHER THAN A PLACEHOLDER.

The final sweep finds zero removable guards, so there is nothing to disposition and this
map is empty. It exists because `--gate` has to fail on a removable guard NOBODY DECIDED
ABOUT, and the only honest way to distinguish "accepted" from "unnoticed" is an explicit,
committed, per-site entry that a reviewer can read in the diff.

Two things it deliberately is not. It is not a policy mechanism: no globs, no severities,
no expiry, no categories. And nothing here is inferred from the guard's own message text.
The report above prints a timezone-hygiene breakdown derived from keywords in that prose,
which is fine for a breakdown and would be indefensible as an acceptance criterion -- a
guard would become acceptable because of how its exception happened to be worded. The gate
below never reads `guard.message`.
"""


def gate_failures(
    results: list[Result], accepted: dict[str, str] | None = None
) -> list[str]:
    """Every reason this result set fails the Phase-5 guard criterion. Empty means pass.

    MEASUREMENT AND ACCEPTANCE ARE DIFFERENT QUESTIONS, AND THIS TOOL ANSWERED ONLY ONE.

    `main` deliberately exits 0 whatever it finds, so that a sweep could never be
    reverse-engineered into a number somebody tunes. That is right for a measurement, and
    it is not sufficient for a gate: a third party running this tool got process success
    from a run containing INCONCLUSIVE results, INVALID results, a load-bearing verdict
    with nothing to reproduce, or a removable guard nobody had decided about.

    So the decision is a pure function over the result objects, separate from the process
    that produced them and from anything printed. It can be unit-tested against
    hand-built `Result`s in both directions, which is the only way to know a gate can say
    no.

    An EMPTY result set fails. A gate that passes when it measured nothing is the failure
    mode this programme has hit more than any other.
    """
    accepted = ACCEPTED_REMOVABLE if accepted is None else accepted
    reasons: list[str] = []

    if not results:
        return ["no results at all: an empty result set is not evidence of anything"]

    for result in sorted(results, key=lambda r: (r.guard.file, r.guard.line)):
        site = result.guard.site_id
        if result.verdict is Verdict.INCONCLUSIVE:
            reasons.append(f"{site}: INCONCLUSIVE -- {result.detail}")
        elif result.verdict is Verdict.INVALID:
            reasons.append(f"{site}: INVALID -- {result.detail}")
        elif result.verdict is Verdict.LOAD_BEARING and not result.detail:
            reasons.append(
                f"{site}: load-bearing with no named reproduced killer, so the verdict "
                f"rests on nothing a reader could re-run"
            )
        elif result.verdict is Verdict.REMOVABLE and site not in accepted:
            reasons.append(
                f"{site}: REMOVABLE with no committed disposition in ACCEPTED_REMOVABLE"
            )
        if result.retried:
            reasons.append(
                f"{site}: a full-suite retry was exercised, so this verdict is not "
                f"reproducible on a single run"
            )
    return reasons


def as_records(results: list[Result]) -> list[dict]:
    """The per-guard record set, ordered deterministically, for `diff` between runs.

    Deliberately narrow. Only fields whose value is fixed by the guard and its verdict
    appear: a nodeid is stable, whereas the free-text `detail` on an INCONCLUSIVE result
    can carry a return code or an error string that varies between runs and would make
    `diff` report differences that are not disagreements.

    Ordering is by file then line then scope, so two runs of the same tree emit
    byte-identical documents and ordinary `diff` is the whole comparison algorithm.
    """
    return [
        {
            "site_id": r.guard.site_id,
            "verdict": r.verdict.value,
            "killer": r.detail if (r.verdict is Verdict.LOAD_BEARING and r.detail) else None,
            "retried": r.retried,
        }
        for r in sorted(
            results, key=lambda r: (r.guard.file, r.guard.line, r.guard.scope)
        )
    ]


def main() -> int:
    show = "--list" in sys.argv
    # `--gate` DECIDES; the default still only measures. See `gate_failures`.
    gate = "--gate" in sys.argv
    # `--json` emits the record set on stdout and pushes every progress line to stderr,
    # so `guard_sweep.py --json --jobs 1 > j1.json` is a clean document a diff can read.
    as_json = "--json" in sys.argv
    # Per-site output exists so `--jobs 1` and `--jobs 2` can be DIFFED rather than
    # compared on totals. With every guard landing in one bucket the totals agree
    # vacuously, and a per-site claim resting on two empty sets is not reproducibility
    # evidence. The killer nodeid travels with each line, so a site that is load-bearing
    # in both runs for DIFFERENT reasons is visible too.
    sites = "--sites" in sys.argv
    # --jobs N, AND WHY A DEFAULT OF cpu_count-1 IS NOT GOOD ENOUGH FOR EVIDENCE.
    #
    # This was hardcoded. Nine workers each running a full pytest saturate the machine,
    # and under that load a test ERRORs in setup for reasons that have nothing to do with
    # the guard being removed -- which is why the retry below the fold exists at all.
    #
    # A retry is a fine diagnostic. It is not a standard of evidence: a number that
    # depended on a re-run is a number produced by a run that was not reproducible. So the
    # worker count is now an argument, and the release protocol takes its figures from
    # --jobs 1 and --jobs 2 and requires the two to agree per site, not merely in total.
    # A disagreement between them is a defect in this tool, not a fact about the package.
    jobs = max(1, (os.cpu_count() or 2) - 1)
    for index, argument in enumerate(sys.argv):
        if argument == "--jobs" and index + 1 < len(sys.argv):
            jobs = max(1, int(sys.argv[index + 1]))
        elif argument.startswith("--jobs="):
            jobs = max(1, int(argument.split("=", 1)[1]))

    # Every existing progress line goes to stderr for the duration of a --json run, so the
    # document on stdout is the whole of stdout. Rebinding once here beats threading a
    # stream argument through prints that exist only to be read by a human.
    real_stdout = sys.stdout
    if as_json:
        sys.stdout = sys.stderr
    try:
        return _run(targets=guards(), jobs=jobs, show=show, sites=sites,
                    gate=gate, as_json=as_json, real_stdout=real_stdout)
    finally:
        sys.stdout = real_stdout


def _run(*, targets, jobs, show, sites, gate, as_json, real_stdout) -> int:
    print(f"{len(targets)} raise statements in src/cai")
    print("checking the baseline suite is green in a worker-shaped workspace...")
    collected, why = check_baseline()
    if collected is None:
        print("\nBASELINE IS NOT GREEN. Every guard would read as load-bearing and this "
              "sweep would report zero removable, which looks like the best possible "
              "answer. Refusing to run.\n")
        print(why)
        return 2
    print(f"baseline collects {collected} tests\n")

    with multiprocessing.Pool(jobs, initializer=_init_worker,
                              initargs=(collected,)) as pool:
        results: list[Result] = []
        for done, result in enumerate(
            pool.imap_unordered(_evaluate, targets, chunksize=1), start=1
        ):
            results.append(result)
            if done % 25 == 0 or done == len(targets):
                free = sum(1 for r in results if r.verdict is Verdict.REMOVABLE)
                print(f"  {done}/{len(targets)} evaluated, {free} removable")

    results.sort(key=lambda r: (r.guard.file, r.guard.line))
    by_verdict = {v: [r for r in results if r.verdict is v] for v in Verdict}
    removable = by_verdict[Verdict.REMOVABLE]
    invalid = by_verdict[Verdict.INVALID]
    inconclusive = by_verdict[Verdict.INCONCLUSIVE]

    tz = [r for r in removable if any(
        w in r.guard.message.lower() for w in ("timezone", "tz-aware", "tzinfo"))]

    print("\n" + "=" * 78)
    print("GUARD SWEEP RESULT")
    print("=" * 78)
    print(f"jobs                         {jobs}")
    print(f"guards discovered            {len(targets)}")
    print(f"behaviourally load-bearing   {len(by_verdict[Verdict.LOAD_BEARING])}")
    print(f"removable                    {len(removable)}")
    # Stated whether or not any occurred, so "no retries" is a reported fact rather than
    # the absence of a line nobody looked for.
    retried = [r for r in results if r.retried]
    print(f"retries exercised            {len(retried)}")
    for result in retried:
        print(f"  {result.guard.file}:{result.guard.line}  {result.detail}")
    print(f"  timezone-awareness hygiene {len(tz)}")
    print(f"  not                        {len(removable) - len(tz)}")
    print(f"inconclusive (not attributed) {len(inconclusive)}")
    print(f"invalid (no test ran)        {len(invalid)}")

    # Counted, not claimed. See `attribution_summary`.
    named, unnamed = attribution_summary(results)
    print(f"  load-bearing with a reproduced named killer  {named}")
    if unnamed:
        print(f"  load-bearing with NO named killer           {unnamed}")
        print("  ^ a load-bearing verdict with nothing to re-run is a defect in this "
              "tool, not a fact about the package")

    if removable and show:
        print("\nREMOVABLE -- nothing in the suite holds these up:")
        for result in removable:
            print(f"  {result.guard.site_id:44} {result.guard.message[:90]}")
    elif removable:
        print("\nrun with --list to see each removable guard")

    if inconclusive:
        print("\nINCONCLUSIVE -- the suite went red but nothing reproduced against the "
              "guard. Not counted as load-bearing:")
        for result in inconclusive:
            print(f"  {result.guard.site_id:44} {result.detail}")

    if invalid:
        print("\nINVALID -- removing these broke the instrument, which proves nothing:")
        for result in invalid:
            print(f"  {result.guard.site_id:44} {result.detail}")

    if sites:
        print("\nPER-SITE CLASSIFICATION")
        print("diff this file between --jobs 1 and --jobs 2; totals agreeing is not the "
              "same claim.")
        for result in results:
            print(f"  {result.guard.site_id:44} {result.verdict.value:14} "
                  f"{result.detail}")

    print("\nre-checking the baseline in a fresh workspace...")
    after, why = check_baseline()
    if after != collected:
        print(f"\nthe tree does not return to its baseline: {why or after}")
        return 2
    print(f"clean: {after} tests collected and green")

    if as_json:
        json.dump(as_records(results), real_stdout, indent=2, sort_keys=True)
        real_stdout.write("\n")

    if not gate:
        # Default mode exits 0 whatever it finds. This measures; it does not decide. A
        # sweep that failed the build would be reverse-engineered into a number somebody
        # tunes, which is why the deciding lives behind --gate instead of replacing this.
        return 0

    failures = gate_failures(results)
    print("\n" + "=" * 78)
    if failures:
        print(f"GATE FAILED: {len(failures)} condition(s) unmet")
        print("=" * 78)
        for reason in failures:
            print(f"  {reason}")
        return 1
    print("GATE PASSED: every guard is load-bearing with a reproduced named killer, "
          "no inconclusive or invalid results, no retries, and every removable guard "
          "carries a committed disposition.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
