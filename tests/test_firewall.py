"""The naming firewall, proven rather than assumed.

WHY THIS FILE EXISTS
--------------------
A prohibited name reached two commits of this repository. `scan_history.sh` caught it;
the pre-commit hook did not, and the miss was never reproduced.

That is the worst failure available to a safety gate. Not missing a leak -- reporting
coverage it does not have, so nobody looks again. Every claim below was previously made
in prose in a shell script's header comment, which is exactly the form of evidence this
repository refuses everywhere else.

TWO DEFECTS THE MATCHERS HAD
----------------------------
The hook matched with `grep -iE` while the authoritative scanner matched with `grep -iaF`.
One dictionary, two matchers, disagreeing in both directions:

    as a regex, `acme-corp.io` matches `acme-corpXio`       -- a false positive
    as a regex, a term containing `+` is an invalid pattern -- and MISSES a real leak

The second is the dangerous one, and it is the one a reader would never guess. Both are
demonstrated below against the shared matcher, so the regression is a fact rather than a
comment.

WHAT THESE TESTS USE FOR A DICTIONARY
-------------------------------------
A synthetic term list written per-test into a temp file and pointed at with
`CAI_FIREWALL_LIST`. Never the real dictionary: it lives outside the repository precisely
so that committing an opportunity-specific term list cannot leak the opportunity through
the history it guards, and a test that embedded real terms would do exactly that.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOKS = REPO / ".githooks"
SYNTHETIC_TERMS = ["acme-corp.io", "c++", "Ordinary-Name"]


@pytest.fixture()
def term_list(tmp_path):
    listing = tmp_path / "terms.txt"
    listing.write_text("# a synthetic dictionary, never the real one\n"
                       + "\n".join(SYNTHETIC_TERMS) + "\n")
    return listing


def match(text: str, term_list: pathlib.Path) -> list[str]:
    """Run the shared matcher over `text` and return the terms it found."""
    script = f'source "{HOOKS}/firewall_match.sh"; firewall_matches_in'
    done = subprocess.run(["bash", "-c", script], input=text, capture_output=True,
                          text=True, env={"CAI_FIREWALL_LIST": str(term_list),
                                          "PATH": "/usr/bin:/bin:/usr/local/bin"})
    return [line for line in done.stdout.splitlines() if line]


# ===========================================================================
# THE MATCHER ITSELF.
# ===========================================================================


def test_the_matcher_finds_a_term_however_it_is_capitalised(term_list):
    assert match("a line mentioning ORDINARY-NAME here", term_list) == ["Ordinary-Name"]
    assert match("a line mentioning ordinary-name here", term_list) == ["Ordinary-Name"]


def test_the_matcher_does_not_treat_a_dot_as_a_wildcard(term_list):
    """The false-positive direction. As a regex, `acme-corp.io` matches `acme-corpXio`;
    the dictionary holds names, not patterns."""
    assert match("a leak in acme-corpXio here", term_list) == []
    assert match("a leak in acme-corp.io here", term_list) == ["acme-corp.io"]


def test_the_matcher_finds_a_term_containing_regex_metacharacters(term_list):
    """THE DANGEROUS DIRECTION, and the one nobody would guess.

    `c++` is not a valid extended regex -- the old hook's `grep -iE` would error on it and
    match NOTHING, so a real prohibited term passed silently while the hook reported a
    clean commit. A filter more permissive than the gate behind it is worse than no
    filter, because it teaches the author that a clean commit means a clean history.
    """
    assert match("a mention of c++ in passing", term_list) == ["c++"]


def test_the_matcher_reports_every_term_present_not_merely_the_first(term_list):
    found = match("acme-corp.io and c++ and Ordinary-Name walk into a bar", term_list)
    assert sorted(found) == sorted(SYNTHETIC_TERMS)


def test_clean_text_matches_nothing(term_list):
    """The twin. A matcher that flagged everything would pass every test above."""
    assert match("an entirely unremarkable line about forklifts", term_list) == []


def test_the_matcher_fails_closed_when_the_dictionary_is_missing(tmp_path):
    """A matcher that silently passes because it could not find its policy input is the
    exact failure this apparatus exists to prevent."""
    script = f'source "{HOOKS}/firewall_match.sh"; firewall_require_list'
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={"CAI_FIREWALL_LIST": str(tmp_path / "absent.txt"),
                               "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert done.returncode == 1
    assert "fail-closed" in done.stderr


# ===========================================================================
# THE HOOKS, IN A REAL THROWAWAY REPOSITORY.
# ===========================================================================


def commit_in(repo: pathlib.Path, term_list: pathlib.Path, *, content: str,
              message: str) -> subprocess.CompletedProcess:
    """Stage `content` and attempt a commit with `message`, hooks armed."""
    (repo / "note.md").write_text(content)
    env = {"CAI_FIREWALL_LIST": str(term_list), "PATH": "/usr/bin:/bin:/usr/local/bin",
           "HOME": str(repo), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "add", "note.md"], cwd=repo, env=env, check=True,
                   capture_output=True)
    return subprocess.run(["git", "commit", "-m", message], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.fixture()
def throwaway_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "config", "core.hooksPath", str(HOOKS)], cwd=repo, env=env,
                   check=True)
    return repo


def test_the_hook_blocks_a_prohibited_term_in_staged_content(throwaway_repo, term_list):
    done = commit_in(throwaway_repo, term_list,
                     content="a line naming Ordinary-Name\n", message="an honest message")

    assert done.returncode != 0, "the commit must not succeed"
    assert "staged content contains prohibited term: Ordinary-Name" in done.stderr


def test_the_hook_blocks_a_prohibited_term_in_the_commit_message(throwaway_repo,
                                                                term_list):
    """The half that did not exist. Staged content was checked and the message was not,
    so a prohibited term written into a message entered history unopposed and was first
    discovered by a full-history scan -- after the fact."""
    done = commit_in(throwaway_repo, term_list,
                     content="an entirely clean line\n",
                     message="a message naming Ordinary-Name")

    assert done.returncode != 0, "the commit must not succeed"
    assert "commit message contains prohibited term: Ordinary-Name" in done.stderr


def test_the_hook_blocks_a_term_containing_regex_metacharacters(throwaway_repo,
                                                                term_list):
    """End to end, the case the old regex hook let through."""
    done = commit_in(throwaway_repo, term_list, content="mentions c++ here\n",
                     message="an honest message")

    assert done.returncode != 0
    assert "c++" in done.stderr


def test_a_clean_commit_still_succeeds(throwaway_repo, term_list):
    """The twin, and the one that matters most operationally: a firewall that blocks
    every commit gets disabled within a day."""
    done = commit_in(throwaway_repo, term_list, content="forklift telemetry notes\n",
                     message="record the yard reading")

    assert done.returncode == 0, done.stderr

# ===========================================================================
# A STAGED BINARY BLOB. THE GAP BOTH STAGED-CONTENT GATES HAD.
#
# The hook and the scanner's index pass both read `git diff --cached -U0`, which is a
# RENDERING of a change rather than the change itself. Git renders a staged binary as
#
#     Binary files a/report.pdf and b/report.pdf differ
#
# so the prohibited bytes inside the blob are not in the text either gate searched. A
# binary staged file naming the opportunity committed clean through both.
#
# The tests below stage a real binary blob whose bytes carry a synthetic term, and put
# DIFFERENT, clean bytes in the working tree at the same path -- because a gate that
# read the working tree instead of the index would otherwise pass this by accident and
# prove nothing about which of the two it looked at.
# ===========================================================================


BINARY_PREFIX = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
"""A PNG signature and a NUL, which is what makes git classify the blob as binary."""


def stage_binary(repo: pathlib.Path, term_list: pathlib.Path, *, staged: bytes,
                 worktree: bytes) -> dict:
    """Put `staged` in the index at report.png and `worktree` on disk at the same path.

    The divergence is the point. If a gate reports clean here, it either read the
    working tree or read a patch -- and the test can tell which, because neither
    contains the staged bytes.
    """
    env = {"CAI_FIREWALL_LIST": str(term_list), "PATH": "/usr/bin:/bin:/usr/local/bin",
           "HOME": str(repo), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    target = repo / "report.png"
    target.write_bytes(staged)
    subprocess.run(["git", "add", "report.png"], cwd=repo, env=env, check=True,
                   capture_output=True)
    target.write_bytes(worktree)
    return env


def test_git_really_does_hide_the_staged_bytes_in_the_patch(throwaway_repo, term_list):
    """The premise, asserted rather than assumed.

    Every test below is worthless if git happens to include binary content in
    `--cached -U0` on this platform. It does not, and this fixes that in place -- so a
    future reader can see the gap was real and not a story about it.
    """
    env = stage_binary(throwaway_repo, term_list,
                       staged=BINARY_PREFIX + b"Ordinary-Name\x00trailing",
                       worktree=BINARY_PREFIX + b"entirely clean\x00trailing")
    patch = subprocess.run(["git", "diff", "--cached", "-U0"], cwd=throwaway_repo,
                           env=env, capture_output=True).stdout

    assert b"Ordinary-Name" not in patch, (
        "the premise of this whole section does not hold on this platform"
    )
    assert b"Binary files" in patch


def test_the_hook_blocks_a_prohibited_term_inside_a_staged_binary(throwaway_repo,
                                                                  term_list):
    env = stage_binary(throwaway_repo, term_list,
                       staged=BINARY_PREFIX + b"Ordinary-Name\x00trailing",
                       worktree=BINARY_PREFIX + b"entirely clean\x00trailing")
    done = subprocess.run(["git", "commit", "-m", "an honest message"],
                          cwd=throwaway_repo, env=env, capture_output=True, text=True)

    assert done.returncode != 0, "a staged binary carrying a prohibited term committed"
    assert "Ordinary-Name" in done.stderr


def test_the_scanner_index_pass_blocks_a_staged_binary(throwaway_repo, term_list):
    """The authoritative gate's own index pass, which had the same defect."""
    env = stage_binary(throwaway_repo, term_list,
                       staged=BINARY_PREFIX + b"Ordinary-Name\x00trailing",
                       worktree=BINARY_PREFIX + b"entirely clean\x00trailing")
    done = subprocess.run(["bash", str(REPO / "scan_history.sh")], cwd=throwaway_repo,
                          env=env, capture_output=True, text=True)

    assert done.returncode != 0, done.stdout
    assert "staged:" in done.stdout, "the index pass is not the pass that caught it"
    assert "Ordinary-Name" in done.stdout


