#!/bin/sh
# tools/verify.sh — every gate, grouped into named SLICES, and the one place the gate
# set is written down. CI runs slices of this file and nothing else, so what CI runs
# and what this file runs cannot differ: there is one description, and it runs.
#
#   tools/verify.sh                         every per-run slice (what CI runs on every run)
#   tools/verify.sh --only lint,js          only the named slices
#   tools/verify.sh --only selftests --shard 2/3
#                                           one part of a sweep slice (what a CI cell runs)
#   tools/verify.sh --list                  every slice, its tier, and the steps it runs,
#                                           without running any of them
#   tools/verify.sh --fast                  iteration mode: narrower browser sweeps and no
#                                           legacy-code-page or spaced leg, NOT a gate
#   tools/verify.sh --release               the per-run slices PLUS the release slice
#   tools/verify.sh --affected              only the checks the working tree's changes need
#   tools/verify.sh --loud                  stream every step's output as it runs (the
#                                           default when CI=true, so a CI log carries it)
#
# THE SLICES ARE THE TIERS. `--list` prints them, read off the same `run` calls a run
# makes rather than kept beside them, and `tools/gate-parity.py` holds ci.yml to that
# list: every slice a job names must be listed, every per-run slice must have a job,
# and a sharded slice's matrix must cover every part. A slice `--only` names that does
# not exist is a refusal (exit 2), and so is `--shard` on a slice that is not a sweep:
# a narrowed run that quietly dropped what it was asked for would report it as covered.
#
# `--affected` REFUSES rather than narrowing when the selector names a check this file
# cannot dispatch: it exits 2 having run nothing, because a narrowed run that quietly
# drops a gate reports the change as covered when it is not.
#
# `--release` also PRINTS the followers a bump stales, in the order they must be redone
# and with the command that refreshes each (the `#R` block in the release slice).
#
# NOT `&&`-chained, deliberately. A chain stops at the first red and tells you nothing
# about the checks behind it; you fix one thing, re-run, and pay the whole wall clock
# again to discover the next. Every step here runs, and the summary at the end is the
# whole truth at once.
#
# WHY THIS FILE AND NOT THE WORKFLOW. The gate set used to be written four times - here,
# in .github/workflows/ci.yml, in CONTRIBUTING.md and in CLAUDE.md - and a checker held
# the copies together, so each CI change was four edits plus that checker's fixtures. A
# CI job that calls a slice of this file needs no second copy: the workflow says WHERE a
# slice runs (which runner, which shard, which tier) and this file says WHAT it runs.
#
# Wall clock is dominated by the panel browser gate and the sweeps; the commands that
# re-derive each leg's cost stand here rather than figures, which rot:
#
#   python3 tools/sweep-selftests.py                     # the python leg
#   node tools/capture-screenshots.mjs --check           # the panel leg
#   node tools/check-report-interactive.mjs docs/demo-large.html   # one report leg
set -u

self=
rest=$0
while :; do
  case "$rest" in
    *\\*) self=$self${rest%%\\*}/; rest=${rest#*\\} ;;
    *)    self=$self$rest; break ;;
  esac
