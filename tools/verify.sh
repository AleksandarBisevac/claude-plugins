#!/bin/sh
# tools/verify.sh — every gate CI runs, in one command, and NONE of them skipped
# because an earlier one went red.
#
#   tools/verify.sh                 the full set (what CI runs)
#   tools/verify.sh --fast          iteration mode: narrower browser sweeps, NOT a gate
#   tools/verify.sh --release       the full set PLUS the checks a version bump owes
#   tools/verify.sh --affected      only the checks the working tree's changes need
#
# WHY THIS EXISTS. Nothing here is new; every line below was already a command
# somebody had to remember. Typing them by hand cost real money twice in one day:
#
#   1. The `ajv` schema step was skipped locally, so a manifest-validation failure
#      only appeared in CI.
#   2. The full sweep was run and THEN the version was bumped. A bump is itself a
#      source change: it stales the README's runnable `curl` pins (a lint fails the
#      build by name) and the three rendered artifacts (which embed the version).
#      CI went red on three stale pins, on a commit whose only defect was the order
#      two commands were typed in.
#
# NOT `&&`-chained, deliberately. A chain stops at the first red and tells you
# nothing about the eight checks behind it; you fix one thing, re-run, and pay the
# whole wall clock again to discover the next. Every step here runs, and the
# summary at the end is the whole truth at once.
#
# Wall clock is dominated by the panel browser gate; `--fast` narrows that leg and
# is worth it while iterating and worth nothing before a release. It prints what it
# skipped. The figures that used to sit here rotted the day the selftest sweep
# became parallel, which is what this repo's own rule about numbers in prose
# predicts, so the command that re-derives them stands in their place:
#
#   python3 tools/sweep-selftests.py                     # the python leg
#   node tools/capture-screenshots.mjs --check           # the panel leg
#   node tools/check-report-interactive.mjs docs/index.html   # one report leg
set -u

here=$(dirname "$0")
root=$(cd "$here/.." && pwd)
cd "$root" || exit 2

FAST=0
RELEASE=0
AFFECTED=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --release) RELEASE=1 ;;
    --affected) AFFECTED=1 ;;
    -h|--help)
      # Prints the header comment and stops where it stops. This was `sed -n
      # '2,30p'` - a magic line number into this file's own top - and the header
      # grew past 30 the first time it was edited, silently truncating --help
      # mid-sentence. A rule beats a number here for the same reason it does in
      # prose.
      awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
      exit 0 ;;
    *) echo "verify.sh: unknown argument $a" >&2; exit 2 ;;
  esac
done

# --- scratch state, one directory per run --------------------------------------
# Every step's log and every parallel leg's exit code used to live at a FIXED /tmp
# path (`/tmp/verify-step.log`, `/tmp/verify-par-$n.rc`, ...), so two runs on one
# machine shared them. A log crossing is a nuisance; `.rc` is not a log. A parallel
# leg WRITES its exit code to that path and the reader below turns it into the
# verdict - and both runs number their legs from zero, so one could read the
# other's success and print `ok` for work it never did. A green that covers
# nothing, in the tool whose whole job is to stop exactly that.
#
# `affected.txt` is worse by a nose: it is the LIST OF STEPS. A crossed read runs
# somebody else's gates and silently skips its own, and a skipped gate looks
# identical to a passed one in the summary.
#
# The repair is to STOP SHARING rather than to arbitrate it. A lock would serialise
# two runs that have no reason to wait for each other - parallel phases through
# worktrees are an advertised feature, and several agents running the gates at once
# is the normal case now, not the edge. `capture-screenshots.mjs` keeps its lock
# for the opposite reason: its fixed path is load-bearing (F18 - a committed PNG is
# byte-comparable only against the same path) and it arbitrates one real resource,
# a single panel-server per project. Neither is true of a throwaway log.
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/verify-XXXXXX") || {
  echo "verify.sh: could not create a scratch directory, so this run is refused." >&2
  echo "Falling back to a shared path is the defect this exists to prevent." >&2
  exit 2
}
trap 'rm -rf "$WORKDIR"' EXIT INT TERM

