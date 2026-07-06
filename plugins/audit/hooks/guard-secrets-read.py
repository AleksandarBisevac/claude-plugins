#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Read|Grep|Bash).

Enforces two universal secret-safety rules as a hard backstop:
  - Rule #1: never read the *contents* of .env / credentials / signing material.
  - Rule #2: never dump env values (printenv/env) or echo token-like variables.

Reading file *names* (e.g. `ls .env*`, Glob on names) stays allowed — only content
reads are blocked. `.env.example` / `.env.sample` / `.env.template` are safe templates.

The base secret-path set is generic (env, credentials, .p12/.mobileprovision/
.keystore/.jks/.p8/.pem). A consuming repo can ADD patterns via
`.claude/audit.config.json` → secretPatterns.extra (list of regexes matched against
the target path/command).

Covered read vectors:
  - Read tool  → file_path against SECRET_PATH (+ extras).
  - Grep tool  → path/glob against SECRET_PATH/SECRET_GLOB (+ extras). Grep prints
                 matching *lines*, so a Grep over `.env` would leak contents. The
                 `pattern` is the query, NOT a target, and is ignored.
  - Bash       → (a) shell read verbs piped at a secret file token;
                 (b) inline-eval reads (python/node/ruby/perl/… -c/-e) whose code text
                     references a secret-file token;
                 (c) env-value dumps (printenv/env) and echoing token-like variables;
                 (d) best-effort: inline-eval WRITES to a non-exempt source path (a
                     known plan-first bypass vector — steer to Edit/Write instead).

Trade-off (accepted): the inline-eval matcher is text-based and may over-block an
innocent one-liner that merely mentions `.env`. We accept over-blocking on the read
side — a harmless retry vs. an irreversible leak. Listing NAMES is never blocked.
Full Bash-write coverage is undecidable by static text inspection; the recommended
complete control is a PostToolUse diff/worktree check (out of scope here).

Contract: exit code 2 + stderr blocks the tool call. Any unexpected input exits 0.
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
      | \.p12$
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
        (^|/)\.env(?!\.(?:example|sample|template|dist|defaults)\b)
      | (^|/)credentials
      | \.p12\b
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
    r"|grep|rg|tee|dd|base64|openssl|gpg)"
)
_SECRET_TOKEN = (
    r"(?:\.env(?!\.(?:example|sample|template|dist|defaults))(?:\.|\b)"
    r"|credentials[\w.-]*\.(?:json|plist|p8|pem|key|txt)"
    r"|\.p12\b|\.mobileprovision\b|\.keystore\b|\.jks\b|\.p8\b|\.pem\b)"
)
BASH_FILE_READ = re.compile(
    r"\b" + _READ_VERB + r"\b[^|&;\n]*?" + _SECRET_TOKEN, re.IGNORECASE
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

ENV_DUMP = re.compile(r"(?:^|[|&;]\s*)(?:printenv\b|env\s*(?:$|[|&>]))", re.IGNORECASE)
ECHO_SECRET = re.compile(
    r"\b(?:echo|printf)\b[^|&;\n]*\$\{?\s*[A-Za-z_]*"
    r"(?:TOKEN|SECRET|BEARER|PASSWORD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)


def block(msg: str) -> None:
    sys.stderr.write("[guard-secrets-read] " + msg + "\n")
    sys.exit(2)


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


# --- decision core (pure; returns ("allow"|"block", message) for testability) ---
def decide(data: dict, *, cfg=None):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    if cfg is None:
        cfg = _config.load(_config.repo_root(data))
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
        if BASH_FILE_READ.search(cmd) or (extras and _hits_extra(cmd, extras)
                                          and BASH_FILE_READ.search(cmd + " ")):
            return ("block",
                    "Reading a secret file's contents via shell is blocked (Rule #1). "
                    "Reading file names is fine; contents are not.")
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
    sys.exit(0)


# --- selftest -------------------------------------------------------------------
def _selftest() -> int:
    """Exercise the decision core with fictional secret paths (never real files)."""
    results = []
    cfg = dict(_config.DEFAULTS)

    def check(name, expected, data):
        try:
            verdict, _ = decide(data, cfg=cfg)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    def read(fp):
        return {"tool_name": "Read", "tool_input": {"file_path": fp}}

    def grep(pattern="x", path=None, glob=None):
        ti = {"pattern": pattern}
        if path is not None:
            ti["path"] = path
        if glob is not None:
            ti["glob"] = glob
        return {"tool_name": "Grep", "tool_input": ti}

    def bash(cmd):
        return {"tool_name": "Bash", "tool_input": {"command": cmd}}

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
    check("w8 plain echo > .ts allowed (not inline-eval)", "allow",
          bash("echo 'x' > src/foo/a.ts"))

    # --- extra pattern from config ---
    cfg_extra = _config._deep_merge(
        _config.DEFAULTS, {"secretPatterns": {"extra": [r"\.secretrc$"]}})

    def check_extra(name, expected, data):
        try:
            verdict, _ = decide(data, cfg=cfg_extra)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    check_extra("x1 Read .secretrc (extra) blocked", "block", read("app/.secretrc"))
    check_extra("x2 Read normal (extra cfg) allowed", "allow", read("app/index.ts"))

    # --- malformed / unhandled → allow ---
    check("u1 unhandled tool allowed", "allow",
          {"tool_name": "Glob", "tool_input": {"pattern": ".env"}})
    check("u2 empty input allowed", "allow", {})

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