done
case "$self" in
  */*) here=${self%/*} ;;
  *)   here=. ;;
esac
root=$(cd "$here/.." && pwd)
cd "$root" || exit 2

FAST=0
RELEASE=0
AFFECTED=0
LIST=0
LOUD=0
ONLY=
SHARD=
[ "${CI:-}" = "true" ] && LOUD=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fast) FAST=1 ;;
    --release) RELEASE=1 ;;
    --affected) AFFECTED=1 ;;
    --list) LIST=1 ;;
    --loud) LOUD=1 ;;
    --only)
      [ "$#" -ge 2 ] || { echo "verify: --only takes a comma-separated slice list" >&2; exit 2; }
      ONLY=$2; shift ;;
    --only=*) ONLY=${1#--only=} ;;
    --shard)
      [ "$#" -ge 2 ] || { echo "verify: --shard takes I/N" >&2; exit 2; }
      SHARD=$2; shift ;;
    --shard=*) SHARD=${1#--shard=} ;;
    -h|--help)
      # Prints the header comment and stops where it stops: a rule beats a line
      # number into this file's own top, which silently truncated --help once.
      awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
      exit 0 ;;
    *) echo "verify: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

# --- the slices ----------------------------------------------------------------------
# PER_RUN is what every CI run runs and what a plain `verify.sh` runs. RELEASE_SLICES is
# what a release adds: `release` is the preflight a version bump owes, run by
# `--release` here, and `resample` draws the suites with a Windows intermittent record
# again and again, which CI's release tier runs on a Windows runner.
#
# `selftests-cp1252` is the legacy-code-page leg alone, for the Windows cells: there
# the runner refuses `--spaced`, so the stress leg cannot run, and a pipe on Windows is
# already that code page. It stays a slice of its own until the Windows intermittents
# are shown gone from the plain cells; the deletion waits on that evidence.
PER_RUN_SLICES="selftests selftests-stress selftests-cp1252 runner e2e lint js manifests plugin report panel"
RELEASE_SLICES="release resample"
ALL_SLICES="$PER_RUN_SLICES $RELEASE_SLICES"

slice_tier() {
  case " $PER_RUN_SLICES " in
    *" $1 "*) echo "per-run" ;;
    *) echo "release" ;;
  esac
}

if [ -n "$ONLY" ]; then
  if [ "$AFFECTED" -eq 1 ] || [ "$RELEASE" -eq 1 ] || [ "$LIST" -eq 1 ]; then
    echo "verify: --only names the slices itself; it does not combine with --affected, --release or --list" >&2
    exit 2
  fi
  SELECTED=$(printf '%s' "$ONLY" | tr ',' ' ')
  for s in $SELECTED; do
    case " $ALL_SLICES " in
      *" $s "*) ;;
      *) echo "verify: there is no slice named '$s' - tools/verify.sh --list names them" >&2
         exit 2 ;;
    esac
  done
  if [ -z "$(printf '%s' "$SELECTED" | tr -d ' ')" ]; then
    echo "verify: --only named no slice, and a run over nothing is not a green run" >&2
    exit 2
  fi
elif [ "$LIST" -eq 1 ]; then
  SELECTED=$ALL_SLICES
elif [ "$RELEASE" -eq 1 ]; then
  SELECTED="$PER_RUN_SLICES release"
else
  SELECTED=$PER_RUN_SLICES
fi

SHARD_ARGS=
if [ -n "$SHARD" ]; then
  if [ -z "$ONLY" ]; then
    echo "verify: --shard splits a sweep slice, so it needs --only naming one" >&2
    exit 2
  fi
  for s in $SELECTED; do
    case "$s" in
      selftests|selftests-stress|selftests-cp1252) ;;
      *) echo "verify: --shard splits a sweep slice, and '$s' is not one" >&2; exit 2 ;;
    esac
  done
  # The sweep itself refuses an I/N it cannot honour; this only keeps a word with a
  # space or a flag in it from being split into arguments nobody asked for.
  case "$SHARD" in
    *[!0-9/]*|'') echo "verify: --shard takes I/N, got '$SHARD'" >&2; exit 2 ;;
  esac
  SHARD_ARGS="--shard $SHARD"
fi

# --- the interpreter -------------------------------------------------------------------
# Every step below spells `python3`. On a Windows runner that name can be the store's
# app-execution stub, which exists on PATH and runs nothing, while `python` is the real
# interpreter. The probe asks each name to run before trusting it - the rule
# plugins/audit/hooks/py-launch.sh uses - and when only `python` runs, `python3` becomes
# a function calling it, so no step has to be spelled twice.
if python3 -c '' >/dev/null 2>&1; then
  INTERPRETER="python3"
elif python -c '' >/dev/null 2>&1; then
  python3() { python "$@"; }
  INTERPRETER="python, because python3 is on PATH but does not run, or is absent"
else
  echo "verify: neither python3 nor python runs here, so this run is refused." >&2
  exit 2
fi
# WHICH interpreter, not only which name: two names can be two installations, and a
# suite run on another version than the one set up for it is not the run anyone asked for.
INTERPRETER="$INTERPRETER = $(python3 -c 'import sys; print("%s %s" % (sys.executable, sys.version.split()[0]))')"

# --- scratch state, one directory per run --------------------------------------------
# Every step's log and every parallel leg's exit code used to live at a FIXED /tmp path,
# so two runs on one machine shared them, and a crossed `.rc` read somebody else's
# success as this run's - a green that covers nothing. The repair is to STOP SHARING
# rather than to arbitrate it: several agents running the gates at once is the normal
# case, and a lock would serialise runs that have no reason to wait for each other.
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/verify-XXXXXX") || {
  echo "verify.sh: could not create a scratch directory, so this run is refused." >&2
  echo "Falling back to a shared path is the defect this exists to prevent." >&2
  exit 2
}
# THE DIRECTORY GOES ON THE EXIT TRAP ALONE, and a signal turns into an exit so that
# trap runs. `trap '...' EXIT INT TERM` removed the directory on a signal and then
# RESUMED the script (a POSIX shell continues after a trap action), so an interrupted
# run kept going with its scratch directory gone. 130 and 143 are the 128+signal
# statuses a shell reports for them.
trap 'rm -rf "$WORKDIR"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# One row per step, appended as each finishes. Printed at the end so the summary
# reads as a table rather than as scrollback.
RESULTS=""
FAILED=0

# A failing step's log, printed so the failure can be NAMED: every line shaped like
# one (a cross, FAIL, ERR_, error) from the part the tail would drop, then the tail
# itself. Keeping only the tail lost a failing test's name whenever the runner's
# summary came after it.
show_failure() {
  log=$1
  keep=$2
  total=$(wc -l <"$log" | tr -d ' ')
  if [ "$total" -gt "$keep" ]; then
    dropped=$((total - keep))
    head -n "$dropped" "$log" | grep -E '✖|FAIL|ERR_|[Ee]rror' | head -40 | sed 's/^/      /'
    printf '      [... %s earlier line(s) not shown except the failure lines above ...]\n' "$dropped"
  fi
  sed 's/^/      /' "$log" | tail -n "$keep"
}

record() {
  RESULTS="$RESULTS
  $1"
}

# One step. Under `--list` it prints its label and command and runs nothing, which is
# what makes the list the same thing as the run. Quiet by default: a row per step, and
# the log only when it fails. LOUD streams the step's output as it runs, unindented,
# because a CI log is read by machines too - the sweep's per-file rows are what
# `--costs-from-log` parses - and a step killed by the job's bound must already have
# printed what it was doing.
run() {
  label=$1
  shift
  if [ "$LIST" -eq 1 ]; then
    printf '    %s\n        %s\n' "$label" "$*"
    return 0
  fi
  if [ "$LOUD" -eq 1 ]; then
    printf '== %s\n' "$label"
    rm -f "$WORKDIR/step.rc"
    { "$@" 2>&1; echo $? >"$WORKDIR/step.rc"; } | tee "$WORKDIR/step.log"
    code=$(cat "$WORKDIR/step.rc" 2>/dev/null || echo 1)
    if [ "$code" = "0" ]; then
      printf '== %s: ok\n' "$label"
      record "ok    $label"
    else
      printf '== %s: FAILED (exit %s)\n' "$label" "$code"
      record "FAIL  $label"
      FAILED=$((FAILED + 1))
    fi
    return 0
  fi
  printf '  %-44s' "$label"
  if "$@" >"$WORKDIR/step.log" 2>&1; then
    printf 'ok\n'
    record "ok    $label"
  else
    code=$?
    printf 'FAILED (exit %s)\n' "$code"
    show_failure "$WORKDIR/step.log" 12
    record "FAIL  $label"
    FAILED=$((FAILED + 1))
  fi
}

# A step `--fast` leaves out, said in the summary rather than dropped from it.
skip() {
  if [ "$LIST" -eq 1 ]; then
    printf '    %s\n        (skipped under --fast)\n' "$1"
    return 0
  fi
  printf '  %-44s%s\n' "$1" "skipped (--fast)"
  record "skip  $1 (--fast)"
}

# --- only what changed, when asked and only when it can be decided -------------------
# `affected.py` exits 2 when it cannot narrow honestly (an unrecognised path, or a
# version bump, which every rendered artifact embeds). That exit is a REQUEST FOR THE
# FULL SET, not an error, and falling through to it is the whole safety of this mode.
if [ "$AFFECTED" -eq 1 ]; then
  if python3 tools/affected.py > "$WORKDIR/affected.txt" 2>&1; then
    echo "verify: --affected — running only what the working tree needs"
    sed 's/^/  /' "$WORKDIR/affected.txt"
    rc=0
    # THE STEP LIST, CUT OUT ONCE, BEFORE ANYTHING DISPATCHES OVER IT. The selector
    # prints its reasons first and its commands after a `run:` line, both indented by
    # two spaces, so a dispatcher reading the whole file cannot tell a command from a
    # sentence. Every line of steps.txt is a command, and nothing else is; the
    # `(nothing ...)` line is the selector's way of saying it selected no check.
    awk '/^run:$/ { steps = 1; next }
         steps && /^  \(/ { next }
         steps && /^  / { sub(/^  /, ""); print }' \
      "$WORKDIR/affected.txt" > "$WORKDIR/steps.txt"

    # REFUSE, DO NOT SKIP - and refuse before a single step runs. A check the
    # selector names and this runner cannot run is a disagreement between the two,
    # and the honest answer names it and stops. This grep is the ONLY place the
    # accepted prefixes are spelled; the loops below dispatch whatever survives it.
    grep -v -e '^python3 ' -e '^node ' -e '^npx ' -e '^claude ' \
      "$WORKDIR/steps.txt" > "$WORKDIR/undispatchable.txt"
    if [ -s "$WORKDIR/undispatchable.txt" ]; then
      echo ""
      echo "VERIFY (--affected) REFUSED. Nothing ran. tools/affected.py selected"
      echo "check(s) this runner has no way to dispatch:"
      sed 's/^/  /' "$WORKDIR/undispatchable.txt"
      echo ""
      echo "A narrowed run that dropped these would still have reported every"
      echo "selected check green, which is worse than not narrowing at all. Teach"
      echo "the accepted-prefix list above the new prefix, or stop the selector"
      echo "emitting it. Until then, run with no flag: that is the full set."
      exit 2
    fi

    # ...AND AN EMPTY SELECTION IS NOT A GREEN RUN: a verdict over nothing is the
    # same sentence a run that checked everything prints.
    if [ ! -s "$WORKDIR/steps.txt" ]; then
      echo ""
      echo "VERIFY (--affected) REFUSED. The selector matched NO check for this"
      echo "change, so there was nothing to narrow to. That is a run that checked"
      echo "nothing, not a run that found nothing wrong."
      echo "Run with no flag: that is the full set."
      exit 2
    fi

    # The report documents go concurrently, as in the full run: independent file://
    # Chromiums with nothing shared.
    n=0
    while IFS= read -r cmd; do
      case "$cmd" in
        "node tools/check-report-interactive.mjs "*)
          n=$((n + 1))
          ( sh -c "$cmd" >"$WORKDIR/par-$n.log" 2>&1; echo $? >"$WORKDIR/par-$n.rc" ) & ;;
      esac
    done < "$WORKDIR/steps.txt"
    [ "$n" -eq 0 ] || wait
    i=0
    while [ "$i" -lt "$n" ]; do
      i=$((i + 1))
      printf '  %-58s' "report gate #$i"
      if [ "$(cat "$WORKDIR/par-$i.rc" 2>/dev/null || echo 1)" = "0" ]; then printf 'ok\n'
      else printf 'FAILED\n'; show_failure "$WORKDIR/par-$i.log" 10; rc=1; fi
    done
    while IFS= read -r cmd; do
      case "$cmd" in
        "node tools/check-report-interactive.mjs "*) ;;
        *)
          printf '  %-58s' "$cmd"
          if sh -c "$cmd" >"$WORKDIR/step.log" 2>&1; then printf 'ok\n'
          else printf 'FAILED\n'; show_failure "$WORKDIR/step.log" 10; rc=1; fi ;;
      esac
    done < "$WORKDIR/steps.txt"
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

# --- slice: selftests, the plain leg ----------------------------------------------------
# ONE runner, shared with CI: a rule added to it is added to both at once. CI splits a
# sweep slice into `--shard I/N` cells whose union is this whole run (the runner's sh0
# case); here it runs whole, which is the same leg. Either way the workers are one
# budget of slots, and each file's timeout is calibrated from its recorded cost.
slice_selftests() {
  run "selftests (hooks + scripts + tests + tools)" \
    python3 tools/sweep-selftests.py $SHARD_ARGS
}

# --- slice: selftests-stress, both stress conditions in one execution -----------------
# A legacy code page on the child's stdout AND a spaced, symlinked TMPDIR and
# interpreter path, graded by the plain rules. A pipe on Windows is the machine's
# legacy code page, and a suite printing a character that page lacks dies there; a
# fixture building a shell command from an unquoted path is a different command under
# a spaced temp root. One execution asks both. Posix only: the runner refuses
# `--spaced` on Windows rather than report a leg it did not run.
slice_selftests_stress() {
  if [ "$FAST" -eq 1 ]; then
    skip "selftests under cp1252 and a spaced, linked TMPDIR"
    return 0
  fi
  run "selftests under cp1252 and a spaced, linked TMPDIR" \
    python3 tools/sweep-selftests.py --encoding cp1252 --spaced $SHARD_ARGS
}

# --- slice: selftests-cp1252, the code-page leg alone, for the Windows cells ----------
slice_selftests_cp1252() {
  if [ "$FAST" -eq 1 ]; then
    skip "selftests on a legacy code page"
    return 0
  fi
  run "selftests on a legacy code page" \
    python3 tools/sweep-selftests.py --encoding cp1252 $SHARD_ARGS
}

# --- slice: runner, the one suite the sweep may not run for us --------------------------
# A `grade()` that always answered "ok" would report its own suite as passing while
# hiding the failure. Run directly, the exit code is read by this shell instead of by
# the thing under test. Per-OS in CI on purpose: it uses threads, subprocesses and a
# forced codec, and all three behave differently on Windows.
slice_runner() {
  run "the sweep runner's own cases, read directly" \
    python3 tools/sweep-selftests.py --selftest
}

# --- slice: e2e, the hooks driven through the launcher ----------------------------------
# The selftests call decide() directly and cannot prove the wiring: the launcher, the
# stdin contract and the emitted JSON shape. Every fixture project lives under this
# run's scratch directory.
e2e_launcher_runs() {
  # a Bash payload the guard allows: the launcher must exec python and exit 0
  printf '{"tool_name":"Bash","tool_input":{"command":"ls"}}' \
    | sh plugins/audit/hooks/py-launch.sh guard-secrets-read.py ask
}

e2e_launcher_loud() {
  out=$(env PATH=/nonexistent "$(command -v sh)" plugins/audit/hooks/py-launch.sh guard-edits.py ask < /dev/null)
  echo "$out"
  echo "$out" | grep -q '"permissionDecision":"ask"'
}

e2e_cap() {
  printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s","hook_event_name":"PreToolUse"}' \
    "$1" "$2" "$e2e_proj" \
    | env CLAUDE_PROJECT_DIR="$e2e_proj" sh plugins/audit/hooks/py-launch.sh \
        guard-capabilities.py ask
}

# A policy that resolves perfectly and is never dispatched is the failure this feature
# has to be honest about, so its own wiring is checked rather than assumed. Warn is a
# systemMessage and NEVER a permissionDecision: an advisory written as `allow` would
# bypass the permission system entirely.
e2e_capability() {
  e2e_proj=$(mktemp -d "$WORKDIR/e2e-cap-XXXXXX") || return 1
  mkdir -p "$e2e_proj/.claude"
  out=$(e2e_cap Skill '{"skill":"dataviz"}')
  [ -z "$out" ] || { echo "expected silence when inert, got: $out"; return 1; }
  printf '{"policy":{"skills":{"default":"deny","allow":["safe-*"]}}}' \
    > "$e2e_proj/.claude/audit.config.json"
  out=$(e2e_cap Skill '{"skill":"dataviz"}')
  echo "$out" | grep -q '"permissionDecision": *"deny"' || { echo "expected deny, got: $out"; return 1; }
  echo "$out" | grep -q 'policy.skills.default is deny' || { echo "the deny names no basis: $out"; return 1; }
  out=$(e2e_cap Skill '{"skill":"safe-thing"}')
  [ -z "$out" ] || { echo "an allowed skill must be silent, got: $out"; return 1; }
  out=$(e2e_cap Skill '{"skill":"audit:next"}')
  [ -z "$out" ] || { echo "audit's own must pass, got: $out"; return 1; }
  printf '{"policy":{"onViolation":"warn","mcp":{"deny":["mcp__prod-db__*"]}}}' \
    > "$e2e_proj/.claude/audit.config.json"
  out=$(e2e_cap mcp__prod-db__query '{}')
  echo "$out" | grep -q '"systemMessage"' || { echo "warn must be a systemMessage, got: $out"; return 1; }
  if echo "$out" | grep -q 'permissionDecision'; then
    echo "warn must not emit a permissionDecision, got: $out"; return 1
  fi
  echo "OK: inert / deny / allow / required / warn all behave through the launcher"
}

e2e_payload() {
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s/%s"},"session_id":"%s","cwd":"%s","hook_event_name":"PostToolUse"}' \
    "$e2e_projp" "$1" "$2" "$e2e_projp"
}

e2e_tdd_call() {
  e2e_payload "$1" "$2" \
    | env CLAUDE_PROJECT_DIR="$e2e_projp" sh plugins/audit/hooks/py-launch.sh \
        remind-tdd.py open
}

# This hook is FAIL-OPEN, so a crash and a decision to stay quiet are the same empty
# stdout. When an expectation fails, ask decide() directly with nothing swallowing it.
e2e_tdd_explain() {
  echo "--- asking decide() directly, exceptions unswallowed ---"
  e2e_payload "$1" "$2" | env CLAUDE_PROJECT_DIR="$e2e_projp" python3 -c "import importlib.util,json,os,sys; h=os.path.join('plugins','audit','hooks'); sys.path.insert(0,h); s=importlib.util.spec_from_file_location('remind_tdd',os.path.join(h,'remind-tdd.py')); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('decide() ->', m.decide(json.load(sys.stdin)))" || true
}

# The TDD nudge's channel is additionalContext, never a permissionDecision, so a hook
# that emitted the blocking shape would look identical to a working one in every check
# written for its neighbours. The state file one invocation writes is read back by the
# next, and a fresh session warns again - the second direction, without which a hook
# that had simply stopped speaking would pass. The payload is spelled for the
# interpreter: under Git Bash a scratch path is an MSYS path the native Python reads
# as driveless, so it is converted where `cygpath` exists.
e2e_tdd() {
  e2e_proj=$(mktemp -d "$WORKDIR/e2e-tdd-XXXXXX") || return 1
  mkdir -p "$e2e_proj/src"
  if command -v cygpath >/dev/null 2>&1; then
    e2e_projp=$(cygpath -m "$e2e_proj")
  else
    e2e_projp=$e2e_proj
  fi
  out=$(e2e_tdd_call src/cart.ts ci-tdd-warn)
  echo "$out" | grep -q '"additionalContext"' \
    || { echo "expected a nudge on additionalContext, got: <$out>"
         e2e_tdd_explain src/cart.ts ci-tdd-warn; return 1; }
  echo "$out" | grep -q 'tdd-reminder' \
    || { echo "the nudge does not name itself, got: <$out>"; return 1; }
  if echo "$out" | grep -q 'permissionDecision'; then
    echo "a nudge must never emit a permissionDecision, got: $out"; return 1
  fi
  out=$(e2e_tdd_call src/cart.test.ts ci-tdd-quiet)
  [ -z "$out" ] || { echo "touching a test must be silent, got: $out"; return 1; }
  out=$(e2e_tdd_call src/checkout.ts ci-tdd-quiet)
  [ -z "$out" ] || { echo "expected silence after a test touch, got: $out"; return 1; }
  out=$(e2e_tdd_call src/checkout.ts ci-tdd-again)
  echo "$out" | grep -q 'tdd-reminder' \
    || { echo "a fresh session must warn again; the silence above was not the state file: $out"
         e2e_tdd_explain src/checkout.ts ci-tdd-again; return 1; }
  mkdir -p "$e2e_proj/.claude"
  printf '{"tddReminder":{"enabled":false}}' > "$e2e_proj/.claude/audit.config.json"
  out=$(e2e_tdd_call src/basket.ts ci-tdd-disabled)
  [ -z "$out" ] || { echo "disabled must be silent, got: $out"; return 1; }
  echo "OK: nudge / record / satisfied / fresh session / disabled all behave through the launcher"
}

slice_e2e() {
  run "launcher resolves an interpreter" e2e_launcher_runs
  run "launcher fails LOUD without any interpreter" e2e_launcher_loud
  # The plan gate's tiers through the launcher, as one script with its own cases in
  # the sweep: a shell block no local gate ran is how the tiers once went stale.
  run "plan gate grades on evidence, through the launcher" \
    python3 tools/check-plan-gate-e2e.py
  run "capability policy decides, through the launcher" e2e_capability
  run "the TDD nudge, through the launcher" e2e_tdd
  # The write half of the pipeline, against a real repository: the commit trail, the
  # branch resolution, the history guard's ancestry question, the journal's git anchor
  # and the ledger's author each fail OPEN when git cannot be asked, so their absence
  # looked exactly like a clean result. It also wires the hooks the steps above leave out.
  run "git pipeline (a real repository)" python3 tools/check-git-pipeline.py
}

# --- slice: lint, the repository-wide checks ---------------------------------------------
slice_lint() {
  # What the slices themselves owe: every slice ci.yml names is listed here, every
  # per-run slice has a job, every sharded slice's matrix covers every part - plus
  # the rules that read a runner or a document for a living.
  run "gate parity (ci.yml against these slices)" python3 tools/gate-parity.py
  # The import graph is gated, not the wall clock, which swings between repeats by
  # more than a deferred import is worth. It measures every interpreter it can find
  # and names the supported ones it could not reach.
  run "hook import budget" python3 tools/bench-hooks.py --gate
  # What each pipeline entry makes the main loop read before any work, against the
  # pipeline-cost design's ceilings.
  run "pipeline context ceilings" python3 tools/measure-context.py --gate
  run "ruff" ruff check plugins/audit tools
  # `-t=3.8-` carries the trailing dash on purpose: "the detected floor must not
  # exceed 3.8". A bare `-t=3.8` demands the floor EQUAL it.
  run "vermin (3.8 floor)" vermin -t=3.8- --no-tips --violations \
    plugins/audit/scripts plugins/audit/hooks plugins/audit/tests
  # Reads what git tracks and never prints what it matched: a public CI log echoing a
  # leak would be the same bug one layer out.
  run "committed artifacts carry no machine identity" python3 tools/check-committed-pii.py
  # Every committed evidence row against the schema's vocabulary and against itself,
  # and every commit a committed manifest names resolves - refusing on a clone too
  # truncated to answer, which is why CI's checkout takes the whole history.
  run "committed ledgers record a verdict the runner can make, and every commit a manifest names resolves" \
    python3 tools/check-example-ledgers.py
}

# --- slice: js, the browser JavaScript as behaviour ----------------------------------------
# vitest is the ONLY layer that reads ui/*.js as behaviour, cross-checked against
# _fmt.py in the same run. `node --check` per part catches the other class: a syntax
# error kills the whole inline script while every substring pin stays green. A walk
# that parsed fewer parts than the smallest real tree is reported, not passed: a glob
# that matched nothing once graded none of the tree as clean.
ui_parts_parse() {
  n=0
  for f in $(find plugins/audit/scripts/ui -name '*.js' | sort); do
    node --check "$f" || { echo "FAIL: $f is not parseable"; return 1; }
    n=$((n + 1))
  done
  [ "$n" -ge 2 ] || { echo "FAIL: only $n ui asset(s) parsed - the walk is not reaching them"; return 1; }
  echo "OK: $n ui asset(s) parse"
}

slice_js() {
  run "vitest (tools/ui-tests)" npx vitest run
  run "every ui/ JavaScript part parses" ui_parts_parse
}

# --- slice: manifests, the plans and the committed artifacts -------------------------------
sharded_layout_intact() {
  python3 - <<'PY'
import json, os
for idx in ("docs/audit/audit-plan.json", "examples/acme-store/audit-plan.json"):
    d = json.load(open(idx)); base = os.path.dirname(idx)
    assert d["meta"]["version"] == 3, idx + " is not sharded (meta.version != 3)"
    for p in d["phases"]:
        assert "shard" in p, "%s: phase %s missing shard ref" % (idx, p.get("id"))
        b = json.load(open(os.path.join(base, p["shard"])))
        assert b.get("id") == p["id"] and "tasks" in b, "bad shard %s" % p["shard"]
    print("OK sharded:", idx, "-", len(d["phases"]), "shards")
PY
}

# The doctor's value is entirely in what it says about a REAL setup. Exit 0 means no
# findings; warnings are expected. --json stays parseable, since that is the form other
# tools consume - and it is captured before it is read, because a pipeline reports the
# status of its last command alone.
doctor_json_clean() {
  _doctor_json=$(python3 plugins/audit/scripts/status/audit-doctor.py --project . --json) \
    || return 1
  printf '%s' "$_doctor_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["checks"]; assert d["counts"]["FINDING"] == 0, d["counts"]; print("OK: doctor json clean")'
}

status_gate_and_render() {
  python3 plugins/audit/scripts/status/audit-status.py docs/audit/audit-plan.json --gate || return 1
  python3 plugins/audit/scripts/report/render-report.py docs/audit/audit-plan.json \
    --out-dir "$WORKDIR/audit-report" || return 1
  test -s "$WORKDIR/audit-report/audit-report.html" || { echo "no html rendered"; return 1; }
  test -s "$WORKDIR/audit-report/audit-report.md" || { echo "no markdown rendered"; return 1; }
}

# docs/index.html is the GitHub Pages demo and a BYTE COPY of the committed example
# report; it is not in check-rendered-artifacts.py's table on purpose, because covering
# it there would render one published page from two inputs. Fresh source (that tool)
# plus proven copy (here) is a fresh copy - and that tool's `copy_check_missing()`
# reads THIS cmp, so deleting it turns that tool red rather than going quiet.
docs_index_is_copy() {
  if ! cmp -s docs/index.html examples/acme-store/acme-store-audit.html; then
    echo "docs/index.html has drifted from examples/acme-store/acme-store-audit.html"
    echo "fix: examples/report.sh — it re-renders the example AND makes this copy"
    echo "     by hand: cp examples/acme-store/acme-store-audit.html docs/index.html"
    return 1
  fi
  grep -q 'id="usage"' docs/index.html || { echo "docs/index.html carries no Usage section"; return 1; }
}

# The example's usage ledger is COMMITTED and DERIVED - `gen-demo-usage.py` builds it
# from the manifest - so a phase added to the example desynchronises the two unless
# something regenerates and compares.
#
# THE REGENERATED DIRECTORY LIVES UNDER $WORKDIR, SO THE EXIT TRAP COVERS IT. This
# used to be `trap '...' RETURN`, a bash extension: dash and every other POSIX sh
# treat it as a signal name they do not have and never run it, so the directory
# stayed under `$TMPDIR` on each run. A directory inside $WORKDIR goes with it on a
# return, a signal and a plain exit alike; the explicit removal below is only the
# early release. gate-parity.py's vsh cases run these two functions under dash.
ledger_compare() {
  python3 plugins/audit/scripts/demo/gen-demo-usage.py \
    examples/acme-store/audit-plan.json --out-dir "$1" >/dev/null || return 1
  for f in examples/acme-store/.claude/usage/*.jsonl; do
    cmp -s "$f" "$1/$(basename "$f")" && continue
    echo "the committed ledger no longer matches a fresh deterministic run:"
    echo "  $f"
    echo "fix: python3 plugins/audit/scripts/demo/gen-demo-usage.py \\"
    echo "       examples/acme-store/audit-plan.json \\"
    echo "       --out-dir examples/acme-store/.claude/usage"
    return 1
  done
  return 0
}
ledger_reproducible() {
  regen=$(mktemp -d "$WORKDIR/ledger-XXXXXX") || return 1
  ledger_compare "$regen"
  ledger_status=$?
  rm -rf "$regen"
  return "$ledger_status"
}

# The scale demo's fixture is rebuilt and validated, and the page is judged over its
# markup with every <script> block stripped, so a JS string holding a markup literal
# cannot move a count or trip the invalid-banner probe. Its BYTES are
# check-rendered-artifacts.py's question; content assertions cannot see age.
scale_demo_valid() {
  dl=$(mktemp -d "$WORKDIR/scale-XXXXXX") || return 1
  python3 plugins/audit/scripts/demo/gen-demo-manifest.py "$dl" --phases 40 --tasks 5 || return 1
  python3 plugins/audit/scripts/manifest/validate-manifest.py "$dl/audit-plan.json" || return 1
  python3 - <<'PYEOF'
import io, re, sys
s = io.open("docs/demo-large.html", encoding="utf-8").read()
m = re.sub(r"(?is)<script\b.*?</script\s*>", "", s)
if "INVALID MANIFEST" in m:
    sys.exit("docs/demo-large.html was rendered from an invalid manifest")
if 'id="usage"' not in m:
    sys.exit("no Usage section in the markup")
n = m.count('tr class="phase"')
if n != 40:
    sys.exit("expected 40 phase rows in the markup, got %d" % n)
print("OK: scale demo renders 40 valid phases with a Usage section")
PYEOF
}

slice_manifests() {
  run "validate starter manifest" python3 plugins/audit/scripts/manifest/validate-manifest.py \
    plugins/audit/templates/audit-plan.starter.json
  run "validate this repo's own plan" python3 plugins/audit/scripts/manifest/validate-manifest.py \
    docs/audit/audit-plan.json
  run "validate the example's plan" python3 plugins/audit/scripts/manifest/validate-manifest.py \
    examples/acme-store/audit-plan.json
  run "sharded layout intact" sharded_layout_intact
  # Needs the network the first time; a miss is reported like any other red rather
  # than hidden. It was skipped by hand once and only failed in CI.
  run "ajv schema: starter" npx --yes ajv-cli validate --spec=draft2020 \
    -s plugins/audit/schema/audit-plan.schema.json \
    -d plugins/audit/templates/audit-plan.starter.json
  run "ajv schema: this repo's plan" npx --yes ajv-cli validate --spec=draft2020 \
    -s plugins/audit/schema/audit-plan.schema.json \
    -d docs/audit/audit-plan.json
  run "ajv schema: the example's plan" npx --yes ajv-cli validate --spec=draft2020 \
    -s plugins/audit/schema/audit-plan.schema.json \
    -d examples/acme-store/audit-plan.json
  run "doctor: this repo" python3 plugins/audit/scripts/status/audit-doctor.py --project .
  run "doctor: the example" python3 plugins/audit/scripts/status/audit-doctor.py --project examples/acme-store
  run "doctor: --json is clean" doctor_json_clean
  run "status --gate and a report render" status_gate_and_render
  # THE FRESH RENDER ONLY, because a plain run is a before-commit run: the tool's
  # other arm asks whether HEAD carries the pages on disk, which is red before a
  # commit while a re-rendered page is uncommitted - the correct change included. On
  # a CI checkout that arm cannot fire, since the checkout is the commit; `--release`
  # asks it after one.
  run "committed artifacts match a fresh render" \
    python3 tools/check-rendered-artifacts.py --before-commit
  run "docs/index.html is still a byte copy" docs_index_is_copy
  run "committed example ledger is reproducible from the generator" ledger_reproducible
  run "scale demo is renderable and valid" scale_demo_valid
  # Replays the plan gate refusing the recorded edit and asserts the deny still names
  # the file and the way out; writes no file.
  run "demo preconditions (the gate still refuses)" python3 tools/capture-demo-gif.py --check
}

slice_plugin() {
  run "claude plugin validate (marketplace)" claude plugin validate .
  run "claude plugin validate (plugin)" claude plugin validate plugins/audit
}

# --- slice: report, the shipped reports driven in a browser -------------------------------
# A JavaScript error that kills every event handler leaves every marker a grep reads
# intact, so the report could ship inert with every other gate green. These drive the
# real files over file://. The committed reports run CONCURRENTLY: independent Chromium
# instances, sharing no port and no server. docs/index.html is not among them: it is a
# byte copy of the acme report, which the manifests slice proves.
#
# THE RENDERED-PLAN LEGS are reports nothing commits: this repo's own live plan (whose
# shape moves with every phase merged), a plan whose phases all share one status, an
# all-parked plan with and without --no-proposals, and a report older than the checks.
rendered_plan_legs() {
  lp="$WORKDIR/live-plan"
  one="$WORKDIR/one-status"
  ap="$WORKDIR/all-parked"
  dl="$WORKDIR/dl"
  mkdir -p "$lp" "$ap" || return 1
  echo "== live plan: render and check"
  python3 plugins/audit/scripts/report/render-report.py docs/audit/audit-plan.json \
    --out-dir "$lp" --format html || return 1
  node tools/check-report-interactive.mjs "$lp"/*.html || return 1
  python3 plugins/audit/scripts/demo/gen-demo-manifest.py "$dl" --phases 40 --tasks 5 \
    >/dev/null || return 1
  echo "== one-status plan: every phase done"
  python3 - "$dl" "$one" <<'PYEOF' || return 1
import io, json, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
shutil.copytree(src, dst)
path = os.path.join(dst, "audit-plan.json")
plan = json.load(io.open(path, encoding="utf-8"))
for phase in plan["phases"]:
    if phase["status"] != "done":
        os.remove(os.path.join(dst, phase["shard"]))
plan["phases"] = [p for p in plan["phases"] if p["status"] == "done"]
ids = set()
for phase in plan["phases"]:
    shard = json.load(io.open(os.path.join(dst, phase["shard"]),
                              encoding="utf-8"))
    ids |= set(t["id"] for t in shard["tasks"])
plan["fileIndex"] = dict((f, [t for t in ts if t in ids])
                         for f, ts in plan["fileIndex"].items()
                         if any(t in ids for t in ts))
plan["bugs"] = [b for b in plan["bugs"]
                if b.get("taskId") is None or b.get("taskId") in ids]
plan["proposals"] = []
io.open(path, "w", encoding="utf-8").write(json.dumps(plan, indent=2))
PYEOF
  python3 plugins/audit/scripts/manifest/validate-manifest.py "$one/audit-plan.json" \
    || return 1
  python3 plugins/audit/scripts/demo/gen-demo-usage.py "$one/audit-plan.json" \
    >/dev/null || return 1
  CLAUDE_PROJECT_DIR="$one" python3 plugins/audit/scripts/report/render-report.py \
    "$one/audit-plan.json" --out-dir "$one" --format html --basename one-status \
    || return 1
  node tools/check-report-interactive.mjs "$one/one-status.html" || return 1
  echo "== all-parked plan: names its proposals, with and without --no-proposals"
  python3 - "$dl/audit-plan.json" "$ap/audit-plan.json" <<'PYEOF' || return 1
import io, json, sys
src = json.load(io.open(sys.argv[1], encoding="utf-8"))
src["phases"] = []
src["fileIndex"] = {}
src["bugs"] = []
for prop in src.get("proposals") or []:
    prop["status"] = "proposed"
    prop["materializedAs"] = None
    prop["materializedAt"] = None
    prop.pop("notes", None)
    prop.pop("droppedAt", None)
io.open(sys.argv[2], "w", encoding="utf-8").write(json.dumps(src, indent=2))
PYEOF
  python3 plugins/audit/scripts/manifest/validate-manifest.py "$ap/audit-plan.json" \
    || return 1
  CLAUDE_PROJECT_DIR="$ap" python3 plugins/audit/scripts/report/render-report.py \
    "$ap/audit-plan.json" --out-dir "$ap" --format html || return 1
  # A glob: the file is named after the plan it renders.
  grep -q "parked proposal" "$ap"/*.html \
    || { echo "an all-parked report does not name its proposals"; return 1; }
  CLAUDE_PROJECT_DIR="$ap" python3 plugins/audit/scripts/report/render-report.py \
    "$ap/audit-plan.json" --out-dir "$ap" --format html --basename np --no-proposals \
    || return 1
  grep -q "parked proposal" "$ap/np.html" \
    || { echo "--no-proposals swallowed the empty-plan sentence"; return 1; }
  if grep -q 'id="proposals"' "$ap/np.html"; then
    echo "--no-proposals did not drop the section"; return 1
  fi
  # Exit 2 is the assertion - "could not run", NOT exit 1 "the report is inert". The
  # grep is the second half: exit 2 alone is also what a missing browser produces.
  echo "== a report older than the checks: exit 2 (cannot check), element named"
  sed 's/class="toolbar sectools"/class="toolbar was-sectools"/' \
    "$lp/audit-report.html" > "$lp/aged.html" || return 1
  node tools/check-report-interactive.mjs "$lp/aged.html" > "$lp/aged.log" 2>&1
  aged=$?
  cat "$lp/aged.log"
  [ "$aged" -eq 2 ] || { echo "expected exit 2 (cannot check), got $aged"; return 1; }
  grep -q 'no \.sectools' "$lp/aged.log" \
    || { echo "expected the missing element to be named"; return 1; }
  return 0
}

slice_report() {
  report_docs="examples/acme-store/acme-store-audit.html docs/demo-large.html"
  if [ "$LIST" -eq 1 ]; then
    for f in $report_docs; do
      printf '    %s\n        %s\n' "report is interactive: $(basename "$f")" \
        "node tools/check-report-interactive.mjs $f"
    done
  else
    for f in $report_docs; do
      ( node tools/check-report-interactive.mjs "$f" >"$WORKDIR/$(basename "$f").log" 2>&1
        echo $? >"$WORKDIR/$(basename "$f").rc" ) &
    done
    wait
    for f in $report_docs; do
      b=$(basename "$f")
      [ "$LOUD" -eq 1 ] && { printf '== report is interactive: %s\n' "$b"; cat "$WORKDIR/$b.log"; }
      printf '  %-44s' "report is interactive: $b"
      if [ "$(cat "$WORKDIR/$b.rc" 2>/dev/null || echo 1)" = "0" ]; then
        printf 'ok\n'
        record "ok    report is interactive: $b"
      else
        printf 'FAILED\n'
        show_failure "$WORKDIR/$b.log" 12
        record "FAIL  report is interactive: $b"
        FAILED=$((FAILED + 1))
      fi
    done
  fi
  run "rendered-plan legs (live, one-status, all-parked, aged)" rendered_plan_legs
}

# --- slice: panel, the panel driven in a browser -------------------------------------------
# Serial on purpose: it runs a real server and waits out real timers, so CPU contention
# could turn a pass into a flake. Gates the artifact, not the stylesheet: a Python
# selftest can assert what the CSS says, and only a browser can prove the page paints.
slice_panel() {
  if [ "$FAST" -eq 1 ]; then
    run "panel + report preconditions (--fast)" node tools/capture-screenshots.mjs --check --fast
  else
    run "panel + report preconditions" node tools/capture-screenshots.mjs --check
  fi
}

# --- slice: release, what a version bump owes ------------------------------------------------
# THE FOLLOWER LIST LIVED IN A PERSON'S MEMORY. Bumping plugin.json is itself a source
# change, and it stales other files that carry the number; they surfaced one at a time,
# each as a red gate after the fact. The `#R` block below is that list, written down
# once and printed by `--release` at the moment somebody needs it.
#
# THE ORDER IS LOAD-BEARING: capture FOLLOWS the bump, and docs/index.html is a byte
# copy, so it can only be refreshed after the artifact it copies.
#
# THIS BLOCK CHECKS AND NEVER REFRESHES: a verifier that repaired what it found would
# go green BECAUSE it repaired it. Every row calls the lint that already owns its
# question rather than re-deciding it in shell.
#
#R a bump to plugins/audit/.claude-plugin/plugin.json stales the following, and they
#R must be redone IN THIS ORDER:
#R
#R   1. plugins/audit/README.md — the `curl` pins name the tag a reader fetches
#R      from, so an unbumped pin serves the previous release's files.
#R        rewrite each `claude-plugins/v<old>/` in the README to the new tag
#R
#R   2. the committed rendered artifacts — every report stamps the version that
#R      produced it, in the page and again inside its embedded Markdown twin.
#R        examples/report.sh
#R        ...and the scale demo, which renders from a generated fixture. Its exact
#R        commands are printed by the gate that compares it, built from the same
#R        flags that comparison renders with:
#R          python3 tools/check-rendered-artifacts.py --how
#R
#R   3. docs/index.html — a BYTE COPY of the example report, so it follows 2 and
#R      can never precede it.
#R        examples/report.sh makes this copy for you; by hand it is
#R          cp examples/acme-store/acme-store-audit.html docs/index.html
#R
#R   4. docs/screenshots/ — each image records the version it was shot at.
#R        node tools/capture-screenshots.mjs
#R
#R   4b. docs/examples/ — an example that clones the plugin pins a release tag, and
#R      a bump that leaves it behind sends a reader to scripts the tag may not have.
#R        repin each example to the newest tag that exists (at preflight that is
#R        the previous release, since the new tag is cut afterwards); the row
#R        below asks each pinned tag's tree for every script the example calls
#R
#R CAPTURE FOLLOWS THE BUMP. Capturing first and bumping afterwards invalidates
#R every picture and the shutter runs twice. That is not a hypothetical.
#R
#R AND ONE STEP THAT IS NOT A FOLLOWER, because it happens AFTER the push rather
#R than before it: a Release is created FOR a tag, so once `v<version>` is pushed,
#R
#R   5. the GitHub Release for the tag you just pushed.
#R        gh release create v<version> --title v<version> --notes-file <notes>
#R        ...with the notes taken from that version's CHANGELOG.md section.
#R
#R A tag is a git object; a Release is the page a reader lands on, and the README's
#R fetch pins make the tag a published claim. The row below asks the REMOTE whether
#R the newest published tag has a Release and whether Latest names it - and at this
#R moment that tag is the PREVIOUS release, so it is the drift detector rather than a
#R check of the release you are about to cut. It needs the network and says so when
#R it cannot ask; "could not ask" is never printed as "clean".
refs_rule() {
  python3 - "$1" <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join("plugins", "audit", "scripts"))
import _refs
rows = getattr(_refs, sys.argv[1])()
for row in rows:
    sys.stdout.write("%s\n" % (row,))
sys.exit(1 if rows else 0)
PYEOF
}

changelog_has_section() {
  grep -q "^## \[$version\]" CHANGELOG.md \
    || { echo "CHANGELOG.md has no '## [$version]' section"; return 1; }
}

# v2.0.0 and v2.0.1 both went out while bugs sat `open` in the plan, and every gate
# was green and honest about it: they check the tree, not the tracker. NOT piped into
# `tail`: a pipeline reports the LAST command's status, so the verdict would be thrown
# away and the row would be green over an open bug. Captured, then re-emitted.
no_open_bugs() {
  _bugs_out=$(python3 plugins/audit/scripts/status/audit-status.py \
    docs/audit/audit-plan.json --gate --fail-on open-bugs 2>&1)
  _bugs_rc=$?
  [ "$_bugs_rc" -eq 0 ] || echo "$_bugs_out" | tail -2
  return "$_bugs_rc"
}

tag_is_free() {
  git rev-parse "v$version" >/dev/null 2>&1 \
    && { echo "tag v$version already exists — a pushed tag is never moved here"; return 1; }
  return 0
}

slice_release() {
  version=$(python3 -c 'import json,io;print(json.load(io.open("plugins/audit/.claude-plugin/plugin.json",encoding="utf-8"))["version"])')
  if [ "$LIST" -eq 0 ]; then
    echo "verify: release preflight"
    echo "  plugin.json version: $version"
    echo ""
    # The list, printed from the comment block above so there is exactly one copy.
    sed -n '/^#R/{s/^#R //;s/^#R$//;p;}' "$0" | sed '/./s/^/  /'
    echo ""
  fi
  run "follower 1: fetch pins name v$version" refs_rule raw_url_pin_drift
  run "follower 2: artifacts stamp v$version" refs_rule artifact_version_drift
  run "follower 3: docs/index.html copies follower 2" docs_index_is_copy
  run "follower 4: screenshots were shot at v$version" refs_rule screenshot_capture_drift
  # Asks git, not the network: a pinned tag missing locally is a refusal, never a
  # pass. --pending: the tag does not exist yet here, so a pin naming this release is
  # read against HEAD instead of being refused.
  run "follower 4b: example pins hold the scripts they call" \
    python3 tools/check-example-pins.py --pending "v$version"
  # THE ARM THE PLAIN RUN LEAVES OUT. A release is cut from a commit, so here the
  # question has an answer: does HEAD carry the pages the render found current.
  run "HEAD carries the published pages" \
    python3 tools/check-rendered-artifacts.py --against-commit
  run "the plan carries no open bug" no_open_bugs
  run "CHANGELOG has a [$version] section" changelog_has_section
  run "tag v$version does not exist yet" tag_is_free
  # THE ONLY GATE IN THIS FILE THAT ASKS A REMOTE, which is why it is in the release
  # slice and nowhere CI runs on every push: what it reads changes once per release.
  run "the newest published tag has a Release" \
    python3 tools/check-release-published.py
}

# --- slice: resample, the Windows intermittents drawn on purpose ------------------------------
# Each entry is a suite with an intermittent record on windows-latest and the number of
# draws a release candidate gives it. The draws come from the suite's measured red rate,
# so that an intermittent at that rate is more likely caught than missed; the derivation
# and the runs it was measured on are in the CI study that introduced this slice, and it
# is re-derived when a suite's record changes. A suite leaves the list when the record
# shows its class fixed, not when a draw happens to pass. A red draw on a green SHA is a
# finding to file with /audit:bug: nothing files it automatically yet.
RESAMPLE="plugins/audit/tests/test__journal_io.py:15
plugins/audit/tests/test_panel_server.py:20
plugins/audit/tests/test__locks.py:20
plugins/audit/tests/test_audit_usage.py:10
.claude/hooks/guard-release.py:10
plugins/audit/tests/test_run_test_gate.py:5
plugins/audit/tests/test_stamp_verification.py:5"

# One pass sweeps every listed suite still owed a draw. A sweep that ran a different
# number of files than it was handed is refused: a runner that ignored the list and
# swept the whole tree would otherwise read as a green re-sample of nothing in particular.
resample_pass() {
  want=0
  paths=
  for entry in $RESAMPLE; do
    if [ "$1" -le "${entry##*:}" ]; then
      paths="$paths ${entry%:*}"
      want=$((want + 1))
    fi
  done
  [ "$want" -gt 0 ] || { echo "pass $1: no suite is owed a draw"; return 0; }
  out=$(python3 tools/sweep-selftests.py $paths 2>&1)
  rc=$?
  echo "$out"
  got=$(echo "$out" | sed -n 's/^[0-9][0-9]*\/\([0-9][0-9]*\) files ok.*/\1/p' | tail -1)
  if [ "$got" != "$want" ]; then
    echo "resample: the sweep reported ${got:-no} file(s) for the $want it was handed, so it did not take the list and nothing was re-sampled"
    return 1
  fi
  return "$rc"
}

