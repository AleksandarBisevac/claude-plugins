#!/usr/bin/env python3
"""
PreToolUse hook (matcher: Bash) - refuse a `git commit` on a claim-bearing surface whose
message carries no `claims:` block. THIS REPO'S OWN CONFIGURATION, not the audit plugin's
product; it sits beside `guard-release.py` and draws the same line.

WHAT IT IS FOR. The `before-you-claim` skill asks seven questions at the moment a comment,
document, check, guard, brief or fault fix is written, and asks for the seven answers in the
commit message. A skill that lived in prose alone would be the fourth of its own questions
answered "no" - a rule with no mechanism - and this repository's fault register holds eleven
entries of exactly that. This hook is the mechanism.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT. Presence and shape only: the block is
there, it has seven numbered lines, each line says something. It never judges whether the
evidence is good - a hook that graded prose would be a lint over prose, and the register
shows those get routed around within a week. The reviewer reads the block first and judges;
this only makes sure there is a block to read.

WHICH COMMITS. Those whose STAGED paths touch a surface the skill covers: any `.md` under the
root or the plugin, and any `.py` under the plugin's `hooks/`, `scripts/`, `tests/`, the
repo's `tools/`, or this `.claude/hooks/` directory, plus `agents/*.md` and `reference/*.md`.
A commit that touches none of those - a screenshot, a rendered artifact, a fixture - passes
with no block and no message. That allow case is what keeps this hook installed: a guard that
fires on every commit is a guard somebody switches off.

WHERE THE MESSAGE COMES FROM. `-m "<text>"` (any number of them, joined), `-F <file>` /
`--file <file>`, `-F -` when the command carries the text in a heredoc, and `--amend
--no-edit`, which reuses HEAD's message read from git. A `git commit` with none of those
opens an editor this hook cannot see and is allowed through: no message exists yet, a human
is about to type one, and the hook says so rather than guessing. A message that DOES exist
and reaches git on a channel this hook will never hold - `-F -` fed by a pipe - is refused
instead, naming the routes it can read; `message_of` decides which of the two an unreadable
message earns, and the comment above it says why the line falls there.

Fail-open on its own malfunction, like every advisory hook in `SECURITY.md`'s table: if git
cannot be asked or the payload is not a commit, allow silently. The thing it protects is a
review habit, not an irreversible object, so it must not stop legitimate work by breaking.

Contract: a refusal emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0; the reason carries the block's
template so a subagent can act on it without a human.

Exit codes: 0 always (the decision travels in the payload, never in the code).
"""
import io
import json
import os
import re
import subprocess
import sys

# Surfaces the skill covers. Each is a predicate over a repo-relative POSIX path so the list
# reads as the rule it is; a new surface is one line here.
COVERED = (
    lambda p: p.endswith(".md"),
    lambda p: p.endswith(".py") and (
        p.startswith("plugins/audit/hooks/") or p.startswith("plugins/audit/scripts/")
        or p.startswith("plugins/audit/tests/") or p.startswith("tools/")
        or p.startswith(".claude/hooks/")),
)

BLOCK_HEAD = re.compile(r"^\s*claims:\s*$", re.MULTILINE)
BLOCK_LINE = re.compile(r"^\s*([1-7])\s+(\S.*)$")
QUESTIONS = 7

TEMPLATE = """claims:
1 <file:line that does what the sentence says | rewritten to say only what the code does | n/a - no behaviour claimed>
2 <mutation -> red -> restored; allow case red under over-fire | n/a - no check touched>
3 <grep for the shape: N hits, each fixed or named as left | n/a - not a fault fix>
4 <hook/script/schema that enforces it | "unenforced because ..." in the rule | n/a - no rule to an agent>
5 <two runs, gap, spread | "measured once" beside the number | n/a - no property recorded>
6 <decision reads the operation, not the text; allow case proven quiet | n/a - no guard>
7 <command beside the number | number deleted, pointer kept | n/a - no number written>"""

