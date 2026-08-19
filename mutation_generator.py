#!/usr/bin/env python3
"""Mutations derived from the SOURCE, not from the tests that already exist.

WHY THIS EXISTS BESIDE `mutation_harness.py`
--------------------------------------------
`mutation_harness.py` runs a hand-curated corpus: 141 named mutants, each written after a
defect was found, each declaring the tests that must fail to kill it. That is excellent
regression evidence and it is worthless as a claim about suite COMPLETENESS, because the
corpus was built from the tests. A mutation nobody thought of is a mutation nobody wrote,
and the score says nothing about it.

Wave 4 demonstrated the circularity rather than arguing it: fresh mutations written
against uncovered behaviour survived while the curated corpus was fully green. A green
score over a corpus derived from the suite measures the corpus, not the suite.

So this generates candidates from the AST of `src/cai` and knows nothing about the tests.
Every load-bearing branch, comparison and refusal guard gets mutated whether or not
anybody remembered it existed.

WHAT IT GENERATES
-----------------
    negate_condition        if X            ->  if not (X)
    condition_always_true   if X            ->  if True
    condition_always_false  if X            ->  if False
    branch_body_pass        the if-body     ->  pass
    comparison_swap         ==/!=, </<=, >/>=, is/is not, in/not in
    boolean_operator_swap   and <-> or
    remove_raise_guard      raise ...       ->  pass
    permissive_return       return X        ->  return True   (for a refusal predicate)
    conservative_return     return X        ->  return False

WHAT IT DELIBERATELY DOES NOT GENERATE
--------------------------------------
Mutations that cannot change behaviour are noise, and noise in a gate is how a gate stops
being read. Skipped: anything under `if TYPE_CHECKING`, docstrings, `assert` statements,
and the two branch mutations on a test that is already a literal.

THE GATE
--------
Exit 1 if any generated mutant survives and is not declared equivalent below. A survivor
is either a behaviour nothing asserts -- write the test -- or genuinely unreachable, in
which case it goes in `DECLARED_EQUIVALENT` with a reason a reader can check. A stale
declaration that no longer matches any generated mutant is also reported and also fails:
a suppression nobody can see is how a corpus quietly stops covering anything.

    python3 mutation_generator.py                # run the gate
    python3 mutation_generator.py --list         # every generated mutation, no run
    python3 mutation_generator.py --jobs 4       # worker count (default: cpu_count)
    python3 mutation_generator.py --only evidence.py,policy.py

Bytecode is purged and `PYTHONDONTWRITEBYTECODE=1` is set, for the reason
`mutation_harness.py` documents at length: a same-length edit applied and restored inside
one second leaves a `.pyc` CPython considers current, and the next run imports mutated
bytecode from a pristine file.
"""
from __future__ import annotations

import argparse
import json
import ast
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

# OVERRIDABLE SO THE TOOL CAN BE TESTED AGAINST SOMETHING OTHER THAN ITSELF.
#
# A defect that makes every mutant look killed also makes the production suite look
# fully protective, so using that suite as the only check on this tool is circular --
# and it is how three of the five defects here survived. `tests/test_mutation_tooling.py`
# points this at miniature repositories whose answer is known in advance.
ROOT = Path(os.environ.get("CAI_MUTGEN_ROOT") or Path(__file__).resolve().parent)
PACKAGE = os.environ.get("CAI_MUTGEN_PACKAGE", "cai")
"""The package under mutation. Overridable for the same reason `ROOT` is, and separately
from it: a miniature test repository cannot ALSO call its package `cai`, because the real
one is installed in the environment running the tests and would shadow it."""
SRC = ROOT / "src" / PACKAGE

# Mutants that CANNOT change behaviour, each with the stronger invariant that makes it
# unreachable. Every entry is a claim a reader can check against the source, not a
# tolerance. Keyed by (file, mutation class, the exact original snippet); the line number
# is deliberately not part of the key, because line numbers move and a suppression that
# silently stops matching is worse than no suppression.
DECLARED_EQUIVALENT: dict[str, str] = {
    # REBUILT FROM MEASUREMENT, AND THEN DEFENDED AGAINST A FALSE KILL.
    #
    # The old ledger keyed on (file, mutation_class, original), which is a pattern rather
    # than an identity: one entry silently suppressed every matching site in a file, and
    # the report counted DECLARATIONS while implying it had counted sites. So it was
    # emptied, the gate run with nothing declared, and every survivor read.
    #
    # Eight survived. Seven are below. The eighth --
    # `VerificationReport.fully_verified` returning a constant True -- was a real coverage
    # gap: every test that read the method read it on an honest record, so it could have
    # been a constant and nothing would have noticed. It is asserted in both directions
    # in tests/test_public_bool_contracts.py rather than excused here.
    #
    # A LATER ROUND REPORTED ALL SEVEN AS KILLED, AND THAT WAS AN ARTIFACT.
    # A test had been added that audited this ledger against the live `src/cai`. Inside a
    # mutation run that directory IS the mutant, so a mutation at any declared site moved
    # the fragment, made the declaration read as stale, failed the test, and scored a
    # KILL. Seven kills produced by a test noticing that source text it was told to
    # expect had moved. The test is gone; the declarations are real.
    #
    # Keyed on the five-part site identity. One declaration matches exactly one generated
    # mutant. Zero is stale, two is ambiguous, and a declaration whose mutant is KILLED is
    # unnecessary -- all three fail the gate.

    # SIX ENTRIES LEFT THIS LEDGER AND ARE NOW IN `DECLARED_DIAGNOSTIC_ONLY`.
    #
    # They were not equivalent and calling them equivalent was a claim this tool could
    # not support. Take the clearest: `len(errors) > 10` mutated to `len(errors) >= 10`.
    # With exactly ten schema violations the original prints no suffix and the mutant
    # appends "(and 0 further violations)". Those are two observably different programs.
    # Nobody is fooled about which records are accepted -- and "no observable difference
    # for any valid input" is a much stronger sentence than the situation warranted, on
    # the one ledger whose entire value is that a reader can check each claim.
    #
    # The distinction is not pedantry. EQUIVALENT means the mutation testing found
    # nothing because there was nothing to find. DIAGNOSTIC_ONLY means it found a real
    # behavioural difference in a place this gate has decided not to pin. The second is
    # an admission; the first is a proof. Filing admissions as proofs is how a
    # measurement flatters itself.

    # ---- A GUARD THAT CANNOT CHANGE WHAT IT GUARDS. The one genuine equivalence.
    #
    # `if evidence.release_decision() is WITHHOLD: reasons.extend(blocking_reasons())`
    # mutated so the condition is always true.
    #
    # THE PROOF, FROM THE IMPLEMENTATION RATHER THAN FROM INSPECTION.
    # `EvidenceAssessment.release_decision()` is, in full:
    #
    #     return Release.RELEASE if not self.blocking_reasons() else Release.WITHHOLD
    #
    # so `release_decision() is WITHHOLD` holds exactly when `blocking_reasons()` is
    # non-empty. The arm the guard excludes is therefore precisely the arm on which
    # `blocking_reasons()` returns `()`, and `reasons.extend(())` appends nothing to any
    # list in any state. The mutant runs one extra no-op call and produces a `reasons`
    # list identical element-for-element to the original's, for every reachable input.
    #
    # That is an equivalence proven from the definition of the function the condition
    # calls, not an observation that no test noticed. `condition_always_false` at the same
    # site is NOT equivalent -- it drops the reasons on the WITHHOLD arm -- and is killed.
    #
    # Kept in the source as a statement of intent rather than deleted: it tells a reader
    # that the policy consults the evidence verdict, which a bare `extend` would not.
    "policy.py::ReleasePolicy.evaluate::condition_always_true"
    "::#0::evidence.release_decision() is Release.WITHHOLD":
        "release_decision() returns RELEASE exactly when blocking_reasons() is empty, so "
        "the arm this guard excludes is the arm where extend() receives the empty tuple; "
        "the mutant appends nothing and produces an identical reasons list for every "
        "reachable input",
}