def test_the_history_pass_blocks_a_committed_binary_blob(throwaway_repo, term_list):
    """Once it is in, it is in. Committed with the hook bypassed, exactly as a leak that
    got past a commit-time filter would be."""
    env = stage_binary(throwaway_repo, term_list,
                       staged=BINARY_PREFIX + b"Ordinary-Name\x00trailing",
                       worktree=BINARY_PREFIX + b"Ordinary-Name\x00trailing")
    subprocess.run(["git", "commit", "--no-verify", "-m", "clean message"],
                   cwd=throwaway_repo, env=env, check=True, capture_output=True)

    done = subprocess.run(["bash", str(REPO / "scan_history.sh")], cwd=throwaway_repo,
                          env=env, capture_output=True, text=True)

    assert done.returncode != 0, done.stdout
    assert "history:" in done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_clean_binary_twin_commits_and_scans_clean(throwaway_repo, term_list):
    """The twin, and it carries real weight here: a gate that refused every binary would
    pass all four tests above and be useless. Same shape, same NUL bytes, no term."""
    env = stage_binary(throwaway_repo, term_list,
                       staged=BINARY_PREFIX + b"forklift telemetry\x00trailing",
                       worktree=BINARY_PREFIX + b"forklift telemetry\x00trailing")
    committed = subprocess.run(["git", "commit", "-m", "add the yard chart"],
                               cwd=throwaway_repo, env=env, capture_output=True,
                               text=True)

    assert committed.returncode == 0, committed.stderr

    scanned = subprocess.run(["bash", str(REPO / "scan_history.sh")], cwd=throwaway_repo,
                             env=env, capture_output=True, text=True)
    assert scanned.returncode == 0, scanned.stdout