# THE DECISION READS A STATEMENT'S VERB, NOT A PATTERN OVER THE COMMAND TEXT.
#
# Two earlier versions were patterns, and each was widened after it let a real commit
# through. The first read `git\s+commit`, so `git -C ../wt commit` was "not a commit".
# The second added the global-option run and the separators `&&`, `;`, `||` - and still
# missed the commonest shape an agent writes, because `^` is not `re.MULTILINE` and a
# `git commit` that BEGINS ITS OWN LINE after a heredoc has none of those to its left.
# Baseline runs in one eval of this repo's own skill committed a covered surface that
# way, and every one of them was graded "not a commit".
#
# A third pattern would be a third widening. What the guard needs is the shell's own
# reading: a command is a list of statements, and a newline separates two statements
# exactly as `&&` does. So the text is cut into statements and each is classified by the
# argv it would run.
#
# HEREDOC BODIES ARE NOT STATEMENTS. Text on its way into a file is data; classifying it
# as a command is the same defect one surface over, and this repo's own history guard has
# it (it refuses a command whose only act is to write a file carrying a force-push
# literal). So the splitter skips from a `<<WORD` to its terminator.

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SEPARATORS = re.compile(r"&&|\|\||[;\n|]")


def _cut(command):
    """(statement texts, [(heredoc word, body)]) - one walk, both halves.

    The bodies are KEPT because `git commit -F - <<WORD` delivers its message in one, and
    they are kept SEPARATELY for the same reason they were dropped before: only the first
    half is ever classified, so a body remains data no matter what it spells."""
    pending, bodies = [], []
    lines = (command or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        pending.append(line)
        marks = _HEREDOC.findall(line)
        i += 1
        for _quote, word in marks:
            # Collect the body; the terminator may be indented when `<<-` was used.
            body = []
            while i < len(lines) and lines[i].strip() != word:
                body.append(lines[i])
                i += 1
            i += 1                       # step over the terminator itself
            bodies.append((word, "\n".join(body)))
    text = "\n".join(pending)
    return [s.strip() for s in _SEPARATORS.split(text) if s.strip()], bodies


def statements(command):
    """The command cut into the statements a shell would run, heredoc bodies removed.

    Returns the statement texts in order. A statement that is empty after the cut is
    dropped, so `a && && b` yields two rather than three."""
    return _cut(command)[0]


def heredoc_on(command, statement):
    """The text a heredoc opened by `statement` would feed to its standard input, or None
    when there is not exactly one such text to read.

    The word is read from the statement's OWN text - `git commit -F - <<'MSG'` carries
    `<<'MSG'` in it - so a body opened by some other statement, which git's stdin never
    sees, is not offered here. None when the statement opens no heredoc (a pipe, a
    redirect from a file, a here-string), when it opens more than one, or when the word it
    names was opened elsewhere too with different text: reading the wrong body would let
    through a commit whose real message nobody graded, so an ambiguity is not read."""
    words = [w for _quote, w in _HEREDOC.findall(statement or "")]
    if len(words) != 1:
        return None
    bodies = set(body for word, body in _cut(command)[1] if word == words[0])
    if len(bodies) != 1:
        return None
    return bodies.pop()


def _git_verb(statement):
    """The git subcommand this statement would run, or None when it is not git.

    Global options may sit between `git` and the verb - `git -C ../wt commit`, `git -c
    core.x=y commit`, `git --no-pager commit` - so the scan walks argv rather than
    matching a shape."""
    argv = _shell_split(statement)
    # A leading assignment or `cd`-style prefix is not git; find the program itself.
    while argv and ("=" in argv[0] and not argv[0].startswith("-")):
        argv = argv[1:]
    if not argv or os.path.basename(argv[0]) != "git":
        return None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-C", "-c"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def _commit_statement(command):
    """The statement that runs the commit, or None when none does.

    Its text is where `heredoc_on` reads the redirect word: the heredoc that feeds git's
    standard input is the one opened on the commit's own line, never one opened by some
    other statement of the same command."""
    for statement in statements(command):
        if _git_verb(statement) == "commit":
            return statement
    return None


def is_commit(command):
    return _commit_statement(command) is not None


def target_dir(command, cwd):
    """The directory git will run in: `cwd`, moved by every `cd <dir>` statement ahead of
    the commit and then by every `-C <dir>` ahead of the verb, each relative to the one
    before - the way a shell and git resolve them. The index this hook reads must be that
    directory's; reading the session's directory instead graded an empty index for a
    commit made in a sibling worktree and let a covered change through with no block.

    It walks the same statement list the classifier does, so a `cd` that is not the first
    thing on the line still moves the directory - the earlier version matched only a
    leading `cd <dir> &&` and then read argv across the whole remaining text, heredoc
    body included."""
    where = cwd
    for statement in statements(command):
        argv = _shell_split(statement)
        if argv and argv[0] == "cd" and len(argv) > 1:
            where = os.path.join(where, argv[1])
            continue
        if _git_verb(statement) != "commit":
            continue
        i = 1
        while i < len(argv) and argv[i] != "commit":
            if argv[i] == "-C" and i + 1 < len(argv):
                where = os.path.join(where, argv[i + 1]); i += 2; continue
            if argv[i].startswith("-C") and len(argv[i]) > 2:
                where = os.path.join(where, argv[i][2:]); i += 1; continue
            i += 1
        break
    return os.path.normpath(where)


def _shell_split(command):
    """`shlex` with a fallback: an unbalanced quote must not make the guard crash and thereby
    allow, so a command shlex cannot read is split on whitespace and read as best it can."""
    import shlex
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


# A MESSAGE ON STANDARD INPUT IS A MESSAGE THAT EXISTS, SO IT IS GRADED.
#
# `git commit -F -` and `git commit -F /dev/stdin` are one operation - git reads the text
# on file descriptor 0 - and they used to get opposite verdicts, neither of them chosen.
# `-` was joined to the target directory, the open of a file called `-` failed, and an
# unreadable message was graded fail-open. `/dev/stdin` opened, and what it read was THIS
# PROCESS's standard input: the hook's own JSON payload channel, consumed at `main`'s
# `json.load(sys.stdin)`. Driven with a block on the hook's stdin and none in the
# heredoc, that arm ALLOWED a commit carrying no block at all.
#
# The line between fail-open and refusal is not "can the hook read it" but WHETHER THERE
# IS A MESSAGE YET. The editor arm has none - a human is about to type one, and a hook
# cannot refuse what has not been written. A message on stdin has been written already;
# the author picked a channel, and the hook's business is the message, not the channel.
# So when the channel is a heredoc the text is IN the command and is read from there, and
# the same message delivered by `-m`, by `-F <file>` or by a heredoc gets one verdict.
# When it is anything else - a pipe, a redirect, a here-string - the message exists, this
# hook is never going to hold that descriptor, and the commit is REFUSED with the routes
# it can read.
#
# Refusing the heredoc as well would have been the shorter rule and is the wrong one: it
# would refuse commits that CARRY a complete block, for the spelling of their delivery
# alone. The docstring's reason for letting an uncovered staging through applies here
# too - a guard that fires on work it has nothing to say about is a guard somebody
# switches off.
STDIN_ROUTES = ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")

STDIN_UNREADABLE = (
    "this commit takes its message from standard input, which is a channel this hook does "
    "not hold - what it would read there is its own payload, not git's message. Deliver "
    "the message a way that can be graded: `-m \"<text>\"`, `-F <file>`, or `-F -` with the "
    "text in a heredoc on the commit itself")


def message_of(command, cwd):
    """(message, source, unreadable) - the commit message this command will use.

    `unreadable` is None when the message was read. Otherwise `message` is None, `source`
    says why, and `unreadable` carries the verdict that reason has earned: "allow" where
    no message exists yet or where the hook may simply have resolved a path the shell
    resolves differently, "deny" where a message exists and was handed to git on a
    channel this hook will never have."""
    statement = _commit_statement(command)
    if statement is None:
        return None, "not a commit", "allow"
    # The flag scan reads the WHOLE command, not just that statement: the statement cutter
    # treats every newline as a separator, so a multi-line `-m "..."` message is several
    # statements to it and scanning one of them would read only the part of the message
    # that sits on the commit's own line. The
    # cost is that a `-m` written inside a heredoc body still reaches this scan; the
    # statement is used where it is sound - deciding which heredoc, if any, is git's stdin.
    argv = _shell_split(command)
    parts, i = [], 0
    from_file, amend_noedit = None, False
    while i < len(argv):
        a = argv[i]
        if a in ("-m", "--message") and i + 1 < len(argv):
            parts.append(argv[i + 1]); i += 2; continue
        if a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
            parts.append(a[2:]); i += 1; continue
        if a.startswith("--message="):
            parts.append(a[len("--message="):]); i += 1; continue
        if a in ("-F", "--file") and i + 1 < len(argv):
            from_file = argv[i + 1]; i += 2; continue
        if a.startswith("--file="):
            from_file = a[len("--file="):]; i += 1; continue
        if a == "--amend":
            amend_noedit = amend_noedit or ("--no-edit" in argv)
        i += 1
    if parts:
        return "\n".join(parts), "-m", None
    if from_file:
        if from_file in STDIN_ROUTES:
            body = heredoc_on(command, statement)
            if body is None:
                return None, STDIN_UNREADABLE, "deny"
            return body, "-F - (the heredoc the command carries)", None
        path = from_file if os.path.isabs(from_file) else os.path.join(cwd, from_file)
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read(), "-F", None
        except OSError as exc:
            # Fail-open, unlike the channel above: a path is something this hook
            # RESOLVES, and a resolution it got wrong where the shell got it right would
            # refuse a commit whose message is on disk and carries the block. git fails
            # on a `-F` it cannot read too, so no commit comes of it either way.
            return None, "message file could not be read (%s)" % (exc,), "allow"
    if amend_noedit:
        try:
            out = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=cwd,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=5).stdout.decode("utf-8", "replace")
            return out, "HEAD (--amend --no-edit)", None
        except Exception as exc:
            return None, "HEAD message could not be read (%s)" % (exc,), "allow"
    return None, "the message comes from an editor this hook cannot read", "allow"


