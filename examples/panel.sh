#!/bin/sh
# examples/panel.sh — open the /audit:panel UI on the worked example, no Claude
# session required.
#
# The panel is a local web UI over one project's `.claude/audit.config.json` and
# manifest. `examples/acme-store/` is a project with both, so nothing here needs
# the plugin installed: it is the same `panel-server.py` the command runs, aimed
# at the example.
#
#   examples/panel.sh                 open it (foreground — Ctrl-C stops it)
#   examples/panel.sh --detach        open it in the background, print the URL
#   examples/panel.sh status          is one running, and where
#   examples/panel.sh stop            stop the one running for this example
#
# Any other argument passes straight through to panel-server.py (`--port 8899`,
# `--no-open`). Works from any cwd: every path is resolved from this script's
# own location, never $PWD.
#
# The panel binds 127.0.0.1 only and writes its pid/port/token to
# examples/acme-store/.claude/audit-panel.json — gitignored (the panel maintains
# that rule itself since 0.35; this example commits .claude/.gitignore so the
# first launch writes nothing), so running it never dirties the tree. It writes
# the manifest only when you save a change in the UI.
set -e

case "$0" in
  */*) here=${0%/*} ;;
  *)   here=. ;;
esac
root=$(cd "$here/.." && pwd)
project=$root/examples/acme-store
panel=$root/plugins/audit/scripts/panel/panel-server.py

# Same interpreter resolution as plugins/audit/hooks/py-launch.sh, for the same
# reason: `python3` is not the only name a working Python 3 answers to.
PY=
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then PY=$py; break; fi
done
if [ -z "$PY" ]; then
  echo "examples/panel.sh: no Python interpreter found (tried python3, python, py)" >&2
  exit 127
fi

action=start
detach=0
# Rotate unrecognized arguments to the end of "$@" so they survive as
# pass-through with their quoting intact (a string accumulator would not).
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  arg=$1; shift; i=$((i + 1))
  case "$arg" in
    start|stop|status) action=$arg ;;
    -d|--detach)       detach=1 ;;
    -h|--help)
      # The header comment IS the help text, so the two can never disagree:
      # print it from line 2 up to the first line that is not a comment.
      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
      exit 0 ;;
    *) set -- "$@" "$arg" ;;
  esac
done

case "$action" in
  stop)   exec "$PY" "$panel" --project "$project" --stop "$@" ;;
  status) exec "$PY" "$panel" --project "$project" --status "$@" ;;
esac

if [ "$detach" -eq 1 ]; then
  # Detached, so it outlives this shell — then read the URL back from the
  # pidfile rather than guessing it, since --port 0 means the kernel picks one.
  # Stderr goes to the launch log, NEVER to /dev/null: a child that dies at
  # startup would otherwise leave exactly the trace a clean stop leaves, and
  # --status would have nothing to report but its absence (F99). The append is
  # load-bearing — panel-server.py empties that file once it is listening, and an
  # O_APPEND fd re-seeks instead of writing past the hole.
  mkdir -p "$project/.claude"
  nohup "$PY" "$panel" --project "$project" "$@" >/dev/null 2>>"$project/.claude/audit-panel.log" &
  sleep 1
  "$PY" "$panel" --project "$project" --status
  echo "stop it with: examples/panel.sh stop"
else
  exec "$PY" "$panel" --project "$project" "$@"
fi
