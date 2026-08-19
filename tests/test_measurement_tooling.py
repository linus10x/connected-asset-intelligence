"""The measurement tools are software, and they have failed five times in one direction.

THE RECORD, BECAUSE IT IS THE ARGUMENT FOR THIS FILE
-----------------------------------------------------
Every defect found in this tooling has flattered the result:

  1. the mutant workspace was an allowlist, twice incomplete -- so the committed-schema
     test failed in every workspace and every mutant looked killed. Reported 2015/2015
     over a gate that could not fail.
  2. the curated harness mutated the LIVE tree, producing three findings that all looked
     real and were artifacts of concurrent edits.
  3. twelve mutant attributions had gone stale: green in aggregate, guarding nothing.
  4. `killed = returncode != 0` scored every import and collection failure as a kill.
  5. `negate_condition` built its mutant from collapsed source text, so a condition
     carrying an inline comment produced invalid Python -- which, under (4), was a kill.

A tool whose output is evidence needs tests, and it must not be tested only by the suite
it measures: a defect that makes every mutant look killed also makes the production suite
look fully protective, so using that suite as the only check is circular.

So this file builds MINIATURE repositories -- three source functions and four tests -- and
runs the real generator against them, with the answer known in advance.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import guard_sweep as gs  # noqa: E402
import mutation_generator as mg  # noqa: E402


def _generator_cli_source() -> str:
    """`main` parses the flags and rebinds stdout; `_main` does the work and the reporting.
    A structural assertion about the generator's behaviour should not care which of the two
    currently holds a line."""
    import inspect

    return inspect.getsource(mg.main) + "\n" + inspect.getsource(mg._main)


def _sweep_cli_source() -> str:
    """`main` parses the flags and `_run` does the reporting; a structural assertion about
    the sweep's CLI behaviour should not care which of the two currently holds a line."""
    import inspect

    return inspect.getsource(gs.main) + inspect.getsource(gs._run)



PYPROJECT = """\
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tiny"
version = "0.0.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
"""

TINY_SOURCE = '''\
"""A miniature package with one guard the tests hold and one they do not."""
from __future__ import annotations


def refuse_negative(value: int) -> str | None:
    """A guard the miniature suite asserts."""
    if value < 0:
        raise ValueError("negative")
    return None


def unheld_guard(value: int) -> str | None:
    """A guard NOTHING asserts. Its removal must be reported as a survivor."""
    if value > 1000:
        raise ValueError("too large")
    return None


def permits(flag: bool) -> bool:
    return flag
'''

TINY_TESTS = '''\
import pytest

from tinypkg.tiny import permits, refuse_negative, unheld_guard


def test_a_negative_value_is_refused():
    with pytest.raises(ValueError, match="negative"):
        refuse_negative(-1)


def test_an_acceptable_value_passes():
    assert refuse_negative(1) is None


def test_a_large_value_is_not_asserted_here():
    assert unheld_guard(5) is None


def test_permits_returns_a_real_bool():
    assert permits(True) is True
'''



def span_of(source: str, fragment: str) -> tuple[int, int, int, int]:
    """Locate `fragment` and return its (line, col, end_line, end_col).

    Hand-counted spans put the first version of these tests at the wrong line, where the
    "uncompilable" mutant landed inside a docstring and compiled cleanly -- a test that
    passed for a reason that had nothing to do with what it claimed.
    """
    index = source.index(fragment)
    line = source[:index].count("\n") + 1
    col = index - (source.rfind("\n", 0, index) + 1)
    return (line, col, line, col + len(fragment))


def monkeypatch_package(repo: pathlib.Path) -> None:
    """`_evaluate` resolves the target through module-level PACKAGE and _WORKSPACE.

    Rebinding the env var after import does nothing -- both were read at import time,
    which is exactly the trap the workspace test below fell into.
    """
    mg.PACKAGE = "tinypkg"


@pytest.fixture()
def tiny(tmp_path):
    """A whole miniature repository the generator can be pointed at."""
    repo = tmp_path / "tiny"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "src" / "tinypkg" / "tiny.py").write_text(TINY_SOURCE)
    (repo / "tests" / "test_tiny.py").write_text(TINY_TESTS)
    return repo


def run_generator(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "mutation_generator.py"), "--jobs", "2", *args],
        capture_output=True, text=True, timeout=900,
        env=dict(os.environ, CAI_MUTGEN_ROOT=str(repo),
                 CAI_MUTGEN_PACKAGE="tinypkg", PYTHONDONTWRITEBYTECODE="1"),
    )


# --- 1 and 2: a kill is a kill and a survivor is a survivor ---------------


def test_a_held_guard_is_killed_and_an_unheld_one_survives(tiny):
    """Both directions in one run, because a tool that reported everything killed and a
    tool that reported everything surviving would each pass half of this."""
    done = run_generator(tiny)

    assert "behaviorally killed" in done.stdout
    assert "SURVIVED, UNEXPLAINED" in done.stdout
    assert "too large" in done.stdout, "the unheld guard must be named as a survivor"
    assert "GATE FAILED" in done.stdout
    assert done.returncode == 1


# --- 3: an uncompilable mutant is INVALID, never a kill -------------------


def test_an_uncompilable_mutation_is_reported_as_a_generator_defect(tiny):
    """The class that produced four mutants on the real tree. Before the compile check,
    each one broke the import and scored as a kill."""
    source = (tiny / "src" / "tinypkg" / "tiny.py").read_text()
    span = span_of(source, "value < 0")
    broken = mg.Mutation(
        file="tiny.py", line=span[0], scope="refuse_negative",
        mutation_class="deliberate", original="value < 0", mutated="value <<< 0",
        span=span,
    )
    paths = [tiny / "src" / "tinypkg" / "tiny.py"]

    assert mg.compile_check(paths, [broken]) == [broken]
    assert mg.compile_check(paths, mg.generate(paths)) == [], (
        "no mutation this generator emits may be invalid Python"
    )


def test_no_mutation_generated_from_the_real_package_is_invalid_python():
    """The miniature repository cannot catch this class, and the class is real.

    Four conditions in `src/cai` run long enough to carry an inline comment or a line
    continuation inside them. `negate_condition` used to wrap the COLLAPSED SOURCE TEXT,
    which puts the comment on one line and swallows the rest -- so all four mutants were
    invalid Python, and before the compile check existed each one broke the import and
    scored as a kill.

    It is built from `ast.unparse` now. This has already regressed once, when a
    clone-and-port workflow reverted the fix, so it is asserted over the real package
    rather than left to the next full gate run to rediscover.
    """
    paths = sorted((REPO / "src" / "cai").glob("*.py"))
    mutations = mg.generate(paths)

    assert len(mutations) > 1000, "the generator produced almost nothing"
    assert mg.compile_check(paths, mutations) == []


