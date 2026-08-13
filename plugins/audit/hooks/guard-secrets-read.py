#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Read|Grep|Bash).

Enforces two universal secret-safety rules as a hard backstop:
  - Rule #1: never read the *contents* of .env / credentials / signing material.
  - Rule #2: never dump env values (printenv/env) or echo token-like variables.

Reading file *names* (e.g. `ls .env*`, Glob on names) stays allowed — only content
reads are blocked. `.env.example` / `.env.sample` / `.env.template` are safe templates.

The base secret-path set is generic (env, credentials, SSH private keys
id_rsa/id_dsa/id_ecdsa/id_ed25519, .p12/.pfx/.mobileprovision/.keystore/.jks/
.p8/.pem). A consuming repo can ADD patterns via
`.claude/audit.config.json` → secretPatterns.extra (list of regexes matched against
the target path/command).

Covered read vectors:
  - Read tool  → file_path against SECRET_PATH (+ extras).
  - Grep tool  → path/glob against SECRET_PATH/SECRET_GLOB (+ extras). Grep prints
                 matching *lines*, so a Grep over `.env` would leak contents. The
                 `pattern` is the query, NOT a target, and is ignored.
  - Bash       → (a) shell read verbs aimed at a secret file token — including the
                     indirect ones: `git show HEAD:.env`, `git cat-file`,
                     `source .env` / `. .env`, and copy-verbs (`cp`/`mv`/`rsync`/
                     `install`) that would relocate a secret for later reading;
                 (b) inline-eval reads (python/node/ruby/perl/… -c/-e) whose code text
                     references a secret-file token;
                 (c) env-value dumps (printenv/env) and echoing token-like variables.

Plan-first backstop for Bash WRITES (this is the only hook that sees Bash):
  - inline-eval writes to a non-exempt source path;
  - the high-signal shell write forms into a non-exempt source file that no
    in_progress manifest task covers: `sed -i`, `tee <file>`, and `>`/`>>`
    redirects (which also catches `cat > file <<EOF` heredocs). The block
    message steers to the Edit/Write tools, which the plan gate governs.