# One row per step, appended as each finishes. Printed at the end so the summary
# reads as a table rather than as scrollback.
RESULTS=""
FAILED=0

run() {
  label=$1
  shift
  printf '  %-44s' "$label"
  if "$@" >"$WORKDIR/step.log" 2>&1; then
    printf 'ok\n'
    RESULTS="$RESULTS
  ok    $label"
  else
    code=$?
    printf 'FAILED (exit %s)\n' "$code"
    sed 's/^/      /' "$WORKDIR/step.log" | tail -12
    RESULTS="$RESULTS
  FAIL  $label"
    FAILED=$((FAILED + 1))
  fi
}

# --- only what changed, when asked and only when it can be decided -------------
# `affected.py` exits 2 when it cannot narrow honestly (an unrecognised path, or a
# version bump, which every rendered artifact embeds). That exit is a REQUEST FOR
# THE FULL SET, not an error, and falling through to it is the whole safety of
# this mode.
if [ "$AFFECTED" -eq 1 ]; then
  if python3 tools/affected.py > "$WORKDIR/affected.txt" 2>&1; then
    echo "verify: --affected — running only what the working tree needs"
    sed 's/^/  /' "$WORKDIR/affected.txt"
    rc=0
    # The report documents go concurrently here for the same reason as in the full
    # run: three file:// Chromiums with nothing shared. Running them through the
    # serial loop below cost more than the narrowing saved on a change that
    # selected both surfaces - measured 323s against a 305s full run, which is a
    # selector that made things worse.
    n=0
    while IFS= read -r cmd; do
      case "$cmd" in
        "  node tools/check-report-interactive.mjs "*)
          c=$(printf '%s' "$cmd" | sed 's/^  //')
          n=$((n + 1))
          ( sh -c "$c" >"$WORKDIR/par-$n.log" 2>&1; echo $? >"$WORKDIR/par-$n.rc" ) & ;;
      esac
    done < "$WORKDIR/affected.txt"
    [ "$n" -eq 0 ] || wait
    i=0
    while [ "$i" -lt "$n" ]; do
      i=$((i + 1))
      printf '  %-58s' "report gate #$i"
      if [ "$(cat "$WORKDIR/par-$i.rc" 2>/dev/null || echo 1)" = "0" ]; then printf 'ok\n'
      else printf 'FAILED\n'; sed 's/^/      /' "$WORKDIR/par-$i.log" | tail -10; rc=1; fi
    done
    while IFS= read -r cmd; do
      case "$cmd" in
        "  node tools/check-report-interactive.mjs "*) ;;
        # `npx ` is in the list because `npx vitest run` became selectable and this
        # case statement did not know the word - so the selector named a gate and
        # the runner silently skipped it, which is worse than not selecting it at
        # all: the summary would have said every selected check was green.
        "  python3 "*|"  node "*|"  npx "*)
          c=$(printf '%s' "$cmd" | sed 's/^  //')
          printf '  %-58s' "$c"
          if sh -c "$c" >"$WORKDIR/step.log" 2>&1; then printf 'ok\n'
          else printf 'FAILED\n'; sed 's/^/      /' "$WORKDIR/step.log" | tail -10; rc=1; fi ;;
      esac
    done < "$WORKDIR/affected.txt"
    echo ""
    if [ "$rc" -ne 0 ]; then
      echo "VERIFY (--affected) FAILED. This was a NARROWED run: re-run without"
      echo "--affected before concluding anything about the rest of the tree."
      exit 1
    fi
    echo "VERIFY (--affected): every selected check is green — and only the"
    echo "selected ones ran. NOT the gate; the full set is what CI compares to."
    exit 0
  fi
  echo "verify: --affected could not narrow this change, so the full set runs:"
  sed 's/^/  /' "$WORKDIR/affected.txt"