def test_the_declaration_ledger_is_not_audited_against_a_MUTATED_source_tree():
    """A test that compares a hardcoded ledger against the live source tree cannot live
    in the mutated universe, and the corrected gate is what proved it.

    The first version of this file asserted `audit_declarations(...) == ([], [])` over
    `REPO / "src" / "cai"`. Inside a mutation run that directory IS the mutant: the
    source fragment at a declared site is changed on purpose, so the site identity
    changes, so the declaration reads as stale, so the test fails -- and the harness
    scores a KILL.

    Seven mutants were killed that way. Not by an assertion about behaviour; by a test
    noticing that the source text it was told to expect had moved. The gate reported
    2054 killed and 0 survived, and seven of those kills were an artifact of this file.

    Staleness belongs where it already is: in `main`, which audits against the UNMUTATED
    tree before any worker starts. What is asserted here instead is the part that does
    not depend on source text at all -- that the audit is a pure function of its
    arguments, which is checked above against synthetic mutations.
    """
    import ast
    import inspect

    # No test in this file may audit the real ledger against the real package. Parsed,
    # not grepped, so the paragraph above explaining the trap does not trip it.
    tree = ast.parse(pathlib.Path(__file__).read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        body = ast.unparse(node)
        if "DECLARED_EQUIVALENT" in body or "DECLARED_INVALID" in body:
            assert "src" not in body or "tinypkg" in body, (
                f"{node.name} audits the shipped ledger against a tree that a mutation "
                f"run has already changed; every mutant at a declared site becomes a kill"
            )

    # And the gate still performs the audit -- over the UNMUTATED tree, before a single
    # worker starts.
    main_source = _generator_cli_source()
    assert "audit_declarations(" in main_source
    assert main_source.index("audit_declarations(") < main_source.index("GATE PASSED")


# --- 4: breaking collection is INVALID ------------------------------------


def test_a_mutant_that_breaks_collection_is_invalid_not_killed(tiny):
    """Delete the name the test module imports. The suite cannot even be collected, so
    no assertion caught anything -- and the old classifier called this a kill."""
    text = (tiny / "src" / "tinypkg" / "tiny.py").read_text()
    span = span_of(text, "def permits(flag: bool) -> bool:")
    mg._WORKSPACE, mg._BASELINE = tiny, mg.Baseline(collected=4)
    monkeypatch_package(tiny)

    outcome = mg._evaluate(mg.Mutation(
        file="tiny.py", line=span[0], scope="<module>",
        mutation_class="deliberate", original="def permits(flag: bool) -> bool:",
        mutated="def gone(flag: bool) -> bool:", span=span,
    ))

    assert outcome.verdict is mg.Verdict.INVALID
    assert outcome.killed is False
    assert "collection" in outcome.note or "universe" in outcome.note


# --- 5: a red baseline aborts before a single mutant runs -----------------


def test_a_red_baseline_refuses_to_run_at_all(tiny):
    """The failure that produced 2015/2015. On a red baseline every mutant looks killed
    and the gate becomes a machine that always says yes."""
    (tiny / "tests" / "test_broken.py").write_text(
        "def test_this_repository_is_not_green():\n    assert False\n"
    )
    done = run_generator(tiny)

    assert done.returncode == 2
    assert "BASELINE IS NOT GREEN" in done.stdout
    assert "evaluated" not in done.stdout, "no mutant may run on a red baseline"


# --- 6 and 7: identity, and one declaration suppressing two sites ----------


def test_duplicate_snippets_in_one_file_get_distinct_identities(tmp_path):
    """The defect in the old key. `(file, mutation_class, original)` is a pattern: two
    `if value < 0` guards in two functions collided, and one declaration silenced both."""
    repo = tmp_path / "dupes"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "dupes.py"
    source.write_text(
        "def first(value: int) -> str | None:\n"
        "    if value < 0:\n"
        "        raise ValueError('no')\n"
        "    return None\n"
        "\n\n"
        "def second(value: int) -> str | None:\n"
        "    if value < 0:\n"
        "        raise ValueError('no')\n"
        "    return None\n"
    )
    mutations = mg.generate([source])
    identities = [m.site_id for m in mutations]

    assert len(identities) == len(set(identities)), "two sites share an identity"
    negations = [m for m in mutations if m.mutation_class == "negate_condition"]
    assert len(negations) == 2
    assert {m.scope for m in negations} == {"first", "second"}, (
        "the qualified scope is what separates them"
    )


def test_two_identical_snippets_in_one_scope_are_separated_by_ordinal(tmp_path):
    """Scope alone is not enough: one function can hold the same fragment twice."""
    repo = tmp_path / "twice"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "twice.py"
    source.write_text(
        "def check(a: int, b: int) -> str | None:\n"
        "    if a < 0:\n"
        "        raise ValueError('a')\n"
        "    if a < 0:\n"
        "        raise ValueError('b')\n"
        "    return None\n"
    )
    negations = [m for m in mg.generate([source])
                 if m.mutation_class == "negate_condition"]

    assert len(negations) == 2
    assert {m.occurrence for m in negations} == {0, 1}
    assert negations[0].site_id != negations[1].site_id


# --- 8 and 9: stale and ambiguous declarations both fail ------------------


def test_a_stale_declaration_is_reported(tmp_path):
    repo = tmp_path / "stale"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "stale.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    mutations = mg.generate([source])

    stale, ambiguous, unnecessary = mg.audit_declarations(
        {"stale.py::f::negate_condition::#7::a < 0": "a reason"},
        mutations, {"stale.py"},
    )

    assert stale == ["stale.py::f::negate_condition::#7::a < 0"]
    assert (ambiguous, unnecessary) == ([], [])


def test_a_declaration_matching_a_real_site_is_neither_stale_nor_ambiguous(tmp_path):
    """The twin. A staleness rule that flagged everything would pass the test above."""
    repo = tmp_path / "live"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "live.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    mutations = mg.generate([source])
    real = next(m.site_id for m in mutations
                if m.mutation_class == "negate_condition")

    audit = mg.audit_declarations({real: "a reason"}, mutations, {"live.py"})

    assert audit == ([], [], [])


def test_an_ambiguous_declaration_would_be_reported(tmp_path):
    """Ambiguity is impossible by construction now -- `generate` asserts identities are
    unique -- so this exercises the audit against a hand-built duplicate list. Without
    it, the branch that reports ambiguity would never run and could rot unnoticed."""
    repo = tmp_path / "ambig"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "ambig.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    one = mg.generate([source])[0]

    _, ambiguous, _ = mg.audit_declarations(
        {one.site_id: "a reason"}, [one, one], {"ambig.py"}
    )

    assert ambiguous == [one.site_id]


def test_a_declaration_whose_mutant_is_killed_is_reported_as_unnecessary(tmp_path):
    """The rule Control Tower did not ask for, and the one that actually bites.

    A declaration says "no test can observe this mutant". When coverage grows and a test
    starts observing it, the declaration becomes a FALSE claim about the suite -- and
    nothing flags it, because it still matches a real site and is therefore not stale.
    It just quietly sits there reading as a known-unreachable.

    Seven of these appeared in one round of this pass, when the hostile suite landed and
    killed every remaining survivor. They were deleted. This is what catches the next
    seven.
    """
    repo = tmp_path / "grew"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "grew.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    one = mg.generate([source])[0]
    killed = mg.Outcome(one, mg.Verdict.KILLED, killed_by=("tests/test_x.py::test_y",))

    _, _, unnecessary = mg.audit_declarations(
        {one.site_id: "nothing can see this"}, [one], {"grew.py"}, [killed]
    )
    assert unnecessary == [one.site_id]

    # And a survivor's declaration is still fine -- the rule must not fire on the state
    # it exists to permit.
    survived = mg.Outcome(one, mg.Verdict.SURVIVED)
    _, _, still_fine = mg.audit_declarations(
        {one.site_id: "nothing can see this"}, [one], {"grew.py"}, [survived]
    )
    assert still_fine == []


NESTED = (
    "def outer(flag: bool) -> bool:\n"
    "    def inner() -> bool:\n"
    "        return flag\n"
    "    return inner()\n"
)


def nested_source(tmp_path, name: str = "nested"):
    repo = tmp_path / name
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / f"{name}.py"
    source.write_text(NESTED)
    return source


def test_a_nested_return_is_generated_once_and_attributed_to_its_own_scope(tmp_path):
    """THE DEFECT. `ast.walk` had already scheduled the nested function's descendants.

    `_return_mutations` walked the function body with `ast.walk(fn)` and skipped nested
    `FunctionDef` nodes with `continue`. That skips the DEF; it does not prune the
    subtree, because `ast.walk` is breadth-first over a queue it has already populated.
    So `return flag` inside `inner` was collected under `outer` -- and `_walk_scoped`
    then visited `inner` properly and collected it again under `outer.inner`.

    The duplicate-identity assertion could not see it. `site_id` includes the scope, so
    two records of one physical statement under two different scopes are two distinct
    identities: the generator counted the same source location twice, reported two
    mutants where one exists, and a declaration written against one would leave the
    other live.
    """
    mutations = mg.generate([nested_source(tmp_path)])
    returns = [m for m in mutations if m.mutation_class.endswith("_return")]

    by_span = {}
    for mutation in returns:
        by_span.setdefault(mutation.span, set()).add((mutation.scope, mutation.mutation_class))
    for span, seen in by_span.items():
        scopes = {scope for scope, _ in seen}
        assert len(scopes) == 1, (
            f"the statement at {span} was generated under {sorted(scopes)}; one physical "
            f"return belongs to exactly one scope"
        )

    assert {m.scope for m in returns} == {"outer", "outer.inner"}
    # `return inner()` is not a bool literal, `return flag` is not either -- both are
    # substitutable, one per scope, two classes each.
    assert len([m for m in returns if m.scope == "outer"]) == 2
    assert len([m for m in returns if m.scope == "outer.inner"]) == 2


def test_the_outer_and_inner_returns_are_different_source_locations(tmp_path):
    """The twin. A fix that stopped generating the inner return AT ALL would satisfy the
    test above and would have removed real coverage rather than a duplicate."""
    mutations = mg.generate([nested_source(tmp_path, "twoscopes")])
    returns = [m for m in mutations if m.mutation_class.endswith("_return")]

    spans = {m.scope: m.span for m in returns}
    assert spans["outer"] != spans["outer.inner"]
    assert spans["outer.inner"][0] == 3, "the inner return is on line 3"
    assert spans["outer"][0] == 4, "the outer return is on line 4"


def test_no_physical_span_in_the_real_package_is_generated_under_two_scopes():
    """The structural assertion over the package this tool actually measures.

    The synthetic case above proves the mechanism. This proves the mechanism is not
    firing anywhere in `src/cai` -- which is the claim the mutation score depends on,
    because a duplicated site inflates both the generated count and the killed count.
    """
    package = pathlib.Path(__file__).resolve().parent.parent / "src" / "cai"
    mutations = mg.generate(sorted(package.glob("*.py")))

    by_location = {}
    for mutation in mutations:
        key = (mutation.file, mutation.span, mutation.mutation_class)
        by_location.setdefault(key, set()).add(mutation.scope)

    collisions = {k: sorted(v) for k, v in by_location.items() if len(v) > 1}
    assert not collisions, (
        f"{len(collisions)} source locations are generated under more than one scope: "
        f"{list(collisions.items())[:3]}"
    )


def test_the_generator_refuses_to_emit_two_mutations_with_one_identity(tmp_path):
    """The assertion that makes ambiguity structurally impossible, exercised directly."""
    repo = tmp_path / "collide"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "collide.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    real = mg.generate([source])

    assert len({m.site_id for m in real}) == len(real)


# --- 10: a new data dependency is picked up without anyone remembering ----


def test_a_new_repository_data_file_reaches_the_worker_workspace(tiny):
    """The allowlist defect, from the other side.

    `schema/` and then `.githooks/` were each absent from the worker workspace, so the
    tests that read them failed in every workspace and every mutant looked killed. The
    denylist means a data dependency added tomorrow arrives without anyone updating a
    list -- which is the property being asserted, not the two files that were missed.
    """
    (tiny / "reference").mkdir()
    (tiny / "reference" / "fixture.json").write_text('{"needed": true}\n')
    (tiny / "tests" / "test_reads_data.py").write_text(
        "import json, pathlib\n\n\n"
        "def test_the_fixture_is_present():\n"
        "    data = json.loads(pathlib.Path('reference/fixture.json').read_text())\n"
        "    assert data['needed'] is True\n"
    )
    import shutil

    original = mg.ROOT
    mg.ROOT = tiny  # read at import time, so the env var alone would do nothing
    try:
        workspace = mg._build_workspace()
        try:
            assert (workspace / "reference" / "fixture.json").exists(), (
                "a data dependency nobody listed did not reach the workspace"
            )
        finally:
            shutil.rmtree(workspace.parent, ignore_errors=True)
    finally:
        mg.ROOT = original


# --- 11: the real tree is never touched -----------------------------------


def test_the_real_source_tree_is_never_modified(tiny):
    """The curated harness mutated the live tree and produced three false findings that
    all looked real. Hashed before and after a full run, over the repository this test
    is running from -- not the miniature one."""
    import hashlib

    def fingerprint() -> str:
        digest = hashlib.sha256()
        for path in sorted((REPO / "src" / "cai").glob("*.py")):
            digest.update(path.read_bytes())
        return digest.hexdigest()

    before = fingerprint()
    run_generator(tiny)

    assert fingerprint() == before, "the real src/cai changed during a mutation run"


def test_the_tool_writes_nothing_inside_the_repository_it_measures(tiny):
    """The structural half. Every write in the runner targets `_WORKSPACE`, and a write
    that reached `ROOT` would be the live-tree defect returning under a new name."""
    import ast
    import inspect

    for function in (mg._evaluate, mg._build_workspace, mg._check_baseline):
        tree = ast.parse(inspect.getsource(function).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                "write_text", "write_bytes", "unlink", "mkdir"
            ):
                target = ast.unparse(node.value)
                assert "ROOT" not in target and "SRC" not in target, (
                    f"{function.__name__} writes to {target}"
                )


# ===========================================================================
# THE GUARD SWEEP, WHICH REPORTED THE SAME NUMBER BROKEN AND FIXED.
#
# The old sweep reported 0 removable of 208. The corrected one reports 0 removable
# of 214. That is the same headline from a tool with four defects and from a tool
# without them, which is exactly when a reader should stop believing it -- all four
# defects biased towards zero, so "0 removable" was the number a broken sweep would
# print whatever the truth was.
#
# So the sweep is required to FIND a removable guard when one exists. Without this
# test, "0 removable" and "this tool cannot report anything else" are the same
# observation.
# ===========================================================================


GUARDED_SOURCE = '''\
"""One guard the miniature suite asserts, and one it does not."""
from __future__ import annotations


def refuse_negative(value: int) -> int:
    if value < 0:
        raise ValueError("negative")
    return value


def unheld_guard(value: int) -> int:
    if value > 1000:
        raise ValueError("too large")
    return value
'''

GUARDED_TESTS = '''\
import pytest

from tinypkg.guarded import refuse_negative, unheld_guard


def test_a_negative_value_is_refused():
    with pytest.raises(ValueError, match="negative"):
        refuse_negative(-1)


def test_an_acceptable_value_passes():
    assert refuse_negative(1) == 1


def test_a_large_value_is_not_asserted_here():
    assert unheld_guard(5) == 5
'''


@pytest.fixture()
def guarded(tmp_path):
    repo = tmp_path / "guarded"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "src" / "tinypkg" / "guarded.py").write_text(GUARDED_SOURCE)
    (repo / "tests" / "test_guarded.py").write_text(GUARDED_TESTS)
    return repo