Trade-off (accepted): the matchers are text-based and may over-block an innocent
one-liner that merely mentions `.env` (e.g. `cp .env.example .env`). We accept
over-blocking on the read side — a harmless retry vs. an irreversible leak.
Listing NAMES is never blocked. FULL Bash-write coverage is undecidable by
static text inspection (heredocs into interpreters, obfuscated redirects —
upstream anthropics/claude-code#29709); the complete control would be a
PostToolUse diff/worktree check (out of scope, documented in SECURITY.md).

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 — the canonical
PreToolUse protocol (the exit-2 + stderr channel is deprecated). Any
unexpected input exits 0.
Run `python3 guard-secrets-read.py --selftest` to exercise the decision core.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

# --- secret FILE paths (used for the Read tool's file_path and Grep path/glob) --
SECRET_PATH = re.compile(
    r"""(
        (^|/)\.env(?!\.(?:example|sample|template|dist|defaults)\b)(\.[^/]+)?$
      | (^|/)credentials[^/]*\.(?:json|plist|p8|pem|key|cer|der|txt|cfg|conf|ya?ml)$
      | (^|/)credentials$
      | (^|/)id_(?:rsa|dsa|ecdsa|ed25519)$
      | \.p12$
      | \.pfx$
      | \.mobileprovision$
      | \.keystore$
      | \.jks$
      | \.p8$
      | \.pem$
    )""",
    re.IGNORECASE | re.VERBOSE,
)

SECRET_GLOB = re.compile(
    r"""(
        (^|/)\.env(?!\.(?:example|sample|template|dist|defaults))
      | (^|/)credentials
      | (^|/)id_(?:rsa|dsa|ecdsa|ed25519)\b
      | \.p12\b
      | \.pfx\b
      | \.mobileprovision\b
      | \.keystore\b
      | \.jks\b
      | \.p8\b
      | \.pem\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# --- secret references inside a Bash command ------------------------------------
_READ_VERB = (
    r"(?:cat|bat|head|tail|sed|awk|nl|less|more|strings|xxd|od|hexdump"
    r"|grep|rg|tee|dd|base64|openssl|gpg"
    r"|cp|mv|rsync|install|source"
    r"|git\s+(?:show|cat-file))"
)
_SECRET_TOKEN = (
    r"(?:\.env(?!\.(?:example|sample|template|dist|defaults))(?:\.|\b)"
    r"|credentials[\w.-]*\.(?:json|plist|p8|pem|key|txt)"
    r"|(?:^|[/\s'\"])credentials(?=$|[\s'\";|&])"       # bare `~/.aws/credentials`
    r"|(?:^|[/\s'\"])id_(?:rsa|dsa|ecdsa|ed25519)\b"    # SSH private keys
    r"|\.p12\b|\.pfx\b|\.mobileprovision\b|\.keystore\b|\.jks\b|\.p8\b|\.pem\b)"
)
BASH_FILE_READ = re.compile(
    r"\b" + _READ_VERB + r"\b[^|&;\n]*?" + _SECRET_TOKEN, re.IGNORECASE
)
# `. .env` — POSIX dot-sourcing (the bare-dot form of `source`)
DOT_SOURCE_SECRET = re.compile(
    r"(?:^|[;&|(]\s*)\.\s+[^|&;\n]*?" + _SECRET_TOKEN, re.IGNORECASE
)

_INLINE_EVAL = re.compile(
    r"\b(?:python3?|python3\.\d+|node|nodejs|deno|bun|ruby|perl|php)\b"
    r"[^|&;\n]*?"
    r"(?:\s-(?:c|e|p|E|r|ne|pe)\b|\s--eval\b|\s--exec\b|\seval\b)",
    re.IGNORECASE,
)
SECRET_TOKEN_RE = re.compile(_SECRET_TOKEN, re.IGNORECASE)

_WRITE_CALL = re.compile(
    r"(?:open\s*\([^)]*['\"](?:w|a|wb|ab|w\+|a\+|r\+)['\"]"
    r"|\.write(?:File)?(?:Sync)?\s*\("
    r"|createWriteStream\s*\("
    r"|File\.(?:open|write)\s*\("
    r"|>>?\s*['\"]?[\w./-]+)",
    re.IGNORECASE,
)
_NON_EXEMPT_WRITE_TARGET = re.compile(
    r"['\"][\w./-]+\.(?:tsx?|jsx?|mjs|cjs|json|ya?ml|swift|kt|java|rb|py|sh|gradle|"
    r"podspec|plist)['\"]",
    re.IGNORECASE,
)
_EXEMPT_WRITE_PATH = re.compile(
    r"(?:\.claude/|docs/audit/|\.spec\.|\.test\.|\.md['\"\s])",
    re.IGNORECASE,
)

# --- shell write forms into files (plan-first backstop) --------------------------
# `>`/`>>`, incl. `1>`/`1>>` (explicit stdout) and `>|`/`>>|` (noclobber
# override); NOT `2>`/`&>` (stderr/both — not a source-file write we gate).
_SHELL_REDIRECT = re.compile(r"(?<![0-9&<>])1?>{1,2}\|?\s*([^\s|&;<>]+)")
_TEE_CLAUSE = re.compile(r"\btee\b([^|&;\n]*)", re.IGNORECASE)
_SED_INPLACE_CLAUSE = re.compile(
    r"\bsed\b[^|&;\n]*?\s(?:-i|--in-place)\b[^|&;\n]*", re.IGNORECASE
)
_PATHY_TOKEN = re.compile(r"[\w@~./+-]+\.[A-Za-z][A-Za-z0-9]{0,9}")

ENV_DUMP = re.compile(r"(?:^|[|&;]\s*)(?:printenv\b|env\s*(?:$|[|&>]))", re.IGNORECASE)
ECHO_SECRET = re.compile(
    r"\b(?:echo|printf)\b[^|&;\n]*\$\{?\s*[A-Za-z_]*"
    r"(?:TOKEN|SECRET|BEARER|PASSWORD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)


def _deny_payload(msg: str) -> dict:
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-secrets-read] " + msg,
        }
    }


def _ask_payload(msg: str) -> dict:
    """Canonical PreToolUse ask payload — planGate:"ask" parity with
    require-plan (v0.34 B1). Only the shell PLAN-gate branch can return ask;
    the secret guards are never graded and never ask."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "[guard-secrets-read] " + msg,
        }
    }