def test_a_prohibited_term_in_a_staged_FILENAME_is_blocked(throwaway_repo, term_list):
    """A name in a path is as public as a name in a line, and neither gate looked at
    paths at all -- the patch's `+++ b/...` header carries it, but only for text files
    and only by accident."""
    env = {"CAI_FIREWALL_LIST": str(term_list), "PATH": "/usr/bin:/bin:/usr/local/bin",
           "HOME": str(throwaway_repo), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    (throwaway_repo / "Ordinary-Name.png").write_bytes(BINARY_PREFIX + b"clean\x00")
    subprocess.run(["git", "add", "Ordinary-Name.png"], cwd=throwaway_repo, env=env,
                   check=True, capture_output=True)

    done = subprocess.run(["git", "commit", "-m", "an honest message"],
                          cwd=throwaway_repo, env=env, capture_output=True, text=True)

    assert done.returncode != 0
    assert "Ordinary-Name" in done.stderr


def test_there_is_genuinely_one_matcher_now(throwaway_repo, term_list):
    """STRUCTURAL, and stronger than the test it replaces.

    The old version asserted that no gate still used `grep -iE`. That is a statement
    about one obsolete flag, not about there being one matcher -- and it passed the
    whole time scan_history.sh was running seven `grep -iaF` calls of its own.

    This asserts the actual property: outside firewall_match.sh, no gate invokes grep
    with matching flags of its own. They call `firewall_grep`, `firewall_git_grep` or
    `firewall_matches_in`, or they expand FIREWALL_GREP_OPTS.
    """
    shared = (HOOKS / "firewall_match.sh").read_text()
    assert "FIREWALL_GREP_OPTS=(-i -a -F)" in shared

    for gate in (HOOKS / "pre-commit", HOOKS / "commit-msg", REPO / "scan_history.sh"):
        code = "\n".join(
            line for line in gate.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "firewall_match.sh" in gate.read_text(), gate.name
        for offending in ("grep -iE", "grep -iaF", "grep -iaFq", "grep -iaFl",
                          "grep -iIE", "git grep -iaF"):
            assert offending not in code, (
                f"{gate.name} still matches with its own flags: {offending}"
            )
        # And every grep it does run must take the shared options.
        for line in code.splitlines():
            if "grep" in line and "firewall_grep" not in line \
                    and "firewall_git_grep" not in line \
                    and "firewall_matches_in" not in line:
                assert "FIREWALL_GREP_OPTS" in line, (
                    f"{gate.name} greps without the shared options: {line.strip()}"
                )


def test_no_staged_content_gate_reads_a_patch_any_more():
    """The other half. `git diff --cached -U0` is the construct that hid the binary, so
    no gate may use it as a content source."""
    for gate in (HOOKS / "pre-commit", REPO / "scan_history.sh"):
        code = "\n".join(
            line for line in gate.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "diff --cached -U0" not in code, (
            f"{gate.name} still searches patch text for staged content"
        )
        assert "firewall_staged_content" in code, (
            f"{gate.name} does not read the index"
        )


# ===========================================================================
# PATH NAMES ARE PUBLIC CONTENT TOO.
# ===========================================================================
#
# The binary passes closed the content half: what is INSIDE a blob is scanned wherever
# that blob lives. The path half was left in three places at once.
#
#   the staged pass filtered `--diff-filter=ACM`, so a RENAME onto a prohibited name
#   was neither an Add nor a Modify and was simply not listed;
#
#   the history pass searched committed blob CONTENTS -- `git grep <term> $(rev-list)`
#   never looks at a tree entry -- so a file named Customer-X/private/report.pdf with
#   entirely clean bytes survived the full-history scan, and renaming it clean in a
#   later commit did not remove it from history;
#
#   the untracked and tracked passes grep'd file CONTENT and never the names of the
#   files they were grepping.
#
# A public repository shows its tree. A name in a path is exactly as visible as a name
# in a line, and it is visible without opening anything.


def firewall_env(repo: pathlib.Path, term_list: pathlib.Path) -> dict:
    return {"CAI_FIREWALL_LIST": str(term_list), "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}


def git(repo: pathlib.Path, env: dict, *args: str, check: bool = True):
    return subprocess.run(["git", *args], cwd=repo, env=env, check=check,
                          capture_output=True, text=True)


def scan(repo: pathlib.Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(REPO / "scan_history.sh")], cwd=repo, env=env,
                          capture_output=True, text=True)


def seed(repo: pathlib.Path, env: dict, name: str = "clean.txt") -> None:
    """One clean commit, so the repository has a history to rename within."""
    (repo / name).write_text("forklift telemetry\n")
    git(repo, env, "add", name)
    git(repo, env, "commit", "--no-verify", "-m", "seed")


def test_a_staged_addition_with_a_prohibited_name_and_clean_bytes_is_blocked(
    throwaway_repo, term_list
):
    """CASE 1. The baseline the other path cases are measured against."""
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "Ordinary-Name.md").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "Ordinary-Name.md")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_staged_RENAME_onto_a_prohibited_name_is_blocked(throwaway_repo, term_list):
    """CASE 2. THE DEFECT. `--diff-filter=ACM` has no R in it.

    A rename is not an Add and not a Modify. The blob is unchanged and already committed,
    so the content passes have nothing new to find, and the staged path pass never listed
    the file. The one operation that gives an existing clean file a prohibited name was
    the one the filter excluded.
    """
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)
    git(throwaway_repo, env, "mv", "clean.txt", "Ordinary-Name.txt")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_staged_COPY_onto_a_prohibited_name_is_blocked(throwaway_repo, term_list):
    """CASE 3. Whether git reports it as a copy or as an add depends on detection
    settings, which is exactly why the filter should not be enumerating the operations
    it happens to have thought of."""
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)
    (throwaway_repo / "Ordinary-Name.txt").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "Ordinary-Name.txt")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_prohibited_name_committed_then_renamed_clean_is_still_found(
    throwaway_repo, term_list
):
    """CASE 4. THE SECOND DEFECT, and the one that matters most for publication.

    Commit the file under a prohibited name with the hook bypassed -- exactly what a leak
    that got past a commit-time filter looks like -- then rename it to something innocent
    and commit that. HEAD is clean. Every blob is clean. The name is still in the tree of
    the first commit, and a public repository shows every tree.

    `git grep <term> $(git rev-list --all)` searches blob CONTENTS. It never reads a tree
    entry, so the full-history pass could not see this and reported PASS.
    """
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "Ordinary-Name.md").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "Ordinary-Name.md")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")
    git(throwaway_repo, env, "mv", "Ordinary-Name.md", "innocuous.md")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "rename")

    # The working tree and the index are both clean now, so nothing but the history pass
    # can catch this.
    assert not (throwaway_repo / "Ordinary-Name.md").exists()

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout
    assert "paths:" in done.stdout, (
        "the historical PATH pass must be the one that caught it; a content pass finding "
        "this would mean the test is not exercising what it names"
    )