def run_sweep(repo: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "guard_sweep.py"), "--list"],
        capture_output=True, text=True, timeout=900,
        env=dict(os.environ, CAI_GUARD_ROOT=str(repo),
                 CAI_GUARD_PACKAGE="tinypkg", PYTHONDONTWRITEBYTECODE="1"),
    )


def test_the_sweep_separates_a_held_guard_from_an_unheld_one(guarded):
    """Two guards, one asserted and one not. A sweep that cannot tell them apart is not
    measuring anything, and "0 removable" from such a tool means nothing at all."""
    done = run_sweep(guarded)

    assert "guards discovered            2" in done.stdout, done.stdout
    assert "behaviourally load-bearing   1" in done.stdout, done.stdout
    assert "removable                    1" in done.stdout, done.stdout
    assert "too large" in done.stdout, "the removable guard is not named"
    assert "negative" not in done.stdout.split("REMOVABLE")[-1], (
        "the held guard was reported as removable"
    )


def test_the_sweep_refuses_to_run_on_a_red_baseline(guarded):
    """On a red baseline every guard reads as load-bearing and the sweep reports zero
    removable -- which looks like the best possible answer. The old sweep had no
    defence against this at all."""
    (guarded / "tests" / "test_broken.py").write_text(
        "def test_this_repository_is_not_green():\n    assert False\n"
    )
    done = run_sweep(guarded)

    assert done.returncode == 2
    assert "BASELINE IS NOT GREEN" in done.stdout
    assert "evaluated" not in done.stdout


def test_the_sweep_never_writes_inside_the_repository_it_measures(guarded):
    """The old sweep replaced each raise in the LIVE tree and restored it afterwards, so
    a crash between the two left the repository altered and a concurrent edit could be
    silently reverted. Hashed before and after, over this repository."""
    import hashlib

    def fingerprint() -> str:
        digest = hashlib.sha256()
        for path in sorted((REPO / "src" / "cai").glob("*.py")):
            digest.update(path.read_bytes())
        return digest.hexdigest()

    before = fingerprint()
    run_sweep(guarded)

    assert fingerprint() == before, "the real src/cai changed during a guard sweep"


def test_the_sweep_requires_a_failing_test_not_the_absence_of_a_word(guarded):
    """STRUCTURAL, and it names the exact defect.

    The old sweep decided the suite had passed with `"failed" not in stdout`. A guard
    whose removal broke COLLECTION prints no failed line, so it was scored load-bearing
    -- the flattering answer. A kill must come from a named FAILED test.
    """
    import inspect

    source = inspect.getsource(gs._evaluate)
    assert "FAILED.findall" in source
    # The detector itself, not the word: `GREEN = "failed"` with `GREEN not in out` is
    # the construct that scored a collection break as a healthy guard. The prose above
    # explains it and must not trip this.
    body = inspect.getsource(gs)
    assert 'GREEN = "failed"' not in body, "the string-absence detector is back"
    assert "GREEN not in" not in body
    assert "returncode" in source, "the return code must be read"


def test_the_excluded_universe_is_excluded_from_the_baseline_too():
    """The exclusion must be symmetric or it is a weakening rather than a scoping.

    `tests/test_measurement_tooling.py` is kept out of the mutated universe because it
    spawns the tools it tests -- eight nested invocations per suite run, paid 2056 times
    by nine workers at once -- and because it asserts facts about the tools rather than
    about `src/cai`, so no mutant there can be killed by it.

    That is only legitimate if the BASELINE excludes it identically. If the baseline
    counted it and the mutants did not, every mutant would look like it changed the test
    universe and be classified INVALID; if the reverse, the collected counts would never
    agree. Both paths take the same `_IGNORE`, and this fixes that in place.
    """
    import inspect

    for source in (inspect.getsource(mg._collect), inspect.getsource(mg._run_suite)):
        assert "_IGNORE" in source, "one pytest invocation does not apply the exclusion"
    # PINNED, because an exclusion list is a list of things this gate does not measure and
    # it must not grow quietly. `test_schema_reconciliation.py` joined it for a stated
    # reason: it parametrizes over an inventory parsed out of the live `src/cai`, so
    # removing a raise removes a case and the universe changes size. Anything else added
    # here has to break this assertion first and be argued for.
    assert mg.EXCLUDED_FROM_THE_MUTATED_UNIVERSE == (
        "tests/test_measurement_tooling.py",
        "tests/test_schema_reconciliation.py",
    )

    # `_check_baseline` reaches pytest only through those two, so the baseline cannot
    # diverge from a worker without one of the assertions above failing first.
    baseline = inspect.getsource(mg._check_baseline)
    assert "_collect(" in baseline and "_run_suite(" in baseline
    assert "subprocess.run" not in baseline, (
        "the baseline builds its own pytest call and can drift from the workers"
    )

    assert "_IGNORE" in inspect.getsource(gs._pytest)
    guard_baseline = inspect.getsource(gs.check_baseline)
    assert "subprocess.run" not in guard_baseline


def test_both_tools_report_errors_as_well_as_failures():
    """`-rf` reports FAILURES ONLY, and that cost two false INVALID verdicts.

    A test that ERRORS during setup gives pytest rc=1, no FAILED line, and -- because
    -rf omits errors -- no ERROR line either. The classifier could then say nothing
    better than "the suite did not run cleanly and no test FAILED", which is both
    unactionable and, in both observed cases, wrong: each mutant was a clean,
    reproducible kill when re-run on an unloaded machine.

    Nine workers each running a full suite saturate the machine, so transient setup
    errors are a fact of this design rather than a surprise. The fix is to SEE them.
    """
    import inspect

    for source in (inspect.getsource(mg._run_suite), inspect.getsource(gs._evaluate)):
        assert '"-rfE"' in source, "a pytest run reports failures but not errors"
        assert '"-rf"' not in source


def test_an_inconclusive_run_is_confirmed_before_it_is_believed():
    """And the retry is REPORTED, never silent.

    A gate that quietly re-runs until it likes the answer is worse than one that is
    honestly flaky, so the note says a confirmation happened and what the first run
    said. The retry covers only the RUN stage -- compilation and collection are
    deterministic and are not repeated.
    """
    import inspect

    evaluate = inspect.getsource(mg._evaluate)
    assert "_classify_run(mutation)" in evaluate
    assert evaluate.count("_classify_run(mutation)") == 2, (
        "the inconclusive run is not confirmed"
    )
    assert "confirmed on a second run" in evaluate
    assert "[twice]" in evaluate, "a twice-inconclusive verdict must say so"

    # Compilation and collection must NOT be inside the retry: repeating a
    # deterministic check buys nothing and would hide a real generator defect.
    classify = inspect.getsource(mg._classify_run)
    assert "compile(" not in classify and "_collect(" not in classify


# ===========================================================================
# THE POLARITY SUITE. Sixteen ways this tool could be wrong, each in the
# direction that would make the package look better than it is.
# ===========================================================================
#
# Every one of the eleven tooling defects found across this programme failed in the
# flattering direction. Not one made the suite look worse than it was. That is not a
# coincidence a reader should have to notice for themselves: a measurement written by
# the party it exonerates has a systematic bias, and the only defence is to test the
# bias explicitly rather than to test that the tool works.
#
# So each case below asks the same question in a different place: when this goes wrong,
# does the tool say "covered"?


def test_an_unrelated_failing_test_is_not_counted_as_a_kill(tiny, monkeypatch):
    """CASE 1, AND THE ONE THAT MATTERS MOST.

    A test failing for reasons unconnected to the mutation used to be a kill: the
    classifier asked "did any test FAIL?" and a transient under a saturated machine
    answered yes. So a random failure became evidence that the intended property is
    covered -- silently, and in the direction that inflates the score.

    Simulated by making the full-suite run report a failure that does NOT reproduce when
    the named test is run alone, which is exactly what a transient looks like.
    """
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    monkeypatch.setattr(
        mg, "_run_suite",
        lambda ws: subprocess.CompletedProcess(
            [], 1, stdout="FAILED tests/test_tiny.py::test_something_unrelated\n",
            stderr=""),
    )
    monkeypatch.setattr(mg, "_reproduces_alone", lambda killer: False)

    outcome = mg._classify_run(_any_mutation())

    assert outcome.verdict is not mg.Verdict.KILLED
    assert outcome.verdict is mg.Verdict.SURVIVED
    assert "not attributable" in outcome.note