def block(msg: str) -> None:
    print(json.dumps(_deny_payload(msg)))
    sys.exit(0)


def _extra_patterns(cfg):
    """Compile the consuming repo's extra secret regexes (best-effort)."""
    out = []
    for pat in _config.extra_secret_patterns(cfg):
        try:
            out.append(re.compile(str(pat), re.IGNORECASE))
        except Exception:
            continue
    return out


def _hits_extra(text, extras):
    return any(rx.search(text) for rx in extras)


def _shell_write_targets(cmd: str):
    """Best-effort extraction of file paths a shell command WRITES to."""
    targets = []
    for m in _SHELL_REDIRECT.finditer(cmd):
        t = m.group(1).strip("'\"")
        if t and not t.startswith(("&", "(")) and t != "/dev/null":
            targets.append(t)
    for m in _TEE_CLAUSE.finditer(cmd):
        for tok in m.group(1).split():
            tok = tok.strip("'\"")
            if tok and not tok.startswith("-"):
                targets.append(tok)
    for m in _SED_INPLACE_CLAUSE.finditer(cmd):
        targets.extend(_PATHY_TOKEN.findall(m.group(0)))
    return targets


# shared with guard-bash-writes.py — ONE definition of "source file"
_source_exts = _config.source_exts


def _source_write_hit(cmd: str, root, cfg):
    """First non-exempt SOURCE file (not covered by an in_progress task) that
    `cmd` writes to via sed -i / tee / a >(>) redirect — or None."""
    targets = _shell_write_targets(cmd)
    if not targets:
        return None
    exts = _source_exts(cfg)
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
    in_prog = None
    for t in targets:
        low = t.lower()
        if not any(low.endswith(e) for e in exts):
            continue
        rel = _config.rel_path(root, t)
        if _config.matches_exempt(rel, exempt):
            continue
        if in_prog is None:
            in_prog = _config.in_progress_files(root, manifest_rel)
        if rel in in_prog or any(
            rel.startswith(f) for f in in_prog if f.endswith("/")
        ):
            continue
        return rel
    return None


