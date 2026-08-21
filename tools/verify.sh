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
# Wall clock, measured on this machine: the panel browser gate is ~230s and
# everything else together is ~85s, so `--fast` (~160s for the panel leg) is worth
# it while iterating and worth nothing before a release. It prints what it skipped.
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
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "verify.sh: unknown argument $a" >&2; exit 2 ;;
  esac
done

# One row per step, appended as each finishes. Printed at the end so the summary
# reads as a table rather than as scrollback.
RESULTS=""
FAILED=0

run() {
  label=$1
  shift
  printf '  %-44s' "$label"
  if "$@" >/tmp/verify-step.log 2>&1; then
    printf 'ok\n'
    RESULTS="$RESULTS
  ok    $label"
  else
    code=$?
    printf 'FAILED (exit %s)\n' "$code"
    sed 's/^/      /' /tmp/verify-step.log | tail -12
    RESULTS="$RESULTS
  FAIL  $label"
    FAILED=$((FAILED + 1))
  fi
}

# --- the python side ----------------------------------------------------------
sweep_selftests() {
  rc=0
  for f in $(find plugins/audit/hooks plugins/audit/scripts plugins/audit/tests \
             -name '*.py' | sort); do
    python3 "$f" --selftest >/tmp/verify-selftest.log 2>&1 || {
      echo "RED: $f"; tail -15 /tmp/verify-selftest.log; rc=1; }
  done
  return $rc
}

# --- only what changed, when asked and only when it can be decided -------------
# `affected.py` exits 2 when it cannot narrow honestly (an unrecognised path, or a
# version bump, which every rendered artifact embeds). That exit is a REQUEST FOR
# THE FULL SET, not an error, and falling through to it is the whole safety of
# this mode.
if [ "$AFFECTED" -eq 1 ]; then
  if python3 tools/affected.py > /tmp/verify-affected.txt 2>&1; then
    echo "verify: --affected — running only what the working tree needs"
    sed 's/^/  /' /tmp/verify-affected.txt
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
          ( sh -c "$c" >"/tmp/verify-par-$n.log" 2>&1; echo $? >"/tmp/verify-par-$n.rc" ) & ;;
      esac
    done < /tmp/verify-affected.txt
    [ "$n" -eq 0 ] || wait
    i=0
    while [ "$i" -lt "$n" ]; do
      i=$((i + 1))
      printf '  %-58s' "report gate #$i"
      if [ "$(cat "/tmp/verify-par-$i.rc" 2>/dev/null || echo 1)" = "0" ]; then printf 'ok\n'
      else printf 'FAILED\n'; sed 's/^/      /' "/tmp/verify-par-$i.log" | tail -10; rc=1; fi
    done
    while IFS= read -r cmd; do
      case "$cmd" in
        "  node tools/check-report-interactive.mjs "*) ;;
        "  python3 "*|"  node "*)
          c=$(printf '%s' "$cmd" | sed 's/^  //')
          printf '  %-58s' "$c"
          if sh -c "$c" >/tmp/verify-step.log 2>&1; then printf 'ok\n'
          else printf 'FAILED\n'; sed 's/^/      /' /tmp/verify-step.log | tail -10; rc=1; fi ;;
      esac
    done < /tmp/verify-affected.txt
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
  sed 's/^/  /' /tmp/verify-affected.txt
fi

echo "verify: python"
run "selftests (hooks + scripts + tests)" sweep_selftests
run "ruff" ruff check plugins/audit tools
run "vermin (3.8 floor)" vermin -t=3.8- --no-tips --violations \
  plugins/audit/scripts plugins/audit/hooks plugins/audit/tests

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
  ( node tools/check-report-interactive.mjs "$f" >"/tmp/verify-$(basename "$f").log" 2>&1
    echo $? >"/tmp/verify-$(basename "$f").rc" ) &
done
wait
for f in $report_docs; do
  b=$(basename "$f")
  printf '  %-44s' "report is interactive: $b"
  if [ "$(cat "/tmp/verify-$b.rc" 2>/dev/null || echo 1)" = "0" ]; then
    printf 'ok\n'
    RESULTS="$RESULTS
  ok    report is interactive: $b"
  else
    printf 'FAILED\n'
    sed 's/^/      /' "/tmp/verify-$b.log" | tail -12
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