fi

echo "verify: python"
# ONE runner, shared with CI, and STRICTER than the loop that used to be here.
# The old `sweep_selftests()` asserted the exit code and nothing else, while CI's
# inlined copy also required the `N/M cases passed` contract and applied the
# `--covered` skip - so a file that exited 0 having asserted nothing was green here
# and red there. See tools/sweep-selftests.py for the whole story; the point of
# calling it from both places is that a rule added to it is added to both at once.
run "selftests (hooks + scripts + tests + tools)" python3 tools/sweep-selftests.py
# THE ONE SUITE THE SWEEP MAY NOT RUN FOR US. The sweep now covers tools/, so every
# other tool's cases run inside it and no line here repeats them. The runner's own
# cases are the exception, and the reason is circularity: a `grade()` that always
# answered "ok" would report its own suite as passing while hiding the failure. Run
# directly, the exit code is read by this shell instead of by the thing under test.
run "...and the runner's own cases, read directly" \
  python3 tools/sweep-selftests.py --selftest
# The meta-gate. This file, ci.yml, CONTRIBUTING.md and CLAUDE.md are hand-maintained
# descriptions of one gate set, and they had drifted in both directions before anyone
# measured it; a gate named by one and not another now fails by name. Both documents
# were findings when they were added - each claimed to be the definition while nothing
# compared it, and CONTRIBUTING.md carried seven of thirteen gates.
run "gate parity (every description of the gate set)" python3 tools/gate-parity.py
# A hook is the only cost in this repo that sits on the critical path of EVERY
# matching tool call, and hooks.json puts seven of them on one edit. The wall clock
# is deliberately NOT gated - it swings between repeats by more than a deferred
# import is worth, so a ceiling either flakes or cannot see the regression. What is
# gated is the import graph, which is exact: `bench-hooks.py` (no flag) prints the
# measurement for a human choosing what to optimise.
run "hook import budget" python3 tools/bench-hooks.py --gate
run "ruff" ruff check plugins/audit tools
run "vermin (3.8 floor)" vermin -t=3.8- --no-tips --violations \
  plugins/audit/scripts plugins/audit/hooks plugins/audit/tests

echo "verify: javascript unit tests"
# CI HAS RUN THIS ALL ALONG AND THIS FILE DID NOT, which made the header's claim to
# be "every gate CI runs" false: a change under scripts/ui/ could be taken all the
# way to a push with none of the suites that cover it having run once.
run "vitest (tools/ui-tests)" npx vitest run

echo "verify: manifests and plugin structure"
run "validate starter manifest" python3 plugins/audit/scripts/manifest/validate-manifest.py \
  plugins/audit/templates/audit-plan.starter.json
run "validate this repo's own plan" python3 plugins/audit/scripts/manifest/validate-manifest.py \
  docs/audit/audit-plan.json
# The step that was skipped by hand and only failed in CI. Needs the network the
# first time; a miss here is reported like any other red rather than hidden.
run "ajv schema (draft2020)" npx --yes ajv-cli validate --spec=draft2020 \
  -s plugins/audit/schema/audit-plan.schema.json \
  -d docs/audit/audit-plan.json
run "claude plugin validate (marketplace)" claude plugin validate .
run "claude plugin validate (plugin)" claude plugin validate plugins/audit

echo "verify: rendered artifacts"
run "committed artifacts match a fresh render" python3 tools/check-rendered-artifacts.py
# The other question about the same files, and the only one that reads the BYTES
# GIT TRACKS rather than the code that wrote them: a committed journal row once
# carried a user's home directory into a repository that ships to clients. Fixing
# the writer proves the writer was fixed; only reading the committed file proves
# nothing else writes there and no older artifact is still shipping.
run "committed artifacts carry no machine identity" python3 tools/check-committed-pii.py
# CI HAS RUN THIS ALL ALONG AND THIS FILE DID NOT. It replays the plan gate refusing
# an unplanned edit and asserts the deny still names the file and the way out, so a
# reworded gate would have shipped a GIF of something the product no longer does.
# --check writes no file and needs no font, and costs a fraction of a second.
run "demo preconditions (the gate still refuses)" python3 tools/capture-demo-gif.py --check