# --- decision core (pure; returns ("allow"|"block", message) for testability) ---
def decide(data: dict, *, cfg=None):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    root = _config.repo_root(data)
    if cfg is None:
        cfg = _config.load(root)
    extras = _extra_patterns(cfg)

    if tool == "Read":
        fp = str(ti.get("file_path", "")).replace("\\", "/")
        if fp and (SECRET_PATH.search(fp) or _hits_extra(fp, extras)):
            return ("block",
                    "Reading a secret file's contents is blocked (Rule #1): %s\n"
                    "Listing names is fine; reading contents is not. "
                    "Ask the user to paste any value you actually need." % fp)
        return ("allow", "read: not a secret path")

    if tool == "Grep":
        path = str(ti.get("path", "")).replace("\\", "/")
        glob = str(ti.get("glob", "")).replace("\\", "/")
        if path and (SECRET_PATH.search(path) or SECRET_GLOB.search(path)
                     or _hits_extra(path, extras)):
            return ("block",
                    "Grep over a secret file's contents is blocked (Rule #1): "
                    "path=%s\nGrep prints matching lines of the file. Use `ls` to list "
                    "names, or ask the user to paste any value you need." % path)
        if glob and (SECRET_GLOB.search(glob) or _hits_extra(glob, extras)):
            return ("block",
                    "Grep with a glob targeting secret files is blocked (Rule #1): "
                    "glob=%s\nGrep prints matching lines of matched files. List names "
                    "with `ls` instead." % glob)
        return ("allow", "grep: not a secret target")

    if tool == "Bash":
        cmd = str(ti.get("command", ""))
        if ENV_DUMP.search(cmd):
            return ("block",
                    "Dumping environment values (printenv/env) is blocked (Rule #2). "
                    "Debug with a prefix only: val[:6] + length.")
        if ECHO_SECRET.search(cmd):
            return ("block",
                    "Echoing a token/secret variable is blocked (Rule #2). "
                    "Print only a prefix (first 6 chars) + length if you must debug.")
        if (BASH_FILE_READ.search(cmd) or DOT_SOURCE_SECRET.search(cmd)
                or (extras and _hits_extra(cmd, extras)
                    and BASH_FILE_READ.search(cmd + " "))):
            return ("block",
                    "Reading, sourcing or copying a secret file via shell is blocked "
                    "(Rule #1). Reading file names is fine; contents are not — and "
                    "copying/moving a secret only relocates the leak.")
        if _INLINE_EVAL.search(cmd) and (SECRET_TOKEN_RE.search(cmd)
                                         or _hits_extra(cmd, extras)):
            return ("block",
                    "Reading a secret file via an inline-eval one-liner "
                    "(python -c / node -e / ruby/perl -e …) is blocked (Rule #1). "
                    "Listing names is fine; reading contents is not. Ask the user to "
                    "paste any value you actually need.")
        if (
            _INLINE_EVAL.search(cmd)
            and _WRITE_CALL.search(cmd)
            and _NON_EXEMPT_WRITE_TARGET.search(cmd)
            and not _EXEMPT_WRITE_PATH.search(cmd)
        ):
            return ("block",
                    "Writing source files via an inline-eval one-liner "
                    "(python -c / node -e …) bypasses the plan-first gate.\n"
                    "Use the Edit/Write tools so guard-edits and require-plan can review "
                    "the change. This is a best-effort backstop — full Bash-write "
                    "coverage needs a PostToolUse diff check.")
        hit = _source_write_hit(cmd, root, cfg)
        if hit:
            # This is a PLAN gate, so it is graded on the same evidence
            # require-plan uses. Otherwise `Edit src/x.ts` would be merely observed
            # while `sed -i src/x.ts` still denied — same file, same rule, opposite
            # verdict, decided by which tool the agent happened to reach for.
            #
            # Only this branch is graded. Every secret-detection branch above stays
            # deny-by-default: reading .env is wrong whether or not a plan exists,
            # so those guards need no evidence to be right.
            manifest_rel = (cfg.get("manifestPath")
                            or _config.DEFAULTS["manifestPath"])
            state = _config.manifest_state(root, manifest_rel)
            mode = _config.plan_gate_mode(cfg, state)
            if mode == "deny":
                # The refusal names its ACTUAL cause (F-F4), mirroring
                # require-plan word for word: "a phase is in_progress" was
                # printed here even when the denial came from enforce:true in
                # an empty repo.
                knob = _config.plan_gate_knob(cfg)
                if knob == "deny":
                    cause = ("planGate is set to \"deny\" in "
                             ".claude/audit.config.json - refused regardless "
                             "of what is running.")
                elif _config.enforce_always(cfg):
                    cause = ("enforce: true is set in .claude/audit.config.json "
                             "(legacy; planGate: \"deny\" says the same) - "
                             "refused regardless of what is running.")
                else:
                    cause = ("Phase %s is in_progress, so edits are held to "
                             "the plan." % (state.get("runningPhase") or "?"))
                return ("block",
                        "Shell write into a source file bypasses the plan-first "
                        "gate: %s\n%s Use the Edit/Write tools (guard-edits + "
                        "require-plan review the change), or cover the file "
                        "with an in_progress task. Exempt paths (docs, tests, "
                        ".claude/**) are unaffected." % (hit, cause))
            if mode == "ask":
                # planGate:"ask" parity with require-plan: the same file must be
                # treated the same whether the agent reaches for Edit or sed -i.
                return ("ask",
                        "Shell write into a source file outside the plan: %s\n"
                        "planGate is set to \"ask\" in .claude/audit.config.json, "
                        "so this write waits for your approval - approving covers "
                        "this one command. Prefer the Edit/Write tools "
                        "(guard-edits + require-plan review the change), or cover "
                        "the file with an in_progress task." % hit)
            return ("allow", "bash: source write, plan gate %s: %s" % (mode, hit))
        return ("allow", "bash: no secret read")

    return ("allow", "unhandled tool")


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
    if verdict == "ask":
        print(json.dumps(_ask_payload(msg)))
        sys.exit(0)
    sys.exit(0)