DECLARED_DIAGNOSTIC_ONLY: dict[str, str] = {
    # BEHAVIOUR DIFFERS, AND ONLY IN WHAT A READER IS TOLD.
    #
    # Not counted as killed, and not counted as equivalent. A separate line in the report
    # with the site and the reason visible, because the honest summary of these is "the
    # suite does not pin this wording, and that is a decision" rather than "the suite
    # caught everything".
    #
    # The gate does NOT fail on these. Diagnostic prose is not part of the published
    # contract -- the schema is, the typed refusals are, the rendered card is -- and
    # freezing the phrasing of an internal error detail would make every improvement to a
    # message a test change. What the gate does insist on is that each one is DECLARED,
    # so the count is visible and a new one cannot appear silently.
    #
    # Each entry is auditable on the same terms as an equivalence: exactly one generated
    # mutant, no stale keys, and a site whose mutant is KILLED fails as unnecessary.

    # ---- The wording of a refusal already decided above it.
    #
    # `_verify_nothing_was_dropped_or_invented` raises whatever this computes. The
    # condition only chooses whether the message NAMES the differing keys. Which records
    # are refused does not change; what the reader is told about why does.
    #
    # The refusal itself is asserted by
    # test_wire.test_a_payload_that_does_not_reconstruct_as_itself_is_refused.
    "envelope.py::_verify_nothing_was_dropped_or_invented::boolean_operator_swap"
    "::#0::dropped or invented":
        "chooses whether the refusal message names the differing keys; acceptance is "
        "unchanged and the refusal is asserted in test_wire.py",
    "envelope.py::_verify_nothing_was_dropped_or_invented::condition_always_false"
    "::#0::dropped or invented":
        "message detail only -- the raise below it fires either way, with different prose",
    "envelope.py::_verify_nothing_was_dropped_or_invented::condition_always_true"
    "::#0::dropped or invented":
        "message detail only -- the raise below it fires either way, with different prose",
    "envelope.py::_verify_nothing_was_dropped_or_invented::negate_condition"
    "::#0::dropped or invented":
        "message detail only -- the raise below it fires either way, with different prose",
    "envelope.py::_verify_nothing_was_dropped_or_invented::branch_body_pass"
    '::#0::detail = f" (payload-only keys: {dropped}; reconstruction-on':
        "builds the optional detail appended to a refusal already decided above it; the "
        "detail is absent under the mutant and the refusal is identical",

    # ---- Where a list is truncated for display.
    "envelope.py::validate_against_schema::comparison_swap::#0::len(errors) > 10":
        "decides where the schema-violation list is cut off for display. With exactly "
        "ten violations the mutant appends '(and 0 further violations)' and the original "
        "does not -- observably different output, identical acceptance: every violation "
        "is still collected and the same payloads are refused",
}

DECLARED_INVALID: dict[str, str] = {
    # A mutant that cannot be evaluated BEHAVIOURALLY, with the reason it cannot.
    #
    # Separate from the equivalence ledger on purpose. An equivalent mutant makes no
    # difference; these make a large one and the suite cannot attribute it, which is a
    # different admission and must not be filed under the same heading. Neither is a kill.
    #
    # `MetricApplicability.__post_init__` is the guard. `SUPPORTED_APPLICABILITY` is a
    # module-level tuple of `MetricApplicability(...)`, so a mutant that makes the guard
    # always raise breaks `import cai.predictor` itself: every test module errors during
    # collection and no assertion runs. The OLD classifier scored exactly this as a kill,
    # which is the defect this whole rewrite exists to remove -- so it is named here
    # rather than counted.
    #
    # Not worked around by making the module-level tuple lazy. Changing product code so a
    # measurement tool gets a cleaner number is the wrong direction, and the constant is
    # correct where it is.
    "predictor.py::MetricApplicability.__post_init__::condition_always_true"
    "::#0::not self.metric or not self.subject_type":
        "makes the guard raise for every pair, including the module-level "
        "SUPPORTED_APPLICABILITY constant, so cai.predictor cannot be imported and no "
        "test runs; detected, but not by an assertion",
    "predictor.py::MetricApplicability.__post_init__::negate_condition"
    "::#0::not self.metric or not self.subject_type":
        "same: the negated guard raises for every valid pair, breaking the module-level "
        "constant and therefore collection",
}

_COMPARISON_SWAP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}


@dataclass(frozen=True)
class Mutation:
    """One edit to one span of one file, with an identity that names exactly it.

    WHY THE IDENTITY IS FIVE PARTS AND NOT THREE
    --------------------------------------------
    The key used to be `(file, mutation_class, original)`. That is not an identity, it is
    a pattern -- and the same source fragment appears many times in one file. So a single
    equivalence declaration silently suppressed every site that matched it, the report
    counted the DECLARATIONS while implying it had counted the SITES, and "16 declared
    equivalent" was a number that could not be checked against anything.

    The identity now carries the qualified scope the mutation sits in and its ordinal
    among identical fragments in that scope. One declaration matches exactly one site;
    zero is stale and fails the gate; two is ambiguous and fails the gate.

    The ordinal rather than the raw line/column span, deliberately. A span is unique but
    moves whenever anything above it is edited, so every declaration would go stale on an
    unrelated change and the operator would learn to re-stamp them without reading. An
    ordinal within a named scope survives edits elsewhere and still separates duplicates,
    which is the property that makes a stale declaration mean something.
    """

    file: str
    line: int
    scope: str
    """Qualified class/function the mutated node sits in -- `ModelEnvelope.__post_init__`,
    or `<module>` for module-level code."""
    mutation_class: str
    original: str
    mutated: str
    span: tuple[int, int, int, int]
    occurrence: int = 0
    """Ordinal among sites in this scope sharing file, class and original fragment."""

    @property
    def site_id(self) -> str:
        return (
            f"{self.file}::{self.scope}::{self.mutation_class}"
            f"::#{self.occurrence}::{self.original}"
        )

    def describe(self) -> str:
        return (
            f"{self.file}:{self.line} [{self.mutation_class}] "
            f"{self.original} -> {self.mutated}"
        )


class Verdict(str, Enum):
    """What a mutant actually demonstrated. Seven states, because folding any two of
    them together is how a mutation score flatters itself."""

    KILLED = "killed"
    """A well-formed run of the same test universe, with at least one FAILING test."""
    SURVIVED = "survived"
    """A well-formed run of the same test universe, all green. Nothing asserts this."""
    INVALID = "invalid"
    """The mutant does not compile, or breaks collection, or changes the test universe.
    NOT a kill: no behavioural assertion caught anything."""
    TIMEOUT = "timeout"
    """Non-terminating. Says something is wrong, but not that a test noticed."""


@dataclass
class Outcome:
    mutation: Mutation
    verdict: Verdict
    killed_by: tuple[str, ...] = ()
    note: str = ""
    retried: bool = False
    """Whether a second run was needed before this verdict was believed.

    The retry itself is sound -- a transient setup ERROR under nine saturating workers is
    not evidence about a mutant. What was missing is the count. The release protocol asks
    one question of the whole run: did any number here depend on a re-run? Answering it
    by reading prose in per-site notes is how the answer stops being checked, so it is a
    field, and the report prints it whether or not any occurred.
    """

    @property
    def killed(self) -> bool:
        return self.verdict is Verdict.KILLED


def _byte_index(source: bytes, lineno: int, col: int) -> int:
    """Absolute byte offset of a (1-based line, 0-based UTF-8 column) position.

    Bytes rather than characters because `ast` reports `col_offset` in UTF-8 bytes, and
    this package's source contains non-ASCII (the delivered card's separator). Splicing by
    character index would silently misplace every edit after such a line's first non-ASCII
    byte -- producing mutants that are not the mutants the report names.
    """
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[: lineno - 1]) + col