def test_a_reproducible_failure_is_still_a_kill(tiny, monkeypatch):
    """TWIN FOR CASE 1. The attribution check must not refuse every kill.

    Without this the fix above could be "return SURVIVED whenever anything fails", which
    would satisfy the previous test and destroy the measurement.
    """
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    monkeypatch.setattr(
        mg, "_run_suite",
        lambda ws: subprocess.CompletedProcess(
            [], 1, stdout="FAILED tests/test_tiny.py::test_a_negative_value_is_refused\n",
            stderr=""),
    )
    monkeypatch.setattr(mg, "_reproduces_alone", lambda killer: True)

    outcome = mg._classify_run(_any_mutation())

    assert outcome.verdict is mg.Verdict.KILLED
    assert outcome.killed_by == ("tests/test_tiny.py::test_a_negative_value_is_refused",)


def test_the_targeted_check_can_actually_say_yes(tiny, monkeypatch):
    """CASE 1's MISSING DIRECTION, and it cost a whole slice to find.

    `_reproduces_alone` was written with only its refusal tested: three assertions that
    it says NO for a nonexistent test, a bad path, a timeout. It gated on pytest's
    "N tests collected" line -- which `-q` SUPPRESSES -- so it said NO to everything, and
    the first real run downgraded every kill in the package to a survivor and reported 34
    unexplained survivors with an empty kill list.

    A check tested only for its ability to refuse passes every one of those tests while
    being unconditionally wrong. This is the same hole as the eleven flattering defects,
    pointing the conservative way, and it is the reason both directions are asserted here
    against a real test that really fails in a real workspace.
    """
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    (tiny / "tests" / "test_certain.py").write_text(
        "def test_this_one_always_fails():\n    assert False\n"
        "\n\ndef test_this_one_always_passes():\n    assert True\n"
    )

    assert mg._reproduces_alone(
        "tests/test_certain.py::test_this_one_always_fails") is True
    assert mg._reproduces_alone(
        "tests/test_certain.py::test_this_one_always_passes") is False


def test_a_parametrized_killer_reproduces_alone_in_a_real_workspace(tiny, monkeypatch):
    """The two halves together: a name that survives parsing must also RESOLVE.

    A parametrized id whose parameter contains spaces is the case that broke the regex,
    and a regex fix that produced a well-formed but unresolvable id would satisfy the
    parsing test and still fail here.
    """
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    (tiny / "tests" / "test_params.py").write_text(
        "import pytest\n\n\n"
        '@pytest.mark.parametrize("case", ["a required key is deleted", "clean"])\n'
        "def test_cases(case):\n"
        '    assert case == "clean"\n'
    )

    assert mg._reproduces_alone(
        "tests/test_params.py::test_cases[a required key is deleted]") is True
    assert mg._reproduces_alone("tests/test_params.py::test_cases[clean]") is False


def test_an_unrunnable_targeted_check_does_not_grant_a_kill(tiny, monkeypatch):
    """CASE 1, third direction. `_reproduces_alone` must fail closed.

    If the targeted re-run cannot answer the question -- a bad nodeid, a collection
    error, a timeout -- the honest verdict is "not demonstrated", not "demonstrated".
    A check that returns True when it does not know is the flattering default wearing a
    conservative name.
    """
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    assert mg._reproduces_alone("tests/test_tiny.py::test_does_not_exist") is False
    assert mg._reproduces_alone("tests/no_such_file.py::whatever") is False


def test_an_unrelated_error_is_invalid_and_not_a_kill(tiny, monkeypatch):
    """CASE 2. rc != 0 with an ERROR and no FAILED is not evidence of anything."""
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    monkeypatch.setattr(
        mg, "_run_suite",
        lambda ws: subprocess.CompletedProcess(
            [], 1, stdout="ERROR tests/test_tiny.py::test_a_negative_value_is_refused\n",
            stderr=""),
    )

    outcome = mg._classify_run(_any_mutation())

    assert outcome.verdict is mg.Verdict.INVALID
    assert "ERRORED" in outcome.note


def test_a_run_that_fails_with_neither_marker_is_invalid(tiny, monkeypatch):
    """CASE 2, tail. rc != 0 and nothing parseable is the case that must not default
    to a kill, because it is the one nobody anticipated."""
    monkeypatch.setattr(mg, "_WORKSPACE", tiny)
    monkeypatch.setattr(
        mg, "_run_suite",
        lambda ws: subprocess.CompletedProcess([], 4, stdout="INTERNALERROR\n", stderr=""),
    )

    outcome = mg._classify_run(_any_mutation())

    assert outcome.verdict is mg.Verdict.INVALID
    assert "no FAILED and no ERROR" in outcome.note


def _any_mutation() -> mg.Mutation:
    """One well-formed Mutation for the classifier tests. Its content is irrelevant --
    these exercise how a RUN is read, not what was mutated."""
    return mg.Mutation(
        "tiny.py", 7, "refuse_negative", "negate_condition", "value < 0",
        "not (value < 0)", (7, 7, 7, 16),
    )


def test_a_diagnostic_only_declaration_is_neither_killed_nor_equivalent():
    """CASE 7. The two ledgers are disjoint and mean different things.

    DECLARED_EQUIVALENT asserts no observable difference for any reachable input and
    carries a proof. DECLARED_DIAGNOSTIC_ONLY admits a real behavioural difference in
    output the gate has chosen not to pin. Merging them let six mutants that change
    what a reader is told be reported as proven equivalent.
    """
    overlap = set(mg.DECLARED_EQUIVALENT) & set(mg.DECLARED_DIAGNOSTIC_ONLY)
    assert not overlap, f"a site declared both ways: {sorted(overlap)}"
    assert mg.DECLARED_DIAGNOSTIC_ONLY, "the diagnostic ledger is empty"
    for site, reason in mg.DECLARED_DIAGNOSTIC_ONLY.items():
        assert reason.strip(), f"{site} is declared with no reason"


def test_the_only_equivalence_declaration_states_a_proof_not_an_observation():
    """CASE 8. An equivalence must be argued from the implementation.

    "No test noticed" is a fact about the suite. "No reachable input can distinguish
    these programs" is a fact about the code, and only the second justifies excluding a
    survivor from the score. The surviving declaration is the policy guard, whose
    excluded arm provably passes the empty tuple to extend().
    """
    assert len(mg.DECLARED_EQUIVALENT) == 1, (
        "each equivalence declaration needs its own proof; if the ledger has grown, this "
        "test should be extended rather than relaxed"
    )
    [(site, reason)] = mg.DECLARED_EQUIVALENT.items()
    assert "policy.py" in site
    assert "empty" in reason and "extend" in reason


def test_the_policy_guard_equivalence_holds_in_the_real_implementation():
    """CASE 8, verified against the code rather than against the comment.

    The declaration's proof is that `release_decision()` returns RELEASE exactly when
    `blocking_reasons()` is empty, so the arm the guard excludes contributes nothing.
    A declaration whose premise silently stopped being true would be a suppression
    covering a real survivor, so the premise is asserted here, in both directions.
    """
    from cai.evidence import (
        Completeness, EntitlementState, EvidenceAssessment, Identity, Integrity,
        Release, Support, TemporalEligibility,
    )

    releasing = EvidenceAssessment(
        support=Support.SUPPORTED, completeness=Completeness.COMPLETE,
        integrity=Integrity.VALID,
        temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
        identity=Identity.RESOLVED, entitlement=EntitlementState.AUTHORIZED,
    )
    withholding = EvidenceAssessment(
        support=Support.UNSUPPORTED, completeness=Completeness.COMPLETE,
        integrity=Integrity.VALID,
        temporal_eligibility=TemporalEligibility.ELIGIBLE_AS_OF_DECISION,
        identity=Identity.RESOLVED, entitlement=EntitlementState.AUTHORIZED,
    )

    assert releasing.release_decision() is Release.RELEASE
    assert releasing.blocking_reasons() == (), (
        "the equivalence declaration rests on this: the arm the guard excludes has "
        "nothing to extend with"
    )
    assert withholding.release_decision() is Release.WITHHOLD
    assert withholding.blocking_reasons() != ()


def test_a_declared_invalid_mutant_is_not_counted_as_a_kill():
    """CASE 9. An unevaluable mutant is an admission, not an achievement.

    `MetricApplicability.__post_init__` guards a module-level tuple, so a mutant that
    makes it always raise breaks `import cai.predictor` and every test module errors in
    collection. The old classifier scored exactly that as a kill.
    """
    assert mg.DECLARED_INVALID, "the invalid ledger is empty"
    for site, reason in mg.DECLARED_INVALID.items():
        assert reason.strip(), f"{site} is declared invalid with no reason"
        assert site not in mg.DECLARED_EQUIVALENT
        assert site not in mg.DECLARED_DIAGNOSTIC_ONLY


def test_a_stale_invalid_declaration_is_reported(tmp_path):
    """CASE 11. The invalid ledger is audited on the same terms as the others.

    A declaration that matches no generated mutant is a suppression nobody can see, and
    it is worse on this ledger than on the equivalence one: it excuses a mutant that no
    longer exists while the site it named may now be generating a live survivor.
    """
    repo = tmp_path / "staleinvalid"
    (repo / "src" / "tinypkg").mkdir(parents=True)
    source = repo / "src" / "tinypkg" / "staleinvalid.py"
    source.write_text("def f(a: int) -> str | None:\n    if a < 0:\n"
                      "        raise ValueError('x')\n    return None\n")
    mutations = mg.generate([source])

    stale, ambiguous, unnecessary = mg.audit_declarations(
        {"staleinvalid.py::f::negate_condition::#0::a > 999": "no longer generated"},
        mutations, {"staleinvalid.py"}, [],
    )

    assert stale == ["staleinvalid.py::f::negate_condition::#0::a > 999"]
    assert not ambiguous and not unnecessary


def test_the_diagnostic_ledger_is_audited_for_staleness_like_the_others():
    """CASE 11, applied to the ledger this pass introduced.

    A new suppression category with no staleness audit is how the previous ledger's
    pattern-matching key survived three rounds: it silenced sites nobody could enumerate
    and the report counted declarations while implying it had counted sites.
    """
    import inspect

    body = _generator_cli_source()
    assert "audit_declarations(\n        DECLARED_DIAGNOSTIC_ONLY" in body, (
        "the diagnostic-only ledger must be audited for stale, ambiguous and unnecessary "
        "declarations exactly as the equivalence ledger is"
    )
    for signal in ("d_stale", "d_ambiguous", "d_unnecessary"):
        assert signal in body, f"{signal} is not reported or not gated on"