def test_an_untracked_file_with_a_prohibited_name_and_clean_bytes_is_blocked(
    throwaway_repo, term_list
):
    """CASE 7. Untracked content was scanned and untracked names were not.

    An untracked file is one `git add -A` from being staged, and its name is on the
    author's disk in a directory the scanner claims to cover.
    """
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)
    (throwaway_repo / "Ordinary-Name.png").write_bytes(b"\x89PNG\r\n\x1a\nclean\x00")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_tracked_working_tree_file_with_a_prohibited_name_is_blocked(
    throwaway_repo, term_list
):
    """CASE 7's tracked twin. `git ls-files` was used to enumerate paths to grep INSIDE,
    and the names in that same list were never matched."""
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "Ordinary-Name.md").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "Ordinary-Name.md")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "Ordinary-Name" in done.stdout


def test_a_historical_binary_with_a_clean_name_and_prohibited_bytes_is_blocked(
    throwaway_repo, term_list
):
    """CASE 5. The content half, asserted beside the path half so a fix to one that
    broke the other cannot pass."""
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "chart.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"Ordinary-Name\x00trailing")
    git(throwaway_repo, env, "add", "chart.png")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "history:" in done.stdout


def test_every_clean_twin_passes_all_ten_passes(throwaway_repo, term_list):
    """CASE 8. THE TWIN THAT CARRIES THE MOST WEIGHT IN THIS FILE.

    A firewall that refused everything would pass all seven tests above and be worthless.
    This builds the same repository shapes with innocent names and innocent bytes --
    committed history, a rename, a tracked file, an untracked binary, a staged addition --
    and requires a clean PASS.
    """
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "yard-chart.md").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "yard-chart.md")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")
    git(throwaway_repo, env, "mv", "yard-chart.md", "loading-window.md")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "rename")
    (throwaway_repo / "battery-pack.png").write_bytes(b"\x89PNG\r\n\x1a\nclean\x00")
    (throwaway_repo / "staged-note.md").write_text("degradation signal\n")
    git(throwaway_repo, env, "add", "staged-note.md")

    done = scan(throwaway_repo, env)

    assert done.returncode == 0, done.stdout
    assert "RESULT: PASS" in done.stdout


