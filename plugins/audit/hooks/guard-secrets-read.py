#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Read|Grep|Bash|mcp__.*).

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
                     `source .env` / `. .env`, an input redirection (`envsubst
                     < .env` names no verb and hands over every byte), and
                     copy-verbs (`cp`/`mv`/`rsync`/`install`) that would relocate
                     a secret for later reading. The project's own
                     `secretPatterns.extra` decides a read here too, on its own
                     and not behind the built-in set — see `_extra_read_hit`;
                 (b) inline-eval reads (python/node/ruby/perl/… -c/-e) whose code text
                     references a secret-file token;
                 (c) env-value dumps (printenv/env/direnv dump, `process.env`) and
                     echoing token-like variables;
                 (d) a command that reaches the environment layer with the harness
                     sandbox switched off (`dangerouslyDisableSandbox`).
  - MCP tools  → every path-shaped VALUE in the payload, at any depth, against
                 SECRET_PATH (+ extras). Two halves of that sentence are the
                 rule. The tool name is `mcp__<server>__<operation>` and the
                 server half is an alias the operator chose — the same npm
                 filesystem server is `mcp__filesystem__` on one machine and
                 `mcp__fs__` on the next — so nothing here reads it. The
                 argument keys are the same problem one level down (`path`,
                 `paths` as a list, `file_path`, `uri`), so nothing here reads
                 those either: the walk takes values and asks them the question
                 the `Read` branch asks its `file_path`. `_decide_core` says
                 which side this takes on a write and why.

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

Plan-first backstop for Bash WRITES (this is the only hook that sees Bash).
GRADED, and the ONLY graded rule in this file: both forms below are judged on
the plan gate's tier for the file (`_config.plan_gate_mode` — require-plan's own
resolver), so one file gets one verdict whether it is written through `Edit`,
through `sed -i`, or through `python3 -c`. `_plan_gate_write_verdict` is the one
place a tier is read, and no Rule #1 or Rule #2 branch calls it.
  - the write CALLS inside an interpreter — `python -c`, `node -e`, and the
    heredoc spelling of either — naming a non-exempt source path;
  - the high-signal shell write forms into a non-exempt source file: `sed -i`,
    `tee <file>`, and `>`/`>>` redirects (which also catches
    `cat > file <<EOF` heredocs). The block message steers to the Edit/Write
    tools, which the plan gate governs.
  Both arms ask `_ungoverned_write_target` the same questions — can the
  destination be established at all, source extension, inside the repository,
  not exempt, not covered by an in_progress
  task. They asked different ones for a long time, and the interpreter arm consulted
  no plan at all while its refusal blamed the plan-first gate: a `.ts` file a
  running task declared was denied through the interpreter and allowed through
  `echo >`, and a consumer's own `exemptGlobs` reached only the shell half.
  - those same write forms aimed at the MANIFEST - the configured `manifestPath`,
    its lockfile, or a phase shard `_config.governing_lock` resolves - which are
    refused to a subagent and to a session that is not the live lock holder,
    exactly as `require-plan` refuses them to `Edit`. Not by calling `.json` a
    source extension: that would refuse every package.json in a consumer's repo.
    `_manifest_write_hit` and `_manifest_write_verdict` hold the two halves.

