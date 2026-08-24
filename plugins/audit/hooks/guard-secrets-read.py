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
                 (c) env-value dumps (printenv/env/direnv dump, `process.env`) and
                     echoing token-like variables;
                 (d) a command that reaches the environment layer with the harness
                     sandbox switched off (`dangerouslyDisableSandbox`).

WHAT THIS HOOK CAN AND CANNOT DO — the ceiling, stated here because leaving it
unstated is what made it a defect. Every matcher above reads the TEXT of a tool
call. None of them observes I/O. A value loaded INDIRECTLY prints identically and
names nothing this file can match: that is what `direnv exec . printenv X` did,
against a `.envrc` holding one `export`, with the sandbox off — no deny, no gate
message, no journal row. `.envrc`, the wrapper form of `printenv` and the sandbox
flag are all covered now, and the class is not: a test harness that loads dotenv,
a script that reads the file itself, any program that already has the value.

So the ceiling here is FRICTION plus EVIDENCE, not containment. Containment is
the harness sandbox's job and always was — which is why (d) exists at all, and why
journal-writes records every unsandboxed Bash run whether or not this hook refused
it. SECURITY.md says the same thing in the same words; keep the two in step.

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
static text inspection (obfuscated redirects — upstream
anthropics/claude-code#29709); the complete control would be a PostToolUse
diff/worktree check (out of scope, documented in SECURITY.md).

`heredocs into interpreters` used to be listed on that undecidable line and is
not any more (F31). `python3 - <<PY` is the same capability as `python3 -c`
spelled differently, and it walked through because the pattern knew the spelling
rather than the capability. A heredoc body is now graded when — and only when —
it feeds an interpreter; a body fed to anything else is DATA and leaves the
scanned text, which is what stopped this guard refusing a commit whose message
merely described a write.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 — the canonical
PreToolUse protocol (the exit-2 + stderr channel is deprecated). Any
unexpected input exits 0.
This hook carries no `--selftest` of its own any more; its cases live in
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
        (^|/)\.env(?!\.(?:example|sample|template|dist|defaults)\b)(?:rc)?(\.[^/]+)?$
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
# P0-S. Two edits, and both are about the SAME confusion between a dotenv FILE and
# the process environment:
#
#   * `rc\b` -- `.envrc` was in none of the three secret sets, and it is the file the
#     live report was actually about: one `export VERCEL_SCOPE=` line, read by
#     direnv. `.direnvrc`/`direnvrc` are direnv's own configuration, hold no
#     exports, and stay out because the leading dot is required.
#   * `(?<!process)` -- `process.env` ends in a token this pattern read as a dotenv
#     file, so `node -e "console.log(process.env.NODE_ENV)"` was refused as
#     "reading a secret file's contents". Right family, wrong rule: the environment
#     is Rule #2's subject and files are Rule #1's, and a guard that misnames what
#     it caught is a guard people learn to argue with. KNOWN COST, stated rather
#     than discovered: a file genuinely named `*process.env` loses this token in
#     shell text. The Read and Grep sets are untouched, so that file is still
#     blocked through the tools that read it.
_SECRET_TOKEN = (
    r"(?:(?<!process)\.env(?!\.(?:example|sample|template|dist|defaults))"
    r"(?:rc\b|\.|\b)"
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
# Every write shape this knows, capturing the path ARGUMENT rather than requiring it
# to be a quoted literal.
#
# IT USED TO DEMAND THE LITERAL, and that is F-7: a path arriving through a variable
# did not match a write call at all, so the write was not merely unclassified, it was
# invisible. The argument is captured here and RESOLVED by `_resolve_write_expr`,
# which reads a literal, a join of literals, or one hop of binding.
#
# The alternatives below were each earned, and the reasons outlive the pattern that
# first carried them:
#
#   * `append` alongside `write`: appending to a source file edits it, and
#     `fs.appendFileSync` walked straight through a pattern that only knew the word
#     "write".
#   * the RECEIVER form. `Path('x.py').write_text(...)` names its target BEFORE the
#     call, so a pattern that only looks inside the parentheses cannot reach it
#     however many call names it is given -- which is why adding names had not found
#     it. F20 listed `Path.write_*` in its fix shape.
#   * two-argument forms where the SECOND path is the one written. An atomic rename
#     and a copy are edits with different spelling.
#
# KNOWN LIMIT, said rather than left to be discovered: an argument containing a comma
# ends the capture, so `open(os.path.join(a, b), 'w')` matches nothing here. The
# literal-only pattern this replaced missed it too, for the same reason it missed a
# bare name -- it is a call, not a path. Naming the limit is what keeps a later
# reader from assuming coverage the expression can not give.
_WRITE_CALL_EXPR = re.compile(
    r"(?:open\s*\(\s*([^,)]+?)\s*,\s*['\"](?:w|a|wb|ab|w\+|a\+|r\+)['\"]"
    r"|(?:fs\.)?(?:write|append)(?:File)?(?:Sync)?\s*\(\s*([^,)]+?)\s*[,)]"
    r"|createWriteStream\s*\(\s*([^,)]+?)\s*[,)]"
    r"|File\.(?:open|write)\s*\(\s*([^,)]+?)\s*[,)]"
    r"|Path\s*\(\s*([^,)]+?)\s*\)\s*\.\s*write_(?:text|bytes)"
    r"|(?:os\.(?:replace|rename)|shutil\.(?:copy2?|copyfile|move))\s*\(\s*"
    r"(?:['\"][^'\"]*['\"]|[\w.]+)\s*,\s*([^,)]+?)\s*[,)])",
    re.IGNORECASE,
)

# One hop of binding: `p='x.py'`, `const p = 'x.py'`, `p = 'a/' + 'b.py'`. That is
# what a two-line script writes, and one hop is all this resolves - a chain through
# a second name, an f-string or a `join()` is dataflow this guard does not do, which
# is stated here rather than left for somebody to discover.
# A NEGATIVE LOOKBEHIND, not a list of allowed separators. The list was written
# first - `[;\n{}(\s]` - and it missed the commonest position of all: the FIRST
# statement of a one-liner, where the character before the name is the opening quote
# of `python3 -c "p='...'`. A rule about what may not precede a name is shorter than
# an inventory of what may, and it cannot be short by one.
_EVAL_BINDING = re.compile(
    r"(?<![\w$.])(?:const\s+|let\s+|var\s+)?([A-Za-z_$][\w$]*)\s*=\s*"
    r"((?:['\"][^'\"\n]*['\"])(?:\s*\+\s*['\"][^'\"\n]*['\"])*)")

_STRING_LITERAL = re.compile(r"['\"]([^'\"\n]*)['\"]")

_BARE_NAME = re.compile(r"^[A-Za-z_$][\w$]*$")


def _eval_bindings(clause):
    """{name: the string it was bound to} for the literal bindings in `clause`."""
    out = {}
    for m in _EVAL_BINDING.finditer(clause):
        joined = "".join(_STRING_LITERAL.findall(m.group(2)))
        if joined:
            out.setdefault(m.group(1), joined)
    return out


def _resolve_write_expr(expr, bindings):
    """The path an argument NAMES: a literal, a join of literals, or a bound name.

    Returns None when the argument is something this cannot read - a call, an
    f-string, a name bound to anything but literals. None means "no target", not
    "no write", and the caller treats it as nothing to judge, which keeps this on
    the same side of the line `_clauses` and `_split_heredocs` are on: unreadable
    input is never quietly graded as clean by INVENTING a target for it.
    """
    expr = expr.strip()
    literals = _STRING_LITERAL.findall(expr)
    if literals:
        return "".join(literals)
    if _BARE_NAME.match(expr):
        return bindings.get(expr)
    return None


def _eval_write_targets(clause):
    """Every path this clause actually WRITES, from the write calls themselves.

    F-P-7 narrowed this from "a write shape and a path in the same clause" to "the
    path the write call NAMES", and that narrowing is what F-7 walked through: the
    pattern required the name to be a quoted LITERAL in the argument position, so

        p = 'src/app.ts'
        open(p, 'w').write(...)

    named nothing and was allowed - while the identical write with the path spelled
    inline was blocked. Same capability, same target, same intent; only the
    syntactic adjacency differed, and it is the shape every two-line bulk edit uses.
    Measured after the fact: fifteen source edits in one session went through it.

    So the argument is RESOLVED rather than required to be a literal - one hop of
    binding, plus a join for a concatenation. F-P-7's property survives: a path that
    merely shares the clause is still not a target, because only the expression the
    write call actually names is read.
    """
    out = []
    bindings = None
    for m in _WRITE_CALL_EXPR.finditer(clause):
        expr = next((g for g in m.groups() if g), None)
        if expr is None:
            continue
        if bindings is None:
            bindings = _eval_bindings(clause)
        target = _resolve_write_expr(expr, bindings)
        if target:
            out.append(target)
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
#
# A DRIVE-ABSOLUTE PATH IS ONE TOKEN, and the first alternative is only there
# because it was not. The redirect and `tee` branches take their target whole -
# `[^\s|&;<>]+` and a whitespace split both carry `C:\out\probe.ts` intact - so
# `within_root` gets the path the command named and answers OUTSIDE. This
# pattern's class holds no drive designator and no backslash, so the same path
# arrived here as `probe.ts`: a bare basename, which is relative, which is
# unconditionally inside the repository. One file, one command, and the verdict
# depended on which write form spelled it - while SECURITY.md promises "the same
# file gets the same verdict whether it is edited through a tool or through `sed
# -i`". Forward slashes lost only the drive (`C:/out/probe.ts` -> `/out/probe.ts`)
# and pathlib then re-attached the ROOT's drive, so a repo on `D:` judged a `C:`
# path to be its own. Fail-closed either way - the wrong answer is a deny - but a
# deny nobody can act on is the route-around class, which is what the `xs` cases
# in the suite exist to close.
#
# The drive form is a separate alternative rather than `\\` added to the class:
# adding it there makes `sed -i 's/foo\.ts/bar/' README.md` match `s/foo\.ts` and
# report a write to a file the command only mentions. `(?<!\w)` keeps `http://`
# out of the drive branch, so a URL inside a sed script tokenises exactly as it
# did. Checked against both spellings and the POSIX corpus: nothing but a
# drive-absolute path changes.
_PATHY_TOKEN = re.compile(
    r"(?<!\w)[A-Za-z]:[\\/][\w@~/\\.+-]*\.[A-Za-z][A-Za-z0-9]{0,9}"
    r"|[\w@~./+-]+\.[A-Za-z][A-Za-z0-9]{0,9}")

# --- Rule #2: the environment itself -------------------------------------------
# P0-S: `printenv` USED TO BE ANCHORED to the start of a clause, so any wrapper in
# front of it was enough to walk past this guard entirely --
# `direnv exec . printenv VERCEL_SCOPE` printed a secret and left no deny, no
# gate message and no journal row. The verb is a dump wherever it stands, so the
# rule is now about what may not PRECEDE it rather than about what may: an
# inventory of legal wrappers cannot be written, and would be short by one the
# day somebody reaches for `sudo`, `xargs` or a container. Same lesson
# `_EVAL_BINDING` below carries, in the same shape.
#
# `env` keeps its clause anchor deliberately: as a bare word it is the commonest
# fragment in this whole file's subject matter (`NODE_ENV`, `--env`, `.env.example`),
# and `env FOO=1 cmd` is a launcher, not a dump. The wrapper case that matters --
# `env -i printenv X` -- is caught by the `printenv` half anyway.
#
# `direnv dump` / `direnv export` print the loaded environment and are the two
# direnv subcommands that do; `direnv exec`, `direnv allow` and the rest are the
# tool doing its job and stay allowed (the second-direction cases pin that).
#
# WHAT THIS PATTERN IS SEARCHED OVER IS PART OF THE RULE, and it is not the raw
# command: see `_executed_text` below. Un-anchoring the verb was right and stays;
# searching the whole TEXT for it was not, and it made a word in an `echo`
# argument or in a commit message weigh exactly as much as a command.
ENV_DUMP = re.compile(
    r"(?:(?<![\w.$-])printenv\b"
    r"|(?:^|[|&;]\s*)env\s*(?:$|[|&>])"
    r"|\bdirenv\s+(?:dump|export)\b)",
    re.IGNORECASE,
)
# ONE definition of "a token-shaped variable name", shared by the shell form and
# the JavaScript one. It existed only inside ECHO_SECRET, and `process.env.API_KEY`
# needed the same vocabulary -- a second copy is how the two spellings drift apart.
_TOKEN_NAME = (
    r"[A-Za-z_]*"
    r"(?:TOKEN|SECRET|BEARER|PASSWORD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)"
)
ECHO_SECRET = re.compile(
    r"\b(?:echo|printf)\b[^|&;\n]*\$\{?\s*" + _TOKEN_NAME,
    re.IGNORECASE,
)
# `process.env` is the environment, not a file. The whole object is a dump; a
# token-SHAPED name is a secret by the same vocabulary `echo $API_KEY` is judged
# by; one ordinary named variable (`process.env.NODE_ENV`) is neither, and used to
# be refused as a secret-file read.
PROCESS_ENV = re.compile(
    r"process\.env\s*(?![.\[\w])"
    r"|process\.env\s*(?:\.\s*|\[\s*['\"])" + _TOKEN_NAME,
    re.IGNORECASE,
)

# --- P0-S: the sandbox escape hatch ---------------------------------------------
# Commands that reach the environment layer, whether or not they name a file. This
# is the set the sandbox flag is judged against -- NOT a deny list of its own, or
# `direnv exec . npm test` would be refused for loading an env so a test can run.
ENV_ADJACENT = re.compile(
    r"(?:\.envrc\b"
    r"|(?<!process)\.env(?!\.(?:example|sample|template|dist|defaults))(?:\.|\b)"
    r"|\bdirenv\b"
    r"|\bdotenvx?\b"
    r"|(?<![\w.$-])printenv\b"
    r"|process\.env\b"
    r"|(?:^|[|&;]\s*)env\s*(?:$|[|&>]))",
    re.IGNORECASE,
)


def _sandbox_disabled(ti):
    """True when the call asked to run OUTSIDE the harness sandbox.

    `dangerouslyDisableSandbox` arrives in the same `tool_input` every branch here
    already reads, and nothing in this plugin looked at it until P0-S: a Bash call
    carrying it read `.envrc` through direnv and left no trace anywhere.

    A JSON boolean is what the harness sends. The string form is accepted too
    because a payload is not this hook's to validate, and testing `is True` alone
    would grade `"true"` as SANDBOXED -- a default quietly filling a gap, on the
    side that fails open.
    """
    value = (ti or {}).get("dangerouslyDisableSandbox")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _deny_payload(msg):
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-secrets-read] " + msg,
        }
    }


