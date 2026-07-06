#!/usr/bin/env python3
"""
Plan-first enforcement — registered under BOTH PreToolUse and PostToolUse
(matcher: Edit|Write|MultiEdit|NotebookEdit).

Enforces a "Plan-first development" workflow: a non-trivial code change must be
planned via a task in the audit manifest and executed through /audit, OR opted out
for a single change with the bypass keyword (armed by detect-plan-skip.py).

This is the PLUGIN version — every project-specific value comes from the consuming
repo's `.claude/audit.config.json` (loaded by _config.py) with safe defaults:
  manifestPath, exemptGlobs, trivialLineThreshold, stateDir, logsDir, bypassKeyword.

Decision order (ALLOW = exit 0; BLOCK = stderr msg + exit 2, PreToolUse only):
  1. No file_path / unknown tool / parse error → ALLOW (never break legit work).
  2. Target matches an exempt glob (from config) → ALLOW.
  3. Target belongs to a task whose status == "in_progress" in the manifest → ALLOW.
  4. A single-use bypass is armed for this session → ALLOW.
  5. Trivial-edit allowance: the FIRST non-exempt code file in a session with
     change magnitude <= trivialLineThreshold → ALLOW. A 2nd distinct
     non-exempt file, or a change over the threshold → BLOCK.

"Change magnitude" is max(added lines, added chars / 200, removed lines) — a
single-line minified blob and a large deletion both count as large.

TRANSACTIONAL STATE (decide at PreToolUse, commit at PostToolUse):
  PreToolUse only OBSERVES state — it neither consumes the bypass nor records
  the free-file slot, because the edit may still be denied by a sibling hook
  (guard-edits) or by the user's permission prompt. PostToolUse — which fires
  only after the tool actually ran — CONSUMES the bypass (single-use, logged)
  and RECORDS the free-file slot. Accepted residual: several edits batched in
  one assistant message can ride one armed bypass ("single-use per tool batch"),
  and two files racing the single free slot are both allowed once — the second
  file blocks from its NEXT edit onward.

Contract: exit 2 + stderr blocks the edit and tells Claude why (PreToolUse).
PostToolUse always exits 0. Any unexpected input / exception exits 0.

Run `python3 require-plan.py --selftest` to exercise the core decision function.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


# --- helpers (shared implementations live in _config.py) -----------------------
_rel_path = _config.rel_path
_matches_exempt = _config.matches_exempt
_strip_line_suffix = _config.strip_line_suffix
_in_progress_files = _config.in_progress_files


def _change_magnitude(tool: str, ti: dict) -> int:
    """Effective size of a change, in 'lines'.

    max(added lines, added chars / 200, removed lines): line count alone lets a
    20k-char single-line blob or a 2000-line deletion pass as 'trivial'. The
    old content of a Write is unknowable from tool_input — documented residual.
    """
    def lines(text) -> int:
        s = str(text)
        return 0 if s == "" else len(s.splitlines())

    def char_lines(text) -> int:
        return (len(str(text)) + 199) // 200

    if tool == "Write":
        t = ti.get("content", "")
        return max(lines(t), char_lines(t))
    if tool == "Edit":
        new, old = ti.get("new_string", ""), ti.get("old_string", "")
        return max(lines(new), char_lines(new), lines(old))
    if tool == "MultiEdit":
        new_l = new_c = old_l = 0
        for e in ti.get("edits", []) or []:
            new, old = e.get("new_string", ""), e.get("old_string", "")
            new_l += lines(new)
            new_c += char_lines(new)
            old_l += lines(old)
        return max(new_l, new_c, old_l)
    if tool == "NotebookEdit":
        t = ti.get("new_source", "")
        return max(lines(t), char_lines(t))
    return 0


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _append_log(logs: Path, line: str) -> None:
    try:
        _ensure_dir(logs)
        with open(logs / "plan-bypass.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def block(msg: str) -> None:
    sys.stderr.write("[require-plan] " + msg + "\n")
    sys.exit(2)


# --- core decision ------------------------------------------------------------
def decide(data: dict, *, cfg=None, state_dir: Path = None, logs_dir: Path = None,
           event: str = None):
    """Pure-ish decision core. Returns ("allow", reason) or ("block", message).

    `event` selects the transactional side: "PreToolUse" (default) is read-only
    on state; "PostToolUse" commits state (consumes the bypass / records the
    free-file slot). `cfg`/`state_dir`/`logs_dir` override real values
    (used by --selftest).
    """
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    if event is None:
        event = str(data.get("hook_event_name") or "PreToolUse")
    commit_state = event == "PostToolUse"

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "") or ti.get("notebook_path", "")
    if not file_path:
        return ("allow", "no file_path")

    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    threshold = int(cfg.get("trivialLineThreshold") or 80)
    manifest_rel = cfg.get("manifestPath") or "docs/audit/audit-plan.json"
    exempt = cfg.get("exemptGlobs") or []
    sd = state_dir if state_dir is not None else _config.state_dir(root, cfg)
    ld = logs_dir if logs_dir is not None else _config.logs_dir(root, cfg)
    rel = _rel_path(root, file_path)

    # 2. exempt globs
    if _matches_exempt(rel, exempt):
        return ("allow", "exempt path: %s" % rel)

    # 3. covered by an in_progress task (exact match OR directory prefix match)
    in_prog = _in_progress_files(root, manifest_rel)
    if rel in in_prog or (rel + "/") in in_prog or any(
        rel.startswith(f) for f in in_prog if f.endswith("/")
    ):
        return ("allow", "covered by in_progress task: %s" % rel)

    session_id = str(data.get("session_id", "") or "no-session")

    # 4. single-use bypass — observed at Pre, consumed at Post
    bypass_file = sd / ("plan-bypass-%s.json" % session_id)
    try:
        if bypass_file.exists():
            if not commit_state:
                return ("allow", "bypass armed: %s" % rel)
            try:
                bypass_file.unlink()
            except Exception:
                pass
            _append_log(
                ld,
                "%s session=%s consumed by successful edit of %s"
                % (_now_iso(), session_id, rel),
            )
            return ("allow", "bypass consumed: %s" % rel)
    except Exception:
        pass

    # 5. trivial-edit allowance (per-session state; recorded at Post)
    gate_file = sd / ("plan-gate-%s.json" % session_id)
    files_list = []
    try:
        if gate_file.exists():
            with open(gate_file, "r", encoding="utf-8") as fh:
                files_list = (json.load(fh) or {}).get("files", []) or []
    except Exception:
        files_list = []

    if rel in files_list:
        return ("allow", "already being worked: %s" % rel)

    magnitude = _change_magnitude(tool, ti)

    if len(files_list) == 0 and magnitude <= threshold:
        if commit_state:
            files_list.append(rel)
            try:
                _ensure_dir(sd)
                with open(gate_file, "w", encoding="utf-8") as fh:
                    json.dump({"files": files_list}, fh)
            except Exception:
                pass
            return ("allow",
                    "recorded first trivial code file (magnitude %d): %s"
                    % (magnitude, rel))
        return ("allow",
                "first trivial code file (magnitude %d): %s" % (magnitude, rel))

    reason = (
        "second distinct file in session"
        if len(files_list) > 0
        else "change magnitude %d (> %d)" % (magnitude, threshold)
    )
    keyword = cfg.get("bypassKeyword") or _config.DEFAULTS["bypassKeyword"]
    return (
        "block",
        "Non-trivial change without an active plan (%s): %s\n"
        "Plan-first development is enforced for this repo. To proceed, either:\n"
        "  1. Add a phase/task covering this file to %s "
        "(set its status to \"in_progress\") and run /audit, OR\n"
        "  2. Include %s anywhere in your prompt to opt out for this one "
        "change (single-use, logged).\n"
        "Exempt without a plan: %s, and the first single small (magnitude <= %d: "
        "lines added, chars/200, or lines removed — whichever is larger) "
        "non-exempt file per session."
        % (reason, rel, manifest_rel, keyword, ", ".join(exempt), threshold),
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = str(data.get("hook_event_name") or "PreToolUse")
    try:
        verdict, msg = decide(data, event=event)
    except Exception:
        sys.exit(0)

    # PostToolUse runs only for its state side-effects — the edit already
    # happened; never block or complain there.
    if event == "PostToolUse":
        sys.exit(0)

    if verdict == "block":
        block(msg)
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="require-plan-selftest-"))
    sd = tmp / "state"
    ld = tmp / "logs"
    sd.mkdir(parents=True, exist_ok=True)
    ld.mkdir(parents=True, exist_ok=True)
    cfg = dict(_config.DEFAULTS)  # generic defaults, no project specifics

    session = "selftest-session-1"
    big = "\n".join("line %d" % i for i in range(120))  # 120 lines > 80

    def payload(tool, file_path, *, new_string=None, old_string=None,
                content=None, edits=None, new_source=None, sid=session):
        ti = {}
        if tool == "NotebookEdit":
            ti["notebook_path"] = file_path
        else:
            ti["file_path"] = file_path
        if content is not None:
            ti["content"] = content
        if new_string is not None:
            ti["new_string"] = new_string
        if old_string is not None:
            ti["old_string"] = old_string
        if edits is not None:
            ti["edits"] = edits
        if new_source is not None:
            ti["new_source"] = new_source
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    results = []

    def check(name, expected, data, *, event="PreToolUse"):
        try:
            verdict, _ = decide(data, cfg=cfg, state_dir=sd, logs_dir=ld,
                                event=event)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    # (a) exempt paths → allow
    check("a1 .md file", "allow", payload("Write", "README.md", content="hi"))
    check("a2 manifest json (docs/audit/**)", "allow",
          payload("Write", "docs/audit/x.json", content="{}"))
    check("a3 *.spec.ts", "allow",
          payload("Write", "src/foo/bar.spec.ts", content="test('x',()=>{})"))

    # (b) transactional slot: Pre allows but does NOT record; the matching Post
    #     records; only then does a second distinct file block.
    sess_b = "selftest-session-b"
    p_first = payload("Write", "src/foo/a.ts", content="export const a = 1;",
                      sid=sess_b)
    check("b1 first small file (Pre) allowed", "allow", p_first)
    gate = sd / ("plan-gate-%s.json" % sess_b)
    results.append(not gate.exists())
    print("%s b2 Pre did NOT record the slot" % ("PASS" if not gate.exists() else "FAIL"))
    check("b3 second small file BEFORE any Post still allowed", "allow",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    check("b4 Post records the slot", "allow", p_first, event="PostToolUse")
    results.append(gate.exists())
    print("%s b5 Post recorded the slot" % ("PASS" if gate.exists() else "FAIL"))
    check("b6 second distinct file after Post blocks", "block",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    check("b7 same first file again allowed", "allow", p_first)

    # (c) magnitude: many lines, single-line blob, deletion-heavy edit
    check("c1 large new file blocks", "block",
          payload("Write", "src/foo/huge.ts", content=big, sid="selftest-session-c"))
    check("c2 single-line 20k-char blob blocks", "block",
          payload("Write", "src/foo/min.js", content="x" * 20000,
                  sid="selftest-session-c2"))
    check("c3 deletion-heavy edit blocks", "block",
          payload("Edit", "src/foo/mod.ts", new_string="// removed",
                  old_string=big + big, sid="selftest-session-c3"))
    check("c4 big NotebookEdit blocks", "block",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source=big,
                  sid="selftest-session-c4"))
    check("c5 small NotebookEdit is the free slot", "allow",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source="print(1)",
                  sid="selftest-session-c5"))

    # (d) with no in_progress task (empty tmp manifest), an uncovered file blocks
    check("d1 uncovered file blocks", "block",
          payload("Edit", "src/example/module.ts", new_string=big,
                  sid="selftest-session-d"))

    # (e) armed bypass: Pre observes without consuming; Post consumes + logs
    sess_e = "selftest-session-e"
    bp = sd / ("plan-bypass-%s.json" % sess_e)
    bp.write_text(json.dumps({"ts": _now_iso(), "reason": "selftest"}),
                  encoding="utf-8")
    p_bypass = payload("Write", "src/foo/bypassed.ts", content=big, sid=sess_e)
    check("e1 armed bypass (Pre) allows", "allow", p_bypass)
    results.append(bp.exists())
    print("%s e2 Pre left the bypass armed" % ("PASS" if bp.exists() else "FAIL"))
    check("e3 Post consumes the bypass", "allow", p_bypass, event="PostToolUse")
    consumed = not bp.exists()
    results.append(consumed)
    print("%s e4 bypass consumed (single-use)" % ("PASS" if consumed else "FAIL"))

    # (f) bypass consumption writes to the provided logs_dir
    log_file = ld / "plan-bypass.log"
    wrote = log_file.exists() and "session=%s" % sess_e in log_file.read_text(
        encoding="utf-8")
    results.append(wrote)
    print("%s f1 bypass logged to provided logs_dir" % ("PASS" if wrote else "FAIL"))

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