def staged_paths(cwd):
    """Repo-relative staged paths, or None when git cannot be asked."""
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=cwd,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5).stdout.decode("utf-8", "replace")
    except Exception:
        return None
    return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def covered(paths):
    return [p for p in paths if any(rule(p) for rule in COVERED)]


def block_verdict(message):
    """None when the block is present and shaped; else the sentence saying what is missing.

    A numbered line may CONTINUE on indented lines below it - an author giving real
    evidence (three file:lines, a grep and its hits) needs more than one line, and the
    first eval of the skill produced exactly that shape. A continuation is any line
    that starts with whitespace; the block ends at the first non-blank line that
    neither starts a numbered answer nor continues one."""
    m = BLOCK_HEAD.search(message or "")
    if not m:
        return "no `claims:` block"
    seen = {}
    for line in message[m.end():].splitlines():
        if not line.strip():
            continue
        lm = BLOCK_LINE.match(line)
        if lm:
            seen[int(lm.group(1))] = lm.group(2).strip()
        elif line[:1] in (" ", "\t") and seen:
            continue                    # a continuation of the answer above it
        else:
            break                       # the block ends at the first other line
    missing = [str(n) for n in range(1, QUESTIONS + 1) if n not in seen]
    if missing:
        return "the `claims:` block is missing line(s) %s" % ", ".join(missing)
    return None