def test_the_scanner_states_the_passes_it_actually_runs():
    """The failure this whole file exists for: a banner promising coverage the script
    does not have. Every pass named in the header must be a pass in the body."""
    body = (REPO / "scan_history.sh").read_text()

    for claim in ("historical path", "staged path", "untracked path", "tracked path"):
        assert claim in body.lower(), f"the scanner does not mention {claim!r}"
    assert "--diff-filter=ACM " not in body and "--diff-filter=ACM\n" not in body, (
        "ACM excludes renames and copies"
    )


# ===========================================================================
# A PATH WITH A SPACE IN IT. THE SHELL WAS RE-SPLITTING THE FILENAMES.
# ===========================================================================
#
# The tracked-content pass transported its file list as `-- $(git ls-files)`. Unquoted
# command substitution word-splits on IFS, so `quarterly report.pdf` reached git as
# `quarterly` and `report.pdf` -- two paths that do not exist. git grep found nothing in
# either, the pass printed nothing, and the banner went on listing "tracked file contents
# in the working tree" as one of ten passes performed.
#
# That is this script's original sin repeated one layer in: not a missed leak, but
# CLAIMED COVERAGE THAT DOES NOT EXIST, so nobody looks again. And the filename shape that
# triggers it is the shape most likely to carry a prohibited name -- a document, named the
# way a person names a document.
#
# Every case below fails towards "clean" under the old code.