def _ask_payload(msg):
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


def block(msg):
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


_HEREDOC_START = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# The head of a heredoc line, when what it invokes reads its program from stdin.
# `python3 - <<PY`, `python3 <<PY`, `node <<JS`, `bash -s <<EOF` are all the same
# capability as `python -c`, spelled differently; `git commit -F - <<MSG` and
# `cat <<EOF` are not, because the body is data those commands never execute.
_STDIN_INTERP = re.compile(
    r"\b(?:python3?|python3\.\d+|node|nodejs|deno|bun|ruby|perl|php|bash|sh|zsh)\b"
    r"(?:\s+-[A-Za-z-]+)*\s*-?\s*$",
    re.IGNORECASE,
)


def _split_heredocs(cmd):
    """(text without heredoc bodies, bodies that are CODE).

    F31, found while committing a fix to this file: the guard refused its own
    commit, because the message DESCRIBED the write forms it had just learned and
    every branch here scans the whole command text. Probing that turned up the
    mirror defect -- `python3 - <<'PY'` performs exactly what `python3 -c` does
    and walked straight through, because the pattern knows the `-c` SPELLING
    rather than the capability. One root, two directions.

    So the body is separated from the text and handed back only when it feeds an
    interpreter. Prose in a commit message stops being read as code; a heredoc
    fed to python or node starts being read as the code it is.

    Fail-safe about its own limits, like `_clauses`: a heredoc whose terminator
    never arrives is left in the text, so an unparseable command is judged
    exactly as strictly as before this existed.
    """
    if "<<" not in cmd:
        return cmd, []
    lines = cmd.split("\n")
    kept, code, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_START.search(line)
        if not m:
            kept.append(line)
            i += 1
            continue
        delim = m.group(2)
        # Look for the terminator before consuming anything: without one there is
        # no body to separate, only a line that happens to contain `<<`.
        end = None
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == delim:
                end = j
                break
        if end is None:
            kept.append(line)
            i += 1
            continue
        kept.append(line[:m.start()])
        body = "\n".join(lines[i + 1:end])
        if _STDIN_INTERP.search(line[:m.start()].strip()):
            code.append(body)
        i = end + 1
    return "\n".join(kept), code