def _refusal(why, hit):
    """The deny reason: what is wrong, which staged surfaces make it matter, and the
    template to fill. One builder, because a message this hook cannot read and a message
    with no block ask the author for the same thing."""
    return (
        "[require-claim-block] %s, and this commit stages a surface the "
        "`before-you-claim` skill covers: %s.\n"
        "Answer the seven questions (evidence or `n/a - <reason>` per line) and put the "
        "block in the commit message:\n\n%s\n\n"
        "The hook checks that the block is present and has seven lines; the reviewer "
        "judges the answers. Read .claude/skills/before-you-claim/SKILL.md for what each "
        "line must carry."
        % (why, ", ".join(hit[:4]) + (" ..." if len(hit) > 4 else ""), TEMPLATE))


def decide(payload, cwd):
    """('allow'|'deny', reason). Pure over its inputs except for the two git reads."""
    command = ((payload or {}).get("tool_input") or {}).get("command") or ""
    if not is_commit(command):
        return "allow", "not a commit"
    where = target_dir(command, cwd)
    paths = staged_paths(where)
    if paths is None:
        return "allow", "git could not be asked (fail-open)"
    hit = covered(paths)
    if not hit:
        return "allow", "no claim-bearing surface staged"
    message, source, unreadable = message_of(command, where)
    if message is None:
        if unreadable == "deny":
            return "deny", _refusal(source, hit)
        return "allow", source
    why = block_verdict(message)
    if why is None:
        return "allow", "claims block present (%s)" % source
    return "deny", _refusal(why, hit)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    cwd = (payload or {}).get("cwd") or os.getcwd()
    verdict, reason = decide(payload, cwd)
    if verdict == "deny":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    return 0