SPACED = "ordinary file.txt"


def test_1_tracked_worktree_content_is_scanned_when_the_filename_has_spaces(
    throwaway_repo, term_list
):
    """(1) THE NAMED DEFECT, isolated so only pass 5 can catch it.

    Committed clean, so the history pass has nothing. Filename itself is clean, so the
    path passes have nothing. Dirtied in the WORKING TREE and left unstaged, so the index
    pass has nothing. The only pass that can see this is tracked working-tree content --
    which is the pass the word-splitting silently disabled.
    """
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / SPACED).write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", SPACED)
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")

    (throwaway_repo / SPACED).write_text("please contact acme-corp.io today\n")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, f"the leak was not caught at all:\n{done.stdout}"
    assert "worktree:" in done.stdout, (
        "caught, but NOT by the tracked working-tree content pass -- pass 5 is still "
        f"blind to a filename with a space in it:\n{done.stdout}"
    )
    assert "acme-corp.io" in done.stdout


def test_2_a_clean_twin_with_the_same_spaced_filename_still_passes(
    throwaway_repo, term_list
):
    """(2) The twin, and it carries the weight here.

    A scanner that refused every filename containing a space would satisfy case 1 and be
    worthless. Same name, same shape, no term.
    """
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / SPACED).write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", SPACED)
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")

    (throwaway_repo / SPACED).write_text("yard maintenance notes for the morning\n")

    done = scan(throwaway_repo, env)

    assert done.returncode == 0, done.stdout
    assert "RESULT: PASS" in done.stdout


