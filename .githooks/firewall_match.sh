#!/usr/bin/env bash
# The ONE prohibited-term matcher. Sourced by every gate that needs one.
#
# WHY THIS FILE EXISTS
# --------------------
# The commit-time hook matched with `grep -iE` while the authoritative scanner matched
# with `grep -iaF`. One dictionary, two matchers, and they disagree in BOTH directions:
#
#   as a regex, `acme-corp.io` matches `acme-corpXio`      -- a false positive
#   as a regex, a term containing `+` is an invalid pattern -- and MISSES a real leak
#
# The second is the dangerous one. A commit-time filter more permissive than the gate
# behind it teaches the author that a clean commit means a clean history.
#
# WHY IT WAS NOT YET TRUE THAT THERE IS ONE MATCHER
# -------------------------------------------------
# `scan_history.sh` sourced this file and then ran seven `grep -iaF` invocations of its
# own. Sharing a file is not sharing an implementation, and the structural test that
# claimed "one matcher" only checked that nobody still used `grep -iE` -- which is a
# weaker statement than the one it was written under.
#
# The flags now exist in exactly one place, `FIREWALL_GREP_OPTS`, and every transport
# below goes through a function that uses them. Different transports are unavoidable --
# a pipe, the object database, a list of paths are genuinely different mechanisms -- but
# the SEMANTICS are in one array that one edit changes everywhere.
#
# Literal (-F) because the dictionary holds names, not patterns. Case-insensitive (-i)
# because a name is a name however it is capitalised. Binary-inclusive (-a) because a term
# inside a PDF is exactly as public as one in a README.

FIREWALL_GREP_OPTS=(-i -a -F)

# Every literal match in every gate goes through one of these two. Nothing else greps.
firewall_grep() { grep "${FIREWALL_GREP_OPTS[@]}" "$@"; }
firewall_git_grep() { git grep "${FIREWALL_GREP_OPTS[@]}" "$@"; }

firewall_term_list() {
  printf '%s' "${CAI_FIREWALL_LIST:-$HOME/.config/cai/firewall_terms.txt}"
}

# Fail CLOSED when the dictionary is unreadable. A matcher that silently passes because it
# could not find its policy input is the failure mode this whole apparatus exists to avoid.
firewall_require_list() {
  local list
  list="$(firewall_term_list)"
  if [[ ! -f "$list" ]]; then
    echo "FIREWALL: term list not found at $list -- refusing (fail-closed)." >&2
    return 1
  fi
  return 0
}