# --- text that is DATA, for Rule #2's dump verb ---------------------------------
# The arguments of a pure text-emitter, up to the end of its clause. `echo` and
# `printf` do not execute what they are handed, so a verb standing there is a word
# and not a command.
#
# TWO THINGS ARE DELIBERATELY NOT MATCHED, and both are the same rule: the emitter's
# output must not be able to become code again.
#   * a clause ending in `|` never matches at all -- the lookahead admits only `;`,
#     `&`, a newline or the end of the command -- because `echo printenv | sh`
#     hands the text to a shell, which runs it. Not stripping it leaves that
#     judged exactly as strictly as before this existed;
#   * a substitution INSIDE the arguments (`$(...)`, backticks, `<(...)`) keeps the
#     whole span, because `echo $(printenv X)` really does dump the environment.
#     The argument text is inert; a substitution inside it is not.
#
# The verb is fenced on BOTH sides, and `\b` alone is not enough on the right: it
# holds between `o` and `-`, so `echo-server printenv` would have claimed the
# exemption while being a different program entirely. A name this exemption cannot
# read is a name it does not exempt.
_TEXT_EMITTER_ARGS = re.compile(
    r"(?<![\w.$/-])(echo|printf)(?![\w.-])([^|&;\n]*)(?=$|[&;\n])")