slice_resample() {
  most=0
  for entry in $RESAMPLE; do
    [ "${entry##*:}" -gt "$most" ] && most=${entry##*:}
  done
  i=1
  while [ "$i" -le "$most" ]; do
    run "re-sample, pass $i" resample_pass "$i"
    i=$((i + 1))
  done
}

# --- the dispatch ----------------------------------------------------------------------------
if [ "$LIST" -eq 1 ]; then
  echo "verify: slices (interpreter: $INTERPRETER)"
  for s in $SELECTED; do
    printf '  %s (%s)\n' "$s" "$(slice_tier "$s")"
    "slice_$(printf '%s' "$s" | tr '-' '_')"
  done
  exit 0
fi

echo "verify: interpreter $INTERPRETER; slices: $SELECTED${SHARD:+; shard $SHARD}"
for s in $SELECTED; do
  echo "verify: $s"
  "slice_$(printf '%s' "$s" | tr '-' '_')"
done

# --- the whole truth, at once ------------------------------------------------------------------
echo ""
echo "verify: summary$RESULTS"
echo ""
if [ "$FAILED" -gt 0 ]; then
  echo "VERIFY FAILED: $FAILED step(s) red. Every step above ran, so this is the"
  echo "complete list rather than the first thing that broke."
  exit 1
fi
if [ -n "$ONLY" ]; then
  echo "VERIFY OK (--only $ONLY${SHARD:+ --shard $SHARD}): every step of the named"
  echo "slice(s) is green. The other slices did not run here."
  exit 0
fi
if [ "$FAST" -eq 1 ]; then
  echo "VERIFY (--fast): every step green, but the browser sweeps were narrowed"
  echo "and the legacy-code-page and spaced legs were skipped."
  echo "This is NOT the gate — re-run without --fast before trusting a change."
  exit 0
fi
echo "VERIFY OK: every gate CI runs is green here."