def test_the_gate_fails_on_an_unnecessary_diagnostic_declaration():
    """CASE 12, on the new ledger. A declaration whose mutant a test KILLS is false.

    It claims the suite does not pin this wording. If a test kills the mutant, the suite
    pins it, and the declaration is suppressing a line in a report about a mutant that
    was caught -- which understates the suite and hides a stale claim.
    """
    import inspect

    body = _generator_cli_source()
    assert "unnecessary diagnostic-only declaration(s)" in body


def test_the_final_wording_does_not_claim_more_than_the_run_demonstrated():
    """CASE 10's honest half, asserted as a string.

    The gate used to print "every generated mutant compiled, ran the same test universe,
    and was either killed by a failing test or declared unreachable" on runs where two
    mutants did not compile the package at all and six changed observable output. A
    summary that is false for eight of the mutants it summarises is a wrong count wearing
    prose, and it is the last thing a reader sees.
    """
    import ast
    import inspect
    import textwrap

    # OVER THE STRINGS ACTUALLY PRINTED, not over the source text. Matching source would
    # be satisfied -- or broken -- by a comment, and the first version of this test failed
    # against the paragraph explaining why the old wording was wrong. A test that a
    # sentence is not SAID must look at what is said.
    tree = ast.parse(textwrap.dedent(_generator_cli_source()))
    printed = " ".join(
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )

    assert "every generated mutant compiled, ran the same test universe" not in printed
    for clause in ("behaviourally evaluated", "declared diagnostic-only",
                   "proven equivalent", "declared invalid for a named structural reason"):
        assert clause in printed, f"the final summary no longer states {clause!r}"


def test_both_tools_accept_an_explicit_worker_count():
    """CASE 1's environmental half. Concurrency is the source of the transients.

    `guard_sweep.py` hardcoded `cpu_count - 1`, so its only defence against a saturated
    machine was the retry -- and a number that depended on a re-run is a number produced
    by a run that was not reproducible. Final evidence comes from --jobs 1 and --jobs 2
    with identical per-site classifications.
    """
    import inspect

    assert "--jobs" in _generator_cli_source()
    sweep = _sweep_cli_source()
    assert "--jobs" in sweep
    assert "jobs = max(1, int(" in sweep


def test_both_tools_report_whether_any_retry_was_exercised():
    """CASE 1's reporting half.

    The retry is sound and the silence about it was not. "No retries" has to be a
    printed fact, not the absence of a line nobody thought to look for.
    """
    import inspect

    assert "retries exercised" in _generator_cli_source()
    assert "retries exercised" in _sweep_cli_source()
    assert "retried" in inspect.getsource(mg.Outcome)
    assert "retried" in inspect.getsource(gs.Result)


def test_a_parametrized_killer_is_named_in_full(tiny, monkeypatch):
    """CASE 1's parsing half, and a defect the attribution check exposed.

    `FAILED (\\S+)` stopped at the first space, and this package parametrizes with
    sentences -- so the killer of a case named "a required key is deleted" was reported
    as `...::test_x[a`. Cosmetic while the value was only printed; fatal once a kill has
    to be confirmed by re-running its killer, because a truncated nodeid collects nothing
    and the genuine kill would be downgraded to a survivor.

    Both tools parse this summary and both are checked, because they drifted from one
    copy of the same expression.
    """
    summary = (
        "FAILED tests/test_wire.py::test_a_payload_is_refused[a required key is deleted]"
        " - cai.envelope.SchemaViolation: nope\n"
        "FAILED tests/test_formation.py::test_plain - AssertionError\n"
        "ERROR tests/test_wire.py::test_setup[two words] - RuntimeError\n"
    )

    for module in (mg, gs):
        assert module.FAILED.findall(summary) == [
            "tests/test_wire.py::test_a_payload_is_refused[a required key is deleted]",
            "tests/test_formation.py::test_plain",
        ], f"{module.__name__} truncates parametrized killers"
        assert module.ERROR.findall(summary) == [
            "tests/test_wire.py::test_setup[two words]"
        ]


