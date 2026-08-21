#!/bin/sh
# tools/redfirst.sh — break the thing a check guards, prove the check goes red,
# and put the file back in the same command.
#
#   tools/redfirst.sh <file> --replace <old> <new> [--render] -- <gate command...>
#
# Example:
#   tools/redfirst.sh plugins/audit/scripts/ui/report/areas.js \
#     --replace "syncAreaOptions();" "" --render -- \
#     node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html
#
# THE VERDICT IS INVERTED, and that is the whole point. A gate that stays GREEN
# while the thing it guards is broken is a gate asserting nothing, so green here is
# reported as FAILED and red is reported as ok. `CONTRIBUTING.md` has said "break it
# and confirm it goes red" for a long time; this makes that one command instead of
# six, which is why it kept being done by hand and occasionally not at all.
#
# RESTORE IS TRAPPED, not sequential. A mutation was stranded in the tree once when
# a run timed out between the edit and the restore, and the next hour was spent
# debugging a file nobody meant to change. The trap fires on EXIT, TERM and INT, so
# the only way to keep the mutation is to kill -9 this script.
#
# --render re-renders the committed artifacts after mutating, for gates that read a
# rendered file rather than the source. Without it, a source mutation is invisible
# to those gates and the run would report a green gate as a weak check.
set -u

here=$(dirname "$0")
root=$(cd "$here/.." && pwd)
cd "$root" || exit 2

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

[ $# -ge 5 ] || usage
FILE=$1; shift
[ -f "$FILE" ] || { echo "redfirst: no such file: $FILE" >&2; exit 2; }

OLD=""; NEW=""; RENDER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --replace) OLD=${2:-}; NEW=${3:-}; shift 3 ;;
    --render)  RENDER=1; shift ;;
    --)        shift; break ;;
    *)         echo "redfirst: unexpected argument $1" >&2; usage ;;
  esac
done
[ $# -ge 1 ] || usage
[ -n "$OLD" ] || { echo "redfirst: --replace needs a non-empty <old>" >&2; exit 2; }

BACKUP=$(mktemp "${TMPDIR:-/tmp}/redfirst-XXXXXX")
cp "$FILE" "$BACKUP"
restore() {
  cp "$BACKUP" "$FILE"
  if [ "$RENDER" -eq 1 ]; then sh examples/report.sh >/dev/null 2>&1 || true; fi
}
trap 'restore' EXIT TERM INT

# Exactly one occurrence, or the mutation is not the one described. A replace that
# hit three places proves nothing about which of them the gate noticed.
OLD="$OLD" NEW="$NEW" python3 - "$FILE" <<'PY' || exit 2
import io, os, sys
path = sys.argv[1]
old, new = os.environ["OLD"], os.environ["NEW"]
text = io.open(path, encoding="utf-8").read()
n = text.count(old)
if n != 1:
    sys.stderr.write("redfirst: %r occurs %d time(s) in %s - a mutation must be "
                     "exactly one place, or a red gate does not say which\n"
                     % (old, n, path))
    raise SystemExit(2)
io.open(path, "w", encoding="utf-8").write(text.replace(old, new))
PY

echo "redfirst: mutated $FILE"
if [ "$RENDER" -eq 1 ]; then
  printf 'redfirst: re-rendering artifacts... '
  if sh examples/report.sh >/dev/null 2>&1; then echo "ok"; else echo "FAILED"; fi
fi

echo "redfirst: running the gate (expecting it to go RED)"
"$@" >"${TMPDIR:-/tmp}/redfirst-gate.log" 2>&1
GATE=$?

restore
trap - EXIT TERM INT
if cmp -s "$BACKUP" "$FILE"; then
  RESTORED="restored byte-for-byte"
else
  RESTORED="NOT RESTORED — $FILE still differs from its backup at $BACKUP"
fi
rm -f "$BACKUP" 2>/dev/null

echo ""
if [ "$GATE" -eq 0 ]; then
  echo "REDFIRST FAILED: the gate stayed GREEN while the thing it guards was"
  echo "broken. The check is not asserting what it claims."
  echo "  file: $FILE ($RESTORED)"
  tail -12 "${TMPDIR:-/tmp}/redfirst-gate.log" | sed 's/^/      /'
  exit 1
fi
echo "REDFIRST ok: the gate went red (exit $GATE), so it does assert this."
echo "  file: $FILE ($RESTORED)"
grep -iE "^(FAIL|ERROR|  FAIL)" "${TMPDIR:-/tmp}/redfirst-gate.log" | head -4 | sed 's/^/      /'
exit 0
