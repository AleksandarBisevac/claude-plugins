#!/usr/bin/env python3
"""
The cases for `_panel_runstate.py` - the audit locks and their liveness, the
on-disk change stamp the poll watches, and the Plan gate card.

Moved out of `test__panel_state.py` at U3.1, with the code it covers. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _panel_paths as _paths                     # noqa: E402  (the shared base)
import _panel_runstate as M         # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import pathlib                                 # noqa: F401  (used by moved cases)
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer -- straight through `_manifest_io`,
        the implementation panel-server's `_atomic_write_json` delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-runstate-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_paths._config_path(proj), {"trivialLineThreshold": 40})
    mpath = _paths._manifest_path(proj, _paths.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    led = os.path.join(proj, ".claude", "usage")
    os.makedirs(led, exist_ok=True)
    with open(os.path.join(led, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for i, (model, author) in enumerate(
                (("claude-opus-5", "a@x.io"), ("claude-haiku-4-5", "b@x.io"))):
            fh.write(json.dumps({
                "ts": "2026-08-0%dT1%d" % (i + 1, i), "sessionId": "s%d" % i,
                "phaseId": "P1", "taskId": "P1.%d" % (i + 1), "attr": "task",
                "model": model, "author": author, "agentType": "audit-executor",
                "msgs": 2, "in": 5, "out": 100, "cacheW5m": 0, "cacheW1h": 0,
                "cacheR": 50, "costUSD": 0.25}) + "\n")
        fh.write("{ torn line\n")

    # --- the audit locks, and whether the run behind one is alive ---------------
    ld = os.path.join(tmp, "audit-locks")
    os.makedirs(ld)
    _atomic_write_json(os.path.join(ld, "index.lock"), {"hostname": "hi", "startedAt": "t"})
    _atomic_write_json(os.path.join(ld, "phase-P1.lock"), {"hostname": "hp", "startedAt": "t2"})
    li = M._lock_info(ld)
    check("_lock_info reads the index lock", (li["index"] or {}).get("hostname") == "hi")
    check("_lock_info reads a phase lock", (li["phases"].get("P1") or {}).get("hostname") == "hp")

    # C1 — the badge says "running", which is a claim about a live process.
    import platform as _pf
    import subprocess as _sp
    import time as _t
    _here = _pf.node()
    _old = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - 95 * 60))
    _atomic_write_json(os.path.join(ld, "phase-P2.lock"),
                       {"hostname": _here, "pid": os.getpid(), "startedAt": _old})
    _d = _sp.Popen([sys.executable, "-c", "pass"]); _d.wait()
    _atomic_write_json(os.path.join(ld, "phase-P3.lock"),
                       {"hostname": _here, "pid": _d.pid,
                        "startedAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())})
    li = M._lock_info(ld)
    check("lock verdict: a 95-min-old run with a live pid is live",
          li["phases"]["P2"].get("live") is True)
    check("lock verdict: a 1-min-old run whose pid is gone is not",
          li["phases"]["P3"].get("live") is False)
    check("lock verdict: each carries the basis behind it",
          bool(li["phases"]["P2"].get("liveBasis"))
          and bool(li["phases"]["P3"].get("liveBasis")))
    check("lock verdict: a pid-less lock gets one too (age fallback)",
          li["phases"]["P1"].get("live") is not None)
    os.remove(os.path.join(ld, "phase-P2.lock"))
    os.remove(os.path.join(ld, "phase-P3.lock"))
    # --- v0.34 C5 (lv): the data fingerprint -------------------------------------
    # Pure stats per request, folded into /api/runstatus so the existing 5s
    # poll carries it. The browser half (refreshFromDisk) is driven in
    # capture-screenshots.mjs --check.
    _fp1 = M.data_fingerprint(proj, M.read_config(proj))
    _fp2 = M.data_fingerprint(proj, M.read_config(proj))
    check("lv: the fingerprint is a pure stat - stable across two calls with "
          "nothing changed", isinstance(_fp1, str) and _fp1 and _fp1 == _fp2)
    # Change the SIZE, not only the mtime: coarse filesystems round mtime to a
    # second, and a rewrite inside that second would otherwise stamp equal.
    _m_orig = open(mpath, encoding="utf-8").read()
    try:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig + " ")
        check("lv: a manifest rewrite moves it",
              M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    finally:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig)
    _c_orig = open(M._config_path(proj), encoding="utf-8").read()
    try:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig + " ")
        check("lv: a config write moves it (manifestPath/ledgerDir live there, "
              "so the config file is stamped FIRST)",
              M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    finally:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig)
    with open(os.path.join(led, "2026-08.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-08-03T10", "sessionId": "s9",
                             "model": "m", "msgs": 1, "in": 1, "out": 1,
                             "costUSD": 0.0}) + "\n")
    check("lv: a ledger append moves it (newest *.jsonl stat)",
          M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    # Sharded: every shard body is stamped, so a phase edit that never touches
    # the index still moves the stamp.
    _lvproj = tempfile.mkdtemp(prefix="state-lv-")
    try:
        _atomic_write_json(M._config_path(_lvproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _lvm = M._manifest_path(_lvproj, M.read_config(_lvproj))
        os.makedirs(os.path.dirname(_lvm), exist_ok=True)
        _mio.save_sharded(_lvm, {
            "meta": {"version": 3},
            "phases": [{"id": "P1", "title": "One", "status": "pending",
                        "tasks": [{"id": "P1.1", "title": "T",
                                   "status": "pending"}]}]})
        _lv1 = M.data_fingerprint(_lvproj, M.read_config(_lvproj))
        with open(os.path.join(os.path.dirname(_lvm), "phases", "P1.json"),
                  "a", encoding="utf-8") as fh:
            fh.write(" ")
        check("lv: a sharded phase body moves it without the index changing",
              M.data_fingerprint(_lvproj, M.read_config(_lvproj)) != _lv1)
    finally:
        shutil.rmtree(_lvproj, ignore_errors=True)
    _lvmiss = os.path.join(tmp, "lv-nothing-here")
    check("lv: missing everything is a stable sentinel, never a raise",
          M.data_fingerprint(_lvmiss, {}) == M.data_fingerprint(_lvmiss, {})
          and isinstance(M.data_fingerprint(_lvmiss, {}), str))
    check("lv: the fingerprint rides /api/runstatus's payload - with and "
          "without a manifest - so the existing poll carries it for free "
          "while it stays OUT of runStatusKey (a moved stamp hands off to "
          "refreshFromDisk instead of repainting)",
          isinstance(M._run_status(proj, M.read_config(proj), {})
                     .get("fingerprint"), str)
          and isinstance(M._run_status(_lvmiss, {}, {}).get("fingerprint"), str))
    check("lv: SSE is weighed and rejected in prose where the stamp is "
          "defined, so the next person does not re-litigate it blind",
          "SSE" in (M.data_fingerprint.__doc__ or ""))

    # --- v0.34 B3 (gt): the Plan gate block on /api/runstatus --------------------
    # Tier + why, bypass-armed, and the tail of the gate events feed - the
    # panel's Overview card is fed from here, so the server computes the tier
    # with the hooks' own functions rather than letting the browser guess.
    _gtcfg = _paths.hooks_config()
    _gt = M._run_status(proj, M.read_config(proj), {}).get("gate")
    check("gt: runstatus carries a gate block with the tier and its source",
          isinstance(_gt, dict) and _gt.get("mode") in ("observe", "warn",
                                                        "ask", "deny")
          and bool(_gt.get("source")) and isinstance(_gt.get("events"), list)
          and _gt.get("bypassArmed") is False)
    check("gt: a pinned planGate names the knob as the source, tier included",
          (M._run_status(proj, {"planGate": "ask"}, {}).get("gate") or {})
          .get("mode") == "ask"
          and "planGate" in str((M._run_status(proj, {"planGate": "ask"}, {})
                                 .get("gate") or {}).get("source")))
    check("gt: legacy enforce:true is named as legacy, not as evidence",
          "legacy" in str((M._run_status(proj, {"enforce": True}, {})
                           .get("gate") or {}).get("source")))
    for _i in range(25):
        _gtcfg.append_gate_event(os.path.join(proj, ".claude", "logs"),
                                 {"event": "observe", "file": "f%d.ts" % _i,
                                  "sessionId": "gt"})
    _gt = M._run_status(proj, M.read_config(proj), {}).get("gate") or {}
    check("gt: the events table is the feed's tail, newest first, capped at 20",
          len(_gt.get("events") or []) == 20
          and _gt["events"][0].get("file") == "f24.ts"
          and _gt["events"][-1].get("file") == "f5.ts")
    _gtsd = os.path.join(proj, ".claude", "state")
    os.makedirs(_gtsd, exist_ok=True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())}, fh)
    check("gt: a live bypass slot flips the armed indicator",
          (M._run_status(proj, M.read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())
                   - _gtcfg.BYPASS_TTL_SECONDS - 60}, fh)
    check("gt: an EXPIRED slot does not count as armed - the card must not "
          "claim a bypass require-plan would refuse",
          (M._run_status(proj, M.read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is False)
    os.unlink(os.path.join(_gtsd, "plan-bypass-gt.json"))
    check("gt: a project with nothing on disk still gets a gate block, never "
          "a raise",
          isinstance(M._run_status(_lvmiss, {}, {}).get("gate"), dict))

    # --- F113 (rd): what the `file` cell is allowed to say on a screen -----------
    # `audit-logs.py prune` counts an out-of-repository row by CLASS and never
    # echoes its path; this card rendered the same rows verbatim - the operator's
    # user name, the temp root and the session slug, in the one card
    # `docs/screenshots/panel-gate.png` is a committed render of, and
    # `tools/check-committed-pii.py` cannot read a PNG.
    #
    # The fixture's marker is a segment that appears NOWHERE else in the payload,
    # so these count it instead of looking for the token - a fix that tokenised
    # only some rows would still produce the token, and a presence check would
    # call that clean.
    import _journal_io as _jio                     # the redactor, and its token
    _rdmark = "zz-operator-9f3c"
    _rdlogs = os.path.join(proj, ".claude", "logs")
    _gtcfg.append_gate_event(_rdlogs, {
        "event": "deny", "file": "../%s/fetched-empty.json" % _rdmark,
        "reason": "require-plan: no plan", "sessionId": "rd"})
    _gtcfg.append_gate_event(_rdlogs, {
        "event": "observe", "file": os.path.join(proj, "src", "inside-abs.ts"),
        "sessionId": "rd"})
    _gtcfg.append_gate_event(_rdlogs, {
        "event": "ask.shown", "file": "src/inside-rel.ts", "sessionId": "rd"})
    _gtcfg.append_gate_event(_rdlogs, {
        "event": "deny", "file": "grep -r secret src", "sessionId": "rd"})
    _gtcfg.append_gate_event(_rdlogs, {"event": "observe", "sessionId": "rd"})
    _rdgate = M._run_status(proj, M.read_config(proj), {}).get("gate") or {}
    _rdblob = json.dumps(_rdgate, sort_keys=True)
    _rdfiles = [e.get("file") for e in _rdgate.get("events") or []]
    check("rd: an out-of-repo row's file cell leaves as the journal's token, and "
          "the path it named reaches the payload nowhere at all",
          _rdblob.count(_rdmark) == 0
          and _rdblob.count(_jio.OUTSIDE_TOKEN) == 1
          and _jio.OUTSIDE_TOKEN in _rdfiles)
    check("rd: an absolute INSIDE path is collapsed to repo-relative, so the "
          "directories above the repository are not painted either",
          "src/inside-abs.ts" in _rdfiles
          and _rdblob.count("inside-abs.ts") == 1
          and os.path.realpath(proj) not in _rdblob)
    check("rd: the redaction does not narrow to nothing - a relative in-repo "
          "path and the command-shaped cell guard-secrets-read writes both "
          "survive verbatim",
          "src/inside-rel.ts" in _rdfiles
          and "grep -r secret src" in _rdfiles)
    check("rd: a row that named no file is passed through rather than stamped "
          "with a token it never earned",
          any("file" not in e for e in _rdgate.get("events") or []))
    check("rd: the rule IS the journal's own function - a token spelled here "
          "would be a second redactor free to disagree with the committed rows "
          "(the last clause is a property of the source, and only source can "
          "check it)",
          M._redacted_event(proj, {"file": "../elsewhere/x"})["file"]
          == _jio.OUTSIDE_TOKEN
          and M._redacted_event(proj, {"file": "   "}) == {"file": "   "}
          and "_journal_io.repo_relative_or_token" in _src)

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_runstate.py --selftest\n")
    raise SystemExit(2)