# Print each prohibited term found in the text on stdin. Empty output means clean.
# Reads the text ONCE into a variable so the dictionary loop can re-scan it; the loop
# itself must not consume stdin, which is why the list is redirected on the `done`.
firewall_matches_in() {
  local text list term
  text="$(cat)"
  list="$(firewall_term_list)"
  while IFS= read -r term || [[ -n "$term" ]]; do
    [[ -z "$term" || "$term" == \#* ]] && continue
    if printf '%s' "$text" | firewall_grep -q -- "$term"; then
      printf '%s\n' "$term"
    fi
  done < "$list"
}

# THE ACTUAL BYTES ABOUT TO BE COMMITTED, from the index rather than from a patch.
#
# Both staged-content gates read `git diff --cached -U0`, which is a RENDERING of a
# change and not the change itself. Git renders a staged binary as
#
#     Binary files a/report.pdf and b/report.pdf differ
#
# so the prohibited bytes inside the blob are simply not in the text either gate
# searched, and a staged PDF naming the opportunity walked past both of them. Patch text
# also omits unchanged bytes of a modified file, and elides content behind `-U0` hunk
# headers -- so even for text the patch is a subset of what is being committed.
#
# `git show :path` returns the indexed blob exactly. Staged PATHS are emitted too: a
# filename carries a name as publicly as a line inside the file does.
#
# `--diff-filter=ACM` WAS NOT THE SET OF THINGS BEING COMMITTED.
#
# A rename is none of Add, Copy-as-A, or Modify -- git reports it as R -- so `git mv
# clean.txt Customer-X.txt` produced an EMPTY staged path list. The blob is unchanged and
# already committed, so every content pass had nothing new to find, and the one operation
# whose entire effect is to give an existing file a new name was the one the filter
# excluded. Verified against git rather than reasoned about: ACM returns nothing for a
# staged rename, `d` returns the destination.
#
# `d` -- lowercase, meaning EXCLUDE deletions -- rather than a longer list of letters.
# Enumerating the operations one has thought of is what produced the gap; the question
# this gate asks is "which paths will exist after this commit", and that is every staged
# change except a deletion, however git chose to classify it. It is also correct whether
# or not rename detection is enabled: with it off, the rename appears as an A.
firewall_staged_content() {
  local path
  git diff --cached --name-only --diff-filter=d -z 2>/dev/null |
    while IFS= read -r -d '' path; do
      printf '%s\n' "$path"
      git show ":$path" 2>/dev/null
      printf '\n'
    done
}

# EVERY PATH THAT HAS EVER EXISTED IN A REACHABLE TREE.
#
# The history pass was `git grep <term> $(git rev-list --all)`, which searches blob
# CONTENTS. It never reads a tree entry, so a file named `Customer-X/private/report.pdf`
# holding entirely clean bytes passed the full-history scan -- and renaming it to
# something innocent in a later commit did not remove the name from the earlier tree.
#
# A public repository shows every tree. The name is visible without opening anything, and
# it is visible forever.
#
# `git rev-list --objects --all` LOOKS LIKE THE ANSWER AND IS NOT.
#
# It prints `<sha> <path>` for reachable named objects, and it prints each OBJECT once.
# A file renamed without being edited is one blob under two names, so rev-list emits it
# under whichever name it reached first and the other name is gone. Tried against the
# exact case this pass exists for -- commit as a prohibited name, rename clean, scan --
# and it reported PASS.
#
# That is worth writing down rather than quietly replacing: the wrong implementation
# fails in the flattering direction. It produces a pass, a "historical path" line in the
# banner, and no coverage of the one history a rename creates.
#
# Every tree of every reachable commit, enumerated. `sort -u` because the same path in
# sixty commits is one name, and the dictionary loop re-reads this for every term.
#
# `-z` HERE IS ABOUT QUOTING, NOT SPLITTING.
#
# Without it git applies `core.quotePath`: a path with a space is wrapped in quotes, and
# one with a non-ASCII byte is rendered as octal escapes. A prohibited name containing
# either was therefore compared against an ESCAPED rendering of itself and did not match.
# The bytes are the name; `-z` emits them raw. They are re-joined on newlines immediately
# because what happens next is a line-oriented literal grep for a term.
firewall_historical_paths() {
  local commit
  for commit in $(git rev-list --all 2>/dev/null); do
    git ls-tree -r --name-only -z "$commit" 2>/dev/null | tr '\0' '\n'
  done | sort -u
}

# The names of files on disk right now: tracked, and untracked-but-not-ignored.
#
# Both were already enumerated -- `git ls-files` supplied the paths the tracked content
# pass grepped INSIDE, and the untracked pass built the same list to grep inside -- and
# in both cases the names themselves went unexamined. The list was in hand and was used
# only as an address.
firewall_worktree_paths() {
  git ls-files -z 2>/dev/null | tr '\0' '\n'
}

firewall_untracked_paths() {
  git ls-files -z --others --exclude-standard 2>/dev/null | tr '\0' '\n'
}

# THE SAME TWO LISTS, KEPT NUL-DELIMITED, FOR THE PASSES THAT OPEN THE FILES.
#
# The functions above answer "what are these files called", and joining on newlines is
# faithful enough for a literal grep over names. These answer "which files must be read",
# and there the boundary IS the safety property.
#
# `scan_history.sh` transported this list as `-- $(git ls-files)`. Unquoted command
# substitution word-splits on IFS, so a tracked file called `quarterly report.pdf` reached
# git as two arguments, `quarterly` and `report.pdf`, neither of which exists. git grep
# reported nothing for both, the pass printed no violation, and the banner went on
# claiming that tracked working-tree content had been scanned. The one file most likely to
# carry a prohibited name -- a document, named the way people name documents -- was the
# one shape of filename the scan could not read.
#
# Fails towards "clean", like every other defect found on this programme.
firewall_tracked_paths_z() {
  git ls-files -z 2>/dev/null
}

firewall_untracked_paths_z() {
  git ls-files -z --others --exclude-standard 2>/dev/null
}

# The dictionary's fingerprint, for a handoff that must show which policy input was used
# without publishing its contents.
firewall_list_digest() {
  shasum -a 256 "$(firewall_term_list)" 2>/dev/null | awk '{print $1}'
}