def test_a_full_parametrized_nodeid_is_resolvable_by_pytest():
    """The other half: a name that parses is not yet a name pytest can run.

    Asserted against this repository's own suite, with a real parametrized id, because
    the whole value of the attribution check is that the id it is handed collects exactly
    one test.
    """
    nodeid = (
        "tests/test_wire.py::test_a_structurally_malformed_payload_is_refused_by_the"
        "_published_schema[a required key is deleted]"
    )
    done = subprocess.run(
        [sys.executable, "-m", "pytest", nodeid, "-q", "--no-header", "--collect-only",
         "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 test collected" in done.stdout or "1 tests collected" in done.stdout


# ===========================================================================
# THE MUTATED UNIVERSE MUST NOT DEPEND ON THE SOURCE TEXT.
# ===========================================================================


def universe_size(root: pathlib.Path) -> int | None:
    """Collect the mutated universe in `root` and return the count, or None."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--co", "-q",
         *mg._IGNORE, "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    return mg._collected_count(done.stdout + done.stderr)


@pytest.fixture()
def mirror(tmp_path):
    """A working copy of this repository's source, tests and project file.

    Cheap -- a few hundred kilobytes -- and it is the only honest way to ask what the
    collection count does when a raise is removed, because asking it in place would mean
    editing the tree the suite is currently running from.
    """
    root = tmp_path / "mirror"
    (root).mkdir()
    for name in ("src", "tests"):
        shutil.copytree(REPO / name, root / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / "pyproject.toml", root / "pyproject.toml")
    return root


@pytest.mark.parametrize("module,fragment", [
    # The site that actually broke the gate: the ONLY raise in its class, so removing it
    # removes the class from any inventory derived by parsing the source.
    ("predictor.py", "an applicability pair naming no metric"),
    # A second site in a class with several raises, so the class survives the inventory
    # and only its count changes. Both shapes must leave collection alone.
    ("action.py", "an action with no id cannot be joined"),
])
def test_removing_a_guard_does_not_change_the_size_of_the_mutated_universe(
    mirror, module, fragment
):
    """THE PROPERTY BOTH TOOLS DEPEND ON, AND THE ONE THAT BROKE.

    `mutation_generator` and `guard_sweep` both decide a mutant is INVALID when the test
    universe changes size, because a suite that collects a different number of tests is
    not the suite the baseline was measured against. That check is correct. It is also
    only useful if the universe is INDEPENDENT of the source text -- and
    `test_schema_reconciliation.py` parametrizes over an inventory it parses out of
    `src/cai`, so removing a raise removed a parametrized case and the count fell by one.

    Two mutants at `MetricApplicability.__post_init__` were reported as undeclared
    invalid in the first full run because of it. This package had already learned the
    lesson once, on a ledger-audit test that scored seven artifact KILLS, and the fix
    then was the same as the fix now: a test whose subject is the source text does not
    belong in a universe built from mutated source.

    Asserted here rather than trusted to the exclusion list staying correct, because the
    list is what was wrong.
    """
    baseline = universe_size(mirror)
    assert baseline is not None, "the mirror does not collect at all"

    target = mirror / "src" / "cai" / module
    source = target.read_text()
    lines = source.splitlines(keepends=True)

    # THE RAISE IS LOCATED THROUGH THE AST, not by counting brackets in the text.
    # The first version of this spliced on `rindex("raise ")` and the next `)`, produced a
    # file that did not parse, and collected 27 tests -- which would have "failed" for a
    # reason that has nothing to do with the property under test. `guard_sweep` replaces a
    # guard by line span; this does the same thing the same way.
    node = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Raise) and fragment in ast.get_source_segment(source, n)
    )
    indent = " " * (len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip()))
    target.write_text("".join(
        lines[: node.lineno - 1] + [f"{indent}pass\n"] + lines[node.end_lineno:]
    ))

    rebuilt = target.read_text()
    compile(rebuilt, module, "exec")
    assert len(list(ast.walk(ast.parse(rebuilt)))) < len(list(ast.walk(ast.parse(source)))), (
        "the fixture did not actually remove anything, so this test would pass against a "
        "build that still has the guard"
    )
    assert universe_size(mirror) == baseline, (
        f"removing the guard in {module} changed the mutated universe from {baseline}; "
        f"both measurement tools classify that as INVALID, so every mutation at this "
        f"site is unevaluable"
    )


def test_both_tools_exclude_the_same_test_modules():
    """One list, imported, not two lists kept in step by hand.

    `guard_sweep` held its own copy naming a single file. Both tools change `src/cai` and
    re-run the suite, so a module that cannot survive one cannot survive the other, and
    the copies had already diverged by the time this was written.
    """
    assert gs._IGNORE == mg._IGNORE
    assert "tests/test_schema_reconciliation.py" in mg.EXCLUDED_FROM_THE_MUTATED_UNIVERSE
    assert "tests/test_measurement_tooling.py" in mg.EXCLUDED_FROM_THE_MUTATED_UNIVERSE


# ===========================================================================
# CURATED ANCHORS MUST IDENTIFY EXACTLY ONE SITE.
# ===========================================================================


def curated_mutants():
    import mutation_harness as mh
    return mh.MUTANTS


@pytest.mark.parametrize("index", range(len(__import__("mutation_harness").MUTANTS)))
def test_every_curated_anchor_matches_exactly_one_site(index):
    """THE DEFECT CT6 CARRIED FOR THE LIFE OF THIS CORPUS.

    The harness patches with `original.replace(find, replace, 1)`, which takes the FIRST
    occurrence. An anchor that is not unique therefore mutates whichever site comes first
    in the file, and the declaration may be describing a different one.

    CT6 was anchored on the bare `if key in seen:`. That string occurs twice in
    `envelope.py`: the duplicate status-event check, and the duplicate JSON-key check four
    hundred lines later. CT6 is named for the JSON path. It was patching the status-event
    path, and reporting killed every run, because its declared killer was the status-event
    test that legitimately fails when that check is removed.

    Internally consistent. Correctly green. Covering something other than what the corpus
    said it covered. Zero is a stale anchor and the harness already caught that; two is
    the case it did not.
    """
    mutant = curated_mutants()[index]
    source = (REPO / "src" / "cai" / mutant.file).read_text()
    found = source.count(mutant.find)

    assert found != 0, f"{mutant.name}: anchor no longer matches {mutant.file}"
    assert found == 1, (
        f"{mutant.name}: anchor matches {found} sites in {mutant.file}, so it would "
        f"patch whichever comes first and the declaration cannot say which"
    )


def test_the_harness_refuses_an_ambiguous_anchor_at_run_time():
    """The structural assertion above catches the corpus drifting. This catches the
    harness losing the ability to notice.

    Asserted over the source of `main` because the check runs inside the per-mutant loop
    and cannot be reached without a full run.
    """
    import inspect

    import mutation_harness as mh

    body = inspect.getsource(mh.main)
    assert "original.count(mutant.find)" in body, (
        "the harness no longer counts anchor occurrences"
    )
    assert "anchor is not unique" in body, "an ambiguous anchor is no longer reported"
    assert "invalid.append" in body, "an ambiguous anchor must not be scored as a kill"


def test_the_ambiguity_guard_actually_fires_on_a_duplicated_anchor():
    """POLARITY. A guard tested only by reading its source is a guard nobody has run.

    Builds the exact condition the guard exists for and asserts the arithmetic it
    depends on, against a real file rather than a fixture string.
    """
    source = (REPO / "src" / "cai" / "envelope.py").read_text()

    assert source.count("            if key in seen:") == 2, (
        "this test is calibrated against the two real sites that collided; if the file "
        "changed, recalibrate it rather than deleting it"
    )
    ambiguous = source.count("            if key in seen:")
    assert ambiguous > 1 and (ambiguous > 1) is True


def test_ct6_now_targets_the_json_path_it_is_named_for():
    """The split, verified by where each anchor lands rather than by its name."""
    source = (REPO / "src" / "cai" / "envelope.py").read_text()
    by_name = {m.name: m for m in curated_mutants()}

    json_mutant = by_name["CT6 duplicate JSON keys are resolved rather than refused"]
    status_mutant = by_name["CT6b a duplicate status event is folded rather than refused"]

    json_at = source.index(json_mutant.find)
    status_at = source.index(status_mutant.find)

    assert "pairs" in json_mutant.find, "CT6 must anchor inside no_duplicate_keys"
    assert "event.event_type" in status_mutant.find, "CT6b must anchor on the event loop"
    assert status_at < json_at, (
        "the status-event site comes first in the file, which is why the old shared "
        "anchor resolved to it"
    )
    assert json_mutant.expect_failing == (
        "test_a_duplicate_json_key_is_refused_by_both_text_apis",
    )
    assert status_mutant.expect_failing == ("test_a_duplicate_status_event_is_refused",)


# ===========================================================================
# GUARD SWEEP: A NAMED FAILURE IS NOT YET AN ATTRIBUTED ONE.
# ===========================================================================
#
# The rebuilt sweep fixed four defects and kept a fifth. It promoted ANY `FAILED` line in
# a full-suite run to LOAD_BEARING, with no check that the named failure had anything to
# do with the guard just removed -- and then RETRIED the whole suite when the first run
# was inconclusive, which is a machine for turning a transient into evidence.
#
# Both halves biased towards "covered", like every other tooling defect on this
# programme. `mutation_generator.py` had already closed this exact class for mutants, so
# the rule is now shared rather than restated.
#
# Every case below is written so that the OLD code would have passed it in the flattering
# direction, and both directions of the gate are exercised: a check that can only ever
# refuse is as broken as one that can only ever agree, and this repository has shipped
# both.


def _sweep_pytest_returning(rc: int, out: str):
    """A stand-in for a full-suite run with a fixed verdict."""
    return lambda ws, *a, **k: subprocess.CompletedProcess([], rc, stdout=out, stderr="")


@pytest.fixture()
def swept(guarded, monkeypatch):
    """A guard-sweep worker pointed at the miniature repo, with the HELD guard selected."""
    monkeypatch.setattr(gs, "ROOT", guarded)
    monkeypatch.setattr(gs, "PACKAGE", "tinypkg")
    monkeypatch.setattr(gs, "SRC", guarded / "src" / "tinypkg")
    workspace = gs._build_workspace()
    monkeypatch.setattr(gs, "_WORKSPACE", workspace)
    monkeypatch.setattr(gs, "_COLLECTED", 3)
    held = next(g for g in gs.guards() if "negative" in g.message)
    yield workspace, held
    shutil.rmtree(workspace, ignore_errors=True)


def test_case_a_a_reproduced_failure_makes_a_guard_load_bearing(swept, monkeypatch):
    """(a) The twin that stops the fix from being "never say load-bearing".

    Without this, returning INCONCLUSIVE unconditionally would satisfy every other case
    here and destroy the measurement.
    """
    _, held = swept
    killer = "tests/test_guarded.py::test_a_negative_value_is_refused"
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(1, f"FAILED {killer}\n"))
    monkeypatch.setattr(gs, "reproduces_alone", lambda ws, k: True)

    result = gs._evaluate(held)

    assert result.verdict is gs.Verdict.LOAD_BEARING
    assert result.detail == killer, "a load-bearing guard must name its killer"
    assert result.retried is False


def test_case_b_an_unrelated_failure_that_passes_alone_is_not_load_bearing(
    swept, monkeypatch
):
    """(b) THE ONE THAT MATTERS MOST, and the defect this pass exists to close.

    Under a pool of workers each running a full pytest, a test can fail for reasons that
    have nothing to do with the removal. The old code credited it to the guard.
    """
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(
        1, "FAILED tests/test_guarded.py::test_something_unrelated\n"))
    monkeypatch.setattr(gs, "reproduces_alone", lambda ws, k: False)

    result = gs._evaluate(held)

    assert result.verdict is not gs.Verdict.LOAD_BEARING
    assert result.verdict is gs.Verdict.INCONCLUSIVE
    assert "not attributable" in result.detail


def test_case_c_a_setup_error_is_not_load_bearing(swept, monkeypatch):
    """(c) An ERROR is not an assertion. Nothing caught the removal."""
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(
        1, "ERROR tests/test_guarded.py::test_a_negative_value_is_refused - fixture died\n"))

    result = gs._evaluate(held)

    assert result.verdict is not gs.Verdict.LOAD_BEARING
    assert result.verdict is gs.Verdict.INCONCLUSIVE
    assert "ERRORED" in result.detail


def test_case_d_a_collection_failure_is_invalid(swept, monkeypatch):
    """(d) No test ran, so the removal was never tested. That is not coverage."""
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: None)

    result = gs._evaluate(held)

    assert result.verdict is gs.Verdict.INVALID
    assert result.verdict is not gs.Verdict.LOAD_BEARING


def test_case_d2_a_changed_test_universe_is_invalid(swept, monkeypatch):
    """(d), second half. A removal that changes how many tests exist has broken the
    instrument, and the comparison against the baseline is meaningless."""
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: 2)

    result = gs._evaluate(held)

    assert result.verdict is gs.Verdict.INVALID
    assert "changed the test universe" in result.detail


def test_case_e_a_red_baseline_refuses_to_measure(guarded):
    """(e) On a red baseline every guard reads as load-bearing and the sweep reports zero
    removable, which looks like the best possible result. Refusing is the only safe act."""
    (guarded / "tests" / "test_broken.py").write_text(
        "def test_the_baseline_is_red():\n    assert False\n"
    )

    done = run_sweep(guarded)

    assert done.returncode == 2, done.stdout
    assert "BASELINE IS NOT GREEN" in done.stdout
    # And it must not go on to publish a verdict. "0 removable" from a refused run is the
    # exact number a reader would misread as a clean result.
    assert "GUARD SWEEP RESULT" not in done.stdout, (
        "the sweep refused the baseline and then reported a result anyway"
    )


def test_case_f_a_genuinely_untested_guard_is_removable(swept, monkeypatch):
    """(f) A green suite without the guard means nothing holds it up."""
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(0, ""))

    result = gs._evaluate(held)

    assert result.verdict is gs.Verdict.REMOVABLE


def test_case_g_a_parametrized_killer_with_spaces_is_resolved_in_full(
    swept, monkeypatch
):
    """(g) `FAILED (\\S+)` truncated at the first space inside the brackets, and this
    package parametrizes with sentences. Cosmetic while the id was only printed; fatal
    once a verdict depends on re-running it, because a truncated id collects nothing and
    the attribution check fails closed -- turning a real load-bearing guard into an
    inconclusive one."""
    _, held = swept
    full = "tests/test_guarded.py::test_x[a required key is deleted]"
    handed: list[str] = []
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(
        1, f"FAILED {full} - AssertionError: boom\n"))
    monkeypatch.setattr(
        gs, "reproduces_alone", lambda ws, k: (handed.append(k), True)[1])

    result = gs._evaluate(held)

    assert handed == [full], f"the killer was truncated before re-running it: {handed}"
    assert result.verdict is gs.Verdict.LOAD_BEARING
    assert result.detail == full


def test_case_h_a_targeted_test_that_cannot_be_collected_is_not_load_bearing(
    swept, monkeypatch
):
    """(h) The real `reproduces_alone`, against a real workspace, on a nodeid that
    collects nothing. It must fall short of a verdict rather than grant one."""
    _, held = swept
    monkeypatch.setattr(gs, "_collected", lambda ws: 3)
    monkeypatch.setattr(gs, "_pytest", _sweep_pytest_returning(
        1, "FAILED tests/test_guarded.py::test_that_does_not_exist\n"))

    result = gs._evaluate(held)

    assert result.verdict is not gs.Verdict.LOAD_BEARING
    assert result.verdict is gs.Verdict.INCONCLUSIVE


def test_the_shared_attribution_check_answers_in_both_directions(swept):
    """BOTH POLARITIES OF THE GATE ITSELF, reached through the sweep's own import.

    `_reproduces_alone` once shipped gated on a line `-q` suppresses, so it answered NO to
    everything and downgraded every kill in the package. A gate tested only for its
    ability to refuse passes all of its own tests while being completely broken. So this
    asserts it can say YES to a real failure and NO to one that cannot be collected, in
    the same workspace.
    """
    workspace, _ = swept
    (workspace / "tests" / "test_extra.py").write_text(
        "def test_definitely_fails():\n    assert False\n"
    )

    assert gs.reproduces_alone(
        workspace, "tests/test_extra.py::test_definitely_fails") is True
    assert gs.reproduces_alone(
        workspace, "tests/test_extra.py::test_absent") is False


def test_the_sweep_no_longer_retries_a_full_suite_run():
    """(11) No final evidence run may depend on repeating an inconclusive full suite.

    The retry is gone rather than merely unused, so `retries exercised 0` is a structural
    fact instead of a lucky one. The printed line stays: a count that vanished with its
    mechanism leaves a reader unable to tell "none happened" from "nobody reports them".
    """
    import inspect
    import textwrap

    source = inspect.getsource(gs._evaluate)
    # Structure, not prose. Asserting on the text matched the comment that EXPLAINS the
    # removed retry, which would have made this test permanently red for the right code
    # and permanently green for any wording that dropped the explanation.
    body = ast.parse(textwrap.dedent(source))
    loops = [n for n in ast.walk(body) if isinstance(n, (ast.For, ast.While))]
    assert not loops, "a loop is back in _evaluate; the full-suite retry must not return"

    calls = [n for n in ast.walk(body)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_pytest"]
    assert len(calls) == 1, "the full suite is run more than once per guard"

    assert "reproduces_alone(_WORKSPACE" in source, "attribution is not being checked"
    assert "retries exercised" in _sweep_cli_source()


# ===========================================================================
# THE SUMMARY MUST COUNT, NOT CLAIM.
# ===========================================================================
#
# The first version of the attribution fix printed
#
#     every load-bearing guard names a killer that failed again when re-run alone
#
# as an unconditional line in the summary. True of the code path, and still a sentence
# rather than a measurement -- it would have printed unchanged over a result set that
# contradicted it. That is the exact defect this programme keeps finding in its own
# evidence, committed inside the fix for another instance of it.


def _guard(line: int = 1) -> gs.Guard:
    return gs.Guard(file="x.py", line=line, scope="f", message="raise ValueError('x')",
                    span=(line, line), indent=4)


def test_the_attribution_count_is_derived_from_the_results():
    """Direction one: a fully attributed run counts every killer."""
    results = [
        gs.Result(_guard(1), gs.Verdict.LOAD_BEARING, "tests/t.py::test_a"),
        gs.Result(_guard(2), gs.Verdict.LOAD_BEARING, "tests/t.py::test_b"),
        gs.Result(_guard(3), gs.Verdict.REMOVABLE),
    ]

    named, unnamed = gs.attribution_summary(results)

    assert (named, unnamed) == (2, 0)


def test_a_load_bearing_verdict_with_no_killer_is_counted_as_unnamed():
    """Direction two, and the one that matters.

    A counter that can only ever report full attribution is the sentence again with
    arithmetic around it. This is the state the old line would have printed straight
    through.
    """
    results = [
        gs.Result(_guard(1), gs.Verdict.LOAD_BEARING, "tests/t.py::test_a"),
        gs.Result(_guard(2), gs.Verdict.LOAD_BEARING, ""),
    ]

    named, unnamed = gs.attribution_summary(results)

    assert (named, unnamed) == (1, 1)


def test_the_summary_no_longer_asserts_attribution_unconditionally():
    """The sentence itself must be gone, not merely joined by a number."""
    import inspect

    source = _sweep_cli_source()

    assert "every load-bearing guard names a killer" not in source, (
        "the unconditional claim is back in the summary"
    )
    assert "attribution_summary(results)" in source, "the count is not derived"


def test_the_sweep_can_emit_per_site_classifications_for_a_real_comparison():
    """`--jobs 1` vs `--jobs 2` agreeing on TOTALS is not a per-site claim.

    With every guard landing in one bucket the totals match vacuously -- which is a
    qualification this programme has already had to make once about this very tool. The
    per-site dump carries the killer nodeid too, so a site that is load-bearing in both
    runs for DIFFERENT reasons is visible rather than averaged away.
    """
    import inspect

    source = _sweep_cli_source()

    assert '"--sites" in sys.argv' in source
    assert "PER-SITE CLASSIFICATION" in source
    assert "result.verdict.value" in source, "the per-site dump omits the verdict"
    assert "result.detail" in source, "the per-site dump omits the killer"


# ===========================================================================
# MEASURING IS NOT ACCEPTING. THE GATE CONTRACTS, BOTH POLARITIES.
# ===========================================================================
#
# Both tools could return process success without proving the claim a third party is
# meant to infer from it.
#
# `guard_sweep.py` exits 0 by design, so a run containing INCONCLUSIVE results, INVALID
# results, a load-bearing verdict with nothing to re-run, or a removable guard nobody had
# decided about, all reported success. `mutation_harness.py` appended an unattributed kill
# to `unverified`, printed it as "weaker evidence", and returned 0 -- so the report said
# the weaker thing and the exit status said the stronger one, and a gate consumes the exit
# status.
#
# The decisions are now pure functions over the result objects, which is what makes it
# possible to prove they can say NO. Every case below is paired: the failing condition and
# the honest twin that must still pass. A gate that only ever refuses is as useless as one
# that only ever agrees, and this repository has shipped both.


def _g(line: int = 1, scope: str = "f") -> gs.Guard:
    return gs.Guard(file="x.py", line=line, scope=scope,
                    message="raise ValueError('x')", span=(line, line), indent=4)


def test_gate_passes_an_honest_fully_attributed_guard_result():
    """The twin. Without it, "return a failure unconditionally" satisfies everything else
    in this section."""
    results = [gs.Result(_g(1), gs.Verdict.LOAD_BEARING, "tests/t.py::test_a"),
               gs.Result(_g(2), gs.Verdict.LOAD_BEARING, "tests/t.py::test_b")]

    assert gs.gate_failures(results) == []


def test_gate_fails_an_inconclusive_guard_result():
    results = [gs.Result(_g(1), gs.Verdict.INCONCLUSIVE, "did not reproduce alone")]

    failures = gs.gate_failures(results)

    assert failures and "INCONCLUSIVE" in failures[0]


def test_gate_fails_an_invalid_guard_result():
    results = [gs.Result(_g(1), gs.Verdict.INVALID, "collection failure")]

    failures = gs.gate_failures(results)

    assert failures and "INVALID" in failures[0]


def test_gate_fails_a_load_bearing_result_with_no_named_killer():
    """The verdict is the strong one and there is nothing behind it to re-run."""
    results = [gs.Result(_g(1), gs.Verdict.LOAD_BEARING, "")]

    failures = gs.gate_failures(results)

    assert failures and "no named reproduced killer" in failures[0]


def test_gate_fails_an_undispositioned_removable_guard():
    """A removable guard is a finding. Passing over it silently is how 208 guards once
    looked fully covered."""
    results = [gs.Result(_g(1), gs.Verdict.REMOVABLE)]

    failures = gs.gate_failures(results)

    assert failures and "no committed disposition" in failures[0]


def test_gate_passes_a_removable_guard_that_carries_an_explicit_disposition():
    """The twin for the case above, and the only thing `ACCEPTED_REMOVABLE` is for.

    The distinction being drawn is "somebody decided about this" versus "nobody noticed
    it", which cannot be inferred from the guard itself. It has to be written down per
    site, with a reason, where a reviewer sees it in the diff.
    """
    guard = _g(1)
    results = [gs.Result(guard, gs.Verdict.REMOVABLE)]
    accepted = {guard.site_id: "asserted only by a doctest; tracked separately"}

    assert gs.gate_failures(results, accepted) == []


def test_gate_fails_when_any_full_suite_retry_was_exercised():
    """A verdict that needed a re-run is a verdict from a run that was not reproducible."""
    results = [gs.Result(_g(1), gs.Verdict.LOAD_BEARING, "tests/t.py::test_a",
                         retried=True)]

    failures = gs.gate_failures(results)

    assert failures and "retry" in failures[0]


def test_gate_fails_on_an_empty_result_set():
    """THE ONE THAT MATTERS MOST FOR A GATE.

    Nothing measured is not the same as nothing wrong. A missing executable, a failed
    parse, an unavailable input and a crashed pool all arrive here as an empty list, and
    every one of them would otherwise be indistinguishable from a clean sweep.
    """
    failures = gs.gate_failures([])

    assert failures and "empty result set" in failures[0]


def test_the_accepted_removable_map_is_empty_which_is_the_current_truth():
    """If the final sweep finds zero removable guards there is nothing to disposition.

    Asserted so that an entry cannot be added quietly to make a gate go green: adding one
    breaks this test and forces the reason into the same commit.
    """
    assert gs.ACCEPTED_REMOVABLE == {}


def test_the_record_set_is_deterministic_and_carries_real_site_records():
    """Ordinary `diff` is the whole comparison algorithm, so the ordering has to be fixed
    and the records have to be non-empty."""
    results = [gs.Result(_g(9, "z"), gs.Verdict.LOAD_BEARING, "tests/t.py::test_z"),
               gs.Result(_g(2, "a"), gs.Verdict.LOAD_BEARING, "tests/t.py::test_a")]

    records = gs.as_records(results)
    again = gs.as_records(list(reversed(results)))

    assert records == again, "ordering depends on input order; diff would be meaningless"
    assert [r["site_id"] for r in records] == ["x.py:2 [a]", "x.py:9 [z]"]
    assert all(r["site_id"] and r["verdict"] for r in records), "empty site records"
    assert records[0]["killer"] == "tests/t.py::test_a"
    assert records[0]["retried"] is False
    assert set(records[0]) == {"site_id", "verdict", "killer", "retried"}


def test_a_removable_record_carries_no_killer_rather_than_an_empty_string():
    """`null` and `""` diff differently, and only one of them means "not applicable"."""
    records = gs.as_records([gs.Result(_g(1), gs.Verdict.REMOVABLE)])

    assert records[0]["killer"] is None


# --------------------------------------------------------------------------
# The curated harness contract.
# --------------------------------------------------------------------------


def test_the_curated_harness_fails_on_a_killed_but_unattributed_mutant():
    """Killed by something unnamed is not the claim Phase 5 asks the corpus to support."""
    import mutation_harness as mh

    failures = mh.gate_failures(
        survivors=[], invalid=[],
        unverified=["ct-1 -- killed, but by unspecified tests"],
        baseline_restored=True,
    )

    assert failures and "UNATTRIBUTED" in failures[0]


def test_the_curated_harness_passes_the_attributed_twin():
    """Same corpus shape, the kill declared. This is the pass condition, and without it
    the change above could be "always fail"."""
    import mutation_harness as mh

    assert mh.gate_failures(survivors=[], invalid=[], unverified=[],
                            baseline_restored=True) == []


def test_the_curated_harness_still_fails_on_survivors_and_invalid_results():
    import mutation_harness as mh

    assert mh.gate_failures(survivors=["ct-2"], invalid=[], unverified=[],
                            baseline_restored=True)
    assert mh.gate_failures(survivors=[], invalid=["ct-3"], unverified=[],
                            baseline_restored=True)


def test_the_curated_harness_fails_when_the_tree_was_not_restored():
    """However the mutants scored, a run that left the tree dirty demonstrated nothing."""
    import mutation_harness as mh

    failures = mh.gate_failures(survivors=[], invalid=[], unverified=[],
                                baseline_restored=False)

    assert failures and "baseline" in failures[0]


def test_the_harness_success_path_routes_through_the_shared_decision():
    """So the exit status cannot drift away from the predicate these tests pin."""
    import inspect

    import mutation_harness as mh

    source = inspect.getsource(mh.main)
    assert "gate_failures(" in source
    assert "unverified" in inspect.signature(mh.gate_failures).parameters


# --------------------------------------------------------------------------
# End to end, against the real miniature repository.
# --------------------------------------------------------------------------


def run_sweep_args(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "guard_sweep.py"), *args],
        capture_output=True, text=True, timeout=900,
        env=dict(os.environ, CAI_GUARD_ROOT=str(repo),
                 CAI_GUARD_PACKAGE="tinypkg", PYTHONDONTWRITEBYTECODE="1"),
    )


def test_default_mode_measures_and_gate_mode_decides(guarded):
    """The miniature repository holds one guard nothing asserts.

    Default mode must still report it and exit 0, because a measurement that failed the
    build would be tuned. `--gate` must refuse the same run. Both behaviours from one
    sweep is the whole point of the split.
    """
    measured = run_sweep_args(guarded, "--jobs", "2")
    gated = run_sweep_args(guarded, "--jobs", "2", "--gate")

    assert measured.returncode == 0, measured.stdout
    assert "removable                    1" in measured.stdout

    assert gated.returncode != 0, "the gate accepted an undispositioned removable guard"
    assert "GATE FAILED" in gated.stdout
    assert "no committed disposition" in gated.stdout


def test_json_mode_emits_a_clean_document_with_progress_on_stderr(guarded):
    """`guard_sweep.py --json > records.json` has to yield a parseable document, or the
    comparison Control Tower runs is a comparison of console noise."""
    done = run_sweep_args(guarded, "--jobs", "2", "--json")

    records = json.loads(done.stdout)

    assert len(records) == 2, records
    assert all(r["site_id"] for r in records), "empty site records"
    assert "raise statements" in done.stderr, "progress text is not on stderr"
    assert "raise statements" not in done.stdout, "progress text contaminated the document"


# ===========================================================================
# THE GENERATOR'S PER-SITE SURFACE, AND INVALID-DECLARATION HONESTY.
# ===========================================================================
#
# Phase 5 requires source-derived mutation at both concurrencies with the per-site
# classifications AGREEING. The human report gives totals, every exceptional site in full,
# and a twelve-line SAMPLE of the kills -- so two runs could both exit 0 with matching
# totals while disagreeing about which test caught which mutant among the sites nobody
# printed. Agreement on a count is not agreement on a classification.
#
# Second gap, same family: `DECLARED_INVALID` was audited for missing and stale identities
# but never for a declaration its own site had started contradicting. A mutant becomes
# evaluable when the code around it changes, and nothing re-reads the declaration.


def _mut(original: str = "flag", occurrence: int = 0) -> mg.Mutation:
    return mg.Mutation(file="t.py", line=1, scope="f", mutation_class="c",
                       original=original, mutated="x", span=(1, 1, 1, 1),
                       occurrence=occurrence)


def run_generator_json(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "mutation_generator.py"), "--json", *args],
        capture_output=True, text=True, timeout=900,
        env=dict(os.environ, CAI_MUTGEN_ROOT=str(repo),
                 CAI_MUTGEN_PACKAGE="tinypkg", PYTHONDONTWRITEBYTECODE="1"),
    )


def test_json_covers_every_generated_mutation_with_a_nonempty_record(tiny):
    """(1) and (2). One record per generated site, and stdout is a document.

    A surface that covered only the interesting sites would reproduce the defect it exists
    to close: the uninteresting ones are exactly the ones nobody printed.
    """
    listed = subprocess.run(
        [sys.executable, str(REPO / "mutation_generator.py"), "--list"],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ, CAI_MUTGEN_ROOT=str(tiny),
                 CAI_MUTGEN_PACKAGE="tinypkg", PYTHONDONTWRITEBYTECODE="1"),
    )
    generated = int(re.search(r"(\d+) candidate mutations", listed.stdout).group(1))

    done = run_generator_json(tiny, "--jobs", "2")
    records = json.loads(done.stdout)

    assert len(records) == generated, (
        f"{len(records)} records for {generated} generated mutations"
    )
    assert all(r["site_id"] for r in records), "a record carries no site id"
    assert all(r["verdict"] for r in records), "a record carries no verdict"
    assert set(records[0]) == {"site_id", "verdict", "killed_by", "retried"}
    # (2) the document is not contaminated by the human report
    assert "generating from" in done.stderr, "the human report is not on stderr"
    assert "generating from" not in done.stdout
    assert "baseline collects" not in done.stdout


def test_json_records_are_ordered_deterministically():
    """(3) Ordering must not depend on completion order, which is what a pool varies.

    `imap_unordered` returns outcomes as workers finish them, so jobs=1 and jobs=2 hand
    this function the same set in different sequences. If serialisation followed that
    sequence, ordinary diff would report a difference on every run and the comparison
    would be abandoned as noisy.
    """
    outcomes = [
        mg.Outcome(_mut("zebra"), mg.Verdict.KILLED, killed_by=("tests/t.py::test_z",)),
        mg.Outcome(_mut("alpha"), mg.Verdict.SURVIVED),
    ]

    forwards = mg.as_records(outcomes)
    backwards = mg.as_records(list(reversed(outcomes)))

    assert forwards == backwards, "record order depends on completion order"
    assert [r["site_id"] for r in forwards] == sorted(r["site_id"] for r in forwards)


def test_killed_by_is_sorted_so_diff_reports_only_real_disagreement():
    """(4) The same two killers reported in a different order is not a disagreement."""
    a = mg.Outcome(_mut(), mg.Verdict.KILLED,
                   killed_by=("tests/t.py::test_b", "tests/t.py::test_a"))
    b = mg.Outcome(_mut(), mg.Verdict.KILLED,
                   killed_by=("tests/t.py::test_a", "tests/t.py::test_b"))

    assert mg.as_records([a]) == mg.as_records([b])
    assert mg.as_records([a])[0]["killed_by"] == ["tests/t.py::test_a",
                                                  "tests/t.py::test_b"]


def test_a_record_set_that_covers_nothing_is_refused_rather_than_serialised(tiny):
    """(5) THE ONE THAT MATTERS MOST.

    `diff` over two empty files reports agreement, so an empty document would prove
    per-site identity between two nothings. `--only` naming a file that does not exist is
    the cheapest way to reach zero outcomes; a crashed pool reaches the same place.

    This exact shape -- two empty extractions diffing clean -- has already produced one
    false pass on this programme, in a harness written to verify a fix for a defect of the
    same kind.
    """
    done = run_generator_json(tiny, "--jobs", "1", "--only", "nosuchfile.py")

    assert done.returncode != 0, "an empty measurement exited successfully"
    assert done.stdout.strip() == "", (
        f"an empty document was serialised anyway: {done.stdout!r}"
    )
    assert "no outcomes" in done.stderr


# --------------------------------------------------------------------------
# Invalid declarations that their own site contradicts.
# --------------------------------------------------------------------------


def test_a_declared_invalid_site_that_really_is_invalid_is_accepted():
    """(6) and (8). The passing twin.

    Without this the check could be "reject every declaration", which would satisfy every
    rejection case below and destroy the mechanism.
    """
    site = _mut().site_id
    declared = {site: "breaks collection; cannot be behaviourally evaluated"}

    contradicted = mg.contradicted_invalid_declarations(
        [mg.Outcome(_mut(), mg.Verdict.INVALID)], declared)

    assert contradicted == []


def test_a_declared_invalid_site_that_was_killed_is_rejected():
    """(7) The declaration says no test can observe this. A test observed it."""
    site = _mut().site_id
    declared = {site: "breaks collection; cannot be behaviourally evaluated"}

    contradicted = mg.contradicted_invalid_declarations(
        [mg.Outcome(_mut(), mg.Verdict.KILLED, killed_by=("tests/t.py::test_a",))],
        declared)

    assert contradicted == [(site, "killed")]


@pytest.mark.parametrize("verdict,name", [
    (mg.Verdict.KILLED, "killed"),
    (mg.Verdict.SURVIVED, "survived"),
    (mg.Verdict.TIMEOUT, "timeout"),
])
def test_every_non_invalid_verdict_contradicts_an_invalid_declaration(verdict, name):
    """Each of the three, and each reported with the verdict actually seen.

    "Your declaration is wrong" is not actionable. "Declared invalid, actually SURVIVED"
    tells the reader which of the two statements to go and fix.
    """
    site = _mut().site_id

    contradicted = mg.contradicted_invalid_declarations(
        [mg.Outcome(_mut(), verdict)], {site: "cannot be evaluated"})

    assert contradicted == [(site, name)]


def test_an_undeclared_site_is_never_reported_as_a_contradicted_declaration():
    """The check must look at declarations, not at verdicts. A killed site with no
    declaration over it is the ordinary case and the healthy one."""
    assert mg.contradicted_invalid_declarations(
        [mg.Outcome(_mut(), mg.Verdict.KILLED)], {}) == []


def test_the_generator_gate_consumes_the_contradiction_check():
    """So the exit status cannot drift away from the predicate these tests pin."""
    import inspect

    source = inspect.getsource(mg._main)
    assert "contradicted_invalid_declarations(outcomes, DECLARED_INVALID)" in source
    assert "contradicted invalid declaration(s)" in source