_SUBSTITUTION = re.compile(r"\$\(|`|<\(")


def _strip_emitter_args(m):
    """Keep the emitter verb, drop the inert text after it (see the pattern)."""
    if _SUBSTITUTION.search(m.group(2)):
        return m.group(0)
    return m.group(1)


def _executed_text(cmd):
    """`cmd` with the spans that are DATA removed, leaving what a shell would RUN.

    THE ASYMMETRY THAT MAKES THIS LEGITIMATE, and it is the whole justification.
    P0-S un-anchored the dump verb because an allow-list of legal WRAPPERS cannot
    be written: `sudo`, `xargs`, a container runner, and the list is short by one
    entry the day somebody reaches for the next one. Missing an entry there is a
    BYPASS -- silent, and in the dangerous direction. That reasoning is sound and
    it stands.

    An exemption for places where text is INERT fails the opposite way. The list
    here is the argument list of a pure text-emitter and a heredoc body that feeds
    something which does not execute it. Missing an entry leaves a FALSE POSITIVE:
    a refusal the user sees, argues with, and reports -- loud, and on the safe
    side. So the second kind of list is legitimate exactly where the first is not,
    and that is why this is a fix rather than a hole.

    Heredocs come from `_split_heredocs`, which already draws this line and draws
    it correctly (F31): a body fed to an interpreter is CODE and comes back, so
    `python3 - <<PY` is still judged as `python3 -c` is, and only a body fed to
    something like `git commit -F -` or `cat` leaves. Nothing about that grading
    changes here; this only spends it on one more branch.

    Scoped to Rule #2's dump verb on purpose, and ECHO_SECRET is the reason it
    cannot simply be global: there the emitter's argument list is the PAYLOAD --
    `echo $TOKEN` is the leak -- so stripping it would delete the very text that
    rule exists to read.
    """
    text, code_bodies = _split_heredocs(cmd)
    text = _TEXT_EMITTER_ARGS.sub(_strip_emitter_args, text)
    return "\n".join([text] + code_bodies)


