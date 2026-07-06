#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Edit|Write|MultiEdit) — plan-first enforcement.

Enforces a "Plan-first development" workflow: a non-trivial code change must be
planned via a task in the audit manifest and executed through /audit, OR opted out
for a single change with the bypass keyword (armed by detect-plan-skip.py).

This is the PLUGIN version — every project-specific value comes from the consuming
repo's `.claude/audit.config.json` (loaded by _config.py) with safe defaults:
  manifestPath, exemptGlobs, trivialLineThreshold, stateDir, logsDir, bypassKeyword.

Decision order (ALLOW = exit 0; BLOCK = stderr msg + exit 2):
  1. No file_path / unknown tool / parse error → ALLOW (never break legit work).
  2. Target matches an exempt glob (from config) → ALLOW.
  3. Target belongs to a task whose status == "in_progress" in the manifest → ALLOW.
  4. A single-use bypass is armed for this session → consume it, log it, ALLOW.
  5. Trivial-edit allowance: the FIRST non-exempt code file in a session with
     <= trivialLineThreshold added lines → ALLOW (recorded). A 2nd distinct
     non-exempt file, or a change over the threshold → BLOCK.

Contract: exit 2 + stderr blocks the edit and tells Claude why. Any unexpected
input / exception exits 0.

Run `python3 require-plan.py --selftest` to exercise the core decision function.
"""
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


# --- helpers ------------------------------------------------------------------
def _rel_path(root: Path, file_path: str) -> str:
    """Path of file_path RELATIVE to repo root, posix-style. Falls back gracefully."""
    fp = str(file_path).replace("\\", "/")
    try:
        p = Path(fp)
        if not p.is_absolute():
            p = (root / p)
        rel = os.path.relpath(str(p), str(root))
    except Exception:
        rel = fp
    return rel.replace("\\", "/")


def _matches_exempt(rel: str, globs) -> bool:
    """Generic exempt matcher that understands the common `**` glob forms.

    Handles:  `dir/**` (recursive prefix), `**/*.ext` (basename), and plain fnmatch.
    """
    base = rel.split("/")[-1]
    for g in globs or ():
        g = str(g)
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(base, g):
            return True
        # `some/dir/**` → recursive prefix match
        if g.endswith("/**"):
            prefix = g[:-3]
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
        # `**/*.ext` or `**/name` → match against the basename
        if g.startswith("**/"):
            if fnmatch.fnmatch(base, g[3:]):
                return True
    return False


def _strip_line_suffix(entry: str) -> str:
    """`a/b.tsx:291-294,308` -> `a/b.tsx`."""
    s = str(entry).replace("\\", "/")
    return s.split(":", 1)[0]


def _in_progress_files(root: Path, manifest_rel: str) -> set:
    """Files belonging to tasks whose status == 'in_progress', plus their fileIndex
    siblings keyed by the same path."""
    files: set = set()
    try:
        with open(root / manifest_rel, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        return files

    in_progress_task_ids: set = set()
    try:
        for phase in manifest.get("phases", []) or []:
            for task in phase.get("tasks", []) or []:
                if task.get("status") == "in_progress":
                    tid = task.get("id")
                    if tid:
                        in_progress_task_ids.add(tid)
                    for f in task.get("files", []) or []:
                        files.add(_strip_line_suffix(f))
    except Exception:
        pass

    try:
        for fpath, task_ids in (manifest.get("fileIndex", {}) or {}).items():
            if any(t in in_progress_task_ids for t in (task_ids or [])):
                files.add(_strip_line_suffix(fpath))
    except Exception:
        pass

    return files


def _added_line_count(tool: str, ti: dict) -> int:
    def n(text) -> int:
        s = str(text)
        return 0 if s == "" else len(s.splitlines())

    if tool == "Write":
        return n(ti.get("content", ""))
    if tool == "Edit":
        return n(ti.get("new_string", ""))
    if tool == "MultiEdit":
        return sum(n(e.get("new_string", "")) for e in (ti.get("edits", []) or []))
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
def decide(data: dict, *, cfg=None, state_dir: Path = None, logs_dir: Path = None):
    """Pure-ish decision core. Returns ("allow", reason) or ("block", message).

    `cfg`/`state_dir`/`logs_dir` override real values (used by --selftest).
    """
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit"):
        return ("allow", "unknown tool")

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "")
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

    # 4. single-use bypass
    bypass_file = sd / ("plan-bypass-%s.json" % session_id)
    try:
        if bypass_file.exists():
            try:
                bypass_file.unlink()
            except Exception:
                pass
            _append_log(
                ld,
                "%s session=%s consumed by edit of %s"
                % (_now_iso(), session_id, rel),
            )
            return ("allow", "bypass consumed: %s" % rel)
    except Exception:
        pass

    # 5. trivial-edit allowance (per-session state)
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

    added = _added_line_count(tool, ti)

    if len(files_list) == 0 and added <= threshold:
        files_list.append(rel)
        try:
            _ensure_dir(sd)
            with open(gate_file, "w", encoding="utf-8") as fh:
                json.dump({"files": files_list}, fh)
        except Exception:
            pass
        return ("allow", "first trivial code file (%d lines): %s" % (added, rel))

    reason = (
        "second distinct file in session"
        if len(files_list) > 0
        else "%d added lines (> %d)" % (added, threshold)
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
        "Exempt without a plan: %s, and the first single small (<=%d added lines) "
        "non-exempt file per session."
        % (reason, rel, manifest_rel, keyword, ", ".join(exempt), threshold),
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        verdict, msg = decide(data)
    except Exception:
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

    def payload(tool, file_path, *, new_string=None, content=None, edits=None,
                sid=session):
        ti = {"file_path": file_path}
        if content is not None:
            ti["content"] = content
        if new_string is not None:
            ti["new_string"] = new_string
        if edits is not None:
            ti["edits"] = edits
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    results = []

    def check(name, expected, data):
        try:
            verdict, _ = decide(data, cfg=cfg, state_dir=sd, logs_dir=ld)
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

    # (b) first non-exempt small file → allow; second distinct → block
    sess_b = "selftest-session-b"
    check("b1 first small code file", "allow",
          payload("Write", "src/foo/a.ts", content="export const a = 1;", sid=sess_b))
    check("b2 second distinct code file", "block",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))

    # (c) a >80-line new file in a fresh session → block
    check("c1 large new file", "block",
          payload("Write", "src/foo/huge.ts", content=big, sid="selftest-session-c"))

    # (d) with no in_progress task (empty tmp manifest), an uncovered file blocks
    check("d1 uncovered file blocks", "block",
          payload("Edit", "src/example/module.ts", new_string=big,
                  sid="selftest-session-d"))

    # (e) active bypass file → allow (and consumes it)
    sess_e = "selftest-session-e"
    bp = sd / ("plan-bypass-%s.json" % sess_e)
    bp.write_text(json.dumps({"ts": _now_iso(), "reason": "selftest"}), encoding="utf-8")
    check("e1 armed bypass", "allow",
          payload("Write", "src/foo/bypassed.ts", content=big, sid=sess_e))
    consumed = not bp.exists()
    results.append(consumed)
    print("%s e2 bypass consumed (single-use)" % ("PASS" if consumed else "FAIL"))

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
