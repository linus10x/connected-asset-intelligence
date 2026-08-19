#!/usr/bin/env bash
# Full-history firewall scan, required before any public flip.
#
# A public repository exposes EVERY commit, so removing a term from HEAD is not
# sufficient -- it must never have appeared at all. This was verified rather than
# assumed: a deliberate leak committed and then deleted from HEAD is still caught.
#
# The term list lives OUTSIDE this repo on purpose. Committing an opportunity-specific
# dictionary here would leak the very thing it protects, through this same history.
#
# WHAT THIS USED TO CLAIM, AND WHY IT WAS WRONG
# ---------------------------------------------
# The banner said it scanned "all blobs in all commits, all commit messages, all refs,
# working tree". The content scan was `git grep -iIE <term> $(git rev-list --all)`, which
# covers committed blobs and nothing else -- an uncommitted or untracked file containing a
# prohibited term passed silently while the script printed a line promising otherwise. An
# audit caught it. That is the worst failure available to a safety gate: not missing a
# leak, but reporting coverage it does not have, so nobody looks again.
#
# Three fixes:
#   -F rather than -E   terms are literals. A dictionary entry containing . or - or +
#                       was being interpreted as a pattern, so what it matched was not
#                       what it said.
#   -a rather than -I   binary blobs are searched instead of skipped. A term inside a
#                       PDF or an Office file is exactly as public as one in a README.
#   explicit passes     tracked working tree, untracked files, and the index, each run
#                       separately rather than assumed to be covered by the history pass.
#   one matcher       the hook and this scanner now SHARE firewall_match.sh. They used to
#                     hold their own copies -- `grep -iE` here, `grep -iaF` there -- and a
#                     term containing `+` was an invalid pattern that silently matched
#                     nothing. Agreeing to keep two matchers in step is a promise somebody
#                     keeps by hand; sharing the implementation leaves nothing to drift.
#
# TWO THINGS THAT WERE STILL WRONG AFTER ALL THAT
# ------------------------------------------------
# SOURCING IS NOT SHARING. This file sourced firewall_match.sh and then ran seven
# `grep -iaF` invocations of its own, so "one matcher" was true of the dictionary and
# not of the matching. The structural test that guarded it only checked that nobody
# used `grep -iE` any more -- a weaker claim than the one being made. The flags now
# live in `FIREWALL_GREP_OPTS` and every pass below goes through `firewall_grep` or
# `firewall_git_grep`. Transports still differ, because a pipe and the object database
# genuinely are different mechanisms; the semantics are in one array.
#
# THE INDEX PASS SEARCHED A PATCH. `git diff --cached -U0` renders a staged binary as
# "Binary files a/x and b/x differ" -- the prohibited bytes inside the blob are simply
# not in the text this pass searched, so a staged PDF walked past it. Patch text also
# omits the unchanged bytes of a modified file. `firewall_staged_content` reads the
# actual indexed blob with `git show :path`, and emits the staged PATHS as well: a
# filename carries a name as publicly as a line inside the file does.
#
# AND A THIRD: THE SHELL WAS RE-SPLITTING THE FILENAMES.
#
# The tracked-content pass transported its file list as `-- $(git ls-files)`. Unquoted
# command substitution word-splits on IFS, so a tracked file called
#
#     quarterly report.pdf
#
# arrived as two arguments, `quarterly` and `report.pdf`. Neither exists. The pass found
# nothing, printed nothing, and pass 5 of the ten listed below went on claiming that
# tracked working-tree content had been scanned -- the same class of untrue banner this
# script was already rewritten once to fix, one layer further in.
#
# The shape of file that triggers it is the shape most likely to carry a prohibited name:
# a document, named the way a person names a document. And it fails towards "clean".
#
# Every path now leaves git under `-z` and is read as a NUL-delimited value, NUL being the
# only byte a path cannot contain. No filename passes through command substitution, and no
# `-z` form is parsed as newline-delimited text where opening the file is the point.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.githooks/firewall_match.sh
source "$HERE/.githooks/firewall_match.sh"
LIST="$(firewall_term_list)"
firewall_require_list || exit 1

commits=$(git rev-list --all --count)
echo "scanning, as literal strings (case-insensitive), including binary content:"
echo "  1. every blob in all $commits commits"
echo "  2. every historical path name in every reachable tree"
echo "  3. every commit message and author/committer field"
echo "  4. every ref name"
echo "  5. tracked file contents in the working tree"
echo "  6. tracked path names in the working tree"
echo "  7. untracked file contents not covered by .gitignore"
echo "  8. untracked path names not covered by .gitignore"
echo "  9. staged blob contents, read from the index"
echo " 10. staged path names, including renames and copies"
echo "repo: $(pwd)"
echo

# Warn rather than fail: an uninstalled hook is a real weakness, but this scanner is the
# authoritative gate and must not be blocked by the state of a convenience.
hooks_path=$(git config core.hooksPath || echo ".git/hooks")
if [[ ! -x "$hooks_path/pre-commit" ]]; then
  echo "NOTE: no executable pre-commit hook at $hooks_path -- commit-time filtering is"
  echo "      not active. This scan is still authoritative; run it before any push."
  echo
fi

# THE THREE PATH INVENTORIES, BUILT ONCE.
#
# The dictionary loop below re-reads each of these for every term, and the historical one
# walks every tree of every reachable commit -- so computing it inside the loop would
# multiply that walk by the size of the dictionary. Nothing here depends on the term, so
# nothing here belongs in the loop.
HISTORICAL_PATHS="$(firewall_historical_paths)"
TRACKED_PATHS="$(firewall_worktree_paths)"
UNTRACKED_PATHS="$(firewall_untracked_paths)"

