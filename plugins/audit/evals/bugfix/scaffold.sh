#!/bin/sh
# The bugfix case's scaffold: builds the fixture case.yaml's prompt is about, from
# the one builder both cases share (../build-shop.sh).
#
# ASSUMED, because the harness that runs this is not ours to read: `claude plugin
# eval --scaffold` calls it with NO arguments and with the case's EMPTY workspace as
# its working directory. When that does not hold it refuses, non-zero and saying
# why, rather than building over somebody's files: an argument is refused here, a
# working directory that is not empty by the builder.

if [ "$#" -ne 0 ]; then
  printf 'scaffold: takes no argument (got: %s); run it with the empty workspace as its working directory\n' "$*" >&2
  exit 2
fi

# Separators are normalised before the directory is cut off, as hooks/py-launch.sh
# does: a Windows caller may spell $0 with backslashes only.
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
builder=$here/../build-shop.sh
if [ ! -f "$builder" ]; then
  printf 'scaffold: the shared builder is not at %s; nothing was written\n' "$builder" >&2
  exit 2
fi

set -- bugfix
. "$builder"
