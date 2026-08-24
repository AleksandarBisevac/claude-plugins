#!/usr/bin/env python3
"""
The cases for `status/audit-logs.py` - the `/audit:logs` door.

The RULE has its own suite (`test__gate_feed.py`); what is proven here is the
part a user actually meets. Two properties carry most of it:

  * BOTH COUNTS PRINT, ALWAYS. The command exists because somebody could not tell
    what the plugin had done to a file, so "removed" and "kept" appear at zero
    exactly as they appear at three. The cases count OCCURRENCES of each label
    across a zero run and a non-zero run rather than asserting either is present,
    because a render that dropped a zero row would still contain the other label.
  * THE REMOVED PATH IS NEVER ECHOED. A prune's whole point is to clear
    out-of-repository paths out of a file this plugin displays; printing them
    into the terminal transcript on the way out puts them back. `al5` drives a
    real prune over a real fixture and counts the path in the render.

The module is hyphenated, so it comes through `_loader.load_script` by basename.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _gate_feed                                  # noqa: E402

M = _loader.load_script("audit-logs.py", modname="audit_logs")


def _row(**kw):
    row = {"ts": kw.pop("ts", "2026-08-20T10:00:00Z")}
    row.update(kw)
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def _project(parent, lines=None):
    """A project whose feed holds `lines`; None means the gate never wrote."""
    proj = Path(tempfile.mkdtemp(prefix="audit-logs-", dir=str(parent)))
    if lines is not None:
        logs = proj / ".claude" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "plan-gate-events.jsonl").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8")
    return proj


def _cases(check):
    tmp = Path(tempfile.mkdtemp(prefix="audit-logs-selftest-"))
    outside = Path(tempfile.mkdtemp(prefix="audit-logs-outside-"))
    try:
        _cases_body(check, tmp, outside)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        shutil.rmtree(str(outside), ignore_errors=True)


def _cases_body(check, tmp, outside):
    inside_row = _row(event="deny", file="src/app.ts", reason="not covered")
    outside_row = _row(event="deny", file=str(outside / "probe.py"),
                       reason="not covered")

    # ----------------------------------------------------------- both at zero
    empty_proj = _project(tmp, lines=[])
    zero = M.render(_gate_feed.prune(str(empty_proj)), str(empty_proj))
    check("al1 a run that removed nothing from an empty feed still prints BOTH "
          "counts, once each, at zero - a number that shows up only when it is "
          "non-zero cannot be told from a number nobody computed:\n%s" % zero,
          zero.count("removed      0") == 1 and zero.count("kept         0") == 1)

    dirty_proj = _project(tmp, lines=[inside_row, outside_row, "junk"])
    busy = M.render(_gate_feed.prune(str(dirty_proj), dry_run=True),
                    str(dirty_proj))
    check("al2 ...and a run that WOULD remove rows prints the same two labels, "
          "so the zero render above is the same report with different numbers "
          "rather than a different report:\n%s" % busy,
          busy.count("would remove 2") == 1 and busy.count("would keep   1") == 1)
    check("al3 --dry-run says so, and says the feed was not rewritten - the "
          "counts alone would read exactly like a prune that had already "
          "happened", busy.count("--dry-run: the feed was NOT rewritten.") == 1
          and busy.count("The feed was rewritten.") == 0)

    # ------------------------------------------------- no feed vs empty feed
    never = _project(tmp, lines=None)
    unwritten = M.render(_gate_feed.prune(str(never)), str(never))
    check("al4 'the gate has never written here' and 'the feed is empty' are "
          "different sentences, though both report zero and zero - the render "
          "must not merge the two:\n%s" % unwritten,
          unwritten.count("no feed yet") == 1
          and zero.count("no feed yet") == 0 and zero.count("present") == 1)

    # -------------------------------------------------- the path is not echoed
    echo_proj = _project(tmp, lines=[inside_row, outside_row])
    before = (echo_proj / ".claude" / "logs"
              / "plan-gate-events.jsonl").read_text(encoding="utf-8")
    echoed = M.render(_gate_feed.prune(str(echo_proj)), str(echo_proj))
    # TWO HAYSTACKS, TWO SPELLINGS, and using one needle for both was the bug.
    # The feed is JSON, so the path is there in the encoder's spelling
    # (`_harness.in_json`); the render is prose, so it would be there natively.
    # On POSIX those are the same string and this case is unchanged; on windows
    # the `== 1` half was looking for a spelling no encoder emits, and the `== 0`
    # half passed by looking for the same absent thing. The render is now counted
    # BOTH ways: a render that echoed a raw feed line carries the JSON spelling,
    # one that echoed a parsed `file` field carries the native one, and neither
    # may appear.
    check("al5 the removed path occurs 0 times in the render, where it occurred "
          "once in the feed - a prune that prints what it deleted writes the "
          "out-of-repository path straight back into the transcript:\n%s"
          % echoed,
          before.count(_harness.in_json(str(outside))) == 1
          and echoed.count(str(outside)) == 0
          and echoed.count(_harness.in_json(str(outside))) == 0)
    check("al6 ...and the COUNT is there instead, so the reader is told what "
          "went without being shown it - the class is the report, not the row",
          echoed.count("outside this repository 1") == 1)

    # ----------------------------------------------------------- the age basis
    check("al7 with no threshold the render SAYS age was not applied, rather "
          "than printing an aged-out count of zero that no flag asked for - a "
          "count with no basis is the claim this repo refuses",
          echoed.count("not applied - pass --older-than DAYS") == 1
          and echoed.count("older than ") == 0)
    aged_proj = _project(tmp, lines=[_row(ts="1970-01-02T00:00:00Z",
                                          event="deny", file="src/old.ts")])
    aged = M.render(_gate_feed.prune(str(aged_proj), older_than_days=1),
                    str(aged_proj))
    check("al8 ...and when a threshold IS given the class prints WITH the "
          "number that produced it, and the 'not applied' line is gone:\n%s"
          % aged,
          aged.count("older than 1 day(s) 1") == 1
          and aged.count("not applied") == 0)

    # ----------------------------------------------------------- exit codes
    script = os.path.join(_harness.SCRIPTS_DIR, "status", "audit-logs.py")

    def run(*args):
        return subprocess.run([sys.executable, script] + list(args),
                              capture_output=True, text=True)

    live = _project(tmp, lines=[inside_row, outside_row])
    ok = run("prune", "--project", str(live))
    feed_after = (live / ".claude" / "logs"
                  / "plan-gate-events.jsonl").read_text(encoding="utf-8")
    check("al9 the command exits 0 when the prune ran, and the file on disk "
          "really changed - an exit code proves nothing on its own: %r"
          % (ok.returncode, ),
          ok.returncode == 0 and feed_after == inside_row + "\n")

    js = run("prune", "--project", str(live), "--json")
    parsed = json.loads(js.stdout) if js.returncode == 0 else {}
    check("al10 --json emits the rule's whole result, keys and all, so a caller "
          "reading the machine form is not handed a narrower answer than the "
          "human one: %r" % (sorted(parsed),),
          sorted(parsed) == sorted(["ok", "findings", "path", "exists", "kept",
                                    "removed", "classes", "olderThanDays",
                                    "dryRun", "wrote"]))

    bad_dir = run("prune", "--project", str(live / "nope"))
    check("al11 a --project that is not a directory is a USAGE error (2), not a "
          "refusal and not a silent zero: %r" % (bad_dir.returncode,),
          bad_dir.returncode == 2 and bad_dir.stdout == "")
    bad_days = run("prune", "--project", str(live), "--older-than", "0")
    check("al12 ...and so is --older-than 0, which would otherwise mean 'remove "
          "every row with a readable stamp' - the one threshold nobody types on "
          "purpose: %r" % (bad_days.returncode,),
          bad_days.returncode == 2 and bad_days.stdout == "")
    good_days = run("prune", "--project", str(live), "--older-than", "1")
    check("al13 ...while 1 is accepted, which is what says al12 refuses the "
          "VALUE rather than the flag: %r" % (good_days.returncode,),
          good_days.returncode == 0)
    no_verb = run("--project", str(live))
    check("al14 the verb is required - a bare invocation exits 2 rather than "
          "pruning by default, because this command writes: %r"
          % (no_verb.returncode,), no_verb.returncode == 2)

    # ------------------------------------------------------------- a refusal
    refusal = {"ok": False, "findings": ["logsDir is a symlink"], "path": None,
               "exists": False, "kept": 0, "removed": 0,
               "classes": dict((n, 0) for n in _gate_feed.CLASSES),
               "olderThanDays": None, "dryRun": False, "wrote": False}
    refused = M.render(refusal, str(live))
    check("al15 a refusal renders the reason and says plainly that nothing was "
          "written - the failure mode this replaces is a command that prints "
          "counts after refusing and reads like a successful prune:\n%s"
          % refused,
          refused.count("logsDir is a symlink") == 1
          and refused.count("Nothing was read and nothing was written.") == 1
          and refused.count("removed") == 0 and refused.count("kept") == 0)

    # al16 drives a REAL refusal all the way through `main`, because al15 renders
    # a hand-built one and so says nothing about the exit code - the half a caller
    # in CI actually reads.
    linked = _project(tmp, lines=None)
    llogs = linked / ".claude" / "logs"
    llogs.mkdir(parents=True, exist_ok=True)
    far = outside / "hijacked-by-cli.jsonl"
    far.write_text(outside_row + "\n", encoding="utf-8")
    try:
        os.symlink(str(far), str(llogs / "plan-gate-events.jsonl"))
        made = True
    except (OSError, NotImplementedError, AttributeError):
        made = False
    if not made:
        print("SKIP al16 (this platform will not create a symlink here)")
    else:
        far_before = far.read_bytes()
        refused_run = run("prune", "--project", str(linked))
        check("al16 a refusal exits 1, prints the reason, and leaves the file "
              "on the far end of the link byte-identical - an exit code that "
              "always reads 0 is a CI gate that never fails: %r"
              % ((refused_run.returncode, refused_run.stdout),),
              refused_run.returncode == 1
              and refused_run.stdout.count("REFUSED") == 1
              and far.read_bytes() == far_before)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_logs.py --selftest\n")
    raise SystemExit(2)