# --- selftest -------------------------------------------------------------------
def _selftest():
    """Both directions, driven against a REAL git repository built in a temp dir, because
    the staged-path read is the half of this guard that a mocked git would not test."""
    import shutil
    import tempfile
    results = []

    def check(label, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           ("  -- " + str(detail)[:120]) if (detail and not ok) else ""))

    good = "subject\n\nbody\n\nclaims:\n" + "\n".join(
        "%d n/a - nothing of this kind in the change" % n for n in range(1, 8))
    five = "subject\n\nclaims:\n" + "\n".join("%d n/a" % n for n in range(1, 6))
    tmp = tempfile.mkdtemp(prefix="claimblock-")
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=tmp)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp)
        for rel in ("tools/x.py", "docs/pic.png", "README.md", "plugins/audit/hooks/h.py",
                    "fixtures/data.json"):
            p = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            io.open(p, "w").write("x\n")

        import shlex

        def payload(cmd):
            return {"tool_input": {"command": cmd}, "cwd": tmp}

        # THE FIXTURE QUOTES THE WAY A SHELL DOES. The first version of these cases
        # passed the message through `json.dumps`, which spells a newline as the two
        # characters `\n` - and a shell hands those two characters to git verbatim, so
        # the block's head never sat alone on a line and s2/s3 were red against a hook
        # that was right. `shlex.quote` produces what `git commit -m "$(cat)"` or a
        # multi-line double-quoted string actually gives the hook.
        # 1. a covered surface, no block -> deny, and the refusal carries the template
        subprocess.run(["git", "add", "tools/x.py"], cwd=tmp)
        v, r = decide(payload('git commit -m "fix: thing"'), tmp)
        check("s1 a commit staging a covered .py with no block is REFUSED",
              v == "deny" and "no `claims:` block" in r, (v, r[:80]))
        check("s1b ...and the refusal carries the template a subagent can fill",
              "claims:\n1 <" in r and "7 <" in r)
        # 2. the same commit WITH the block -> allow
        v, r = decide(payload('git commit -m "fix: thing" -m %s' % shlex.quote(good)), tmp)
        check("s2 the same commit with a seven-line block PASSES", v == "allow", (v, r))
        # 3. five lines -> deny naming 6, 7
        v, r = decide(payload('git commit -m %s' % shlex.quote(five)), tmp)
        check("s3 a block with five lines is refused and the refusal NAMES lines 6, 7",
              v == "deny" and "6, 7" in r, (v, r[:100]))
        # 3b. and the literal-backslash-n spelling IS refused, on purpose: what the
        # shell hands git is what the hook grades, and `-m 'claims:\n1 x'` commits a
        # message whose block is one line of `\n` characters, not seven lines.
        v, r = decide(payload('git commit -m %s' % json.dumps(good)), tmp)
        check("s3b a message whose newlines are the two characters backslash-n is refused - "
              "the hook grades what the shell hands git, and that message has no block",
              v == "deny", (v, r[:60]))
        # 4. uncovered-only staging -> allow with no message (the allow case that keeps it installed)
        subprocess.run(["git", "reset", "-q"], cwd=tmp)
        subprocess.run(["git", "add", "docs/pic.png", "fixtures/data.json"], cwd=tmp)
        v, r = decide(payload('git commit -m "chore: assets"'), tmp)
        check("s4 a commit staging only uncovered files passes with no block",
              v == "allow" and "no claim-bearing" in r, (v, r))
        # 5. a .md anywhere is covered
        subprocess.run(["git", "add", "README.md"], cwd=tmp)
        v, r = decide(payload('git commit -m "docs"'), tmp)
        check("s5 a staged .md is a covered surface", v == "deny", (v, r[:60]))
        # 6. -F file carries the block -> allow
        mf = os.path.join(tmp, "msg.txt"); io.open(mf, "w").write(good)
        v, r = decide(payload('git commit -F msg.txt'), tmp)
        check("s6 a message from -F <file> is read and its block honoured",
              v == "allow" and "-F" in r, (v, r))
        # 7. editor commit -> allow, and the reason says the hook could not read it
        v, r = decide(payload('git commit'), tmp)
        check("s7 an editor commit is allowed, and the reason says it could not be read",
              v == "allow" and "editor" in r, (v, r))
        # 8. not a commit at all -> allow
        v, r = decide(payload('git status && git diff --cached --name-only'), tmp)
        check("s8 a non-commit git command is not a commit (the word inside a diff flag is not one)",
              v == "allow" and r == "not a commit", (v, r))
        # 9. --amend --no-edit reads HEAD's message
        subprocess.run(["git", "reset", "-q"], cwd=tmp)
        subprocess.run(["git", "add", "fixtures/data.json"], cwd=tmp)
        subprocess.run(["git", "commit", "-q", "-m", good], cwd=tmp)
        subprocess.run(["git", "add", "tools/x.py"], cwd=tmp)
        v, r = decide(payload('git commit --amend --no-edit'), tmp)
        check("s9 --amend --no-edit reuses HEAD's message, which here carries the block",
              v == "allow" and "HEAD" in r, (v, r))
        # 10. git unavailable -> fail-open, and the reason says so
        v, r = decide(payload('git commit -m "x"'), os.path.join(tmp, "not-a-repo-dir"))
        check("s10 when git cannot be asked the hook fails OPEN and says so",
              v == "allow" and "fail-open" in r, (v, r))
        # 11. the shape check is not fooled by a `claims:` word inside the body
        v, r = decide(payload('git commit -m "subject: my claims: are strong"'), tmp)
        check("s11 the word `claims:` inside a sentence is not the block - the head must sit alone on its line",
              v == "deny", (v, r[:60]))
        # 12. a numbered answer may continue on indented lines - the shape a real
        # author produced when giving three file:lines for one question. The first
        # version of this parser stopped at the first non-numbered line and would
        # have refused a block that was MORE complete than the minimum.
        multi = ("subject\n\nclaims:\n"
                 "1 _evidence_io.py:355 - the docstring; each sentence backed by\n"
                 "  _evidence_io.py:266-343 (no hash key set) and\n"
                 "  _evidence_io.py:441 (record()'s anchor names runId)\n"
                 + "\n".join("%d n/a - not touched" % n for n in range(2, 8)))
        subprocess.run(["git", "add", "tools/x.py"], cwd=tmp)
        v, r = decide(payload('git commit -m %s' % shlex.quote(multi)), tmp)
        check("s12 an answer continued on indented lines still counts as that line, so a block "
              "with real evidence is not refused for having it",
              v == "allow", (v, r[:80]))
        # ...and the second direction: an indented line BEFORE any numbered answer is
        # not a continuation of anything, so a block that opens with prose is still
        # missing its seven lines.
        v, r = decide(payload('git commit -m %s' % shlex.quote("s\n\nclaims:\n  just prose\n")), tmp)
        check("s12b an indented line before the first numbered answer is not a continuation",
              v == "deny" and "missing line(s) 1, 2" in r, (v, r[:80]))
        # 13. THE COMMIT IS NOT WHERE THE SESSION IS. A run in a sibling worktree commits
        # with `git -C <there>` or `cd <there> &&`, and the payload's cwd is still the
        # session's checkout - where nothing is staged. The index that matters is the
        # command's target, and `is_commit` must see the verb past git's global options.
        subprocess.run(["git", "reset", "-q"], cwd=tmp)
        tmp2 = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmp2, check=True)
            os.makedirs(os.path.join(tmp2, "tools"))
            with io.open(os.path.join(tmp2, "tools", "y.py"), "w") as fh:
                fh.write("x = 1\n")
            subprocess.run(["git", "add", "tools/y.py"], cwd=tmp2)
            v, r = decide(payload('git -C %s commit -m "fix: there"' % shlex.quote(tmp2)), tmp)
            check("s13 a commit made with `-C <other repo>` is graded against THAT index, "
                  "not the session's", v == "deny" and "no `claims:` block" in r, (v, r[:80]))
            v, r = decide(payload('cd %s && git commit -m "fix: there"' % shlex.quote(tmp2)), tmp)
            check("s13b ...and so is one made after `cd <other repo> &&`",
                  v == "deny" and "no `claims:` block" in r, (v, r[:80]))
            v, r = decide(payload('git -C %s commit -m "fix: there" -m %s'
                                  % (shlex.quote(tmp2), shlex.quote(good))), tmp)
            check("s13c the allow case survives the widening: the same -C commit WITH the "
                  "block passes", v == "allow", (v, r[:80]))
            v, r = decide(payload('git -C %s status' % shlex.quote(tmp2)), tmp)
            check("s13d ...and a non-commit git command through -C is still not a commit",
                  v == "allow" and r == "not a commit", (v, r))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        # 14. THE SHAPE THAT WALKED PAST TWO EARLIER PATTERNS. A heredoc builds the
        # message, then `git commit` begins its own LINE. Baseline runs in an eval of this
        # repo's own skill committed a covered surface this way, and the guard called every
        # one of them "not a commit".
        #
        # STAGE A COVERED PATH FIRST. Case 13 left the index reset, and the first version
        # of these cases inherited that: s14b read "no claim-bearing surface staged" and
        # s14c PASSED without the message ever being looked at, which is a case asserting
        # nothing. `decide` answers the staged question before the block question, so any
        # case about a block has to put something covered in the index.
        subprocess.run(["git", "add", "tools/x.py"], cwd=tmp)
        msg = os.path.join(tmp, "msg.txt")
        io.open(msg, "w").write("subject\n\nbody with no block\n")
        heredoc = ("cd %s && cat > %s <<'MSG'\nsubject\n\nbody\nMSG\n"
                   "git commit -F %s 2>&1 | tail -40" % (tmp, msg, msg))
        check("s14 a `git commit` that BEGINS ITS OWN LINE after a heredoc is a commit",
              is_commit(heredoc))
        v, r = decide(payload(heredoc), tmp)
        check("s14b ...and with a covered path staged and no block it is REFUSED",
              v == "deny" and "no `claims:` block" in r, (v, r[:90]))
        # The allow case has to put the block where the hook READS it - the file `-F`
        # names, on disk. The first version of this case wrote it into the heredoc body
        # instead, which is the text the command would have written had anything run it;
        # nothing does, so the hook read the old file and refused. The case was right to
        # be red.
        msg_ok = os.path.join(tmp, "msg-ok.txt")
        io.open(msg_ok, "w").write(good)
        v, r = decide(payload(heredoc.replace(msg, msg_ok)), tmp)
        check("s14c the allow case: the same shape WITH the block passes",
              v == "allow", (v, r[:90]))

        # 15. THE OVER-FIRE DIRECTION. Cutting on newlines must not turn every line that
        # merely MENTIONS a commit into one: a heredoc body is data on its way to a file,
        # and reading it as a command is the defect this guard exists to stop, one surface
        # over. Both of these must stay quiet.
        writes_a_script = ("cat > %s/probe.sh <<'EOF'\ngit commit -m x\nEOF\n"
                           "echo wrote it" % tmp)
        check("s15 a heredoc whose BODY contains `git commit` is not a commit - the body "
              "is data being written to a file",
              not is_commit(writes_a_script))
        check("s15b ...and a bare `git status` on its own line is still not a commit",
              not is_commit("echo hello\ngit status --short"))
        check("s15c ...while `git commit` after a plain newline, with no heredoc at all, "
              "IS one",
              is_commit("echo hello\ngit commit -m x"))

        # 16. The directory walk follows the same statements: a `cd` that is not the
        # first thing on the line still moves the tree the index is read from.
        check("s16 target_dir follows a `cd` inside a multi-line command",
              target_dir(heredoc, os.path.dirname(tmp)) == os.path.normpath(tmp),
              target_dir(heredoc, os.path.dirname(tmp)))

        # 17. A MESSAGE ON STANDARD INPUT IS ONE CASE, AND IT IS GRADED. `-F -`,
        # `--file=-` and `-F /dev/stdin` all hand git the text on descriptor 0, and they
        # used to get two different verdicts by accident: the first two were ALLOWED,
        # because a file named `-` cannot be opened and an unreadable message was
        # fail-open, while `/dev/stdin` opened the HOOK's own standard input - driven
        # with a block on the payload channel and none in the heredoc, that arm allowed a
        # commit carrying no block. Now the heredoc the command carries IS the message,
        # so the verdict follows the text a reviewer would read.
        subprocess.run(["git", "reset", "-q"], cwd=tmp)
        subprocess.run(["git", "add", "tools/x.py"], cwd=tmp)

        def on_stdin(flag, body):
            return "%s <<'MSG'\n%s\nMSG\n" % (flag, body)

        v, r = decide(payload(on_stdin("git commit -F -", "subject\n\nno block here")), tmp)
        check("s17 a heredoc message with no block, delivered on stdin, is REFUSED",
              v == "deny" and "no `claims:` block" in r, (v, r[:90]))
        v, r = decide(payload(on_stdin("git commit -F -", good)), tmp)
        check("s17b ...and the allow direction: the same route carrying the block PASSES, "
              "so what decides is the message and not the channel",
              v == "allow" and "heredoc" in r, (v, r[:90]))
        v, r = decide(payload(on_stdin("git commit --file=/dev/stdin", good)), tmp)
        check("s17c `--file=/dev/stdin` is the same operation as `-F -`, so it is the same "
              "verdict", v == "allow" and "heredoc" in r, (v, r[:90]))
        # The deny direction of `/dev/stdin` cannot be told from the accident by its
        # verdict - an empty payload channel read as the message has no block either, so
        # both rules refuse. So this one asserts the TEXT that was graded: it has to be
        # the heredoc's, not whatever this process's own standard input happens to hold.
        cmd = on_stdin("git commit -F /dev/stdin", "subject\n\nnothing anyone can review")
        msg, source, unreadable = message_of(cmd, tmp)
        check("s17d ...and what gets graded is the heredoc's text, not the hook's own "
              "standard input",
              unreadable is None and msg is not None and "nothing anyone can review" in msg,
              (source, repr(msg)[:70]))

        # 18. AND A STANDARD INPUT THE HOOK CANNOT SEE IS REFUSED, NOT WAVED THROUGH.
        # This is where the stdin arm parts from the editor arm below it: a piped message
        # has already been written, so there is something to grade and no human about to
        # type it.
        v, r = decide(payload('printf %s | git commit -F -' % shlex.quote(good)), tmp)
        check("s18 a message piped into `-F -` is refused: it exists, and this hook does "
              "not hold that channel", v == "deny" and "standard input" in r, (v, r[:90]))
        check("s18b ...and the refusal names a route that CAN be read",
              "`-F <file>`" in r, r[:240])

        # 19. THE HEREDOC HAS TO BE THE COMMIT'S OWN. A body opened by another statement
        # is on its way into a file and never reaches git's standard input; reading it
        # would pass a blockless commit on the strength of text being written elsewhere.
        elsewhere = "cat > notes.txt <<'MSG'\n%s\nMSG\ngit commit -F -" % good
        v, r = decide(payload(elsewhere), tmp)
        check("s19 a heredoc opened by a DIFFERENT statement is not this commit's stdin",
              v == "deny" and "standard input" in r, (v, r[:90]))

        # 20. Keeping the bodies must not make them statements - the property the
        # classifier rests on. Both halves in one assertion: the body is there to be read,
        # and the command is still not a commit.
        check("s20 the bodies are kept WITHOUT becoming statements: `_cut` hands back the "
              "body of that script, and the script is still not a commit",
              bool(_cut(writes_a_script)[1]) and not is_commit(writes_a_script),
              _cut(writes_a_script)[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = len(results); ok = sum(1 for x in results if x)
    print("\n%s: %d/%d cases passed" % ("ALL PASS" if ok == n else "SELFTEST FAILED", ok, n))
    return 0 if ok == n else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