def splice(source: bytes, span: tuple[int, int, int, int], replacement: str) -> bytes:
    start = _byte_index(source, span[0], span[1])
    end = _byte_index(source, span[2], span[3])
    return source[:start] + replacement.encode("utf-8") + source[end:]


def _segment(source: bytes, span: tuple[int, int, int, int]) -> str:
    start = _byte_index(source, span[0], span[1])
    end = _byte_index(source, span[2], span[3])
    return " ".join(source[start:end].decode("utf-8").split())


def _span_of(node: ast.AST) -> tuple[int, int, int, int]:
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


REASON, BOOL = "reason", "bool"


def _return_contract(fn: ast.FunctionDef) -> str | None:
    """Which return substitutions mean anything for this function -- or none.

    THE DIRECTION LABELS WERE REVERSED FOR HALF THE FUNCTIONS THEY RAN ON
    ---------------------------------------------------------------------
    One predicate answered "does this return an answer worth substituting", and both
    shapes got the same two mutants: `None` labelled permissive, a non-empty string
    labelled conservative. For a `str | None` reason function that is exactly right --
    None means no problem, a string means refuse.

    For a `bool` it is backwards. `None` is FALSY and a non-empty string is TRUTHY, so
    on `EntitlementAssertion.permits` the "conservative" mutant returns something that
    reads as PERMISSION. The aggregate `conservative_return 53/53` could not be read
    literally, which is worse than not reporting it.

    Two contracts now, with substitutions that fit each. And for a bool the direction is
    not asserted at all -- `constant_true_return` / `constant_false_return` say what the
    mutant DOES, and whether True is the permissive answer depends on the predicate.
    """
    returns = fn.returns
    if isinstance(returns, ast.Name) and returns.id == "bool":
        return BOOL
    if isinstance(returns, ast.Constant) and returns.value == "bool":
        return BOOL
    # `str | None` arrives as a BinOp under `from __future__ import annotations`, and as
    # a string constant when quoted.
    if isinstance(returns, ast.BinOp):
        return REASON
    if isinstance(returns, ast.Constant) and "None" in str(returns.value):
        return REASON
    return None


def generate(paths: list[Path]) -> list[Mutation]:
    mutations: list[Mutation] = []
    for path in paths:
        source = path.read_bytes()
        tree = ast.parse(source.decode("utf-8"))
        mutations.extend(_walk_scoped(path.name, source, tree, scope="<module>"))

    # THE ORDINAL, assigned after generation over the whole file so it is stable: the
    # nth site in this scope sharing (file, class, original fragment).
    counters: dict[tuple[str, str, str, str], int] = {}
    numbered: list[Mutation] = []
    for mutation in sorted(
        mutations, key=lambda m: (m.file, m.span[0], m.span[1], m.mutation_class)
    ):
        bucket = (mutation.file, mutation.scope, mutation.mutation_class,
                  mutation.original)
        index = counters.get(bucket, 0)
        counters[bucket] = index + 1
        numbered.append(replace(mutation, occurrence=index))

    identities = [m.site_id for m in numbered]
    duplicates = sorted({i for i in identities if identities.count(i) > 1})
    if duplicates:
        raise AssertionError(
            f"the site identity does not identify a site: {duplicates[:5]}; a "
            f"declaration keyed on it would suppress more than one mutant"
        )
    return sorted(numbered, key=lambda m: (m.file, m.line, m.mutation_class, m.site_id))


def _walk_scoped(
    name: str, source: bytes, node: ast.AST, *, scope: str
) -> list[Mutation]:
    """Walk the tree carrying the qualified scope, which `ast.walk` throws away.

    The scope is half the site identity, so it has to be tracked rather than recovered:
    two `return False` statements in two methods of one class are two different sites and
    must not share a key.
    """
    out: list[Mutation] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.If) and _is_type_checking_guard(child):
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.extend(_return_mutations(name, source, child, inner))
            out.extend(_walk_scoped(name, source, child, scope=inner))
            continue
        out.extend(_mutations_for(name, source, child, scope))
        out.extend(_walk_scoped(name, source, child, scope=scope))
    return out


def _mutations_for(
    name: str, source: bytes, node: ast.AST, scope: str
) -> list[Mutation]:
    out: list[Mutation] = []

    if isinstance(node, ast.If):
        test_span = _span_of(node.test)
        # Truncated because a few conditions here run to several hundred characters of
        # source and comment, and the untruncated fragment made both the report and the
        # site identity unreadable. Every declared site's fragment is well under this.
        original = _segment(source, test_span)[:80]
        # THE NEGATION IS BUILT FROM THE AST, NOT FROM THE SOURCE TEXT.
        #
        # It used to be `f"not ({original})"`, where `original` is the span's source with
        # its whitespace collapsed. That puts any inline `#` comment on one line and
        # swallows everything after it, and turns a `\` line continuation into a stray
        # backslash. Four conditions in this package are long enough to carry comments
        # inside them, and all four produced mutants that were not valid Python.
        #
        # Before `compile_check` existed, each of those was applied, broke the import,
        # and the old classifier scored it as a KILL. The check has now caught this same
        # defect twice -- the second time because a clone-and-port workflow silently
        # reverted the first fix, which is exactly the sort of regression a gate that
        # only ran mutants would have absorbed as four more kills.
        negated = f"not ({ast.unparse(node.test)})"
        # A literal test is already `if True`/`if False`; mutating it produces the same
        # program and would be pure noise in the report.
        if not isinstance(node.test, ast.Constant):
            for cls, replacement in (
                ("negate_condition", negated),
                ("condition_always_true", "True"),
                ("condition_always_false", "False"),
            ):
                out.append(Mutation(name, node.test.lineno, scope, cls, original,
                                    replacement, test_span))
        body_span = (
            node.body[0].lineno, node.body[0].col_offset,
            node.body[-1].end_lineno, node.body[-1].end_col_offset,
        )
        body = _segment(source, body_span)
        if body != "pass":
            out.append(Mutation(name, node.body[0].lineno, scope, "branch_body_pass",
                                body[:60], "pass", body_span))

    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        swapped = _COMPARISON_SWAP.get(type(node.ops[0]))
        if swapped is not None:
            span = _span_of(node)
            mutated = ast.Compare(left=node.left, ops=[swapped()],
                                  comparators=node.comparators)
            out.append(Mutation(
                name, node.lineno, scope, "comparison_swap", _segment(source, span),
                f"({ast.unparse(ast.fix_missing_locations(mutated))})", span,
            ))

    if isinstance(node, ast.BoolOp) and len(node.values) >= 2:
        span = _span_of(node)
        flipped = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        mutated = ast.BoolOp(op=flipped, values=node.values)
        out.append(Mutation(
            name, node.lineno, scope, "boolean_operator_swap", _segment(source, span),
            f"({ast.unparse(ast.fix_missing_locations(mutated))})", span,
        ))

    if isinstance(node, ast.Raise):
        span = _span_of(node)
        out.append(Mutation(name, node.lineno, scope, "remove_raise_guard",
                            _segment(source, span)[:70], "pass", span))
    return out


def _return_mutations(
    name: str, source: bytes, fn: ast.FunctionDef, scope: str
) -> list[Mutation]:
    """Substitute answers that fit the function's declared return contract.

    Only where the answer decides something: a `bool` predicate, or the `str | None`
    "a reason, or None" shape this package uses for every binding check. Substituting a
    return in an `as_record` builder produces a crash rather than a behaviour change,
    which tells nobody anything.
    """
    contract = _return_contract(fn)
    if contract is None:
        return []
    substitutions = (
        # For a reason predicate the direction is real and worth naming: None is the
        # permissive answer, a refusal string the conservative one.
        (("permissive_return", "None"),
         ("conservative_return", '"mutant: an unconditional refusal"'))
        if contract is REASON else
        # For a bool it is not. Both are booleans; which one is permissive depends on
        # the predicate, so the class says what the mutant does and claims nothing more.
        (("constant_true_return", "True"), ("constant_false_return", "False"))
    )
    out: list[Mutation] = []
    for node in _returns_belonging_to(fn):
        span = _span_of(node.value)
        original = _segment(source, span)
        for cls, replacement in substitutions:
            if original == replacement:
                continue
            out.append(Mutation(name, node.lineno, scope, cls, original, replacement,
                                span))
    return out