echo "verify: browsers"
# The three shipped reports run CONCURRENTLY: three independent Chromium instances
# over three file:// URLs, sharing no port and no server. Measured 32s together
# against 93s one after another.
#
# The panel leg below stays SERIAL on purpose. It runs a real server and several of
# its assertions wait out real five-second timers, so it is the one leg where CPU
# contention could turn a pass into a flake — and this suite already produced one
# unexplained timeout today. Three times the speed is not worth making the slowest
# check less trustworthy.
report_docs="examples/acme-store/acme-store-audit.html docs/index.html docs/demo-large.html"
for f in $report_docs; do
  ( node tools/check-report-interactive.mjs "$f" >"$WORKDIR/$(basename "$f").log" 2>&1
    echo $? >"$WORKDIR/$(basename "$f").rc" ) &
done
wait
for f in $report_docs; do
  b=$(basename "$f")
  printf '  %-44s' "report is interactive: $b"
  if [ "$(cat "$WORKDIR/$b.rc" 2>/dev/null || echo 1)" = "0" ]; then
    printf 'ok\n'
    RESULTS="$RESULTS
  ok    report is interactive: $b"
  else
    printf 'FAILED\n'
    sed 's/^/      /' "$WORKDIR/$b.log" | tail -12
    RESULTS="$RESULTS
  FAIL  report is interactive: $b"
    FAILED=$((FAILED + 1))
  fi
done
if [ "$FAST" -eq 1 ]; then
  run "panel + report preconditions (--fast)" \
    node tools/capture-screenshots.mjs --check --fast
else
  run "panel + report preconditions" node tools/capture-screenshots.mjs --check
fi

# --- what a version bump owes -------------------------------------------------
# These are not extra rigour; they are the three things that follow a bump and get
# forgotten because they live in different files from the number itself.
if [ "$RELEASE" -eq 1 ]; then
  echo "verify: release preflight"
  version=$(python3 -c 'import json,io;print(json.load(io.open("plugins/audit/.claude-plugin/plugin.json",encoding="utf-8"))["version"])')
  echo "  plugin.json version: $version"

  readme_pins_current() {
    stale=$(grep -o 'claude-plugins/v[0-9][^/]*/' plugins/audit/README.md \
            | sort -u | grep -v "^claude-plugins/v$version/$" || true)
    [ -z "$stale" ] || { echo "README pins not on v$version:"; echo "$stale"; return 1; }
  }
  changelog_has_section() {
    grep -q "^## \[$version\]" CHANGELOG.md \
      || { echo "CHANGELOG.md has no '## [$version]' section"; return 1; }
  }
  tag_is_free() {
    git rev-parse "v$version" >/dev/null 2>&1 \
      && { echo "tag v$version already exists — a pushed tag is never moved here"; return 1; }
    return 0
  }
  run "README curl pins name v$version" readme_pins_current
  run "CHANGELOG has a [$version] section" changelog_has_section
  run "tag v$version does not exist yet" tag_is_free
fi

# --- the whole truth, at once --------------------------------------------------
echo ""
echo "verify: summary$RESULTS"
echo ""
if [ "$FAILED" -gt 0 ]; then
  echo "VERIFY FAILED: $FAILED step(s) red. Every step above ran, so this is the"
  echo "complete list rather than the first thing that broke."
  exit 1
fi
if [ "$FAST" -eq 1 ]; then
  echo "VERIFY (--fast): every step green, but the browser sweeps were narrowed."
  echo "This is NOT the gate — re-run without --fast before trusting a change."
  exit 0
fi
echo "VERIFY OK: every gate CI runs is green here."
