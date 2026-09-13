#!/bin/sh
# Interpreter launcher for the audit plugin's hooks.
#
# Usage: sh py-launch.sh <script.py> [open|ask]
#
# Resolves a Python interpreter (python3 -> python -> py) and runs it on
# hooks/<script.py>. The script's stdin is this shell's stdin, inherited with no
# pipe and no subshell in between, so the hook payload is consumed exactly once;
# the script's exit code is propagated unchanged.
#
# IT RUNS THE SCRIPT RATHER THAN `exec`ING IT, and that single line is what the
# fallbacks below are built on. After an `exec` this file is gone, so nobody is
# left to notice that the interpreter never started - which is the failure the
# whole loud path exists for. Running it keeps the shell alive to read the exit
# status, and the status alone is not enough to act on: a `python3 ... || python
# ...` chain would re-run the script on ANY nonzero exit and feed a second copy
# of a payload that was already consumed. So a nonzero status asks the
# interpreter one more question (`-c ''`) before anything is decided, and only an
# interpreter that cannot answer it is treated as one that never ran the script.
#
# THAT QUESTION IS OFF THE HOT PATH BY CONSTRUCTION. Every hook here exits 0
# whether it allows or refuses - a decision is JSON on stdout, never an exit code
# - so the probe costs a process on the failing path and nothing at all on the
# path taken before every tool call.
#
# Uses only shell builtins until an interpreter is chosen, so it behaves the same
# even with a broken PATH.
#
# Three ways the hook can fail to run at all, and the fail mode for each is the
# 2nd argument:
#   ask  -> emit PreToolUse permissionDecision "ask" JSON: the guarded tool
#           call surfaces a manual approval prompt instead of silently
#           proceeding. Fail-LOUD for the blocking guards - a bare nonzero exit
#           would be a non-blocking hook error and the tool would just run.
#   open -> exit 0 silently. For advisory hooks (PostToolUse /
#           UserPromptSubmit) which have no "ask" channel and must never
#           block work.
# Each of the three prints its OWN sentence. They are three different repairs -
# install an interpreter, fix the one you have, reinstall the plugin - and one
# sentence covering all of them tells a reader nothing they can act on.
#
# WHAT IT STILL CANNOT SEE: an interpreter that exits 0 without running the
# script. That is indistinguishable from a hook that allowed, and telling them
# apart would need the hook to report back over a channel it does not have.
#
# AND THE ONE FAILURE THAT IS NOT THIS FILE'S TO CATCH. `hooks.json` spells every
# command `sh "${CLAUDE_PLUGIN_ROOT}/hooks/py-launch.sh" ...`; that variable is
# interpolated into the command string by the harness and is never exported, so a
# root that expands to nothing leaves `sh` opening `/hooks/py-launch.sh`, and `sh`
# exits 127 before the first line below runs. Reading $CLAUDE_PLUGIN_ROOT here
# would not recover it and would be wrong in the other direction: it is absent
# from a HEALTHY hook's environment too, so a branch keyed on it would prompt on
# every tool call. The half that IS observable from inside is the same root fault
# seen from the other side - the named script is not beside this launcher - and it
# reaches the prompt below. For the half that is not, the reader is
# `/audit:doctor`: a launcher that never ran leaves no running-copy stamp on disk,
# and it reports hooks that have never fired.
case "$0" in
  */*) dir=${0%/*} ;;
  *)   dir=. ;;
esac
script="$dir/$1"
mode="${2:-open}"

# The one place the fail mode is read. Always exits 0: in `ask` mode the decision
# rides on the JSON, not on the status, and in `open` mode silence IS the mode.
loud() {
  if [ "$mode" = "ask" ]; then
    printf '%s\n' "$1"
  fi
  exit 0
}

if [ ! -f "$script" ]; then
  loud '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"[audit] The audit plugin hook script is NOT beside this launcher - the plugin root points at a tree without it, or this copy of the plugin is incomplete. The audit plugin guard hooks are NOT running. Reinstall the plugin (/plugin install audit@quality-gates) and run /audit:doctor, or approve this tool call manually."}}'
fi

# No `break` on the first name that exists: `command -v` answers whether a name
# RESOLVES, which a shim that exits 1 also does. A candidate that turns out not to
# run has not run the script either - the payload is still unread - so the next
# name gets the same try it would have had if the first had been missing outright.
broken=
for py in python3 python py; do
  command -v "$py" >/dev/null 2>&1 || continue
  "$py" "$script"
  # `rc` and not `status`: zsh makes that name read-only, so a `/bin/sh` that is
  # zsh would die on the assignment instead of launching the hook.
  rc=$?
  if [ "$rc" -eq 0 ]; then
    exit 0
  fi
  if "$py" -c '' </dev/null >/dev/null 2>&1; then
    exit "$rc"
  fi
  broken="$broken $py"
done

if [ -n "$broken" ]; then
  loud '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"[audit] Python is on PATH but cannot run (tried python3, python, py; the ones that resolved failed a bare `-c` probe) - the audit plugin guard hooks are NOT running. Repair or remove that interpreter, then run /audit:doctor, or approve this tool call manually."}}'
fi
loud '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"[audit] No Python interpreter found (tried python3, python, py) - the audit plugin guard hooks are NOT running. Install Python 3, or approve this tool call manually."}}'