Trade-off (accepted): the matchers are text-based and may over-block an innocent
one-liner that merely mentions `.env` (e.g. `cp .env.example .env`). We accept
over-blocking on the read side — a harmless retry vs. an irreversible leak.
Listing NAMES is never blocked. FULL Bash-write coverage is undecidable by
static text inspection (obfuscated redirects — upstream
anthropics/claude-code#29709); the complete control would be a PostToolUse
diff/worktree check (out of scope, documented in SECURITY.md).

`heredocs into interpreters` used to be listed on that undecidable line and is
not any more. `python3 - <<PY` is the same capability as `python3 -c`
spelled differently, and it walked through because the pattern knew the spelling
rather than the capability. A heredoc body is graded when — and only when — it
feeds something that runs it; a body fed to anything else is DATA and leaves the
scanned text, which is what stopped this guard refusing a commit whose message
merely described a write.

THAT SENTENCE HELD TRUE OF TWO BRANCHES ONLY, BUT WAS WRITTEN AS IF IT HELD FOR
ALL OF THEM. The separation was spent on Rule #2's dump verb and on the
inline-eval arms; the shell-read arm, the echo arm, the sandbox arm and the
shell-write arm went on reading the raw command, so one heredoc body was data for
one branch and a command for the next. Creating a markdown file whose prose quoted
an example command naming a key file was refused as "reading a secret file via
shell" — a write, judged by what its own payload said — and rewording the sentence
let the identical operation through, which is the route-around this header warns
about. Every branch now reads a VIEW of the command (`_shell_text`,
`_runnable_text`, `_executed_text`), and which view is each rule's own claim about
what counts as evidence. Two things fell out of measuring it: the LANGUAGE a body
is code in decides which rules may read it, and a data body piped onward
(`cat <<EOF | bash`) does run — which was a live bypass of Rule #2, not a risk the
narrowing introduced.

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
# ONE VOCABULARY FOR `credentials.<ext>`, READ BY THE TOOL SET AND BY THE SHELL SET.
# It was spelled twice and the two lists had come apart: the shell token knew a
# shorter set, so `cat config/credentials.yaml` was allowed while `Read` of the same
# file was refused - one file, two verdicts, decided by which spelling the agent
# reached for. That is the guard-by-spelling class, and `cat` is the everyday
# spelling, so the half that was wrong is the half everybody uses. SECURITY.md
# promises `credentials*` with no spelling attached, which is the promise this
# constant makes keepable.
_CRED_EXT = "json|plist|p8|pem|key|cer|der|txt|cfg|conf|ya?ml"

SECRET_PATH = re.compile(
    r"""(
        (^|/)\.env(?!\.(?:example|sample|template|dist|defaults)\b)(?:rc)?(\.[^/]+)?$
      | (^|/)credentials[^/]*\.(?:""" + _CRED_EXT + r""")$
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
    r"|credentials[\w.-]*\.(?:" + _CRED_EXT + r")\b"
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
# A READ WITH NO VERB IN IT. `_READ_VERB` is a list of programs, and an input
# redirection names none: `envsubst < .env`, `while read l; do …; done < .env` and
# `pbcopy < .env` all hand the file's bytes to something, and every one of them
# walked past a guard whose whole subject is that file. The redirect IS the read
# verb here, so it is matched as one.
#
# The exclusions are the spellings that do not open a file for reading:
# `<<` (a heredoc, whose body `split_heredocs` already grades), `<<<` (a here
# string, which is the same `<<` prefix), and `<(` (process substitution, whose
# body is a command). A descriptor in front is kept only for `0<`, which IS
# stdin - `2<` is a descriptor nothing reads from, and the lookbehind that keeps
# `a<b` inside a `sed` script from being a redirect keeps that out with it.
STDIN_READ_SECRET = re.compile(
    r"(?<![\w&<>])0?<(?![<(])[^|&;\n]*?" + _SECRET_TOKEN, re.IGNORECASE
)
# What makes a clause a READ at all, for the one rule whose vocabulary belongs to
# the project rather than to this file (see `_extra_read_hit`). The three arms are
# the three above, minus their secret token: a read verb, a dot-source, a redirect
# into something's stdin.
_READ_CLAUSE = re.compile(
    r"\b" + _READ_VERB + r"\b"
    r"|(?:^|[;&|(]\s*)\.\s+"
    r"|(?<![\w&<>])0?<(?![<(])",
    re.IGNORECASE,
)
# A shell WORD, for asking a project pattern about one argument at a time. The
# question `secretPatterns.extra` answers is "is this path a secret of ours", and
# a path is a word - asking it of the whole command line instead makes every
# pattern that is not anchored match the wrong half of a pipeline.
_SHELL_WORD = re.compile(r"[^\s'\"|&;<>()]+")

_INLINE_EVAL = re.compile(
    r"\b(?:python3?|python3\.\d+|node|nodejs|deno|bun|ruby|perl|php)\b"
    r"[^|&;\n]*?"
    r"(?:\s-(?:c|e|p|E|r|ne|pe)\b|\s--eval\b|\s--exec\b|\seval\b)",
    re.IGNORECASE,
)
SECRET_TOKEN_RE = re.compile(_SECRET_TOKEN, re.IGNORECASE)

# How the interpreter got its program, in the words the operator used. Both
# shapes are the same CAPABILITY and are graded identically, but a refusal
# that names the spelling nobody typed reads as a guard firing at random, and
# a guard people believe fires at random is one they route around. The
# distinction costs one word and buys the reader their own command.
_EVAL_SHAPE = {
    "-c": "an inline-eval one-liner (python -c / node -e / ruby/perl -e …)",
    "heredoc": ("a heredoc fed to an interpreter's stdin (python3 - <<EOF …), "
                "which is the same capability as python -c and is graded as one"),
}

# The write CALL and the path it writes, captured TOGETHER. The old
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
# IT USED TO DEMAND THE LITERAL: a path arriving through a variable
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
#     it. `Path.write_*` is matched as that receiver rather than as a call name.
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
    # `(?:fs\.)?` USED TO BE OPTIONAL AROUND A BARE `write`/`append`, and
    # nothing in any of these languages puts a path first in a call spelled that
    # way: Python's `f.write(data)` and Node's `fs.write(fd, buf)` both take the
    # PAYLOAD (or a descriptor) there, and Ruby's path-first `File.write` has its
    # own alternative two lines down. So the commonest write in the tree --
    # `open(scratch, 'w').write(text)` -- was read twice: once correctly through
    # the `open` arm, and once more with its CONTENT captured as a second target.
    # A scratch write whose payload happened to quote a source path was refused,
    # naming a file the command only wrote INTO another file. Requiring the `fs.`
    # prefix or the `File` infix keeps every real path-first spelling
    # (`fs.appendFileSync`, a destructured `writeFileSync`) and drops the arm that
    # could only ever read a payload.
    r"|(?:fs\s*\.\s*(?:write|append)(?:File)?(?:Sync)?"
    r"|(?:write|append)File(?:Sync)?)\s*\(\s*([^,)]+?)\s*[,)]"
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

# One hop of binding for a SEQUENCE of literals - `argv = ['cat', '.env']`, and the
# JavaScript and Ruby spellings of the same line. `_EVAL_BINDING` above reads a name
# bound to a string, which is what a path arrives as; this reads a name bound to an
# argument VECTOR, which is what a command arrives as. Only literals, and the whole
# bracket must be literals: an element this cannot read leaves the name unresolved
# rather than half-resolved, which is the rule `_resolve_write_expr` already states
# for the other shape.
_SEQUENCE_BINDING = re.compile(
    r"(?<![\w$.])(?:const\s+|let\s+|var\s+)?([A-Za-z_$][\w$]*)\s*=\s*"
    r"[\[(]\s*((?:['\"][^'\"\n]*['\"]\s*,?\s*)+)[\])]")

_BARE_NAME = re.compile(r"^[A-Za-z_$][\w$]*$")
# The same vocabulary UNANCHORED, for pulling the names out of a call's argument
# list. `_BARE_NAME` asks whether a whole operand is a name, which is the question
# `_resolve_write_expr` needs; this asks which names occur, which is the question a
# shell-out argument needs, and the two must not be one pattern with one anchor
# missing.
_NAME_IN_ARGS = re.compile(r"[A-Za-z_$][\w$]*")
# A WHOLE operand that is one string literal, anchored at both ends. The
# unanchored `_STRING_LITERAL` above answers "is there a literal in here", which
# is a different question and the wrong one for an operand (see
# `_resolve_write_expr`). `r`/`b`/`u` prefixes are literals and stay readable;
# `f` is deliberately absent, because the interpolated part is exactly what this
# cannot read.
_LITERAL_OPERAND = re.compile(
    r"^(?:[rbu]|br|rb)?(['\"])([^'\"\n]*)\1$", re.IGNORECASE)


def _concat_operands(expr):
    """The `+`-joined operands of `expr`, or None when its quoting is unreadable.

    Quote-aware because `'a+b.py'` is ONE operand: splitting on the character
    would make it two and hand the caller half a filename, which is the same
    class of invented answer `_resolve_write_expr` exists to refuse. Unbalanced
    quoting returns None for the same reason `_clauses` widens to one clause -
    unsure is said, never guessed."""
    parts, buf, quote = [], [], None
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(expr[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == "+":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quote is not None:
        return None
    parts.append("".join(buf).strip())
    return parts


def _eval_bindings(clause):
    """{name: the string it was bound to} for the literal bindings in `clause`."""
    out = {}
    for m in _EVAL_BINDING.finditer(clause):
        joined = "".join(_STRING_LITERAL.findall(m.group(2)))
        if joined:
            out.setdefault(m.group(1), joined)
    return out


def _eval_sequence_bindings(clause):
    """{name: its literal elements, joined with a space} - an argv bound to a name.

    The elements are joined the way a shell would spell them, because the matcher
    that reads the result is `BASH_FILE_READ`, whose grammar is a verb followed by
    a path. Joining is not a claim that the shell ran it: it is the only shape in
    which the question "does this argv read a secret file" can be asked of the one
    matcher this file trusts for that sentence."""
    out = {}
    for m in _SEQUENCE_BINDING.finditer(clause):
        joined = " ".join(_STRING_LITERAL.findall(m.group(2)))
        if joined:
            out.setdefault(m.group(1), joined)
    return out


def _resolve_write_expr(expr, bindings):
    """The path an argument NAMES: a literal, a join of literals, or a bound name.

    Returns None when the argument is something this cannot read - a call, an
    f-string, a name bound to anything but literals. None means "no target", not
    "no write", and the caller treats it as nothing to judge, which keeps this on
    the same side of the line `_clauses` and `split_heredocs` are on: unreadable
    input is never quietly graded as clean by INVENTING a target for it.

    THAT PARAGRAPH USED TO BE FALSE. The body used to ask `_STRING_LITERAL`
    for every literal ANYWHERE in the expression and join whatever came back, so
    a MIXED expression lost its unreadable half silently instead of returning
    None: `open(base + '/probe.json', 'w')` resolved to `/probe.json` - a
    root-anchored basename the command never names. That is how one session got
    opposite verdicts for one operation. `os.path.join(base, 'probe.json')`
    resolved to nothing and was allowed; the `+` spelling of the same write
    resolved to a fabricated path, lost the `/private/tmp/...` prefix that made
    the real target exempt scratch, and was refused - naming an inline-eval
    source write for a file under the session scratchpad. Rewording until it
    passes is the only move that reads as available there, and that is the
    route-around this guard's own header warns about.

    So the expression is now read as a CONCATENATION and every operand must
    resolve. One unreadable operand makes the whole target None, which is what
    `os.path.join` already got and what this docstring already promised. It cuts
    both ways, and the fabrication did too: a write whose first operand was a
    temp-root literal and whose second was a variable resolved to the literal
    alone, claiming the temp exemption for a path whose variable half could have
    been anything. (Spelled that way round rather than shown, because
    `_refs.absolute_reach_violations()` reads this docstring as text and a
    root-anchored literal inside a read/write call is the shape it exists to
    catch. `s61` in the suite carries the executable form.)
    """
    operands = _concat_operands(expr.strip())
    if not operands:
        return None
    parts = []
    for operand in operands:
        literal = _LITERAL_OPERAND.match(operand)
        if literal:
            parts.append(literal.group(2))
            continue
        if not _BARE_NAME.match(operand):
            return None
        bound = bindings.get(operand)
        if bound is None:
            return None
        parts.append(bound)
    return "".join(parts) or None


def _eval_write_targets(clause):
    """Every path this clause actually WRITES, from the write calls themselves.

    This narrows detection from "a write shape and a path in the same clause" to
    "the path the write call NAMES" - and that narrowing still walked through when
    the pattern required the name to be a quoted LITERAL in the argument position, so

        p = 'src/app.ts'
        open(p, 'w').write(...)

    named nothing and was allowed - while the identical write with the path spelled
    inline was blocked. Same capability, same target, same intent; only the
    syntactic adjacency differed, and it is the shape every two-line bulk edit uses.
    Measured after the fact: fifteen source edits in one session went through it.

    So the argument is RESOLVED rather than required to be a literal - one hop of
    binding, plus a join for a concatenation. The narrowing still holds: a path that
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
# Every shape that READS a path in an interpreter body, with the path in the
# argument position. The mirror of `_WRITE_CALL_EXPR`, and it exists for the
# same reason as that one: a token that merely SHARES a clause with a read
# shape is not a read. Write modes are excluded here on purpose — `open(p, 'w')` is
# the write arm's business, and grading it as a read would refuse creating a file
# whose name resembles a secret.
_READ_CALL_EXPR = re.compile(
    r"(?:(?:io|codecs)\s*\.\s*)?open\s*\(\s*([^,)]+?)\s*"
    r"(?:,\s*['\"](?:r|rb|rt|r\+b?)['\"][^)]*)?\)"
    r"|Path\s*\(\s*([^,)]+?)\s*\)\s*\.\s*read_(?:text|bytes)"
    r"|(?:fs\s*\.\s*)?readFile(?:Sync)?\s*\(\s*([^,)]+?)\s*[,)]"
    r"|createReadStream\s*\(\s*([^,)]+?)\s*[,)]"
    r"|(?:File|IO)\s*\.\s*(?:read|readlines|foreach|open)\s*\(\s*([^,)]+?)\s*[,)]"
    r"|load_dotenv\s*\(\s*([^,)]*?)\s*[,)]",
    re.IGNORECASE,
)


def _eval_read_targets(clause):
    """Every path this clause actually READS, from the read calls themselves.

    `_eval_write_targets`' twin, resolving a bound name the same way, so
    `p = '.env'` followed by `open(p)` is the one read it plainly is.
    """
    out = []
    bindings = None
    for m in _READ_CALL_EXPR.finditer(clause):
        expr = next((g for g in m.groups() if g), None)
        if expr is None:
            continue
        if bindings is None:
            bindings = _eval_bindings(clause)
        target = _resolve_write_expr(expr, bindings)
        if target:
            out.append(target)
    return out


# The calls that hand text to a shell. Arm 2 below grades THEIR arguments and no
# other text in the body: `BASH_FILE_READ` over a whole
# interpreter body cannot tell `subprocess.run(["cat", ".env"])` from a list of
# example commands that runs nothing, and this repository's own test fixtures are
# the second kind.
_SHELL_OUT_CALL = re.compile(
    r"\b(?:subprocess\s*\.\s*(?:run|call|check_call|check_output|Popen)"
    r"|os\s*\.\s*(?:system|popen|execv?p?e?)"
    r"|commands\s*\.\s*getoutput"
    r"|child_process\s*\.\s*(?:exec|execSync|execFile|execFileSync|spawn|spawnSync)"
    r"|(?:exec|execSync|spawnSync)"
    r"|Kernel\s*\.\s*system|IO\s*\.\s*popen)\s*\(",
    re.IGNORECASE,
)


def _shell_out_arguments(clause):
    """The argument text of every call in `clause` that hands something to a shell.

    Balanced to the closing parenthesis rather than to the next one, so a nested
    call inside the argument list — `subprocess.run(shlex.split(cmd))` — is kept
    whole instead of being cut at its first `)`. An unbalanced tail (a body cut
    mid-call by a heredoc, say) contributes what there is: refusing to answer
    would be a silent pass, and the arm asking this is a guard.
    """
    out = []
    for m in _SHELL_OUT_CALL.finditer(clause):
        depth, start = 1, m.end()
        i = start
        while i < len(clause) and depth:
            if clause[i] == "(":
                depth += 1
            elif clause[i] == ")":
                depth -= 1
            i += 1
        out.append(clause[start:i])
    return out


def _unestablished_read_target(clause):
    """A read call whose target this cannot resolve but which NAMES a secret.

    -> the argument expression, or None

    THE READ SIDE OF THE RULE THE WRITE SIDE ALREADY LEARNT, and the two point
    opposite ways because the fail-mode table points them there. `_resolve_write_expr`
    returns None for an expression this cannot read, and both arms used to treat
    None the same way: nothing to judge, carry on. On the WRITE side that is right
    - plan coverage is a question about a file the plan could name, an unestablished
    destination is not one, and the allow is said out loud. On the READ side the
    same silence is a guard declining to act on the one clause that names the file
    it exists to protect: `open(base + '/.env')` and `open(f'{d}/.env')` both spell
    a secret inside a read call's own argument and both were allowed.

    So a read call whose target cannot be established is REFUSED when the argument
    itself names a secret. That is narrower than it sounds and deliberately so: the
    expression has to be the ARGUMENT of a read call, which is what keeps prose, a
    comment and a fixture table outside it, and a write-mode `open` outside it too.
    A target built by a CALL (`os.path.join(a, b)`) matches no read call here at
    all and is the residual this cannot reach, stated where the limit is paid."""
    bindings = None
    for m in _READ_CALL_EXPR.finditer(clause):
        expr = next((g for g in m.groups() if g), None)
        if expr is None:
            continue
        if bindings is None:
            bindings = _eval_bindings(clause)
        if _resolve_write_expr(expr, bindings):
            continue
        if SECRET_TOKEN_RE.search(expr):
            return expr.strip()
    return None


def _eval_reads_a_secret(clause, extras):
    """Does this interpreter body READ a secret, as opposed to mentioning one?

    -> the basis, in the words the refusal quotes, or None

    This is a narrowing of Rule #1, so what it keeps is stated first.
    THREE WAYS TO BE A READ, and only prose falls outside all three:

      1. a read call NAMES the path — the definite case, resolved through one hop
         of binding exactly as the write arm resolves its targets;
      2. a call that SHELLS OUT is handed a read of it — `subprocess.run(["cat",
         ".env"])` is a read no Python-shaped pattern would see, and
         `BASH_FILE_READ` is the same matcher the shell lane already trusts for
         that sentence. It is applied to the ARGUMENTS of such a call and to no
         other text in the body: grepping the whole body cannot tell that
         call from a list of example commands, and this repository's own fixtures
         for this guard are the second kind. Both users who met it — a live
         project and this repository — routed around it by writing the script to a
         scratchpad file and running it from there, which is worse for security
         than what was refused;
      3. a project-configured extra names one of the read targets.

    What this stops refusing is a body that merely SPELLS the name: a phase summary
    about a `.env` failing at boot, a comment, a docstring, an error message. That
    was reported from a live run and reproduced twice inside one command here — the
    refusal said *Reading a secret file* about a sentence that read nothing.

    A FOURTH, AND IT IS THE OPPOSITE KIND OF EVIDENCE: a read call whose target
    this cannot establish, where the argument itself names a secret
    (`_unestablished_read_target`). The three above say what a body DOES; this one
    says the body would not answer, and a guard refuses what it cannot classify.

    ARM 2 RESOLVES ONE HOP, which closed the last place this file graded a
    spelling instead of an operation. `subprocess.run(argv)` after
    `argv = ['cat', '.env']` is the same read as `subprocess.run(['cat', '.env'])`,
    and it used to be refused in the inline `-c` spelling and allowed in the
    heredoc one - the inline form being caught by the OUTER shell lane, which reads
    the command text a heredoc body has already left. One operation, two verdicts,
    decided by which of two identical capabilities carried it. The binding is
    resolved here instead, so both spellings meet the same rule and neither depends
    on a lane that happens to see the bytes.

    The direction of the risk is stated rather than hidden: this can still miss a
    read spelled in a way none of the four sees - an argv assembled element by
    element, a command built by a call. The alternative is what was measured twice
    - a guard that fires on prose, or on data, is one people route around, and this
    register already carries that lesson under its own entry.
    """
    targets = _eval_read_targets(clause)
    if any(SECRET_TOKEN_RE.search(t) for t in targets):
        return "a read call names it"
    seqs = None
    for argument in _shell_out_arguments(clause):
        if seqs is None:
            seqs = _eval_sequence_bindings(clause)
        # Every NAME in the argument list, resolved against the sequences bound in
        # this same clause. Names rather than "the whole argument is one name"
        # because an argv arrives beside other arguments as often as alone
        # (`subprocess.run(argv, shell=False)`), and the closing parenthesis is
        # part of the span this walk returns. Only a name bound HERE to literals
        # contributes, so nothing is added that the clause did not spell.
        text = argument
        for name in _NAME_IN_ARGS.findall(argument):
            if name in seqs:
                text += " " + seqs[name]
        if BASH_FILE_READ.search(text) or DOT_SOURCE_SECRET.search(text):
            return "a shell read of it is handed to something that runs commands"
    if targets and _hits_extra(" ".join(targets), extras):
        return "a read target matches this project's own secretPatterns.extra"
    unplaced = _unestablished_read_target(clause)
    if unplaced:
        return ("a read call names it in an argument this cannot resolve (%s), "
                "and a guard refuses what it cannot classify" % (unplaced,))
    return None


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
#
# AN EXPANSION IS PART OF THE TOKEN, and leaving it out is how this branch came
# to name a file the operator never typed. The class held no `$`, `{` or `}`, so
# `sed -i "" "$HOME/notes.py"` arrived here as `HOME/notes.py` - a bare relative
# path, unconditionally inside the repository, refused for plan coverage under a
# name that appears nowhere in the command. Carrying the marks means the target
# reaches `_config.resolvable_destination` still wearing them, which is the only
# state in which that question can be answered at all. The widening cannot invent
# a refusal: every span it newly matches carries one of the marks, and a marked
# target is skipped rather than graded.
_PATHY_TOKEN = re.compile(
    r"(?<!\w)[A-Za-z]:[\\/][\w@~/\\.+-]*\.[A-Za-z][A-Za-z0-9]{0,9}"
    r"|[\w@~./+${}-]+\.[A-Za-z][A-Za-z0-9]{0,9}")

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
    require-plan (v0.34 B1). Only the PLAN-gate write arms can return ask -
    the shell forms and the interpreter ones, through the one function that
    reads a tier; the secret rules are never graded and never ask."""
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


def _extra_read_hit(text, extras):
    """The word a READ clause names that only the PROJECT's patterns call a secret.

    -> that word, or None

    THE CONSUMER'S HALF OF RULE #1 REACHED EVERY MATCHER BUT THE SHELL. `Read`,
    `Grep` and an MCP payload each ask `_hits_extra` of the path they carry; the
    Bash lane's third arm asked it of the whole command AND then required
    `BASH_FILE_READ` to match as well - which is the built-in vocabulary, so a
    project pattern could never be the reason for a refusal. Appending a space to
    the text cannot make that matcher say yes where it said no, so the arm could
    not fire at all: a check with no case able to fail, standing where the whole
    configurable half of the rule was supposed to be. `cat ops/vault-token` was
    allowed while `Read ops/vault-token` was refused, for a file the project had
    itself declared secret - and `cat` is how an agent reads a file.

    Asked PER CLAUSE and PER WORD rather than of the command, because that is the
    shape of the question: a path is a word, `_clauses` already separates the read
    from what it is piped into, and an unanchored project pattern asked of the
    whole line matches wherever it likes. A clause with no read in it is not asked
    at all, so writing a file the project calls secret is still the write arms'
    business and not a refusal here."""
    if not extras:
        return None
    for clause in _clauses(text):
        if not _READ_CLAUSE.search(clause):
            continue
        for word in _SHELL_WORD.findall(clause):
            if _hits_extra(word, extras):
                return word
    return None


# --- MCP tool calls: the operation, never the server it was installed under -----
def _mcp_operation(tool):
    """The last `__`-separated segment of an MCP tool name, or "".

    An MCP tool is `mcp__<server>__<operation>`, and the server segment is a name
    the OPERATOR typed into their own config: one npm filesystem server is
    `mcp__filesystem__read_text_file` in one setup and `mcp__fs__read_text_file`
    in the next. So the server half carries nothing a guard may decide on.

    This is used in the refusal sentence alone — it names the call back to the
    person who made it. No verdict is taken from its spelling, which is the point:
    a list of read verbs here would be `_READ_VERB` again, and that list is only
    ever as complete as the servers whose spellings someone happened to think of.

    A name in this file for `_config.mcp_operation`: the plan gate and the edit
    guard name an MCP call back to its caller too, and a hook may not import a hook.
    """
    return _config.mcp_operation(tool)


def _locators(node, limit=2000):
    """Every path-shaped string a tool payload names, at any depth, in payload order.

    THE ARGUMENT KEYS ARE NOT READ, because they are the server author's
    vocabulary and not a contract: one read names its file under `path`, a batch
    read holds a list under `paths`, others use `file_path` or `uri`. A walk over
    VALUES asks the same question of all of them and of the ones nobody here has
    seen yet.

    Two narrowings, and both are structural rather than a list of names. A
    `file:` URI is reduced to the path inside it, so the locator that reaches the
    secret rule is spelled the way that rule matches. And a string carrying a
    NEWLINE is a body, not a locator — that is what keeps the `content` of a
    write from being graded as a filename, without this function having to know
    that a key called `content` exists.

    A name in this file for the `locators` half of `_config.mcp_payload`. The
    walk moved there when require-plan and guard-edits began asking the same
    question of a WRITE payload: a hook may not import a hook, `_config` is the
    one module all three already load, and two copies of a path walk is one copy
    and one lie. This file reads no other half of that answer — a write basis
    is not a thing this guard's verdict may depend on, which is what its own
    `_decide_core` branch is careful to say.
    """
    return _config.mcp_payload(node, limit)["locators"]


def _mcp_secret_target(ti, extras):
    """(every locator the payload names, the first one that is a secret file).

    The second element is None when the call names no secret file at all, which
    is the ordinary MCP call and the verdict that keeps this guard installed.

    Both halves are wanted by two callers — `_decide_core` refuses on the hit,
    and the gate events row hands every locator to the redactor — so they are
    resolved once, here. Resolving them twice would be two chances for the
    decision and the recorded sentence to disagree about which path this was.
    """
    found = _locators(ti if isinstance(ti, dict) else {})
    for loc in found:
        if SECRET_PATH.search(loc) or _hits_extra(loc, extras):
            return (found, loc)
    return (found, None)


# THE RULE ITSELF NOW LIVES IN `_config.split_heredocs`, and this file reads it
# from there. The classification began here, but `guard-history-rewrite` needs the
# same three-way grading before it can tell a command from a file it is writing,
# and a hook may not import another hook. `_config` is the one module both
# already load, so the classification has one home and the reasoning behind each
# of the three buckets travelled with it. `_shell_text` stays here because only
# this file's shell-grammar rules want the view that drops interpreter bodies.


def _shell_text(cmd):
    """Only the text a SHELL parses: the command, plus heredoc bodies fed to a shell.

    For the rules written in shell GRAMMAR -- a read verb followed by a secret
    path. Those rules used to read the raw command, so the body of
    `cat > notes.md <<EOF` was graded as if a shell were running it, and creating
    a markdown file whose prose quoted an example command naming a key file was
    refused as "reading a secret file via shell". The operation was a write; the
    evidence was an English sentence.

    Dropping a body fed to python or node loses no detection, which is why this is
    a narrowing rather than a hole: those bodies still arrive at the inline-eval
    arms, and `SECRET_TOKEN_RE` there is strictly broader than `BASH_FILE_READ`
    here -- it wants the secret token alone, with no read verb in front of it. So
    every refusal this view gives up is made by a stricter rule one branch down.
    """
    text, _code, shell = _config.split_heredocs(cmd)
    return "\n".join([text] + shell)


def _runnable_text(cmd):
    """The command with only the spans nothing executes removed.

    Everything a machine will run in SOME language: the text, shell bodies and
    interpreter bodies. For the rules that are about a capability rather than
    about shell grammar -- echoing a token variable, reaching the environment
    layer, writing a file -- where the interpreter body is still evidence and
    dropping it would open a hole. Only the data body leaves, which is the same
    heredoc rule spent on the branches that never got it.

    A name in this file for `_config.runnable_text`: the view is wanted by the
    history guard too, so the join lives beside the split that feeds it.
    """
    return _config.runnable_text(cmd)


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

    Heredocs come from `_config.split_heredocs`, which already draws this line and
    draws it correctly: a body fed to an interpreter is CODE and comes back, so
    `python3 - <<PY` is still judged as `python3 -c` is, and only a body fed to
    something like `git commit -F -` or `cat` leaves. Nothing about that grading
    changes here; this only spends it on one more branch.

    Scoped to Rule #2's dump verb on purpose, and ECHO_SECRET is the reason it
    cannot simply be global: there the emitter's argument list is the PAYLOAD --
    `echo $TOKEN` is the leak -- so stripping it would delete the very text that
    rule exists to read. ECHO_SECRET reads `_runnable_text` instead, which is the
    same heredoc rule without the emitter half.
    """
    text, code, shell = _config.split_heredocs(cmd)
    text = _TEXT_EMITTER_ARGS.sub(_strip_emitter_args, text)
    return "\n".join([text] + shell + code)


def _clauses(cmd):
    """Split a shell command into clauses on `;`, `|`, `&`, NEWLINE, outside quotes.

    The newline was added as a separator, matching how a multi-line Bash block is
    actually written -- and its absence was this function's own documented
    defect surviving in the one spelling nobody had tried. Measured: the two
    lines below deny together and neither denies alone, while the same two joined
    with `;` are allowed. The evidence was being taken from two different
    commands and applied to the block as a whole.

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
    and each fragment is still judged by the same regexes.

    A LINE CONTINUATION IS NOT A SEPARATOR and needs no special case: the
    backslash branch above already consumes the character after it, so one
    ending a line eats its own newline and the two lines stay one clause.
    (Spelled without the character itself: in a non-raw docstring it would
    open an invalid escape sequence, which is a SyntaxWarning -- and the
    warning machinery pulls `warnings`, `linecache` and `tokenize` into a
    hook that must import fast, which is how `bench-hooks --gate` found it.)
    A newline inside quotes is likewise held together by the quote tracking, which
    is why the transport shape -- an interpreter invocation and a repo path both
    inside ONE quoted argument handed to another program -- is still refused.
    That one cannot be fixed by splitting: it needs knowing the text is an
    argument rather than a program, which is real shell parsing. Stated here
    rather than left to be rediscovered."""
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
        elif ch in (";", "|", "&", "\n", "\r"):
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


def _ungoverned_write_target(targets, root, cfg):
    """What the plan gate has to say about `targets`.

    -> {"hit", "unresolved"}
       hit         the first path that is a non-exempt SOURCE file inside the
                   consuming repository which no in_progress task covers, else
                   None
       unresolved  the targets whose destination this process cannot establish,
                   in the spelling the command used - a withdrawal, never a
                   finding

    ONE DEFINITION OF "A FILE THE PLAN GATE CARES ABOUT", asked by every Bash
    write form this hook grades: the shell redirect / `tee` / `sed -i` grammar
    below, and the write CALLS inside an interpreter body. The two arms used to
    ask different questions — this one, and a regex over the clause pairing an
    extension list of its own with a hardcoded exempt list — so one `.ts` file
    was refused through `python3 -c` and allowed through `echo >`, and a
    consumer's `exemptGlobs` reached only one of the two. The extension list is
    `_config.source_exts`, whose docstring already claims to be that one place.

    The questions, in this order, and each of them is somebody's recorded bug:

      * ESTABLISHED AT ALL. A target carrying an expansion, a substitution, a
        glob or a home reference names a place only the shell knows, and
        resolving it here against the repository root makes it look like a file
        in the tree: `echo x > "$HOME/notes.py"` was refused for plan coverage
        under the name `$HOME/notes.py`, a path nobody can add to a task's
        `files` because no such file exists. The refusal's whole content came
        from the resolution that produced it, which is the guard-by-spelling
        class. So the destination is reported as unestablished and the coverage
        question is not asked of it - the question is about a file the plan
        could name, and this is not one. The write is not thereby invisible:
        `guard-bash-writes` reads the tree afterwards and reports by the path
        git prints, which is the residual SECURITY.md already assigns it.
      * SOURCE, by extension, derived from `tddReminder.sourceGlobs`. It
        deliberately excludes `.json`, which is why no consumer's package.json,
        tsconfig.json or fixture is gated here — and why the manifest needs the
        separate, RESOLVED target set `_manifest_write_hit` holds.
      * INSIDE the repository. A target outside it is skipped, not reported:
        SECURITY.md promises "the same file gets the same verdict whether it is
        edited through a tool or through `sed -i`", so require-plan's
        containment check is one these arms owe identically. Without it a write
        into a scratch file under the system temp directory relpath'd to
        `../../../private/tmp/probe.py`, matched no exempt glob, was covered by
        no in_progress task, and was denied — a refusal nobody could act on,
        which is the route-around class. It is also what retired the eval arm's
        own `/tmp` / `/private/tmp` / `/var/folders` literals: the
        question those spelled was never "is this a temp directory" but "is
        this my repository", and only one of the two can be answered correctly
        on a machine whose repo lives under a temp root.
      * NOT EXEMPT, against the project's own `exemptGlobs` through
        `_config.matches_exempt` — which carries a carve-out put in
        this file by hand: a test-suffix NAME in a pure data/markup format
        (`tsconfig.test.json`) is build configuration, not a test, and keeps no
        exemption. Shared rather than copied, so the Edit path and these two
        cannot drift over what a test file is.
      * NOT COVERED by an in_progress task, exactly or by directory prefix.

    A `continue` rather than a `return` at each: a command writing one file out
    of scope and one in it still has an in-repo finding to report."""
    graded = {"hit": None, "unresolved": []}
    if not targets:
        return graded
    exts = _source_exts(cfg)
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
    in_prog = None
    for t in targets:
        if not _config.resolvable_destination(t):
            if t not in graded["unresolved"]:
                graded["unresolved"].append(t)
            continue
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
        if graded["hit"] is None:
            graded["hit"] = rel
    return graded


def _source_write_hit(cmd, root, cfg):
    """What the plan gate says about the files `cmd` writes via sed -i / tee /
    a >(>) redirect - `_ungoverned_write_target`'s pair. The shell half of the
    plan gate's write arm."""
    return _ungoverned_write_target(_shell_write_targets(cmd), root, cfg)


def _eval_write_hit(graded, root, cfg):
    """(the ungoverned source file an interpreter clause WRITES, how that clause
    was spelled, the destinations none of them could establish).

    The interpreter half of the same arm, and it is the same question asked of a
    different grammar: `_eval_write_targets` resolves what a write CALL names,
    `_ungoverned_write_target` decides whether the plan gate has anything to say
    about it. Per clause rather than over one flattened target list, because the
    refusal has to name the spelling the operator actually typed and only
    the clause knows whether it arrived as `-c` or as a heredoc body.

    The unestablished destinations accumulate across ALL clauses rather than
    stopping at the first hit: they are what the caller says instead of a
    verdict, so one lost to an early return is a silence with nothing behind
    it."""
    unresolved = []
    first = (None, None)
    for cl, is_eval, how in graded:
        if not is_eval:
            continue
        seen = _ungoverned_write_target(_eval_write_targets(cl), root, cfg)
        for spelling in seen["unresolved"]:
            if spelling not in unresolved:
                unresolved.append(spelling)
        if seen["hit"] and first[0] is None:
            first = (seen["hit"], how)
    return (first[0], first[1], unresolved)


_PLAN_WRITE_DENY = (
    "%s bypasses the plan-first gate: %s\n%s Use the Edit/Write tools "
    "(guard-edits + require-plan review the change), or cover the file with an "
    "in_progress task. Exempt paths (docs, tests, .claude/**) are unaffected."
)
_PLAN_WRITE_ASK = (
    "%s outside the plan: %s\n"
    "planGate is set to \"ask\" in .claude/audit.config.json, so this write waits "
    "for your approval - approving covers this one command. Prefer the Edit/Write "
    "tools (guard-edits + require-plan review the change), or cover the file with "
    "an in_progress task."
)


def _plan_gate_write_verdict(root, cfg, hit, surface):
    """Grade ONE ungoverned write target against the plan gate's tier.

    THE ONLY GRADED RULE IN THIS FILE, and the only function that may reach for
    a tier. Every Rule #1 / Rule #2 branch — reading a secret file, sourcing
    one, copying one, dumping the environment, echoing a token — is a claim
    about the operation alone and returns its own ("block", …) without ever
    coming here: logging an auth token is wrong whether or not a plan exists, so
    those refuse at every tier including the one with no manifest at all. A
    guard that needed a plan to be right about a `.env` would be off in every
    repository that has not adopted this plugin, which is most of them.

    What is graded is plan COVERAGE, which is meaningless without a plan. Both
    Bash write forms come through here because the promise is one file, one
    verdict: `Edit src/x.ts`, `sed -i src/x.ts` and
    `python3 -c "open('src/x.ts','w')"` are one operation in three spellings,
    and the tier is `_config.plan_gate_mode` — require-plan's own resolver —
    for all three. `surface` names the spelling in the operator's words, because
    a refusal that describes a command nobody typed reads as a guard firing at
    random."""
    manifest_rel = (cfg.get("manifestPath")
                    or _config.DEFAULTS["manifestPath"])
    state = _config.manifest_state(root, manifest_rel)
    mode = _config.plan_gate_mode(cfg, state)
    if mode == "deny":
        # The refusal names its ACTUAL cause, mirroring require-plan word
        # for word: "a phase is in_progress" was printed here even when the
        # denial came from enforce:true in an empty repo.
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
        return ("block", _PLAN_WRITE_DENY % (surface, hit, cause))
    if mode == "ask":
        # planGate:"ask" parity with require-plan: the same file must be treated
        # the same whether the agent reaches for Edit, sed -i or python3 -c.
        return ("ask", _PLAN_WRITE_ASK % (surface, hit))
    return ("allow", "bash: source write, plan gate %s: %s" % (mode, hit))


# --- the manifest, reached by shell instead of by Edit ---------------------------
_SHELL_SUBAGENT_MANIFEST = (
    "%s is the audit plan, and the plan belongs to the orchestrator.\n"
    "You are a subagent: your job is one task, and a task that edits the plan it "
    "is being judged by is a task nobody can review. The Edit tool already refuses "
    "you this file; `sed -i`, `tee` and a redirect are the same act spelled "
    "differently, so they are refused here too.\n"
    # AND IT NAMES THE COMMAND, as `require-plan`'s twin of this text does. "Tell
    # the orchestrator what you need" named three writes and no verb, so the
    # report a stopped subagent writes had to be turned into a command by somebody
    # else - a refusal nobody downstream can act on alone. The verbs are the
    # orchestrator's; the subagent quotes one.
    "Do this: STOP, and tell the orchestrator what you need, naming the command "
    "it has to run - a wider scope is `/audit:task scope <taskId> --files ...`, "
    "an unstarted task is `/audit:task start <taskId>`, new work is "
    "`/audit:task add \"<title>\" --phase <phaseId>`. Those are ITS commands, not "
    "yours to run: they write the plan. It owns those writes and will make them, "
    "then tell you to carry on.\n"
    "If you reached for a shell write to get past a plan-gate refusal on a source "
    "file, that is the case this rule exists for: report the refusal instead."
)

_SHELL_MANIFEST_LOCK = (
    "%s is under the %s lock, held by another LIVE session (%s).\n"
    "  doing: %s\n"
    "  basis: %s\n"
    "Writing it now would overwrite their work with no conflict and no warning -\n"
    "one working tree, so git never sees two versions.\n"
    "A shell write is the one form that cannot be reviewed before it lands, so do\n"
    "NOT edit around the lock with it. Wait for that run, check it, or take the\n"
    "lock over properly so the record says who holds it:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py\" status\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py\" acquire "
    "%s --takeover"
)


def _manifest_write_hit(cmd, root, cfg):
    """First manifest path `cmd` writes to via sed -i / tee / a `>`(`>>`) redirect
    - the index, its lockfile, or one of its phase shards - or None.

    THE TARGET SET IS RESOLVED, NEVER SPELLED. `manifestPath` comes from the
    project's config and the shards come from `_config.governing_lock`, which is
    the same predicate require-plan, guard-edits, journal-writes and
    guard-bash-writes ask; a project that moved the manifest or renamed a shard
    file is covered because the resolution moves with it, and the Edit side and
    this side cannot drift apart over what counts as the plan.

    Adding `.json` to `_config.source_exts` would have reached these files too -
    and every package.json, tsconfig.json and test fixture in a consumer's
    repository with them. A guard that refuses unrelated files is a guard the
    operator switches off, so the set is explicit instead of extensional.

    NO CONTAINMENT FILTER, and its absence is the measured thing rather than an
    oversight. The source-write half needs `within_root` because it grades a path
    by its EXTENSION, and `../../../private/tmp/probe.py` is a source file by that
    test. Here the path is compared against a repo-relative literal, which is
    already negative for everything outside the tree - that is the very case
    `_config.within_root`'s own docstring says its callers do not need it for. A
    `within_root` call here was written first and left no case able to fail:
    deleted, allowed and denied the same commands, which is a check that cannot
    fail rather than a guard.

    A CONTAINMENT FILTER IS STILL NOT WHAT THIS SKIPS ON. `rel_path` normalises,
    so a target the shell alone can resolve can be walked onto the literal:
    `> "$X/../docs/audit/audit-plan.json"` came back as the manifest path, and
    the refusal that followed was about a spelling rather than about a file.
    `resolvable_destination` is the same question the source arm asks one
    function up, so the two arms cannot disagree about what `${X}` names."""
    manifest_rel = str(cfg.get("manifestPath")
                       or _config.DEFAULTS["manifestPath"])
    for t in _shell_write_targets(cmd):
        if not _config.resolvable_destination(t):
            continue
        rel = _config.rel_path(root, t)
        if (rel == manifest_rel or rel == manifest_rel + ".lock"
                or _config.governing_lock(manifest_rel, rel)):
            return rel
    return None


def _manifest_write_verdict(data, root, cfg, rel):
    """("block", msg) when a shell write to manifest path `rel` is refused, else
    None - and the two refusals are require-plan's two, in its order.

    A SUBAGENT IS REFUSED THE PLAN. The executor keeps Bash after the Edit tool
    refuses it the manifest, so the one act the security model says a subagent may
    not perform - editing the shard it is being judged by - was reachable by typing
    `sed`. The verdict has to follow the operation rather than the tool that spells
    it, which is the whole of this branch.

    A LIVE LOCK HOLDER IS STILL A LIVE LOCK HOLDER. Two sessions writing one shard
    in one working tree produce no git conflict, so the loser's bookkeeping
    silently replaces the winner's; that this write arrived by shell makes it
    worse, not exempt.

    Everything else - the orchestrator's own bookkeeping, an abandoned lock, an
    unattributable one, no git at all - is None, so the caller falls through to the
    source-write gate. That is require-plan's answer for the same payload, and
    matching it is the point: the manifest is exempt from the PLAN gate on both
    sides, not unconditionally writable on either."""
    if _config.is_subagent(data):
        return ("block", _SHELL_SUBAGENT_MANIFEST % (rel,))
    manifest_rel = str(cfg.get("manifestPath")
                       or _config.DEFAULTS["manifestPath"])
    conflict = _config.manifest_lock_conflict(
        root, cfg, manifest_rel, rel, str(data.get("session_id", "") or ""))
    if conflict and conflict["live"]:
        return ("block", _SHELL_MANIFEST_LOCK % (
            rel, conflict["lock"], conflict["holder"], conflict["note"],
            conflict["basis"], conflict["lock"]))
    return None


def _append_verdict_event(root, cfg, data, verdict, msg):
    """One line into the gate events feed for a deny/ask verdict (v0.36 A4).

    require-plan's verdicts have fed <logsDir>/plan-gate-events.jsonl since
    v0.34 B3; this guard's denials left no trace in the same feed, so "what has
    the gate been doing" had an answer with a hole in it. Same shape, same
    writer (_config.append_gate_event); the reason is prefixed with this hook's
    name so the two sources stay tellable apart. Telemetry only: never raises,
    never blocks, never changes the verdict.

    THE COMMAND IS NOT A FILE, AND IT USED TO BE WRITTEN AS ONE. `file` fell
    back to `tool_input.command`, so `cat ~/…/id_rsa` was stored verbatim — and
    a command is not an absolute path, so every reader's redactor resolved it
    against the repo root, called it inside, and painted it. Readers were all
    correct; the field was wrong. It now goes to the writer's `command` key,
    which stores a digest, a byte length and a program name and never the text.

    SO A BASH VERDICT NAMES NO FILE, and that is the honest row rather than a
    thinner one. This guard's Bash branches deny a READ VERB or a SHELL WRITE;
    the payload names no path of its own, and the shell-write branches already
    put their repo-relative target in the message's first line, which is the
    `reason` this row carries. An empty cell claims nothing; the old cell
    claimed the whole command line was a file in the repository.

    AND THE SAME ROW, ONE CELL OVER, HAD THE OPPOSITE TREATMENT. The Read
    and Grep branches interpolate the payload's path or glob into their message,
    whose first line IS this `reason`, and no reader redacts that cell — so a
    denial over a dotenv file under a home directory published the absolute path
    beside a `file` cell that correctly read the token. The Bash branches were
    already clean: fixed sentences, and the shell-write ones interpolate the
    repo-relative hit `_source_write_hit` returns.

    THE TERMINAL MESSAGE KEEPS ITS ABSOLUTE PATH, and the recorded reason is
    still that message's first line — derived from it here, every time, never
    authored twice. `_config.redact_paths` respells the exact values this
    payload named, so there is no second string to drift out of step with the
    first and nothing that needs comparing. None back from it means the
    redaction could not run, and then the cell is OMITTED rather than written
    raw: the same fail direction `_command_facts` takes one field over, and the
    same argument as the empty `file` cell above.

    AND AN MCP PAYLOAD NAMES ITS TARGET WHEREVER ITS SERVER LIKES, so the three
    fixed keys are not asked of one: `_mcp_secret_target` hands back the same
    locators the verdict was taken from — including the ones that arrived inside
    a list — and every one of them goes to the redactor."""
    try:
        ti = (data or {}).get("tool_input", {}) or {}
        tool = str((data or {}).get("tool_name", "") or "")
        if tool.startswith("mcp__"):
            # A LIST IS SOMEWHERE A PATH ARRIVES, and the redactor has to be
            # handed it. The three fixed keys below cover the two tools that
            # spell their target in one of them; a batch read holds its files
            # under `paths`, so the element that earned the denial occurred in
            # no value this function knew about and the sentence quoting it went
            # to the feed with an absolute path in it — the same defect as the
            # unredacted `reason` cell, one payload shape further on. The
            # resolver that DECIDED is the one asked here, so the cell and the
            # verdict cannot name two different paths.
            named, target = _mcp_secret_target(ti, _extra_patterns(cfg))
        else:
            # The three keys a message here can interpolate, and the same three
            # `target` picks from. Read names `file_path`; Grep names `path` or
            # `glob`, and BOTH are passed because a Grep call can carry the two
            # and be denied on the one `target` did not pick.
            named = (ti.get("file_path"), ti.get("path"), ti.get("glob"))
            target = ti.get("file_path") or ti.get("path") or ti.get("glob")
        first_line = str(msg or "").splitlines()[0] if msg else ""
        shown = _config.redact_paths(root, first_line, named)
        _config.append_gate_event(
            _config.logs_dir(root, cfg),
            {"event": "deny" if verdict == "block" else "ask.shown",
             "file": target,
             "command": ti.get("command"),
             "mode": "deny" if verdict == "block" else "ask",
             "reason": None if shown is None
                       else "guard-secrets-read: %s" % shown,
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
        fp = _config.slashed(ti.get("file_path", ""))
        if fp and (SECRET_PATH.search(fp) or _hits_extra(fp, extras)):
            return ("block",
                    "Reading a secret file's contents is blocked (Rule #1): %s\n"
                    "Listing names is fine; reading contents is not. "
                    "Ask the user to paste any value you actually need." % fp)
        return ("allow", "read: not a secret path")

    if tool == "Grep":
        path = _config.slashed(ti.get("path", ""))
        glob = _config.slashed(ti.get("glob", ""))
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
        # EVERY BRANCH BELOW READS A VIEW OF THE COMMAND, NEVER THE RAW TEXT,
        # and which view is the rule's own claim about what counts as evidence.
        # `_runnable_text` drops what nothing executes; `_shell_text` also drops a
        # body written in another language, because a shell READ VERB inside a
        # Python string is a word. That line was drawn and, for a while, spent on
        # only two branches; a heredoc creating a markdown file was still refused
        # as a secret read by the branches that never got it, and the fix that
        # reads as available there is to reword the prose until the guard stops
        # objecting.
        runnable = _runnable_text(cmd)
        shell_text = _shell_text(cmd)
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
        if _sandbox_disabled(ti) and ENV_ADJACENT.search(runnable):
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
        # `_runnable_text` and NOT `_executed_text`: the emitter half of that view
        # would delete `echo $TOKEN`, which is the leak this rule reads. The
        # heredoc half is all this branch wants -- a documented example inside a
        # file being WRITTEN is not an echo the machine performs.
        if ECHO_SECRET.search(runnable):
            return ("block",
                    "Echoing a token/secret variable is blocked (Rule #2). "
                    "Print only a prefix (first 6 chars) + length if you must debug.")
        # SHELL text, because this rule is shell grammar - a read VERB with a
        # secret path after it. A body in another language reaches the inline-eval
        # arms below, where the token alone is enough, so nothing stops being
        # refused; what stops is `cat > notes.md <<EOF` being read as if the prose
        # inside the markdown file were commands.
        if (BASH_FILE_READ.search(shell_text)
                or DOT_SOURCE_SECRET.search(shell_text)
                or STDIN_READ_SECRET.search(shell_text)):
            return ("block",
                    "Reading, sourcing or copying a secret file via shell is blocked "
                    "(Rule #1). Reading file names is fine; contents are not — and "
                    "copying/moving a secret only relocates the leak.")
        # THE PROJECT'S OWN VOCABULARY, ASKED HERE AND NOT FOLDED INTO THE LINE
        # ABOVE. It was folded in, behind an `and` on the built-in matcher, which
        # made it a clause that could never decide anything - see
        # `_extra_read_hit`. Its own branch, its own sentence: a refusal over a
        # pattern the project wrote has to name the pattern's subject, or the
        # reader goes looking for a `.env` that is not in the command.
        extra_word = _extra_read_hit(shell_text, extras)
        if extra_word:
            return ("block",
                    "Reading a file this project calls a secret is blocked "
                    "(Rule #1): %s\nIt matches secretPatterns.extra in "
                    ".claude/audit.config.json. Reading file names is fine; "
                    "contents are not. Ask the user to paste any value you "
                    "actually need." % extra_word)
        # The two inline-eval heuristics run PER CLAUSE. Over the whole
        # command, a redirect in clause one plus an eval in clause two used to
        # combine into a deny neither clause earns. A single-clause command is
        # judged exactly as before (see _clauses).
        # A heredoc body is graded when, and only when, it feeds an
        # interpreter. Data bodies leave the text entirely (prose that documents
        # a write is not a write); code bodies come back as clauses of their own,
        # so `python3 - <<PY` is judged exactly as `python3 -c` is.
        # Those bodies were sorted by LANGUAGE for the branches above; here both
        # kinds are code and both are graded, which is what they already were.
        _text, _code_bodies, _shell_bodies = _config.split_heredocs(cmd)
        # (clause, is it already known to be code). A heredoc body carries no
        # `-c` spelling of its own -- being fed to an interpreter IS its
        # spelling -- so it arrives pre-judged rather than re-matched.
        graded = [(cl, bool(_INLINE_EVAL.search(cl)), "-c") for cl in
                  _clauses(_text)]
        # ...and the heredoc bodies, carrying HOW they arrived. Grading
        # `python3 - <<PY` as an inline eval is deliberate and stays (it is
        # the same capability as `python3 -c`), but the refusal used to name only
        # the `-c` spelling - so an operator who typed a heredoc was told about a
        # command nobody had written, which is how a correct guard earns a
        # reputation for firing at random. Reported from a live run, and hit three
        # times in one session here.
        graded += [(b, True, "heredoc") for b in _code_bodies + _shell_bodies]
        for cl, is_eval, how in graded:
            basis = _eval_reads_a_secret(cl, extras) if is_eval else None
            if basis:
                return ("block",
                        "Reading a secret file from %s is blocked (Rule #1) - %s. "
                        "Listing names is fine; reading contents is not. Ask the "
                        "user to paste any value you actually need."
                        % (_EVAL_SHAPE[how], basis))
        # EVERY SECRET RULE IS ABOVE THIS LINE AND EVERY GRADED ONE IS BELOW IT.
        # What follows is the plan gate, not a secret guard: it asks whether a
        # WRITE is covered by the plan, which is a question only a repository
        # with a plan can answer, so it is graded through
        # `_plan_gate_write_verdict` and allows on the weakest evidence. Nothing
        # below may be used to weaken anything above it — a secret read is
        # refused at every tier, manifest or not, and the cases that would go
        # red if a tier ever reached one of those branches are the `pg` group in
        # plugins/audit/tests/test_guard_secrets_read.py.
        #
        # Judged on the paths the write calls NAME, not on a write shape
        # and a path that merely share a clause. And graded on the same tier
        # the shell arm below is graded on, which it was not — a `.ts` file
        # an in_progress task declared was refused through `python3 -c` and
        # allowed through `echo >`, by a message that blamed the plan-first gate
        # while consulting no plan at all.
        ehit, ehow, eunplaced = _eval_write_hit(graded, root, cfg)
        if ehit:
            return _plan_gate_write_verdict(
                root, cfg, ehit,
                "A source-file write from %s" % (_EVAL_SHAPE[ehow],))
        # BEFORE the source-write gate, and before any exempt glob is consulted,
        # because the manifest is not a source file and is not this gate's subject
        # under either heading: `.json` is no source extension and the default
        # exempt globs swallow `docs/audit/**`, so both of the tests below answered
        # "nothing to see" for the one file the security model protects hardest.
        # require-plan asks the manifest question first for the same reason.
        #
        # Falls THROUGH on None rather than returning: a command that writes the
        # manifest and a source file in one breath still owes the source verdict.
        #
        # ITS TARGET SET IS THE SHELL GRAMMAR ALONE, and that is a residual, not
        # a decision this line can defend: `_manifest_write_hit` reads redirects,
        # `tee` and `sed -i`, so a subagent writing its own phase shard through
        # `python3 -c "open('docs/audit/phases/P1.json','w')"` reaches neither
        # this arm nor the source arm above it - `docs/audit/**` is exempt there
        # and `.json` is no source extension. Driven, at this line and before it:
        # the shell spellings deny and the interpreter one allows. The two write
        # arms agree about the PLAN GATE now; they do not yet agree about who
        # owns the plan.
        mhit = _manifest_write_hit(runnable, root, cfg)
        if mhit:
            refusal = _manifest_write_verdict(data, root, cfg, mhit)
            if refusal is not None:
                return refusal
        # Over what runs, not over the raw text - a `>` inside prose being
        # written into a file is not a redirect the shell performs. An interpreter
        # body stays in this view: a `sed -i` inside one is still a shell write.
        shell_write = _source_write_hit(runnable, root, cfg)
        if shell_write["hit"]:
            # The same grading, through the same function, as the interpreter arm
            # above. Otherwise `Edit src/x.ts` would be merely observed while
            # `sed -i src/x.ts` still denied — same file, same rule, opposite
            # verdict, decided by which tool the agent happened to reach for.
            return _plan_gate_write_verdict(
                root, cfg, shell_write["hit"], "Shell write into a source file")
        # WHAT COULD NOT BE ESTABLISHED IS SAID, and it is said as an allow
        # rather than swallowed into the line below. A destination only the
        # shell can resolve is not a file the plan could have named, so there is
        # no coverage question to ask and no refusal an operator could act on -
        # but "nothing to see" and "this guard could not see" are two different
        # sentences, and printing the first for the second is how a silence gets
        # mistaken for a clean bill. Both write arms contribute, because a
        # command can spell one destination each way.
        unplaced = list(eunplaced)
        for spelling in shell_write["unresolved"]:
            if spelling not in unplaced:
                unplaced.append(spelling)
        if unplaced:
            return ("allow",
                    "bash: write destination not established (%s): the shell "
                    "resolves it and the payload does not carry the result, so "
                    "the plan cannot be asked about it"
                    % ", ".join(unplaced))
        return ("allow", "bash: no secret read")

    if tool.startswith("mcp__"):
        # THE SIDE CHOSEN, AND ITS COST: a secret file named by an MCP call is
        # refused whatever the call means to do with it — read it, write it, or
        # only stat it. So creating a `.env` through a filesystem server is
        # refused here where the `Write` tool would not refuse it, and that is a
        # real over-block, paid on purpose.
        #
        # It is paid because every way of telling a read from a write inside a
        # PreToolUse payload fails in the LEAK direction, and this guard's whole
        # subject is the leak. The operation's verb is the server author's
        # spelling (`read_text_file`, `get_file_contents`, `view`, `cat`), so a
        # list of read verbs misses the next server's. The argument keys are that
        # same list one level down. "The payload carries bytes, so it is a write"
        # calls any read that also carries a revision or an encoding a write. And
        # "the file does not exist yet, so nothing can leak" answers about THIS
        # machine's filesystem while the server may be reading another host's.
        # A miss on any of those costs the file; this costs a retry, and it costs
        # it only on a call that named a secret file.
        #
        # The friction is bounded by the same rule the header states: NAMES are
        # never the target. A directory listing names a directory, which is not a
        # secret path, so the ordinary MCP traffic this guard now sees goes
        # through it silently.
        found, hit = _mcp_secret_target(ti, extras)
        if hit:
            return ("block",
                    "An MCP call naming a secret file is blocked (Rule #1): %s\n"
                    "This server calls the operation `%s`, and a PreToolUse "
                    "payload cannot tell a read of that file from a write to it "
                    "— so the file is refused either way. Listing names is fine; "
                    "contents are not. Ask the user to paste any value you "
                    "actually need." % (hit, _mcp_operation(tool) or "?"))
        return ("allow", "mcp: names no secret path (%d locators)" % len(found))

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
