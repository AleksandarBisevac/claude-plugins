#!/bin/sh
# examples/report.sh — render the worked example's report, no Claude session
# required.
#
# Runs what /audit:report runs, plus the validation CI runs: validate the
# manifest, then render the interactive HTML and its Markdown twin.
#
#   examples/report.sh                    render in place, next to the manifest
#   examples/report.sh --open             ... and open the HTML in a browser
#   examples/report.sh --out-dir /tmp/x   scratch render; touches nothing committed
#
# Other arguments pass through to render-report.py (`--format`, `--basename`,
# `--summary-file`). Works from any cwd — paths resolve from this script's own
# location, never $PWD.
#
# Two things this does that a bare render-report.py call does not:
#
#   1. It refreshes docs/index.html. That file is the GitHub Pages demo and CI
#      requires it to be a *byte copy* of the committed example report. Re-render
#      and forget the copy and CI goes red — which is exactly how the live demo
#      once went a month stale. The copy happens only when the render actually
#      wrote the committed report (not with --out-dir, --format md, or a
#      different --basename).
#   2. It sets CLAUDE_PROJECT_DIR to the example, so the Usage section reads the
#      example's committed ledger — the same env CI renders it under.
#
# Heads-up: every render stamps a fresh `generated <UTC>` line, so an in-place
# run leaves a small git diff even when nothing else changed. Discard it with
# `git checkout examples/acme-store docs/index.html`.
set -e

case "$0" in
  */*) here=${0%/*} ;;
  *)   here=. ;;
esac
root=$(cd "$here/.." && pwd)
project=$root/examples/acme-store
manifest=$project/audit-plan.json
scripts=$root/plugins/audit/scripts
committed_html=$project/acme-store-audit.html

# Same interpreter resolution as plugins/audit/hooks/py-launch.sh.
PY=
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then PY=$py; break; fi
done
if [ -z "$PY" ]; then
  echo "examples/report.sh: no Python interpreter found (tried python3, python, py)" >&2
  exit 127
fi

do_open=0
# Rotate unrecognized arguments to the end of "$@" so they survive as
# pass-through with their quoting intact.
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  arg=$1; shift; i=$((i + 1))
  case "$arg" in
    --open) do_open=1 ;;
    -h|--help)
      # The header comment IS the help text, so the two can never disagree:
      # print it from line 2 up to the first line that is not a comment.
      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
      exit 0 ;;
    *) set -- "$@" "$arg" ;;
  esac
done

"$PY" "$scripts/validate-manifest.py" "$manifest"

out=$(CLAUDE_PROJECT_DIR=$project "$PY" "$scripts/report/render-report.py" "$manifest" "$@")
printf '%s\n' "$out"

# render-report.py prints one `wrote <path>` line per artifact; the last .html is
# the one to open. Deciding from its actual output means no flag combination can
# make this script copy or open a file the renderer did not write.
html=$(printf '%s\n' "$out" | sed -n 's/^wrote \(.*\.html\)$/\1/p' | tail -1)

if [ "$html" = "$committed_html" ]; then
  cp "$html" "$root/docs/index.html"
  echo "refreshed $root/docs/index.html (the live demo is a byte copy of this report)"
fi

if [ "$do_open" -eq 1 ] && [ -n "$html" ]; then
  if command -v open >/dev/null 2>&1; then
    open "$html"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$html"
  else
    echo "open it yourself: $html"
  fi
fi