def _clauses(cmd):
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


def _shell_write_targets(cmd):
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


def _source_write_hit(cmd, root, cfg):
    """First non-exempt SOURCE file (not covered by an in_progress task) that
    `cmd` writes to via sed -i / tee / a >(>) redirect — or None.

    A target OUTSIDE the consuming repository is skipped, not reported. This is
    the shell-write half of the plan gate and SECURITY.md promises the two
    halves agree — "the same file gets the same verdict whether it is edited
    through a tool or through `sed -i`" — so require-plan's containment check is
    one this branch owes identically. Without it `sed -i` into a scratch file
    under the system temp directory relpath'd to `../../../private/tmp/probe.py`,
    matched no exempt glob, was covered by no in_progress task, and denied. A
    `continue` rather than a `return`: a command writing one file out of scope
    and one in it still has an in-repo finding to report."""
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
        if not _config.within_root(root, t):
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
def decide(data, *, cfg=None):
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


def _decide_core(data, root, cfg):
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
        # FIRST, because it is the only branch that knows the OS layer is off, and
        # a reader who is told "this reads a secret file" learns less than one who
        # is told "this reads it with containment switched off".
        #
        # Bounded to the COMBINATION on purpose. An unsandboxed run is legitimate
        # and common -- it is why the flag exists -- so denying every one of them
        # would make the guard unusable and get it routed around, which is the
        # failure mode this whole item is about. Every other unsandboxed run is
        # RECORDED instead, by journal-writes at PostToolUse: a hook that cannot
        # contain the event can still refuse to let it be invisible.
        if _sandbox_disabled(ti) and ENV_ADJACENT.search(cmd):
            return ("block",
                    "This command reaches the environment layer with the harness "
                    "sandbox switched off (dangerouslyDisableSandbox), and the "
                    "sandbox is the only layer that can actually contain a read.\n"
                    "These hooks match the TEXT of a tool call, not the I/O it "
                    "performs, so a value loaded indirectly (direnv, dotenv, a "
                    "test harness) would print with nothing here able to stop it. "
                    "Run it sandboxed, or ask the user to paste the one value you "
                    "need. The unsandboxed run is journalled either way.")
        # Over what a shell would RUN, not over the whole text. P0-S un-anchored
        # the dump verb, correctly, but implemented "any command position" as "any
        # substring", so a word in an `echo` argument or a commit-message heredoc
        # became a dump. `_executed_text` says which spans are data and why that
        # exemption is safe where a wrapper allow-list is not.
        if ENV_DUMP.search(_executed_text(cmd)):
            return ("block",
                    "Dumping environment values (printenv/env) is blocked (Rule #2). "
                    "Debug with a prefix only: val[:6] + length.")
        # The SAME span rule as the verb above, and it belongs here for the
        # same reason: naming the environment object in an `echo` argument or
        # in a heredoc body that nothing executes is prose, not a read. Threading
        # it into one arm and not the other is how a fixed defect keeps its
        # second spelling - the first thing this branch blocked was the `grep`
        # used to work on the arm above.
        if PROCESS_ENV.search(_executed_text(cmd)):
            return ("block",
                    "Reading the process environment is blocked (Rule #2): this "
                    "prints environment values, not a file.\n"
                    "One ordinary named variable is fine; the whole object and a "
                    "token-shaped name are not. Debug with a prefix only: "
                    "val[:6] + length.")
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
        # F31: a heredoc body is graded when, and only when, it feeds an
        # interpreter. Data bodies leave the text entirely (prose that documents
        # a write is not a write); code bodies come back as clauses of their own,
        # so `python3 - <<PY` is judged exactly as `python3 -c` is.
        _text, _code_bodies = _split_heredocs(cmd)
        # (clause, is it already known to be code). A heredoc body carries no
        # `-c` spelling of its own -- being fed to an interpreter IS its
        # spelling -- so it arrives pre-judged rather than re-matched.
        graded = [(cl, bool(_INLINE_EVAL.search(cl))) for cl in _clauses(_text)]
        graded += [(b, True) for b in _code_bodies]
        for cl, is_eval in graded:
            if is_eval and (SECRET_TOKEN_RE.search(cl)
                            or _hits_extra(cl, extras)):
                return ("block",
                        "Reading a secret file via an inline-eval one-liner "
                        "(python -c / node -e / ruby/perl -e …) is blocked (Rule #1). "
                        "Listing names is fine; reading contents is not. Ask the user to "
                        "paste any value you actually need.")
        for cl, is_eval in graded:
            # F-P-7: judged on the paths the write calls NAME, not on a write
            # shape and a path that merely share a clause.
            targets = _eval_write_targets(cl) if is_eval else []
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


def main():
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