def _returns_belonging_to(fn: ast.FunctionDef) -> list[ast.Return]:
    """The returns of THIS function, not of everything lexically inside it.

    WHY `ast.walk` WAS THE WRONG TOOL
    ---------------------------------
    This was `for node in ast.walk(fn)` with

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
            continue  # a nested def is its own scope and is walked separately

    and the comment describes an intention the code does not carry out. `ast.walk` is
    breadth-first over a queue it populates as it goes: by the time the nested `FunctionDef`
    is yielded, its children are already scheduled. `continue` skips the def NODE and
    prunes nothing.

    So `return flag` inside a nested `inner` was collected under `outer`, and
    `_walk_scoped` then visited `inner` on its own terms and collected it again under
    `outer.inner`. One physical statement, two mutants, two site identities -- because
    `site_id` carries the scope, and two records under different scopes are distinct keys
    that the duplicate-identity assertion is satisfied by.

    That inflates the generated count and, if both mutants die, the killed count with it.
    A declaration written against one of them leaves the other live.

    `iter_child_nodes` descends explicitly and stops at anything that opens a new scope,
    so each function is visited exactly once, by `_walk_scoped`, under its own name.
    `Lambda` is in the stop set for completeness -- a lambda cannot contain a `Return`
    node, so it costs nothing and removes a question a reader would otherwise have to
    answer from the grammar.
    """
    found: list[ast.Return] = []

    def descend(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(child, ast.Return) and child.value is not None:
                found.append(child)
            descend(child)

    descend(fn)
    return found


def compile_check(paths: list[Path], mutations: list[Mutation]) -> list[Mutation]:
    """Every generated mutant must be valid Python BEFORE anything runs it.

    A mutant that cannot compile is a defect in this generator, not a finding about the
    suite -- and the previous version discovered them one at a time, at run time, after
    paying for a pytest invocation. Worse, an uncompilable mutant made the suite
    unimportable, which the old classifier scored as a KILL.

    Returns the ones that fail so the operator sees a generator bug as a generator bug.
    """
    sources = {p.name: p.read_bytes() for p in paths}
    broken: list[Mutation] = []
    for mutation in mutations:
        try:
            mutated = splice(sources[mutation.file], mutation.span, mutation.mutated)
            compile(mutated.decode("utf-8"), mutation.file, "exec")
        except (SyntaxError, ValueError, UnicodeDecodeError):
            broken.append(mutation)
    return broken


# ---------------------------------------------------------------------------
# RUNNING. Each worker owns a scratch copy of the tree, so mutants never touch
# the real source and can be evaluated concurrently.
# ---------------------------------------------------------------------------

_WORKSPACE: Path | None = None

# What a worker's scratch copy of the repository contains.
#
# This was an ALLOWLIST -- src, tests, pyproject.toml -- and it was wrong twice, in the
# same way both times. First it omitted `schema/`, so the committed-schema test failed in
# every workspace and every mutant looked killed: the gate reported 2015/2015 and could
# not fail. Then it omitted `.githooks/` and `scan_history.sh`, and the firewall
# regression failed the same way.
#
# An allowlist of "everything the suite reads" is a list somebody has to remember to
# update whenever a test grows a new data dependency, and the failure mode when they
# forget is a gate that always passes. So it is a DENYLIST now: copy the repository, minus
# the things that are large, regenerable, or actively hostile to being copied. A new data
# dependency is picked up without anyone noticing it was added.
#
# `_check_baseline` is the backstop that caught both omissions, and it caught the second
# one before a single mutant ran.
WORKSPACE_EXCLUDES = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache",
    "*.egg-info", "build", "dist", ".ruff_cache",
)


def _build_workspace() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cai-mutgen-"))
    workspace = root / "repo"
    shutil.copytree(ROOT, workspace, ignore=WORKSPACE_EXCLUDES, symlinks=True)
    return workspace


# TESTS OF THE MEASUREMENT TOOLS THEMSELVES, EXCLUDED FROM THE MUTATED UNIVERSE.
#
# `tests/test_measurement_tooling.py` exercises this generator and the guard sweep. It
# does that by SPAWNING them -- eight nested tool invocations per suite run, each with
# its own worker pool. Inside a mutation run that is paid 2056 times, by nine workers at
# once, and the nesting is a fork bomb with a polite name.
#
# It also cannot contribute anything. Those tests assert facts about the tools, not about
# `src/cai`, so no mutant in the package under test can be killed by them. What they DID
# contribute was noise: one mutant came back with pytest returning 1 and no FAILED line
# parsed from its output, classified INVALID -- and reproducing it in isolation showed a
# clean kill by `test_an_applicability_verdict_with_no_basis_is_an_opinion`. The verdict
# was an artifact of nested runs under load.
#
# Excluded from the BASELINE and from every mutant identically, so the "same test
# universe" rule is satisfied by construction rather than weakened: what is compared is
# consistent, and what is measured is the package this gate exists to measure.
EXCLUDED_FROM_THE_MUTATED_UNIVERSE = (
    "tests/test_measurement_tooling.py",
    # A TEST THAT AUDITS A HARDCODED TABLE AGAINST THE LIVE SOURCE CANNOT LIVE HERE.
    #
    # `test_schema_reconciliation.py` derives its inventory by parsing `src/cai` and
    # counting the `raise` sites in every portable type, and it PARAMETRIZES over that
    # inventory. Inside a mutation run `src/cai` is the mutant, so a mutation that removes
    # a raise removes a class from the inventory and collects one fewer test --
    # 1069 against a 1070 baseline, which the classifier correctly reports as "changed the
    # test universe" and therefore INVALID.
    #
    # Two of those appeared in the first full run, at `MetricApplicability.__post_init__`,
    # whose guard is the only raise in its class. Verified rather than reasoned about: with
    # the raise genuinely deleted the count is 1069, and with this file excluded it is
    # stable.
    #
    # This package has been here before. An earlier ledger-audit test compared declared
    # equivalences against the live tree, so a mutation at any declared site moved the
    # fragment, failed the test, and scored a KILL -- seven kills produced by a test
    # noticing that source text had moved. That one flattered; this one fails
    # conservatively, reporting INVALID rather than a kill. The defect is the same either
    # way: a test whose subject is the source text cannot be run against a mutated copy of
    # it and tell you anything about the mutant.
    #
    # Excluded rather than made collection-stable on purpose. Parametrizing over the
    # hardcoded table instead of the derived inventory would keep the count fixed and turn
    # these mutants into KILLS -- and those kills would be exactly the artifact the earlier
    # test produced, a failure caused by source text changing rather than by behaviour
    # changing. The reconciliation test still runs, in the real suite, where its subject is
    # the real source.
    "tests/test_schema_reconciliation.py",
)

_IGNORE = [arg for path in EXCLUDED_FROM_THE_MUTATED_UNIVERSE
           for arg in ("--ignore", path)]


