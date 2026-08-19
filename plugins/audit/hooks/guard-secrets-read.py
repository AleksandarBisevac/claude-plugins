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
This hook carries no `--selftest` of its own any more; its 93 cases live in
`plugins/audit/tests/test_guard_secrets_read.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
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

# F-P-7: the write CALL and the path it writes, captured TOGETHER. The old
# pattern matched a write-shaped fragment anywhere in the clause and left the
# target to a second, unrelated search — so `>` inside the code (a comparison,
# `len(x)>3`, or a redirect into /tmp) paired with the quoted name of the file
# being READ, and a read-only one-liner over a .json was refused as a source
# write. Reported from a live repo, where the reader routed around the guard
# with `jq`; a guard that fires on reads teaches people to ignore it, which
# costs more than the writes it catches.
#
# Each alternative names its target in group 1 or 2, so `_eval_write_targets`
# can answer "what does this write?" instead of "does a write and a path both
# appear here?". The bare `>`/`>>` redirect is deliberately NOT here: a shell
# redirect into a source file is `_source_write_hit`'s job (it reads the whole
# command with the redirect grammar), and duplicating it here is what produced
# the false positive.
_WRITE_CALL = re.compile(
    r"(?:open\s*\(\s*['\"]([\w./-]+)['\"]\s*,\s*['\"](?:w|a|wb|ab|w\+|a\+|r\+)['\"]"
    # `append` alongside `write`: appending to a source file edits it, and
    # `fs.appendFileSync` walked straight through a pattern that only knew the
    # word "write".
    r"|(?:fs\.)?(?:write|append)(?:File)?(?:Sync)?\s*\(\s*['\"]([\w./-]+)['\"]"
    r"|createWriteStream\s*\(\s*['\"]([\w./-]+)['\"]"
    r"|File\.(?:open|write)\s*\(\s*['\"]([\w./-]+)['\"]"
    # The RECEIVER form. `Path('x.py').write_text(...)` names its target before
    # the call, so a pattern that only looks inside the parentheses cannot reach
    # it however many call names it is given -- which is why adding names had
    # not found it. F20 listed `Path.write_*` in its fix shape.
    r"|Path\s*\(\s*['\"]([\w./-]+)['\"]\s*\)\s*\.\s*write_(?:text|bytes)"
    # Two-argument forms where the SECOND path is the one written. An atomic
    # rename and a copy are edits with different spelling.
    r"|(?:os\.(?:replace|rename)|shutil\.(?:copy2?|copyfile|move))\s*\(\s*"
    r"(?:['\"][^'\"]*['\"]|[\w.]+)\s*,\s*['\"]([\w./-]+)['\"])",
    re.IGNORECASE,
)


def _eval_write_targets(clause):
    """Every path this clause actually WRITES, from the write calls themselves."""
    out = []
    for m in _WRITE_CALL.finditer(clause):
        for g in m.groups():
            if g:
                out.append(g)
                break
    return out
_NON_EXEMPT_WRITE_TARGET = re.compile(
    r"['\"][\w./-]+\.(?:tsx?|jsx?|mjs|cjs|json|ya?ml|swift|kt|java|rb|py|sh|gradle|"
    r"podspec|plist)['\"]",
    re.IGNORECASE,
)
_EXEMPT_WRITE_PATH = re.compile(
    r"(?:\.claude/|docs/audit/|\.md['\"\s]"
    # F20's own class, found by measuring this function rather than by a report:
    # a scratch file under a temp root is not source, and refusing it is how a
    # guard teaches people to route around it -- into the shape it cannot see at
    # all. `/private/tmp` and `/var/folders` are what a macOS session actually
    # gets, so listing only `/tmp` would have exempted the example and not the
    # reality. Matched against the TARGET, never the clause: a source write that
    # merely reads from /tmp stays a write (s43).
    r"|^['\"]/(?:private/)?tmp/|^['\"]/var/folders/)",
    re.IGNORECASE,
)
# F-A-1 (v0.37 A1): `\.test\.|\.spec\.` used to live in _EXEMPT_WRITE_PATH, so
# ANY name containing the suffix walked through the eval-write backstop --
# `python3 -c "open('tsconfig.test.json','w')..."` was allowed while the same
# file through Edit is gated. Same data-format carve-out the Edit-path glob
# lists got in v0.36 A1: a test-suffix NAME whose extension is a pure
# data/markup format is build configuration, not a test. The authoritative
# extension list is _config._NON_CODE_TEST_EXTS -- SHARED, not copied: this
# hook sits in the same hooks package (_config is already its config/manifest
# core), the leading underscore marks the name internal to that package, and a
# public alias would be a second name for one list that the two matchers could
# then drift apart on.
_TEST_SUFFIX_TOKEN = re.compile(r"[\w.+~/-]*\.(?:test|spec)\.[\w.+-]*",
                                re.IGNORECASE)


def _exempt_eval_write(clause):
    """True when an eval-write clause names an exempt path (used per clause).

    Exempt: .claude/, docs/audit/, .md targets, and test-suffix names -- but a
    test-suffix name in a data/markup format (.json/.yaml/.toml/...) is NOT a
    test file and keeps no exemption.
    """
    if _EXEMPT_WRITE_PATH.search(clause):
        return True
    return any(
        not m.group(0).lower().endswith(_config._NON_CODE_TEST_EXTS)
        for m in _TEST_SUFFIX_TOKEN.finditer(clause))

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


def _clauses(cmd: str):
    """Split a shell command into clauses on `;`, `|`, `&` OUTSIDE quotes (F-B-1).

    The inline-eval heuristics must judge each clause on its own facts:
    `x.py --selftest >/tmp/out; python3 -c "json.load(open('a.json'))"` is a
    redirect in one clause and an eval in another, and reading them as one
    command manufactured a deny neither clause earns (reproduced live).

    Deliberately simple, and FAIL-SAFE about its own limits: quote tracking
    covers '...', "..." and backslash escapes; when the quoting cannot be
    tracked (unbalanced at end of string) the WHOLE command is returned as one
    clause, so an unparseable command is judged exactly as strictly as before
    the split existed. A single-clause command comes back unchanged either way
    — the split can only narrow multi-clause false positives, never widen what
    one clause may do. Separators inside `$( )` are an accepted imprecision:
    full shell parsing is out of scope here (see the header's trade-off note),
    and each fragment is still judged by the same regexes."""
    parts, buf, quote = [], [], None
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch in (";", "|", "&"):
            if "".join(buf).strip():
                parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quote is not None:
        return [cmd]  # unbalanced quoting: unsure, so judge it as ONE clause
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts or [cmd]


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


def _append_verdict_event(root, cfg, data, verdict, msg):
    """One line into the gate events feed for a deny/ask verdict (v0.36 A4).

    require-plan's verdicts have fed <logsDir>/plan-gate-events.jsonl since
    v0.34 B3; this guard's denials left no trace in the same feed, so "what has
    the gate been doing" had an answer with a hole in it. Same shape, same
    writer (_config.append_gate_event); the reason is prefixed with this hook's
    name so the two sources stay tellable apart. Telemetry only: never raises,
    never blocks, never changes the verdict."""
    try:
        ti = (data or {}).get("tool_input", {}) or {}
        target = (ti.get("file_path") or ti.get("path") or ti.get("glob")
                  or ti.get("command") or "")
        first_line = str(msg or "").splitlines()[0] if msg else ""
        _config.append_gate_event(
            _config.logs_dir(root, cfg),
            {"event": "deny" if verdict == "block" else "ask.shown",
             "file": str(target),
             "mode": "deny" if verdict == "block" else "ask",
             "reason": "guard-secrets-read: %s" % first_line,
             "sessionId": (data or {}).get("session_id")})
    except Exception:
        pass


# --- decision core (pure; returns ("allow"|"block", message) for testability) ---
def decide(data: dict, *, cfg=None):
    """Resolve config, decide, and leave a gate event for deny/ask verdicts.

    The decision itself lives in _decide_core; this wrapper is the ONE choke
    point every verdict passes through, so no deny branch — present or future —
    can miss the events feed."""
    root = _config.repo_root(data)
    if cfg is None:
        cfg = _config.load(root)
    verdict, msg = _decide_core(data, root, cfg)
    if verdict in ("block", "ask"):
        _append_verdict_event(root, cfg, data, verdict, msg)
    return (verdict, msg)


def _decide_core(data: dict, root, cfg):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
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
        # F-B-1: the two inline-eval heuristics run PER CLAUSE. Over the whole
        # command, a redirect in clause one plus an eval in clause two used to
        # combine into a deny neither clause earns. A single-clause command is
        # judged exactly as before (see _clauses).
        clauses = _clauses(cmd)
        for cl in clauses:
            if _INLINE_EVAL.search(cl) and (SECRET_TOKEN_RE.search(cl)
                                            or _hits_extra(cl, extras)):
                return ("block",
                        "Reading a secret file via an inline-eval one-liner "
                        "(python -c / node -e / ruby/perl -e …) is blocked (Rule #1). "
                        "Listing names is fine; reading contents is not. Ask the user to "
                        "paste any value you actually need.")
        for cl in clauses:
            # F-P-7: judged on the paths the write calls NAME, not on a write
            # shape and a path that merely share a clause.
            targets = _eval_write_targets(cl) if _INLINE_EVAL.search(cl) else []
            if any(_NON_EXEMPT_WRITE_TARGET.search("'%s'" % t)
                   and not _exempt_eval_write("'%s'" % t) for t in targets):
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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("guard-secrets-read.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_guard_secrets_read.py - run that file "
              "instead.")
        sys.exit(0)
    main()