# THE TWO LISTS OF FILES TO OPEN, READ AS NUL-DELIMITED VALUES.
#
# A path is the one kind of string a shell must never transport through unquoted command
# substitution, and the tracked-content pass did exactly that: `-- $(git ls-files)`. IFS
# split `quarterly report.pdf` into two arguments naming two files that do not exist, so
# the file was never opened and the pass reported clean. The banner above still promised
# that tracked working-tree content had been scanned.
#
# Read into arrays once, here, because nothing about them depends on the term and the
# dictionary loop below runs per term. `read -d ''` consumes to the NUL, which is the only
# byte a path cannot contain, so every name survives whatever else is in it.
TRACKED_FILES=()
while IFS= read -r -d '' path; do TRACKED_FILES+=("$path"); done \
  < <(firewall_tracked_paths_z)
UNTRACKED_FILES=()
while IFS= read -r -d '' path; do UNTRACKED_FILES+=("$path"); done \
  < <(firewall_untracked_paths_z)

fail=0
while IFS= read -r term; do
  [[ -z "$term" || "$term" == \#* ]] && continue

  # 1. committed blobs, binaries included, literal match
  hits=$(firewall_git_grep -- "$term" $(git rev-list --all) 2>/dev/null | head -5)
  # 2. HISTORICAL PATH NAMES. `git grep` over commits searches blob CONTENTS and never
  #    reads a tree entry, so a clean file under a prohibited NAME survived the
  #    full-history pass -- and renaming it clean later did not remove the name from the
  #    earlier tree. A public repository shows every tree, forever.
  histpaths=$(printf '%s\n' "$HISTORICAL_PATHS" | firewall_grep -- "$term" | head -3)
  # 3. messages plus author and committer identity lines
  msgs=$(git log --all --format='%H %s%n%b%n%an %ae%n%cn %ce' 2>/dev/null \
         | firewall_grep -- "$term" | head -3)
  # 4. ref names
  refs=$(git for-each-ref --format='%(refname)' | firewall_grep -- "$term" | head -3)
  # 5. tracked working-tree content as it stands on disk right now. The file list arrives
  #    as NUL-delimited array elements and is handed to grep the same way; no filename is
  #    ever re-split by the shell between git and the read.
  tracked=""
  if (( ${#TRACKED_FILES[@]} )); then
    tracked=$(printf '%s\0' "${TRACKED_FILES[@]}" \
              | xargs -0 grep "${FIREWALL_GREP_OPTS[@]}" -l -- "$term" \
                2>/dev/null | head -3)
  fi
  # 6. tracked PATH NAMES. This same list was already being built, and used only as a set
  #    of addresses to grep inside.
  trackedpaths=$(printf '%s\n' "$TRACKED_PATHS" | firewall_grep -- "$term" | head -3)
  # 7. untracked and not ignored -- the gap that made the old banner a lie.
  #    This one already reached xargs through NUL, but it built the list with
  #    `git ls-files --others` and then `tr '\n' '\0'`: git had already C-quoted any
  #    awkward name on the way out, and a name containing a newline was cut in half by the
  #    translation. `-z` from git means neither conversion has to be trusted.
  untracked=""
  if (( ${#UNTRACKED_FILES[@]} )); then
    untracked=$(printf '%s\0' "${UNTRACKED_FILES[@]}" \
                | xargs -0 grep "${FIREWALL_GREP_OPTS[@]}" -l -- "$term" \
                  2>/dev/null | head -3)
  fi
  # 8. untracked PATH NAMES, for the same reason as 6. An untracked file is one
  #    `git add -A` away from being staged.
  untrackedpaths=$(printf '%s\n' "$UNTRACKED_PATHS" | firewall_grep -- "$term" | head -3)
  # 9/10. staged content AND staged paths, which are neither HEAD nor the working tree --
  #    read from the INDEX, not from a patch. A staged binary appears in a patch only as
  #    a "Binary files differ" marker, so this pass used to see none of its bytes; and
  #    `--diff-filter=ACM` listed no path at all for a staged RENAME, which is the one
  #    operation whose whole effect is to give a file a new name.
  staged=$(firewall_staged_content | firewall_grep -- "$term" | head -3)

  if [[ -n "$hits$histpaths$msgs$refs$tracked$trackedpaths$untracked$untrackedpaths$staged" ]]; then
    echo "VIOLATION [$term]"
    [[ -n "$hits"           ]] && echo "  history:         $(echo "$hits" | head -2)"
    [[ -n "$histpaths"      ]] && echo "  paths:           $(echo "$histpaths" | head -2)"
    [[ -n "$msgs"           ]] && echo "  messages:        $(echo "$msgs" | head -2)"
    [[ -n "$refs"           ]] && echo "  refs:            $refs"
    [[ -n "$tracked"        ]] && echo "  worktree:        $(echo "$tracked" | head -2)"
    [[ -n "$trackedpaths"   ]] && echo "  tracked paths:   $trackedpaths"
    [[ -n "$untracked"      ]] && echo "  untracked:       $untracked"
    [[ -n "$untrackedpaths" ]] && echo "  untracked paths: $untrackedpaths"
    [[ -n "$staged"         ]] && echo "  staged:          $(echo "$staged" | head -2)"
    fail=1
  fi
done < "$LIST"

echo
if [[ $fail -eq 1 ]]; then
  echo "RESULT: FAIL -- prohibited terms present. NOT publishable."
  exit 1
fi
echo "RESULT: PASS -- clean across all ten passes listed above."
echo "Necessary, not sufficient: a human read is still required before publication."