def _collect(workspace: Path) -> subprocess.CompletedProcess:
    """Collection only. Cheap (about 60ms against a two-second suite) and it answers the
    one question the old classifier never asked: is this still the same test universe?"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--co", "-q",
         *_IGNORE, "-p", "no:cacheprovider"],
        cwd=workspace, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        timeout=180,
    )


def _run_suite(workspace: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--no-header",
         # `-rfE`, not `-rf`. `-rf` reports FAILURES ONLY, so a test that ERRORS in
         # setup or teardown produced rc=1 with no FAILED line AND no ERROR line, and
         # the classifier could say nothing better than "nobody has said why". Two
         # mutants were misclassified INVALID that way, both reproducibly clean kills
         # when re-run alone.
         "--tb=no", "-rfE", *_IGNORE, "-p", "no:cacheprovider"],
        cwd=workspace, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        timeout=300,
    )


def reproduces_alone(workspace: Path, killer: str) -> bool:
    """Does the named test still fail when it is the only test running?

    PUBLIC, AND TAKING ITS WORKSPACE EXPLICITLY, BECAUSE TWO TOOLS NEED THIS ONE RULE.

    `guard_sweep.py` does the same thing to the tree that this tool does -- it changes
    `src/cai` and re-runs the suite -- and it was reaching the opposite conclusion from the
    same evidence: any FAILED line in a full-suite run made a removed guard LOAD_BEARING,
    with no check that the named failure had anything to do with the guard. That is the
    flattering direction, and it is the identical defect this function was written to close
    here.

    Restating the rule there would have been a second copy of one policy, which is the
    argument already made for `EXCLUDED_FROM_THE_MUTATED_UNIVERSE` a few lines down: two
    copies disagree eventually, and the disagreement surfaces as a tooling defect at the
    worst moment. So the rule lives once and is imported, and the worker-state wrapper
    below is all that stays private.

    `killer` is a nodeid as pytest's `-rfE` summary prints it. Parametrized ids carry
    brackets, which are meaningful to `-k` only as literal text, so the id is passed
    positionally -- pytest resolves it directly and no quoting question arises.

    A failure to RUN the targeted test at all (a collection error, a bad id) returns
    False rather than True. The claim being made is "this mutant was caught", and it must
    be earned: anything that leaves the question unanswered has to fall short of a kill,
    or the check would flatter in exactly the direction it exists to prevent.

    WHAT "FAILS CLOSED" COST ON THE FIRST ATTEMPT, BECAUSE IT IS THE LESSON HERE.
    This gated on `_collected_count(output) in (0, None)` -- and `-q` SUPPRESSES pytest's
    "N tests collected" line, so the count was None on every successful run. Every kill in
    the package was downgraded to a survivor and the first slice reported 34 unexplained
    survivors with an empty kill list.

    That direction is the conservative one, which is why it was survivable. It was still a
    hole in the same shape as the eleven that went the other way: the check had been
    tested for its ability to say NO and never for its ability to say YES, so a defect
    that made it answer NO unconditionally passed its own tests. Both directions are
    asserted now, against a real failing test in a real workspace.

    Exit code 5 is pytest's "no tests ran", which is the honest form of the question this
    was trying to ask.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", killer, "-x", "-q", "--no-header",
             "--tb=no", "-rfE", "-p", "no:cacheprovider"],
            cwd=workspace, capture_output=True, text=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    if completed.returncode == NO_TESTS_RAN:
        return False
    return bool(FAILED.findall(completed.stdout + completed.stderr))


def _reproduces_alone(killer: str) -> bool:
    """Worker-state wrapper. The rule itself is `reproduces_alone`."""
    assert _WORKSPACE is not None
    return reproduces_alone(_WORKSPACE, killer)


NO_TESTS_RAN = 5
"""pytest's exit code for "no tests were collected"."""


COLLECTED = re.compile(r"^(\d+) tests? collected", re.MULTILINE)


def _collected_count(output: str) -> int | None:
    match = COLLECTED.search(output)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class Baseline:
    """What an unmutated worker workspace looks like. Everything is judged against it."""

    collected: int


def _check_baseline() -> tuple[Baseline | None, str]:
    """Run the UNMUTATED suite in a workspace built exactly as the workers build theirs.

    Without this, any defect in the workspace -- a missing data file, an absent
    dependency, a path assumption that only holds in the repo root -- turns every mutant
    into a kill and the gate into a machine that always says yes. That is the single most
    dangerous failure available to a tool whose output is evidence, and it is not
    hypothetical: it is what the first run of this tool actually did.

    It now also records the COLLECTED COUNT, which is the reference every mutant's own
    collection is compared against. A mutant that changes the test universe has not been
    caught by anything; it has broken the instrument.
    """
    workspace = _build_workspace()
    try:
        collected = _collect(workspace)
        count = _collected_count(collected.stdout + collected.stderr)
        if collected.returncode != 0 or count is None:
            return None, (
                "the baseline workspace cannot even COLLECT the suite:\n"
                + (collected.stdout + collected.stderr).strip()[-1500:]
            )
        completed = _run_suite(workspace)
        if completed.returncode != 0:
            return None, (completed.stdout + completed.stderr).strip()[-1500:]
        return Baseline(collected=count), ""
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


_BASELINE: Baseline | None = None


def _init_worker(baseline: Baseline) -> None:
    global _WORKSPACE, _BASELINE
    _WORKSPACE = _build_workspace()
    _BASELINE = baseline