def test_3_untracked_content_is_scanned_when_the_filename_has_spaces(
    throwaway_repo, term_list
):
    """(3) The untracked pass reached xargs through NUL already, but built its list with
    newline-delimited `git ls-files --others` and translated afterwards -- so git had
    already C-quoted anything awkward on the way out."""
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)
    (throwaway_repo / "untracked draft notes.md").write_text("acme-corp.io\n")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "untracked:" in done.stdout, done.stdout


def test_4_staged_content_is_scanned_when_the_filename_has_spaces(
    throwaway_repo, term_list
):
    """(4) Staged, not committed. Read from the index rather than from a patch."""
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)
    (throwaway_repo / "staged draft notes.md").write_text("acme-corp.io\n")
    git(throwaway_repo, env, "add", "staged draft notes.md")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, done.stdout
    assert "staged:" in done.stdout, done.stdout


def test_5_a_rename_to_a_prohibited_filename_with_spaces_is_blocked(
    throwaway_repo, term_list
):
    """(5) The blob never changes, so every content pass has nothing new to find. The
    entire effect of the operation is to give an existing file a new name -- and the name
    now contains both a prohibited term and a space."""
    env = firewall_env(throwaway_repo, term_list)
    seed(throwaway_repo, env)

    git(throwaway_repo, env, "mv", "clean.txt", "Ordinary-Name report.txt")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, f"a staged rename to a prohibited name passed:\n{done.stdout}"
    assert "Ordinary-Name" in done.stdout


def test_6_a_historical_prohibited_pathname_with_spaces_survives_a_clean_rename(
    throwaway_repo, term_list
):
    """(6) And the `-z` change must not have weakened the historical path pass.

    Committed under a prohibited name containing a space, then renamed clean. HEAD is
    spotless and every blob is spotless; the name exists only in an earlier tree, where a
    public repository shows it forever.
    """
    env = firewall_env(throwaway_repo, term_list)
    (throwaway_repo / "Ordinary-Name report.txt").write_text("forklift telemetry\n")
    git(throwaway_repo, env, "add", "Ordinary-Name report.txt")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "seed")

    git(throwaway_repo, env, "mv", "Ordinary-Name report.txt", "clean.txt")
    git(throwaway_repo, env, "commit", "--no-verify", "-m", "rename")

    done = scan(throwaway_repo, env)

    assert done.returncode != 0, f"the historical name was lost:\n{done.stdout}"
    assert "paths:" in done.stdout, (
        f"caught, but not by the historical path pass:\n{done.stdout}"
    )
    assert "Ordinary-Name" in done.stdout


def test_no_filename_is_transported_through_command_substitution():
    """The structural half. `$(git ls-files)` is the defect; its absence is the fix.

    Written against the text because the failure is a shell-quoting one and there is
    nothing to introspect at runtime: by the time the script is running, a split filename
    is indistinguishable from a filename that was never there.
    """
    source = (REPO / "scan_history.sh").read_text()
    # COMMENTS STRIPPED FIRST. The prose above the code quotes the defective line in order
    # to explain it, so asserting over the whole file matched the explanation and would
    # have stayed red for correct code -- and gone green for any rewrite that dropped the
    # explanation. Assert on what executes.
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))

    assert "$(git ls-files)" not in code, "a filename is being word-split again"
    assert "xargs -0" in code, "the file list is not NUL-delimited on the way to grep"
    assert "read -r -d ''" in code, "the file list is not read as NUL-delimited values"
    # `tr '\n' '\0'` means a newline-delimited git list was trusted to contain no
    # newlines, which is the assumption `-z` exists to remove.
    assert "tr '\\n' '\\0'" not in code, (
        "a newline-delimited path list is still being converted after the fact"
    )
