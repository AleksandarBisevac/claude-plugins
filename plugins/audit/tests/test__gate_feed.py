#!/usr/bin/env python3
"""
The cases for `status/_gate_feed.py` - the plan-gate feed's prune rule.

TWO THINGS ARE PROVEN HERE, and they fail apart. The first is the
CLASSIFICATION: which rows no longer belong, counted by class, with every
positive paired against a negative over the SAME fixture so a case cannot be
green because the whole file was dropped. The second is the BLAST RADIUS: the
one file this module may rewrite is derived from the writer's own `logs_dir()` +
`GATE_EVENTS_FILE`, and `gf12` proves that by driving the REAL writer
(`_config.append_gate_event`) and asserting the pruner names the file it just
created - a hand-built path would agree with a hand-built expectation forever.

Counts, never presence: a class that went from one to nought is the only thing
that says a row was removed rather than merely absent, and a sibling file whose
bytes are identical before and after is the only thing that says the prune
stayed inside its one file.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _config                                     # noqa: E402
import _gate_feed as M                             # noqa: E402


# --- fixtures -----------------------------------------------------------------
def _row(**kw):
    """One feed line, spelled the way `append_gate_event` spells one."""
    row = {"ts": kw.pop("ts", "2026-08-20T10:00:00Z")}
    row.update(kw)
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def _write_feed(project, lines):
    path = Path(project) / ".claude" / "logs" / "plan-gate-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = Path(tempfile.mkdtemp(prefix="gate-feed-selftest-"))
    outside = Path(tempfile.mkdtemp(prefix="gate-feed-outside-"))
    try:
        _cases_body(check, tmp, outside)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        shutil.rmtree(str(outside), ignore_errors=True)


def _cases_body(check, tmp, outside):
    inside_row = _row(event="deny", file="src/app.ts", reason="not covered")
    outside_row = _row(event="deny", file=str(outside / "probe.py"),
                       reason="not covered")
    second_inside = _row(event="warn", file="src/other.ts", reason="advisory")
    # THE FEED IS JSON, so a path counted IN it is counted in the spelling the
    # encoder wrote. `str(outside)` is that spelling on POSIX and is not on
    # windows, where a separator arrives doubled - which took gf17's `== 1` half
    # red and left its `== 0` half green over a needle no encoder can emit.
    # `_harness.in_json` is json.dumps with the quotes off, so the two halves are
    # asking about bytes that are really there. The reason strings below stay on
    # `str(outside)`: prose quotes a path natively.
    outside_json = _harness.in_json(str(outside))

    # ---------------------------------------------------------- classification
    # gf1/gf2 are one fixture and one substitution: the SECOND row is the only
    # difference between them, so "the out-of-repo row went" and "everything went"
    # cannot both explain the pair.
    mixed = M.classify(str(tmp), [inside_row, outside_row])
    check("gf1 an out-of-repository row is removed and the in-repository row "
          "over the SAME fixture is kept - counted, so a rule that dropped both "
          "rows would fail here rather than look like a clean prune: %r"
          % (mixed,),
          mixed["removed"] == 1 and mixed["kept"] == 1
          and mixed["classes"][M.CLASS_OUTSIDE] == 1
          and mixed["keep"] == [inside_row])

    both_in = M.classify(str(tmp), [inside_row, second_inside])
    check("gf2 ...and the same fixture with the second row pointing INSIDE "
          "removes nothing: the verdict is about the path, not about being the "
          "second line: %r" % (both_in,),
          both_in["removed"] == 0 and both_in["kept"] == 2
          and both_in["classes"][M.CLASS_OUTSIDE] == 0)

    junk = M.classify(str(tmp), [inside_row, "not json at all", "", "[1,2]"])
    check("gf3 a line that is not a JSON OBJECT is its own class, counted "
          "apart from the path class - three shapes reach it (not JSON, empty, "
          "JSON that is not an object) and none of them is scored as "
          "out-of-repository: %r" % (junk,),
          junk["classes"][M.CLASS_UNREADABLE] == 3
          and junk["classes"][M.CLASS_OUTSIDE] == 0
          and junk["kept"] == 1)

    nofile = M.classify(str(tmp), [_row(event="bypass.armed", reason="#no-plan")])
    check("gf4 a row with no `file` at all is KEPT - `detect-plan-skip` writes "
          "one for every armed bypass, and a rule that removed what it could "
          "not judge would silently eat the bypass history: %r" % (nofile,),
          nofile["kept"] == 1 and nofile["removed"] == 0)

    commandish = M.classify(str(tmp), [
        _row(event="deny", file="grep -rn SECRET .", reason="guard-secrets-read"),
        _row(event="ask.shown", file="**/*.env", reason="guard-secrets-read")])
    check("gf5 a `file` that is a shell command or a glob is kept: "
          "guard-secrets-read puts those in that field, they are relative "
          "spellings, and the question asked is whether a row names somewhere "
          "OUTSIDE this repository: %r" % (commandish,),
          commandish["kept"] == 2 and commandish["removed"] == 0)

    every_class = M.classify(str(tmp), [inside_row])
    check("gf6 every class is reported, including the ones at zero - a count "
          "that appears only when it is non-zero cannot be told from a count "
          "nobody computed: %r" % (every_class["classes"],),
          sorted(every_class["classes"]) == sorted(M.CLASSES)
          and set(every_class["classes"].values()) == set([0]))

    # ------------------------------------------------------------------- age
    # THE FIXTURE IS STAMPED IN 1970 AND READ AGAINST THE REAL CLOCK, and that
    # is what makes gf7 an assertion rather than a wish. A row ten days old
    # survives a hypothetical 30-day default too, so a case built that way is
    # green against the very implementation it is meant to refuse. Nothing
    # anyone would ship as a default outlives half a century.
    old_row = _row(ts="1970-01-02T00:00:00Z", event="deny", file="src/old.ts")
    no_age = M.classify(str(tmp), [old_row])
    check("gf7 age is OFF unless a threshold is named: a row from 1970 is kept, "
          "because the feed already self-trims by SIZE and an old verdict is "
          "still a true record of this repository: %r" % (no_age,),
          no_age["kept"] == 1 and no_age["classes"][M.CLASS_AGED] == 0)
    aged = M.classify(str(tmp), [old_row], older_than_days=1)
    check("gf8 ...and the SAME row goes once a threshold is named, scored under "
          "its own class rather than folded into the total: %r" % (aged,),
          aged["removed"] == 1 and aged["classes"][M.CLASS_AGED] == 1
          and aged["kept"] == 0)
    no_ts = M.classify(str(tmp), [_row(ts="whenever", event="deny",
                                       file="src/a.ts")],
                       older_than_days=1)
    check("gf9 a row whose `ts` cannot be read is never aged out: 'old' is a "
          "claim about when it was written, and without a readable stamp there "
          "is no basis for it: %r" % (no_ts,),
          no_ts["kept"] == 1 and no_ts["classes"][M.CLASS_AGED] == 0)

    both = M.classify(str(tmp),
                      [_row(ts="1970-01-02T00:00:00Z", event="deny",
                            file=str(outside / "old-probe.py"))],
                      older_than_days=1)
    check("gf10 a row that is BOTH outside and old is counted ONCE, in the "
          "first class it falls into - which is what lets a reader add the "
          "class counts up to the removed total: %r" % (both,),
          both["removed"] == 1 and both["classes"][M.CLASS_OUTSIDE] == 1
          and both["classes"][M.CLASS_AGED] == 0
          and sum(both["classes"].values()) == both["removed"])

    # ------------------------------------------------------------ blast radius
    wp = Path(tempfile.mkdtemp(prefix="gate-feed-writer-", dir=str(tmp)))
    logs = _config.logs_dir(wp, _config.DEFAULTS)
    _config.append_gate_event(logs, {"event": "deny", "file": "src/w.ts",
                                     "reason": "written by the real writer"})
    written = str(Path(str(logs)) / _config.GATE_EVENTS_FILE)
    path, refusal = M.feed_path(str(wp))
    check("gf11 the file this module may rewrite IS the file the gate appends "
          "to - proven by driving `_config.append_gate_event` and comparing, "
          "not by two hand-built paths agreeing with each other: %r"
          % ((path, refusal),),
          refusal is None and os.path.isfile(written)
          and os.path.realpath(path) == os.path.realpath(written))

    # ---------------------------------------------------------------- refusal
    sp = Path(tempfile.mkdtemp(prefix="gate-feed-link-", dir=str(tmp)))
    slogs = sp / ".claude" / "logs"
    slogs.mkdir(parents=True, exist_ok=True)
    elsewhere = outside / "hijacked.jsonl"
    # A row the pruner WOULD remove, on purpose: with an out-of-repository row on
    # the far end, an implementation that followed the link REWRITES - which is
    # what gf13's `islink` sees go. A far file holding only in-repo rows would
    # leave gf13 green under exactly the defect it exists to catch.
    elsewhere.write_text(_row(event="deny", file=str(outside / "far.py")) + "\n",
                         encoding="utf-8")
    try:
        os.symlink(str(elsewhere), str(slogs / _config.GATE_EVENTS_FILE))
        linked = True
    except (OSError, NotImplementedError, AttributeError):
        linked = False
    if not linked:
        print("SKIP gf12-gf14 (this platform will not create a symlink here)")
    else:
        before = elsewhere.read_bytes()
        res = M.prune(str(sp))
        check("gf12 a feed that is a symlink OUT of logsDir is REFUSED, not "
              "followed: the gate appends through the link, and os.replace "
              "would swap the link for a file and send the feed somewhere the "
              "gate does not write: %r" % (res,),
              res["ok"] is False and len(res["findings"]) == 1
              and res["path"] is None and res["wrote"] is False)
        check("gf13 ...and the file on the far end is byte-identical "
              "afterwards, which is the only thing that says the refusal is a "
              "refusal rather than a message printed after the write",
              elsewhere.read_bytes() == before
              and os.path.islink(str(slogs / _config.GATE_EVENTS_FILE)))
        # `(… or [""])[0]` rather than `[0]`: an implementation that stops
        # refusing has no findings, and an IndexError here would abort the suite
        # instead of reporting this case red - which is how gf15 below and every
        # case after it would silently stop being run.
        reason = (res["findings"] or [""])[0]
        # `str(slogs)` and not the literal `.claude/logs`: the reason renders a
        # path the OS spelled, and on the windows runner that is `\.claude\logs`
        # - a POSIX separator in the needle made this case red for the one thing
        # it was not asking about. Naming the fixture's own directory is the
        # STRONGER form as well as the portable one: the literal was satisfied by
        # any project's logsDir, this is satisfied only by THIS one's.
        check("gf14 ...and the reason names logsDir and NOT the resolved "
              "destination, which occurs 0 times in it - a refusal that quotes "
              "the outside path has published the thing it refused to touch: "
              "%r" % (res["findings"],),
              reason.count(str(elsewhere)) == 0
              and reason.count(str(outside)) == 0
              and reason.count(str(slogs)) == 1)
        check("gf15 ...and a refusal still carries both counts, at zero, "
              "beside every class - a caller must never tell 'nothing was "
              "removed' from 'the counts were not computed' by which keys "
              "exist: %r" % (res,),
              res["kept"] == 0 and res["removed"] == 0
              and sorted(res["classes"]) == sorted(M.CLASSES))

    # ------------------------------------------------------------------ prune
    pp = Path(tempfile.mkdtemp(prefix="gate-feed-prune-", dir=str(tmp)))
    feed = _write_feed(pp, [inside_row, outside_row, second_inside])
    sibling = feed.parent / "plan-bypass.log"
    sibling.write_text("armed once\n", encoding="utf-8")
    sib_before = sibling.read_bytes()
    raw_before = feed.read_bytes()

    dry = M.prune(str(pp), dry_run=True)
    check("gf16 --dry-run computes the same counts and writes nothing: the "
          "feed's bytes are identical afterwards, so the counts are not a "
          "report of a write that already happened: %r" % (dry,),
          dry["removed"] == 1 and dry["kept"] == 2 and dry["wrote"] is False
          and feed.read_bytes() == raw_before)

    real = M.prune(str(pp))
    kept_text = feed.read_text(encoding="utf-8")
    check("gf17 the real prune rewrites the feed to exactly the kept rows, in "
          "order, each once - and the removed row occurs 0 times in the file "
          "afterwards where it occurred once before: %r" % (real,),
          real["wrote"] is True and real["removed"] == 1
          and kept_text == inside_row + "\n" + second_inside + "\n"
          and kept_text.count(outside_json) == 0
          and raw_before.decode("utf-8").count(outside_json) == 1)
    check("gf18 ...and nothing else in logsDir was touched: the sibling "
          "`plan-bypass.log` is byte-identical, which is what says the blast "
          "radius is one file and not one directory",
          sibling.read_bytes() == sib_before)

    again = M.prune(str(pp))
    check("gf19 a second prune removes nothing AND writes nothing - `wrote` is "
          "False rather than True-with-identical-bytes, so a prune that changes "
          "nothing cannot be mistaken for a gate event by anything watching the "
          "mtime: %r" % (again,),
          again["removed"] == 0 and again["kept"] == 2
          and again["wrote"] is False and again["ok"] is True)

    # gf20/gf21: the empty-file shapes. `"\n".join([]) + "\n"` is a blank line,
    # which the NEXT prune scores as unreadable - so an all-removed feed has to
    # come out at zero bytes, and the proof is the second prune's own counts.
    ep = Path(tempfile.mkdtemp(prefix="gate-feed-empty-", dir=str(tmp)))
    efeed = _write_feed(ep, [outside_row])
    wiped = M.prune(str(ep))
    check("gf20 a feed whose every row goes becomes an EMPTY file, not a blank "
          "line, and the file is still there: %r"
          % (efeed.read_bytes(),),
          wiped["removed"] == 1 and wiped["kept"] == 0
          and efeed.is_file() and efeed.read_bytes() == b"")
    after_wipe = M.prune(str(ep))
    check("gf21 ...proven by the next prune, which finds nothing unreadable - "
          "the case a trailing newline would have failed: %r" % (after_wipe,),
          after_wipe["classes"][M.CLASS_UNREADABLE] == 0
          and after_wipe["removed"] == 0 and after_wipe["kept"] == 0
          and after_wipe["exists"] is True)

    # gf22/gf23: zero and zero mean two different things, and only `exists`
    # separates them.
    np_ = Path(tempfile.mkdtemp(prefix="gate-feed-none-", dir=str(tmp)))
    missing = M.prune(str(np_))
    check("gf22 a project whose gate has never written reports both counts at "
          "zero and `exists` False, with the path still named so the reader "
          "knows where it WOULD be: %r" % (missing,),
          missing["ok"] is True and missing["kept"] == 0
          and missing["removed"] == 0 and missing["exists"] is False
          and missing["path"] is not None)
    _write_feed(np_, [])
    empty = M.prune(str(np_))
    check("gf23 ...while an EMPTY feed reports the same two zeros with `exists` "
          "True. Without that field the two are one answer, and this command "
          "exists because somebody could not tell what the plugin had done to a "
          "file: %r" % (empty,),
          empty["kept"] == 0 and empty["removed"] == 0
          and empty["exists"] is True)

    # gf24: logsDir is read from the project's config rather than assumed, so a
    # project that moved it is pruned where it actually writes.
    mp = Path(tempfile.mkdtemp(prefix="gate-feed-cfg-", dir=str(tmp)))
    (mp / ".claude").mkdir(parents=True, exist_ok=True)
    (mp / ".claude" / "audit.config.json").write_text(
        json.dumps({"logsDir": "var/audit-logs"}), encoding="utf-8")
    moved = mp / "var" / "audit-logs"
    moved.mkdir(parents=True, exist_ok=True)
    (moved / _config.GATE_EVENTS_FILE).write_text(outside_row + "\n",
                                                  encoding="utf-8")
    default_place = mp / ".claude" / "logs" / _config.GATE_EVENTS_FILE
    default_place.parent.mkdir(parents=True, exist_ok=True)
    default_place.write_text(outside_row + "\n", encoding="utf-8")
    movedres = M.prune(str(mp))
    check("gf24 logsDir comes from the project's own config: the moved feed is "
          "pruned and the file sitting at the DEFAULT location is left alone, "
          "which is the pair that tells 'read the config' from 'happened to "
          "guess right': %r" % (movedres,),
          movedres["removed"] == 1
          and (moved / _config.GATE_EVENTS_FILE).read_bytes() == b""
          and default_place.read_text(encoding="utf-8").count(
              outside_json) == 1)

    # gf25: THE SPELLING THE FEED ITSELF IMPOSES, pinned on every platform.
    # gf17/gf24 above count an out-of-repository path in feed BYTES, and on POSIX
    # `str(path)` and `_harness.in_json(str(path))` are the same string - so the
    # needle being wrong is invisible here and shows up only on the windows
    # runner, which is exactly how it shipped: the `== 1` half went red there and
    # the `== 0` half passed by looking for something no encoder can emit. The
    # `file` field carries whatever the gate was handed, and on windows that is a
    # native path, so a row holding a BACKSLASH is the ordinary case there and a
    # legal one here. Counted both ways over one fixture: the escaped spelling is
    # in the file, the raw spelling is not, and the row still goes.
    bp = Path(tempfile.mkdtemp(prefix="gate-feed-escape-", dir=str(tmp)))
    backslashed = str(outside) + "\\weird" + os.sep + "probe.py"
    bfeed = _write_feed(bp, [inside_row, _row(event="deny", file=backslashed)])
    braw = bfeed.read_text(encoding="utf-8")
    bres = M.prune(str(bp))
    check("gf25 a row naming an out-of-repository path that JSON must ESCAPE is "
          "removed like any other, and the feed held it in the encoder's "
          "spelling and not in the raw one - which is the difference a POSIX-only "
          "run cannot see: %r" % (braw,),
          bres["removed"] == 1 and bres["kept"] == 1
          and braw.count(_harness.in_json(backslashed)) == 1
          and braw.count(backslashed) == 0
          and bfeed.read_text(encoding="utf-8") == inside_row + "\n")


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__gate_feed.py --selftest\n")
    raise SystemExit(2)