def _purge(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


# `(\S+)` TRUNCATED EVERY PARAMETRIZED NODEID AT THE FIRST SPACE INSIDE ITS BRACKETS.
#
# pytest's short summary is `FAILED path::test[params] - ExceptionType: message`, and
# this package parametrizes with human-readable ids -- "a required key is deleted",
# "delivered on a refusing assurance". `\S+` stopped at the first one of those spaces, so
# the reported killer was `tests/test_wire.py::test_...[a`.
#
# That was a display defect while `killed_by` was only printed. It became a correctness
# defect the moment a kill had to be confirmed by re-running its killer: a truncated id
# collects nothing, `_reproduces_alone` fails closed, and a genuine kill would be
# downgraded to a survivor. Found by checking what the attribution check would actually
# be handed, rather than by running the gate and reading the count.
FAILED = re.compile(r"^FAILED (.+?)(?: - |\s*$)", re.MULTILINE)
ERROR = re.compile(r"^ERROR (.+?)(?: - |\s*$)", re.MULTILINE)


def _classify_run(mutation: Mutation) -> Outcome:
    """One suite run over an already-mutated workspace, classified.

    Split out of `_evaluate` so a single inconclusive run can be repeated without
    re-applying the mutation or re-checking collection.
    """
    assert _WORKSPACE is not None
    completed = _run_suite(_WORKSPACE)
    output = completed.stdout + completed.stderr
    failures = tuple(FAILED.findall(output))
    errors = tuple(ERROR.findall(output))
    if completed.returncode == 0:
        return Outcome(mutation, Verdict.SURVIVED)
    if failures:
        # A FAILING TEST IS NOT YET EVIDENCE THAT THIS MUTANT WAS CAUGHT.
        #
        # The suite runs under a pool of workers each running a full pytest, and under
        # that load a test can fail for reasons that have nothing to do with the mutation
        # -- the same saturation that produces the transient setup ERRORs the retry below
        # already exists for. On the ERROR path that produced an INVALID, which is
        # conservative and visible. On the FAILED path it produced a KILL, which is the
        # flattering direction: an unrelated failure became evidence that the intended
        # property is covered, and it became evidence silently.
        #
        # So the named killer is re-run ALONE against the same mutated tree. A real
        # behavioural kill reproduces every time -- the mutation is still applied and the
        # assertion still catches it. A transient does not.
        #
        # This is the smallest reliable form of the check: one targeted single-test run,
        # only on the kill path, only for the first named failure. It is not an attempt to
        # decide whether the killer is thematically "related" to the mutation, which would
        # be a heuristic dressed as a rule.
        if _reproduces_alone(failures[0]):
            return Outcome(mutation, Verdict.KILLED, killed_by=failures[:3])
        return Outcome(
            mutation, Verdict.SURVIVED,
            note=f"{failures[0]} failed in the full run and passed when re-run alone "
                 f"against the same mutant; the failure is not attributable to this "
                 f"mutation and is not counted as a kill",
        )
    if errors:
        return Outcome(
            mutation, Verdict.INVALID,
            note=f"no test FAILED; {len(errors)} test(s) ERRORED: {list(errors[:3])}",
        )
    tail = " ".join(output.strip().splitlines()[-2:])[:200]
    return Outcome(
        mutation, Verdict.INVALID,
        note=f"rc={completed.returncode}, no FAILED and no ERROR line. Last output: "
             f"{tail!r}",
    )


def _evaluate(mutation: Mutation) -> Outcome:
    """Four questions, in order, and a kill requires passing the first three.

    THE OLD CLASSIFIER WAS ONE LINE: `killed = completed.returncode != 0`.
    Every way of making the suite fail to RUN scored as a kill -- an import error, a
    collection error, a mutant that could not compile. None of those demonstrate that any
    behavioural assertion caught the changed behaviour, which is the only thing a mutation
    score is supposed to measure. It is the same flattering failure the curated harness
    had already been corrected for, reintroduced in the newer tool.

        1. does it compile?              no -> INVALID
        2. does the suite still collect?  no -> INVALID
        3. is it the SAME test universe?  no -> INVALID
        4. did a test actually FAIL?     yes -> KILLED, no -> SURVIVED

    and a run that never terminates is TIMEOUT, which says something is wrong without
    claiming a test noticed.
    """
    assert _WORKSPACE is not None and _BASELINE is not None
    target = _WORKSPACE / "src" / PACKAGE / mutation.file
    original = target.read_bytes()
    try:
        mutated = splice(original, mutation.span, mutation.mutated)
    except Exception as exc:  # a span that no longer resolves is a generator bug
        return Outcome(mutation, Verdict.INVALID, note=f"could not apply: {exc}")
    try:
        compile(mutated.decode("utf-8"), mutation.file, "exec")
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        return Outcome(mutation, Verdict.INVALID,
                       note=f"does not compile: {type(exc).__name__}")

    target.write_bytes(mutated)
    _purge(_WORKSPACE)
    try:
        collected = _collect(_WORKSPACE)
        count = _collected_count(collected.stdout + collected.stderr)
        if collected.returncode != 0 or count is None:
            return Outcome(mutation, Verdict.INVALID,
                           note="collection or import failure -- no test ran")
        if count != _BASELINE.collected:
            return Outcome(
                mutation, Verdict.INVALID,
                note=f"changed the test universe: {count} collected, "
                     f"baseline {_BASELINE.collected}",
            )

        # RUN, AND CONFIRM ANYTHING THAT IS NOT A CLEAN VERDICT.
        #
        # Nine workers each running a full suite saturate the machine, and under that
        # load a test can ERROR in setup for reasons that have nothing to do with the
        # mutant. `-x` then stops on it, and the run reports neither the mutant's real
        # killer nor anything else useful. Twice this produced an INVALID that was a
        # clean, reproducible kill when re-run alone.
        #
        # So a verdict of INVALID from the RUN stage -- never from compilation or
        # collection, which are deterministic -- is confirmed once before it is
        # believed, and the note says a confirmation happened. Reported rather than
        # silent: a retry nobody can see is how a flaky gate starts reading as a firm one.
        verdict = _classify_run(mutation)
        if verdict.verdict is Verdict.INVALID:
            second = _classify_run(mutation)
            if second.verdict is not Verdict.INVALID:
                return Outcome(
                    second.mutation, second.verdict, second.killed_by,
                    note=f"confirmed on a second run; the first was inconclusive "
                         f"({verdict.note})",
                    retried=True,
                )
            return Outcome(second.mutation, second.verdict, second.killed_by,
                           note=f"{second.note} [twice]", retried=True)
        return verdict
    except subprocess.TimeoutExpired:
        return Outcome(mutation, Verdict.TIMEOUT, note="non-terminating mutant")
    finally:
        target.write_bytes(original)
        # EXACTLY restored, checked rather than assumed. A worker whose tree drifts
        # poisons every mutant it evaluates afterwards, and the drift is invisible.
        if target.read_bytes() != original:
            raise AssertionError(f"worker source not restored: {mutation.file}")
        _purge(_WORKSPACE)


def audit_declarations(
    declared: dict[str, str],
    mutations: list[Mutation],
    in_scope: set[str],
    outcomes: list["Outcome"] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """One declaration, one site, and the site must still need it.

    Returns (stale, ambiguous, unnecessary). All three fail the gate.

    A separate function so the RULE can be tested without running two thousand mutants.
    It was inline in `main`, which meant the only way to exercise it was a full gate run
    -- so the ambiguity branch had never executed at all.

    `stale`       matches no generated site. The declaration describes a mutant that no
                  longer exists, and it silently shrinks the gate.
    `ambiguous`   matches more than one. Impossible now that the identity carries scope
                  and ordinal, and asserted rather than assumed, because that assumption
                  is exactly what the previous key violated.
    `unnecessary` matches a site that was KILLED. This is the one CT did not ask for and
                  it is the one that bites: a declaration saying "no test can observe
                  this" while a test observes it is a false claim about the suite, and
                  it accumulates silently in the flattering direction as coverage grows.
                  Seven of these appeared in a single round when the hostile pass landed.

    Staleness is judged only over the files actually generated from. With `--only`,
    declarations for other files match nothing and were simply not in scope.
    """
    identities = [m.site_id for m in mutations]
    stale = sorted(
        key for key in declared
        if key.split("::")[0] in in_scope and key not in identities
    )
    ambiguous = sorted(key for key in declared if identities.count(key) > 1)
    killed_sites = {
        o.mutation.site_id for o in (outcomes or []) if o.verdict is Verdict.KILLED
    }
    unnecessary = sorted(key for key in declared if key in killed_sites)
    return stale, ambiguous, unnecessary


def contradicted_invalid_declarations(
    outcomes: list[Outcome], declared: dict[str, str]
) -> list[tuple[str, str]]:
    """Declared-invalid sites whose run reached any verdict other than INVALID.

    `DECLARED_INVALID` claims one thing about a site: the generated mutant cannot be
    behaviourally evaluated, so it lands on INVALID and no test could have caught it.
    Staleness was already audited -- a declaration naming a site that no longer exists
    fails the gate. The unchecked case is the site that still exists and now evaluates.

    A mutant becomes evaluable when the code around it changes, and nothing re-reads the
    declaration when that happens. So a KILLED site could sit under a declaration asserting
    no test can observe it, and the gate accepted the pair without complaint. Equivalence
    and diagnostic-only declarations already have this check, where it is called
    `unnecessary`; invalid declarations never got it.

    A pure function over the outcomes so both directions are testable without running a
    corpus: a declared site that really is INVALID must be accepted, and the identical
    declaration over a KILLED site must be refused. Returns `(site_id, verdict)` pairs,
    because "your declaration is wrong" is not actionable and "declared invalid, actually
    KILLED" is.
    """
    return sorted(
        (o.mutation.site_id, o.verdict.value)
        for o in outcomes
        if o.mutation.site_id in declared and o.verdict is not Verdict.INVALID
    )


def as_records(outcomes: list[Outcome]) -> list[dict]:
    """One record per evaluated mutation, ordered so `diff` is the whole comparison.

    WHY TOTALS WERE NOT ENOUGH.

    Phase 5 asks that `--jobs 1` and `--jobs 2` agree PER SITE. The human report prints
    totals, every exceptional site in full, and a twelve-line SAMPLE of the kills -- so two
    runs could both exit 0, and both print the same totals, while disagreeing about which
    test caught which mutant among the two thousand sites nobody printed. Agreement on a
    count is not agreement on a classification.

    Only values fixed by the mutation and its verdict appear. `note` is deliberately absent:
    it carries return codes and error text that vary between environments, and `diff` would
    report those as disagreements when they are not. `killed_by` is sorted here rather than
    trusted in pytest's reporting order, so a difference in the RECORD means a difference in
    WHICH TESTS caught the mutant, not a difference in which one happened to be printed
    first.
    """
    return [
        {
            "site_id": o.mutation.site_id,
            "verdict": o.verdict.value,
            "killed_by": sorted(o.killed_by),
            "retried": o.retried,
        }
        for o in sorted(outcomes, key=lambda o: o.mutation.site_id)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print mutations, run nothing")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--only", default="", help="comma-separated source file names")
    parser.add_argument("--json", action="store_true",
                        help="per-site records on stdout, human report on stderr")
    args = parser.parse_args()

    # Every existing progress line goes to stderr for the duration of a --json run, so the
    # document on stdout is the whole of stdout. Restored in the `finally` below, because
    # a rebinding that survives an exception would corrupt whatever ran next.
    real_stdout = sys.stdout
    if args.json:
        sys.stdout = sys.stderr
    try:
        return _main(args, real_stdout=real_stdout)
    finally:
        sys.stdout = real_stdout


def _main(args, *, real_stdout) -> int:

    paths = sorted(SRC.glob("*.py"))
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        paths = [p for p in paths if p.name in wanted]
    mutations = generate(paths)

    if args.list:
        for mutation in mutations:
            print(mutation.describe())
        print(f"\n{len(mutations)} candidate mutations across {len(paths)} files")
        return 0

    print(f"generating from {len(paths)} source files in src/cai")

    # BEFORE anything is copied or run: is every generated mutant valid Python?
    # An uncompilable mutant is a defect in this generator, and the previous version
    # found them one at a time at run time -- after scoring each one as a KILL.
    broken = compile_check(paths, mutations)
    if broken:
        print("\nGENERATOR DEFECT: mutations that are not valid Python.\n")
        for mutation in broken[:20]:
            print(f"  {mutation.describe()}")
        print(f"\n{len(broken)} uncompilable mutation(s). Fix the generator.")
        return 2

    print("checking the baseline suite is green in a worker-shaped workspace...")
    baseline, broken_baseline = _check_baseline()
    if baseline is None:
        print("\nBASELINE IS NOT GREEN. Every mutant would look killed and this gate "
              "would always pass. Refusing to run.\n")
        print(broken_baseline)
        return 2
    print(f"baseline collects {baseline.collected} tests")
    print(f"{len(mutations)} candidate mutations, {args.jobs} workers\n")

    with multiprocessing.Pool(
        args.jobs, initializer=_init_worker, initargs=(baseline,)
    ) as pool:
        outcomes: list[Outcome] = []
        for done, outcome in enumerate(
            pool.imap_unordered(_evaluate, mutations, chunksize=1), start=1
        ):
            outcomes.append(outcome)
            if done % 25 == 0 or done == len(mutations):
                alive = sum(1 for o in outcomes if o.verdict is Verdict.SURVIVED)
                bad = sum(1 for o in outcomes if o.verdict is Verdict.INVALID)
                print(f"  {done}/{len(mutations)} evaluated, "
                      f"{alive} surviving, {bad} invalid")

    outcomes.sort(key=lambda o: (o.mutation.file, o.mutation.line,
                                 o.mutation.mutation_class))
    by_verdict: dict[Verdict, list[Outcome]] = {v: [] for v in Verdict}
    for outcome in outcomes:
        by_verdict[outcome.verdict].append(outcome)
    killed = by_verdict[Verdict.KILLED]
    survivors = by_verdict[Verdict.SURVIVED]
    invalid = by_verdict[Verdict.INVALID]
    timeouts = by_verdict[Verdict.TIMEOUT]

    # THREE KINDS OF SURVIVOR, AND FOLDING ANY TWO IS HOW THE NUMBER FLATTERS ITSELF.
    #
    # A survivor is a mutant that ran the same test universe and produced no failure.
    # Why is a separate question with three answers: nothing observable changed
    # (equivalent, and provable), something changed that this gate has decided not to pin
    # (diagnostic-only, and admitted), or nobody has said (unexplained, and a gate
    # failure). The first two were one bucket, which meant the report could say "proven
    # equivalent" about six mutants that were nothing of the kind.
    both = sorted(set(DECLARED_EQUIVALENT) & set(DECLARED_DIAGNOSTIC_ONLY))
    if both:
        raise AssertionError(
            f"declared both equivalent and diagnostic-only: {both}; a site cannot be "
            f"both proven to change nothing and admitted to change something"
        )
    declared = [o for o in survivors if o.mutation.site_id in DECLARED_EQUIVALENT]
    diagnostic = [o for o in survivors if o.mutation.site_id in DECLARED_DIAGNOSTIC_ONLY]
    unexplained = [
        o for o in survivors
        if o.mutation.site_id not in DECLARED_EQUIVALENT
        and o.mutation.site_id not in DECLARED_DIAGNOSTIC_ONLY
    ]

    # ONE DECLARATION, ONE SITE. A declaration matching nothing is stale; a declaration
    # matching two sites is impossible now that the identity carries scope and ordinal,
    # and it is asserted rather than assumed because that assumption is exactly what the
    # previous key silently violated.
    #
    # Staleness is judged only over the files actually generated from. With `--only`,
    # declarations for other files match nothing and were simply not in scope.
    stale, ambiguous, unnecessary = audit_declarations(
        DECLARED_EQUIVALENT, mutations, {p.name for p in paths}, outcomes
    )
    # The diagnostic ledger is audited on exactly the same terms. A declaration that
    # suppresses a line in the report is a declaration, whatever it is called, and the
    # three failure modes -- matches nothing, matches several, matches a site a test
    # kills -- apply identically.
    d_stale, d_ambiguous, d_unnecessary = audit_declarations(
        DECLARED_DIAGNOSTIC_ONLY, mutations, {p.name for p in paths}, outcomes
    )

    by_class: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        by_class.setdefault(outcome.mutation.mutation_class, []).append(outcome)

    print("\n" + "=" * 78)
    print("SOURCE-DERIVED MUTATION RESULT")
    print("=" * 78)
    print(f"generated             {len(mutations)}")
    print(f"behaviorally killed   {len(killed)}")
    print(f"survived              {len(survivors)}")
    print(f"  declared equivalent {len(declared)}")
    print(f"  diagnostic-only     {len(diagnostic)}")
    print(f"  unexplained         {len(unexplained)}")
    print(f"invalid               {len(invalid)}")
    print(f"  declared            "
          f"{len([o for o in invalid if o.mutation.site_id in DECLARED_INVALID])}")
    print(f"  undeclared          "
          f"{len([o for o in invalid if o.mutation.site_id not in DECLARED_INVALID])}")
    print(f"timeout               {len(timeouts)}")
    retried = [o for o in outcomes if o.retried]
    print(f"retries exercised     {len(retried)}")
    for outcome in retried:
        print(f"  {outcome.mutation.site_id}")
        print(f"      {outcome.note}")
    print(f"jobs                  {args.jobs}")
    print()
    print("by mutation class (behavioural kills over VALID mutants only):")
    for name in sorted(by_class):
        group = by_class[name]
        hits = sum(1 for o in group if o.verdict is Verdict.KILLED)
        valid = sum(1 for o in group
                    if o.verdict in (Verdict.KILLED, Verdict.SURVIVED))
        print(f"  {name:<24} {hits:>4} killed / {valid:>4} valid  "
              f"({len(group) - valid} invalid or timed out)")

    if declared:
        print("\nDECLARED EQUIVALENT -- no observable difference, with the proof:")
        for outcome in declared:
            print(f"  {outcome.mutation.site_id}")
            print(f"      {DECLARED_EQUIVALENT[outcome.mutation.site_id]}")

    if diagnostic:
        print("\nDIAGNOSTIC-ONLY -- behaviour DOES differ, in what a reader is told and "
              "not in what is accepted or refused. Not killed, not equivalent:")
        for outcome in diagnostic:
            print(f"  {outcome.mutation.site_id}")
            print(f"      {DECLARED_DIAGNOSTIC_ONLY[outcome.mutation.site_id]}")

    if unexplained:
        print("\nSURVIVED, UNEXPLAINED -- behaviour nothing in the suite asserts:")
        for outcome in unexplained:
            print(f"  {outcome.mutation.site_id}")

    declared_invalid = [o for o in invalid if o.mutation.site_id in DECLARED_INVALID]
    undeclared_invalid = [o for o in invalid
                          if o.mutation.site_id not in DECLARED_INVALID]
    stale_invalid = sorted(
        k for k in DECLARED_INVALID
        if k.split("::")[0] in {p.name for p in paths}
        and k not in [m.site_id for m in mutations]
    )
    # A DECLARATION THAT ITS SITE NOW CONTRADICTS.
    #
    # `DECLARED_INVALID` makes one specific claim: this generated mutant cannot be
    # behaviourally evaluated, so it reaches INVALID and no test could have caught it.
    # Staleness was already checked -- a declaration naming a site that no longer exists
    # fails. What was not checked is the site that still exists and now evaluates fine.
    #
    # A mutant becomes evaluable when the code around it changes, and nothing re-reads the
    # declaration when that happens. So a KILLED site could sit under a declaration saying
    # no test can observe it, and the gate accepted both at once. That is the same defect
    # already closed for equivalence and diagnostic-only declarations, where it is called
    # `unnecessary`; invalid declarations simply never got the check.
    #
    # Reported with the verdict actually observed, because "your declaration is wrong" is
    # not actionable and "this site is declared invalid and was KILLED" is.
    contradicted_invalid = contradicted_invalid_declarations(outcomes, DECLARED_INVALID)

    if declared_invalid:
        print("\nINVALID, DECLARED -- no test ran, and the reason is known. NOT kills:")
        for outcome in declared_invalid:
            print(f"  {outcome.mutation.site_id}")
            print(f"      {DECLARED_INVALID[outcome.mutation.site_id]}")

    if undeclared_invalid:
        print("\nINVALID, UNDECLARED -- no test ran and nobody has said why. NOT kills:")
        for outcome in undeclared_invalid:
            print(f"  {outcome.mutation.describe()}")
            print(f"      {outcome.note}")

    if stale_invalid:
        print("\nSTALE INVALID DECLARATIONS -- no generated mutant matches these:")
        for key in stale_invalid:
            print(f"  {key}")

    if contradicted_invalid:
        print("\nCONTRADICTED INVALID DECLARATIONS -- these sites were declared "
              "impossible to evaluate and the run evaluated them:")
        for key, verdict in contradicted_invalid:
            print(f"  {key}")
            print(f"      declared invalid, actually {verdict.upper()}")
            print(f"      declaration says: {DECLARED_INVALID[key]}")

    if timeouts:
        print("\nTIMED OUT:")
        for outcome in timeouts:
            print(f"  {outcome.mutation.describe()}")

    if stale:
        print("\nSTALE EQUIVALENCE DECLARATIONS -- no generated mutant matches these:")
        for key in stale:
            print(f"  {key}")

    if ambiguous:
        print("\nAMBIGUOUS EQUIVALENCE DECLARATIONS -- each matches several sites:")
        for key in ambiguous:
            print(f"  {key}")

    if unnecessary:
        print("\nUNNECESSARY EQUIVALENCE DECLARATIONS -- a test KILLS these, so the "
              "declaration that no test can observe them is false:")
        for key in unnecessary:
            print(f"  {key}")

    if d_stale:
        print("\nSTALE DIAGNOSTIC-ONLY DECLARATIONS -- no generated mutant matches:")
        for key in d_stale:
            print(f"  {key}")

    if d_ambiguous:
        print("\nAMBIGUOUS DIAGNOSTIC-ONLY DECLARATIONS -- each matches several sites:")
        for key in d_ambiguous:
            print(f"  {key}")

    if d_unnecessary:
        print("\nUNNECESSARY DIAGNOSTIC-ONLY DECLARATIONS -- a test KILLS these, so the "
              "claim that the suite does not pin them is false:")
        for key in d_unnecessary:
            print(f"  {key}")

    print("\nsample of kills, with the test that caught each:")
    for outcome in killed[:12]:
        print(f"  {outcome.mutation.describe()}")
        print(f"      killed by {', '.join(outcome.killed_by) or '(unattributed)'}")

    # A FINAL UNMUTATED RUN, after everything. If the tree the workers shared has drifted
    # -- a restore that did not take, a cache that outlived its mutant -- every number
    # above was measured against something other than this repository.
    print("\nre-running the unmutated suite in a fresh workspace...")
    after, why = _check_baseline()
    if after is None or after.collected != baseline.collected:
        print("\nGATE FAILED: the tree does not return to its baseline.\n")
        print(why or f"collected {after.collected} now, {baseline.collected} before")
        return 2
    print(f"clean: {after.collected} tests collected and green")

    if args.json:
        # AN EMPTY DOCUMENT MUST NOT BE A CLEAN COMPARISON.
        #
        # `diff` over two empty files reports agreement, so a run that measured nothing
        # would prove per-site identity between two nothings. Every way this can produce
        # no outcomes -- a crashed pool, an --only that matched no file, a generator that
        # emitted no mutations -- has to fail loudly here rather than serialise `[]`.
        # This exact shape has already produced one false pass on this programme.
        if not outcomes:
            print("\nGATE FAILED: --json was asked for a per-site record set and there "
                  "are no outcomes. An empty document would diff clean against another "
                  "empty document, which is not evidence of agreement.")
            return 2
        if len(outcomes) != len(mutations):
            print(f"\nGATE FAILED: {len(outcomes)} outcomes for {len(mutations)} "
                  f"generated mutations. A record set that does not cover every "
                  f"generated site cannot prove per-site agreement.")
            return 2
        json.dump(as_records(outcomes), real_stdout, indent=2, sort_keys=True)
        real_stdout.write("\n")

    problems = []
    if unexplained:
        problems.append(f"{len(unexplained)} unexplained survivor(s)")
    if stale:
        problems.append(f"{len(stale)} stale declaration(s)")
    if ambiguous:
        problems.append(f"{len(ambiguous)} ambiguous declaration(s)")
    if unnecessary:
        problems.append(f"{len(unnecessary)} unnecessary declaration(s)")
    if undeclared_invalid:
        problems.append(f"{len(undeclared_invalid)} undeclared invalid mutant(s)")
    if stale_invalid:
        problems.append(f"{len(stale_invalid)} stale invalid declaration(s)")
    if contradicted_invalid:
        problems.append(
            f"{len(contradicted_invalid)} contradicted invalid declaration(s)")
    if d_stale:
        problems.append(f"{len(d_stale)} stale diagnostic-only declaration(s)")
    if d_ambiguous:
        problems.append(f"{len(d_ambiguous)} ambiguous diagnostic-only declaration(s)")
    if d_unnecessary:
        problems.append(f"{len(d_unnecessary)} unnecessary diagnostic-only declaration(s)")
    if timeouts:
        problems.append(f"{len(timeouts)} timeout(s)")
    if problems:
        print(f"\nGATE FAILED: {', '.join(problems)}")
        return 1
    # THE WORDING IS THE MEASUREMENT.
    #
    # This used to read "every generated mutant compiled, ran the same test universe, and
    # was either killed by a failing test or declared unreachable" -- and printed it on a
    # run where two mutants did not compile the package at all and six changed observable
    # output. A summary sentence that is false for eight of the mutants it summarises is
    # the same defect as a wrong count, wearing prose.
    #
    # Five outcomes, named, with nothing folded into "killed".
    print(
        "\nGATE PASSED. Every generated mutant was either:\n"
        "  - behaviourally evaluated,\n"
        "  - explicitly declared diagnostic-only,\n"
        "  - proven equivalent,\n"
        "  - or explicitly declared invalid for a named structural reason.\n"
        "No unexplained survivor, undeclared invalid, stale declaration, ambiguous "
        "declaration or timeout remains."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
