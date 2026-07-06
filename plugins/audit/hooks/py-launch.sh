#!/bin/sh
# Interpreter launcher for the audit plugin's hooks.
#
# Usage: sh py-launch.sh <script.py> [open|ask]
#
# Resolves a Python interpreter (python3 -> python -> py) and execs it on
# hooks/<script.py>. `exec` hands the hook's stdin straight to the script
# (single consumption — a `python3 ... || python ...` fallback would eat the
# payload on the first try and re-run the script on ANY nonzero exit) and
# propagates the script's exit code unchanged.
#
# Uses only shell builtins until an interpreter is found, so it behaves the
# same even with a broken PATH.
#
# When NO interpreter can be found, the fail mode is the 2nd argument:
#   ask  -> emit PreToolUse permissionDecision "ask" JSON: the guarded tool
#           call surfaces a manual approval prompt instead of silently
#           proceeding. Fail-LOUD for the blocking guards — a bare exit 127
#           would be a non-blocking hook error and the tool would just run.
#   open -> exit 0 silently. For advisory hooks (PostToolUse /
#           UserPromptSubmit) which have no "ask" channel and must never
#           block work.
case "$0" in
  */*) dir=${0%/*} ;;
  *)   dir=. ;;
esac
script="$dir/$1"
mode="${2:-open}"

for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$script"
  fi
done

if [ "$mode" = "ask" ]; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"[audit] No Python interpreter found (tried python3, python, py) - the audit plugin guard hooks are NOT running. Install Python 3, or approve this tool call manually."}}'
fi
exit 0