# --- selftest -------------------------------------------------------------------
def _selftest() -> int:
    """Exercise the decision core with fictional secret paths (never real files)."""
    import tempfile
    from pathlib import Path

    results = []
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    tmp = Path(tempfile.mkdtemp(prefix="guard-secrets-selftest-"))

    # Pin the project dir: repo_root prefers CLAUDE_PROJECT_DIR over the payload's
    # cwd, so unpinned this suite graded the shell plan gate against whatever
    # repository happened to be open.
    _prev_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # The shell-write branch is a PLAN gate and is graded like require-plan's. The
    # cases that assert full enforcement say so explicitly.
    cfg_enforced = _config._deep_merge(cfg, {"enforce": True})

    def check(name, expected, data, *, use_cfg=None):
        try:
            verdict, _ = decide(data, cfg=use_cfg or cfg)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    def read(fp):
        return {"tool_name": "Read", "tool_input": {"file_path": fp},
                "cwd": str(tmp)}

    def grep(pattern="x", path=None, glob=None):
        ti = {"pattern": pattern}
        if path is not None:
            ti["path"] = path
        if glob is not None:
            ti["glob"] = glob
        return {"tool_name": "Grep", "tool_input": ti, "cwd": str(tmp)}

    def bash(cmd):
        return {"tool_name": "Bash", "tool_input": {"command": cmd},
                "cwd": str(tmp)}

    # --- Read tool ---
    check("r1 Read .env blocked", "block", read("apps/foo/.env"))
    check("r2 Read .env.example allowed", "allow", read("apps/foo/.env.example"))
    check("r3 Read normal file allowed", "allow", read("apps/foo/index.ts"))

    # --- Grep tool ---
    check("g1 Grep path=.env blocked", "block", grep(pattern="X", path="apps/foo/.env"))
    check("g2 Grep glob=**/.env* blocked", "block", grep(pattern="T", glob="**/.env*"))
    check("g3 Grep glob=credentials* blocked", "block",
          grep(pattern="k", glob="credentials*"))
    check("g4 Grep path=.p12 blocked", "block", grep(pattern=".", path="ios/cert.p12"))
    check("g5 Grep .mobileprovision glob blocked", "block",
          grep(pattern=".", glob="**/*.mobileprovision"))
    check("g6 Grep .env.example path allowed", "allow",
          grep(pattern="X", path="apps/foo/.env.example"))
    check("g7 Grep normal source allowed", "allow",
          grep(pattern="useEffect", glob="**/*.tsx"))
    check("g8 Grep no path/glob allowed", "allow", grep(pattern="something"))

    # --- Bash inline-eval reads ---
    check("b1 python3 -c open(.env) blocked", "block",
          bash("python3 -c \"print(open('.env').read())\""))
    check("b3 node -e readFileSync(.env) blocked", "block",
          bash("node -e \"console.log(require('fs').readFileSync('.env','utf8'))\""))
    check("b5 ruby -e File.read(.env) blocked", "block",
          bash("ruby -e 'puts File.read(\".env\")'"))
    check("b7 python3 -c read p12 blocked", "block",
          bash("python3 -c \"open('cert.p12','rb').read()\""))
    check("b8 python3 -c innocent allowed", "allow", bash("python3 -c \"print(2+2)\""))
    check("b10 python selftest of a hook allowed", "allow",
          bash("python3 hooks/require-plan.py --selftest"))

    # --- Bash shell-verb reads ---
    check("b11 cat .env blocked", "block", bash("cat apps/foo/.env"))
    check("b12 printenv blocked", "block", bash("printenv"))

    # --- indirect reads: git show, source, dot-source, copy-verbs ---
    check("i1 git show HEAD:.env blocked", "block", bash("git show HEAD:.env"))
    check("i2 git cat-file -p HEAD:.env blocked", "block",
          bash("git cat-file -p HEAD:.env"))
    check("i3 git show of source file allowed", "allow",
          bash("git show HEAD:src/app.ts"))
    check("i4 source .env blocked", "block", bash("source .env && npm start"))
    check("i5 dot-source .env blocked", "block", bash(". .env && npm start"))
    check("i6 source nvm.sh allowed", "allow",
          bash("source ~/.nvm/nvm.sh && nvm use"))
    check("i7 cp .env to /tmp blocked", "block", bash("cp .env /tmp/e"))
    check("i8 mv secret keystore blocked", "block",
          bash("mv android/release.keystore /tmp/k"))
    check("i9 cp between source files allowed", "allow",
          bash("cp src/a.ts src/b.bak"))

    # --- SSH private keys + bare aws-style credentials ---
    check("k1 Read ~/.ssh/id_rsa (SSH private key) blocked", "block",
          read("~/.ssh/id_rsa"))
    check("k2 Read .ssh/id_ed25519 blocked", "block", read(".ssh/id_ed25519"))
    check("k3 Read id_rsa.pub (PUBLIC key) allowed", "allow",
          read(".ssh/id_rsa.pub"))
    check("k4 cat ~/.aws/credentials (bare, via Bash) blocked", "block",
          bash("cat ~/.aws/credentials"))
    check("k5 cat ~/.ssh/id_rsa via Bash blocked", "block",
          bash("cat ~/.ssh/id_rsa"))
    check("k6 Read client.pfx blocked", "block", read("certs/client.pfx"))
    check("k7 cat credentials.md (not a secret ext) allowed", "allow",
          bash("cat credentials.md"))

    # --- Listing NAMES stays allowed ---
    check("n1 ls .env* allowed", "allow", bash("ls .env*"))
    check("n4 find -name .env allowed", "allow", bash("find . -name '.env'"))

    # --- inline-eval WRITE heuristic ---
    check("w1 python -c write to .ts blocked", "block",
          bash("python3 -c \"open('src/foo/a.ts','w').write('x')\""))
    check("w4 python -c write to .claude path allowed", "allow",
          bash("python3 -c \"open('.claude/state/x.json','w').write('{}')\""))
    check("w5 node -e write to *.spec.ts allowed", "allow",
          bash("node -e \"fs.writeFileSync('src/foo/a.spec.ts','test')\""))

    # --- shell writes into source files (plan-first backstop) ---
    check("s1 echo > source file blocked", "block",
          bash("echo 'x' > src/foo/a.ts"), use_cfg=cfg_enforced)
    check("s2 sed -i on source file blocked", "block",
          bash("sed -i 's/a/b/' src/app.ts"), use_cfg=cfg_enforced)
    check("s3 tee into source file blocked", "block",
          bash("cat patch.txt | tee src/app.py"), use_cfg=cfg_enforced)
    check("s4 heredoc redirect into source blocked", "block",
          bash("cat > src/gen.ts <<'EOF'\nexport {}\nEOF"), use_cfg=cfg_enforced)
    check("s5 append redirect into source blocked", "block",
          bash("echo '// x' >> src/app.go"), use_cfg=cfg_enforced)

    # (s-graded) the shell plan gate follows the same evidence tiers as
    # require-plan, so a file is treated the same whether the agent reaches for
    # `Edit` or for `sed -i`.
    _mdir = tmp / "docs" / "audit"
    _mdir.mkdir(parents=True, exist_ok=True)
    _mfile = _mdir / "audit-plan.json"

    check("s5a no manifest -> shell write observed, not blocked", "allow",
          bash("sed -i 's/a/b/' src/graded.ts"))

    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]}),
        encoding="utf-8")
    check("s5b manifest, nothing running -> shell write not blocked", "allow",
          bash("sed -i 's/a/b/' src/graded.ts"))

    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}),
        encoding="utf-8")
    check("s5c manifest + running phase -> shell write blocked", "block",
          bash("sed -i 's/a/b/' src/graded.ts"))

    # Same running phase, but the file IS covered by its in_progress task: the gate
    # has nothing to object to, on any tier.
    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/covered.ts"]}]}]}), encoding="utf-8")
    check("s5d a covered file is allowed at the deny tier", "allow",
          bash("sed -i 's/a/b/' src/covered.ts"))
    check("s5d2 an uncovered sibling is still blocked there", "block",
          bash("sed -i 's/a/b/' src/uncovered.ts"))

    # Secret detection is NOT graded — it needs no plan to be right, so it denies at
    # every tier including the one with no manifest at all.
    check("s5e reading .env is denied while the plan gate is at deny", "block",
          read(".env"))
    import shutil as _shutil
    _shutil.rmtree(tmp / "docs", ignore_errors=True)
    check("s5f .env is still denied with no manifest present", "block", read(".env"))
    check("s5g so is a credentials file", "block", read("config/credentials.json"))
    check("s5h and an ssh key", "block", read(".ssh/id_ed25519"))

    check("s6 redirect to log file allowed", "allow",
          bash("npm test > out.log 2>&1"))
    check("s7 redirect of grep output to /tmp allowed", "allow",
          bash("grep -r foo src/app.ts > /tmp/out.txt"))
    check("s8 write to exempt .md allowed", "allow",
          bash("echo hi > NOTES.md"))
    check("s9 write to test file allowed", "allow",
          bash("echo 'test' > src/foo/a.spec.ts"))
    check("s10 sed without -i (stdout) allowed", "allow",
          bash("sed 's/a/b/' src/app.ts"))

    # --- shell write covered by an in_progress task → allowed ---
    manifest_dir = tmp / "docs" / "audit"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "audit-plan.json").write_text(json.dumps({
        "meta": {"version": 2},
        "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P0.1", "title": "t", "status": "in_progress",
             "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
        ]}],
    }), encoding="utf-8")
    check("s11 sed -i on in_progress-covered file allowed", "allow",
          bash("sed -i 's/a/b/' src/covered/mod.ts"))
    check("s12 stdout `1>` into source file blocked", "block",
          bash("echo x 1> src/app.ts"))
    check("s13 clobber `>|` into source file blocked", "block",
          bash("echo x >| src/app.ts"))

    # (s14+) planGate parity (v0.34 B1): the shell-write branch follows the SAME
    # knob require-plan follows -- _help's gate page pins in prose that the two
    # halves grade identically, and an ask tier only one of them honours would
    # make that sentence a lie. The manifest fixture above still has phase P0
    # in_progress here, so 'observe while a phase runs' is a real pin, not a
    # vacuous one.
    cfg_ask = _config._deep_merge(_config.DEFAULTS, {"planGate": "ask"})
    check("s14 planGate:'ask' turns an uncovered shell write into ask", "ask",
          bash("sed -i 's/a/b/' src/uncovered-ask.ts"), use_cfg=cfg_ask)
    check("s15 a covered file is allowed at the ask tier", "allow",
          bash("sed -i 's/a/b/' src/covered/mod.ts"), use_cfg=cfg_ask)
    cfg_pin_obs = _config._deep_merge(_config.DEFAULTS, {"planGate": "observe"})
    check("s16 planGate:'observe' lets the shell write through while a phase "
          "runs (the same lowering require-plan honours)", "allow",
          bash("sed -i 's/a/b/' src/uncovered-observe.ts"), use_cfg=cfg_pin_obs)
    cfg_pin_deny = _config._deep_merge(_config.DEFAULTS, {"planGate": "deny",
                                                          "manifestPath":
                                                          "no/such/plan.json"})
    check("s17 planGate:'deny' blocks the shell write with no manifest at all",
          "block", bash("sed -i 's/a/b/' src/uncovered-deny.ts"),
          use_cfg=cfg_pin_deny)
    check("s18 secret reads are NOT graded - .env is refused at the ask tier "
          "too", "block", read(".env"), use_cfg=cfg_ask)
    # (s20+) what the shell refusal SAYS, by actual cause (F-F4) - the mirror
    # of require-plan's h group: this file used to claim "A phase is
    # in_progress" whether or not one was, on the same evidence tiers.
    def sdeny(use_cfg, cmd="sed -i 's/a/b/' src/blamed.ts"):
        try:
            return decide(bash(cmd), cfg=use_cfg)
        except Exception as exc:  # pragma: no cover
            return ("EXC", str(exc))

    import shutil as _sh2
    _sh2.rmtree(tmp / "docs", ignore_errors=True)
    _v, _m = sdeny(cfg_enforced)
    _ok = (_v == "block" and "enforce: true" in _m and "legacy" in _m
           and "A phase is in_progress" not in _m)
    results.append(_ok)
    print("%s s20 enforce:true with NO phase running blames the config, not a "
          "phantom phase%s" % ("PASS" if _ok else "FAIL",
                               "" if _ok else " (%r)" % _m))
    _v, _m = sdeny(_config._deep_merge(_config.DEFAULTS, {"planGate": "deny"}))
    _ok = (_v == "block" and 'planGate is set to "deny"' in _m
           and "regardless of what is running" in _m)
    results.append(_ok)
    print("%s s21 planGate:'deny' names the knob, exactly as require-plan does"
          % ("PASS" if _ok else "FAIL"))
    _mdir2 = tmp / "docs" / "audit"
    _mdir2.mkdir(parents=True, exist_ok=True)
    (_mdir2 / "audit-plan.json").write_text(json.dumps(
        {"meta": {"version": 2}, "phases": [
            {"id": "P7", "title": "p", "status": "in_progress",
             "tasks": [{"id": "P7.1", "title": "t", "status": "pending"}]}]}),
        encoding="utf-8")
    _v, _m = sdeny(cfg)
    _ok = _v == "block" and "Phase P7 is in_progress" in _m
    results.append(_ok)
    print("%s s22 a real running phase is NAMED - 'phase P7', not 'a phase'%s"
          % ("PASS" if _ok else "FAIL", "" if _ok else " (%r)" % _m))
    _sh2.rmtree(tmp / "docs", ignore_errors=True)

    # The ask payload's SHAPE is the pinned contract (the dialog cannot be
    # driven by a selftest) - mirror of require-plan's g9 and of j1 below.
    _ap = json.loads(json.dumps(_ask_payload("why")))
    _hso = _ap.get("hookSpecificOutput") or {}
    _ok = (_hso.get("hookEventName") == "PreToolUse"
           and _hso.get("permissionDecision") == "ask"
           and str(_hso.get("permissionDecisionReason", "")).startswith(
               "[guard-secrets-read]"))
    results.append(_ok)
    print("%s s19 the ask payload is a canonical PreToolUse 'ask' decision"
          % ("PASS" if _ok else "FAIL"))

    # --- extra pattern from config ---
    cfg_extra = _config._deep_merge(
        _config.DEFAULTS, {"secretPatterns": {"extra": [r"\.secretrc$"]}})
    check("x1 Read .secretrc (extra) blocked", "block", read("app/.secretrc"),
          use_cfg=cfg_extra)
    check("x2 Read normal (extra cfg) allowed", "allow", read("app/index.ts"),
          use_cfg=cfg_extra)

    # --- malformed / unhandled → allow ---
    check("u1 unhandled tool allowed", "allow",
          {"tool_name": "Glob", "tool_input": {"pattern": ".env"}, "cwd": str(tmp)})
    check("u2 empty input allowed", "allow", {"cwd": str(tmp)})

    # --- deny payload is canonical PreToolUse JSON ---
    blob = json.loads(json.dumps(_deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    ok = (hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[guard-secrets-read]"))
    results.append(ok)
    print("%s j1 deny payload is canonical PreToolUse JSON" % ("PASS" if ok else "FAIL"))

    if _prev_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = _prev_project_dir

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
