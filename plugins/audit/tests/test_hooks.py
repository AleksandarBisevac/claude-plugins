#!/usr/bin/env python3
"""
The verdict contract of the PreToolUse hooks `hooks/hooks.json` registers, per
operation class and per plan-gate tier, driven through the launcher.

WHY A TABLE KEYED BY OPERATION, NOT BY HOOK. Each guard has its own suite, and
each of those grades the guard it is named after. None of them can see the
property a user meets: the SAME change gets the SAME verdict whichever tool
performs it. `sed -i` on a file and `Edit` of that file are one operation, and
the plan gate's own docstring (`_config.plan_gate_mode`) promises they cannot
disagree. Only a test that sends both through every hook registered for each
tool, and compares the combined answers, can hold that promise - so the unit
here is the operation class, and a row is one spelling of it.

THE TIERS ARE THREE FIXTURE PROJECTS, NOT THREE CONFIG VALUES. The plan gate
grades itself on evidence - no manifest is `observe`, a manifest with nothing
running is `warn`, a running phase is `deny` - so pinning `planGate` by hand
would test the knob and skip the reading. Each fixture is a real git repository
under `_harness.fixture_root`, with its own local identity because the sweep
supplies none, and the same tracked files in each:

  <plugin>/hooks/guard_demo.py   the file the running task declares
  <plugin>/hooks/other_hook.py   a hook file no task declares
  src/app.py                     an uncovered source file
  notes.md                       an uncommitted change (the stash case)
  docs/audit/journal/...jsonl    the append-only journal
  a dotenv file                  a secret path

`<plugin>` is `FX_PLUGIN`, the fixture's copy of this plugin's directory
layout. It is BUILT, never spelled: `_refs` reads every anchored path in this
directory as a reference to a file in THIS repository, and these files exist
only inside the fixture.

The `warn` and `deny` fixtures add a manifest whose done task records HEAD's
commit, so a history rewrite has a recorded SHA to orphan.

COMBINED VERDICT = DENY OVER ASK OVER ALLOW, across every hook whose matcher
fullmatches the row's tool, each run as `hooks.json` spells it - `sh
py-launch.sh <hook> <mode>` - with the plugin root substituted. A hook that
exits nonzero, or prints something that is not a decision, is not an allow: the
row fails and says the hook could not run.

KNOWN DIVERGENCE IS RECORDED, NOT HIDDEN. A row whose verdict today differs
from its class carries `today` (what the hooks answer now, which the
suite asserts) and `contradicts` (the basis it breaks). The task that fixes
the divergence deletes those two keys, and the class verdict becomes the
assertion. A divergence mark on a row that already agrees with its class is a
failure too, so the mark cannot outlive the fix.

WHAT IS LEFT OUT, AND WHERE IT LIVES. Shapes the security document lists as
open are not in this table: their verdict is a known gap, and a contract row
asserting the gap would read as endorsing it. The pure-function rows that grade
`_command_is_read_only` directly go through no hook, so they belong to that
guard's own suite. `OUT_OF_SCOPE_MATCHERS` names every registered matcher no
row exercises, with the reason.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402

PLUGIN_DIR = os.path.dirname(_harness.HOOKS_DIR)
HOOKS_JSON = os.path.join(_harness.HOOKS_DIR, "hooks.json")
TIERS = ("observe", "warn", "deny")
RANK = {"allow": 0, "ask": 1, "deny": 2}

FX_PLUGIN = "/".join(("plugins", "audit"))
DEMO = FX_PLUGIN + "/hooks/guard_demo.py"
OTHER_HOOK = FX_PLUGIN + "/hooks/other_hook.py"
FX_TESTS = FX_PLUGIN + "/tests/"
JOURNAL = "docs/audit/journal/2026-10.corpus.jsonl"
MANIFEST = "docs/audit/audit-plan.json"

# The date and the decider of the verdicts no plugin document states. Kept as
# one string so every such row cites the same decision, word for word.
OPERATOR_DECISION = ("operator decision, 2026-10-06: taken by the orchestrator "
                     "under the operator's standing instruction to run the plan "
                     "to completion, on the analysis's recommendation")


SHELL_EDIT_PARITY = ("_config.plan_gate_mode docstring: a shell write and Edit "
                     "of one file cannot disagree; the Edit twin takes the "
                     "session's trivial-file slot at the deny tier while the "
                     "shell write is refused as outside the plan")


def _all(verdict):
    return {"observe": verdict, "warn": verdict, "deny": verdict}


def _ladder(observe, warn, deny):
    return {"observe": observe, "warn": warn, "deny": deny}


# --- the contract: operation classes and their verdict per tier ------------------
# Every class names its verdict at each tier and the basis for it. A class with
# `tiers` is only defined at those tiers (a manifest edit has no manifest to edit
# at observe).
CLASSES = {
    "edit-declared-file": {
        "verdict": _all("allow"),
        "basis": "_config.plan_gate_mode docstring: observe and warn never "
                 "block, and the deny tier allows a file the running task "
                 "declares, whichever tool writes it"},
    "restore-declared-file-from-head": {
        "verdict": _all("allow"),
        "basis": "agents/audit-executor.md: nothing mechanically stops "
                 "overwriting a declared file with HEAD's copy; the plan gate "
                 "grades which file, not why"},
    "trivial-edit-undeclared-file": {
        "verdict": _all("allow"),
        "basis": "require-plan.py header: the first non-exempt code file of a "
                 "session with a magnitude within trivialLineThreshold is "
                 "allowed, and _config.plan_gate_mode: a shell write and Edit "
                 "of one file cannot disagree"},
    "large-new-undeclared-file": {
        "verdict": _ladder("allow", "allow", "deny"),
        "basis": "require-plan.py header: a magnitude above "
                 "trivialLineThreshold is not trivial, graded by the "
                 "plan_gate_mode ladder"},
    "write-test-file": {
        "verdict": _all("allow"),
        "basis": "_config test-file exemption: a test file and its data are "
                 "outside the plan gate"},
    "run-plugin-script": {
        "verdict": _all("allow"),
        "basis": "CLAUDE.md and reference/execute-task.md: the selftests and "
                 "the plugin's own scripts are how work is checked and "
                 "recorded; journal-writes acquits the plugin's own writers"},
    "read-non-secret": {
        "verdict": _all("allow"),
        "basis": "SECURITY.md secrets section: guard-secrets-read refuses "
                 "secret files and environment dumps, nothing else"},
    "history-safe-git": {
        "verdict": _all("allow"),
        "basis": "guard-history-rewrite.py header: a commit, a quoted phrase "
                 "and a reset that orphans no recorded SHA are allowed; the "
                 "red-first helper's detached worktree is sanctioned"},
    "scratch-outside-tree": {
        "verdict": _all("allow"),
        "basis": "no guard grades a write outside the project tree"},
    "history-rewrite-recorded": {
        "verdict": _ladder("allow", "deny", "deny"),
        "basis": "guard-history-rewrite.py header: a force push, a rebase or "
                 "a reset that orphans a recorded SHA is refused while the "
                 "manifest records one; observe has no manifest"},
    "stash-with-plan": {
        "verdict": _ladder("allow", "deny", "deny"),
        "basis": "guard-history-rewrite.py header: stash is refused as soon "
                 "as an audit plan exists on disk"},
    "unquoted-git-words": {
        "verdict": _ladder("allow", "deny", "deny"),
        "basis": "SECURITY.md: every git word counts, prose included, so an "
                 "unquoted forbidden phrase is refused, deliberately, once a "
                 "plan exists"},
    "journal-write": {
        "verdict": _all("deny"),
        "basis": "_config.plan_gate_mode docstring: a guard whose claim binds "
                 "to a journal file reports at every tier; one operation gets "
                 "one verdict whichever tool performs it"},
    "manifest-edit-orchestrator": {
        "verdict": {"warn": "allow", "deny": "allow"},
        "tiers": ("warn", "deny"),
        "basis": "guard-secrets-read.py: the manifest is exempt from the plan "
                 "gate for the orchestrator, refused to subagents and live "
                 "lock holders"},
    "manifest-edit-subagent": {
        "verdict": {"warn": "deny", "deny": "deny"},
        "tiers": ("warn", "deny"),
        "basis": "guard-secrets-read.py and require-plan.py: a subagent is "
                 "refused the plan it is judged by"},
    "secret-read": {
        "verdict": _all("deny"),
        "basis": "SECURITY.md secrets section: a secret path or an environment "
                 "dump is refused at every tier"},
}


# --- the rows: one spelling of an operation each, cited by id --------------------
# `{ROOT}` is the fixture project, `{PLUGIN}` this plugin, `{TMP}` a scratch
# directory outside every fixture, `{BIGCONTENT}` a source file well past the
# trivial-edit threshold.
def _edit(path, old, new):
    return {"file_path": "{ROOT}/" + path, "old_string": old, "new_string": new}


def _bash(command):
    return {"command": command}


ROWS = (
    # edit-declared-file
    {"id": "n01", "class": "edit-declared-file", "tool": "Edit",
     "input": _edit(DEMO, "VERSION = 1", "VERSION = 2"),
     "why": "edit of a hook file the running task declares"},
    {"id": "b01", "class": "edit-declared-file", "tool": "Bash",
     "input": _bash("sed -i '' 's/VERSION = 1/VERSION = 2/' " + DEMO),
     "why": "the same change through sed -i"},
    {"id": "b03", "class": "edit-declared-file", "tool": "Bash",
     "input": _bash("python3 - <<'PY'\np = '%s'\ns = open(p).read().replace("
                    "'VERSION = 1', 'VERSION = 2')\nopen(p, 'w').write(s)\nPY"
                    % DEMO),
     "why": "the same change through a heredoc program"},
    {"id": "b08", "class": "edit-declared-file", "tool": "Edit",
     "input": _edit(DEMO, "VERSION = 1", "VERSION = 0"),
     "why": "temporarily undo a fix through Edit"},
    # restore-declared-file-from-head
    {"id": "b05", "class": "restore-declared-file-from-head", "tool": "Bash",
     "input": _bash("git show HEAD:%s > %s" % (DEMO, DEMO)),
     "why": "overwrite a declared file with HEAD's copy"},
    {"id": "b06", "class": "restore-declared-file-from-head", "tool": "Bash",
     "input": _bash("git checkout -- " + DEMO),
     "why": "revert one declared file",
     "decided": "allow - " + OPERATOR_DECISION},
    # trivial-edit-undeclared-file
    {"id": "b02e", "class": "trivial-edit-undeclared-file", "tool": "Edit",
     "input": _edit(OTHER_HOOK, "X = 1", "X = 2"),
     "why": "one-line Edit of a hook file no task declares"},
    {"id": "b02", "class": "trivial-edit-undeclared-file", "tool": "Bash",
     "input": _bash("sed -i '' 's/X = 1/X = 2/' " + OTHER_HOOK),
     "why": "the same change as b02e, through sed -i",
     "today": _ladder("allow", "allow", "deny"), "contradicts": SHELL_EDIT_PARITY},
    {"id": "b17", "class": "trivial-edit-undeclared-file", "tool": "Edit",
     "input": _edit("src/app.py", "A = 1", "A = 2"),
     "why": "one-line Edit of an uncovered source file"},
    {"id": "b17s", "class": "trivial-edit-undeclared-file", "tool": "Bash",
     "input": _bash("sed -i '' 's/A = 1/A = 2/' src/app.py"),
     "why": "the same change as b17, through sed -i",
     "today": _ladder("allow", "allow", "deny"), "contradicts": SHELL_EDIT_PARITY},
    {"id": "b03o", "class": "trivial-edit-undeclared-file", "tool": "Bash",
     "input": _bash("python3 - <<'PY'\np = 'src/app.py'\ns = open(p).read()"
                    ".replace('A = 1', 'A = 2')\nopen(p, 'w').write(s)\nPY"),
     "why": "the same change as b17, through a heredoc program",
     "today": _ladder("allow", "allow", "deny"), "contradicts": SHELL_EDIT_PARITY},
    # large-new-undeclared-file
    {"id": "b17w", "class": "large-new-undeclared-file", "tool": "Write",
     "input": {"file_path": "{ROOT}/src/new_module.py", "content": "{BIGCONTENT}"},
     "why": "a new uncovered source file above the trivial threshold"},
    # write-test-file
    {"id": "n02", "class": "write-test-file", "tool": "Write",
     "input": {"file_path": "{ROOT}/" + FX_TESTS + "test_guard_demo.py",
               "content": "CASES = ['cat .env.production', "
                          "'git push --force origin main']\n\n"
                          "def test_cases_are_strings():\n"
                          "    assert all(isinstance(c, str) for c in CASES)\n"},
     "why": "a test whose DATA holds forbidden spellings as strings"},
    {"id": "n14", "class": "write-test-file", "tool": "Write",
     "input": {"file_path": "{ROOT}/" + FX_TESTS + "data/history_deny_cases.json",
               "content": "[\"git push --force origin main\", "
                          "\"git rebase -i HEAD~2\"]\n"},
     "why": "guard test data in a data file"},
    {"id": "b18", "class": "write-test-file", "tool": "Write",
     "input": {"file_path": "{ROOT}/" + FX_TESTS + "test_other.py",
               "content": "def test_x():\n    assert True\n"},
     "why": "a new test file outside the running task"},
    # run-plugin-script
    {"id": "n03", "class": "run-plugin-script", "tool": "Bash",
     "input": _bash("python3 " + FX_TESTS + "test_guard_demo.py --selftest"),
     "why": "a selftest run"},
    {"id": "n04", "class": "run-plugin-script", "tool": "Bash",
     "input": _bash("python3 {PLUGIN}/scripts/manifest/validate-manifest.py "
                    + MANIFEST),
     "why": "manifest validation through the plugin's own script"},
    {"id": "n05", "class": "run-plugin-script", "tool": "Bash",
     "input": _bash("python3 {PLUGIN}/scripts/governance/run-test-gate.py "
                    + MANIFEST + " P1 --json"),
     "why": "the test gate through the plugin's own script"},
    {"id": "n06", "class": "run-plugin-script", "tool": "Bash",
     "input": _bash("python3 {PLUGIN}/scripts/manifest/audit-task.py start "
                    "P1.1 --project-dir ."),
     "why": "a journal row written by the plugin's own verb"},
    # read-non-secret
    {"id": "n07", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("python3 - <<'PY'\nPATTERN = 'sk-' + 'x' * 8\n"
                    "print(len(open('README.md').read()))\nPY"),
     "why": "a heredoc program with a token-shaped literal that reads README.md"},
    {"id": "n08", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("git diff --stat"), "why": "read-only git"},
    {"id": "n09", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("git show HEAD:" + DEMO), "why": "HEAD's copy to stdout"},
    {"id": "n11", "class": "read-non-secret", "tool": "Read",
     "input": {"file_path": "{ROOT}/" + DEMO}, "why": "read a hook source file"},
    {"id": "n12", "class": "read-non-secret", "tool": "Grep",
     "input": {"pattern": "\\.env", "path": "{ROOT}/" + FX_PLUGIN + "/hooks",
               "glob": "*.py"},
     "why": "search sources for a secret file's NAME, the glob excluding it"},
    {"id": "n13", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("ls -la docs/audit/journal"), "why": "list the journal"},
    {"id": "n17", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("grep -n 'git stash' " + DEMO),
     "why": "search source for a QUOTED forbidden phrase"},
    {"id": "g06", "class": "read-non-secret", "tool": "Bash",
     "input": _bash("python3 - <<'PY'\nDOC = \"the guard refuses open('.env') "
                    "in a program\"\nprint(len(DOC))\nPY"),
     "why": "a string literal MENTIONS opening a secret file; the program "
            "reads nothing",
     "decided": "allow - " + OPERATOR_DECISION,
     "today": _all("deny"),
     "contradicts": "the operator's decided verdict (allow): the secrets guard "
                    "matches the program's TEXT, so a literal that only names "
                    "a secret path is refused as a read of it"},
    # history-safe-git
    {"id": "n10", "class": "history-safe-git", "tool": "Bash",
     "input": _bash("git worktree add --detach {TMP}/redfirst-wt HEAD"),
     "why": "the red-first helper's throwaway tree"},
    {"id": "n15", "class": "history-safe-git", "tool": "Bash",
     "input": _bash("git commit -F {TMP}/msg.txt"),
     "why": "a commit whose message is in a file"},
    {"id": "n16", "class": "history-safe-git", "tool": "Bash",
     "input": _bash("git commit -m \"guards: refuse git stash drop in a "
                    "shared tree\""),
     "why": "a commit message that NAMES a forbidden command"},
    {"id": "b13", "class": "history-safe-git", "tool": "Bash",
     "input": _bash("git reset --hard"),
     "why": "a reset to HEAD orphans no recorded commit"},
    # scratch-outside-tree
    {"id": "b07", "class": "scratch-outside-tree", "tool": "Bash",
     "input": _bash("rm -rf {TMP}/scratch-xyz"),
     "why": "remove a named scratch directory"},
    {"id": "b20", "class": "scratch-outside-tree", "tool": "Bash",
     "input": _bash("mkdir -p {TMP}/bk && cp %s {TMP}/bk/" % DEMO),
     "why": "copy a source file OUT of the tree"},
    # history-rewrite-recorded
    {"id": "b12", "class": "history-rewrite-recorded", "tool": "Bash",
     "input": _bash("git push --force origin main"),
     "why": "force push while the plan records a commit"},
    {"id": "b13b", "class": "history-rewrite-recorded", "tool": "Bash",
     "input": _bash("git reset --hard HEAD~2"),
     "why": "a reset that orphans the recorded commit"},
    {"id": "b14", "class": "history-rewrite-recorded", "tool": "Bash",
     "input": _bash("git rebase -i HEAD~2"),
     "why": "a rebase over the recorded commit"},
    # stash-with-plan
    {"id": "b04", "class": "stash-with-plan", "tool": "Bash",
     "input": _bash("git stash"),
     "why": "stash in a tree holding another uncommitted change"},
    # unquoted-git-words
    {"id": "n17b", "class": "unquoted-git-words", "tool": "Bash",
     "input": _bash("grep git stash notes.md"),
     "why": "UNQUOTED words naming a forbidden command"},
    # journal-write
    {"id": "b09", "class": "journal-write", "tool": "Edit",
     "input": _edit(JOURNAL, "{}", "{\"x\": 1}"),
     "why": "hand edit of the append-only journal"},
    {"id": "b10", "class": "journal-write", "tool": "Bash",
     "input": _bash("echo '{}' >> " + JOURNAL),
     "why": "shell append to the journal",
     "decided": "deny - " + OPERATOR_DECISION + "; the edit tools already "
                "refuse the journal, and one operation gets one verdict",
     "today": _all("allow"),
     "contradicts": "the operator's decided verdict (deny), and b09: Edit of "
                    "the same journal is refused at every tier while no "
                    "PreToolUse hook refuses the shell append"},
    # manifest edits
    {"id": "b11", "class": "manifest-edit-orchestrator", "tool": "Edit",
     "input": _edit(MANIFEST, "\"title\": \"r\"", "\"title\": \"renamed\""),
     "why": "the orchestrator hand-edits the manifest"},
    {"id": "b11s", "class": "manifest-edit-subagent", "tool": "Edit",
     "input": _edit(MANIFEST, "\"title\": \"r\"", "\"title\": \"renamed\""),
     "agent_id": "agent-corpus",
     "why": "a subagent edits the manifest it is judged by"},
    # secret-read
    {"id": "b15", "class": "secret-read", "tool": "Read",
     "input": {"file_path": "{ROOT}/.env"}, "why": "read a dotenv file"},
    {"id": "b16", "class": "secret-read", "tool": "Bash",
     "input": _bash("cat .env"), "why": "shell read of a dotenv file"},
    {"id": "b19", "class": "secret-read", "tool": "Bash",
     "input": _bash("printenv"), "why": "dump the environment"},
)

# Registered matchers no row exercises, each with the reason it is outside this
# table. Keyed by the matcher string exactly as hooks.json spells it, so a
# matcher that is renamed or removed leaves a stale entry the suite reports.
OUT_OF_SCOPE_MATCHERS = {
    "Skill|Task|Agent|mcp__.*":
        "guard-capabilities grades capability use against the plan's policy, "
        "not a file or shell operation the plan gate tiers; its own suite "
        "holds that contract",
    "mcp__.*":
        "an MCP tool's operation is defined by its server, so no operation "
        "class here has an MCP spelling to compare; the edit-shaped MCP path "
        "is graded in the suites of the hooks it routes to",
}


# --- the registry: what hooks.json runs for a tool --------------------------------
def pre_tool_entries(registry):
    """[(matcher, [command, ...])] for every PreToolUse block, in file order."""
    return [(block.get("matcher", ""), [h["command"] for h in block.get("hooks", [])])
            for block in registry.get("hooks", {}).get("PreToolUse", [])]


def commands_for(tool, entries):
    """Every command registered for `tool`, in order: a matcher is a regex the
    harness fullmatches against the tool name."""
    return [cmd for matcher, cmds in entries
            if re.fullmatch(matcher, tool) for cmd in cmds]


def launcher_argv(command):
    """hooks.json's command, the plugin root substituted, as an argv."""
    return shlex.split(command.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_DIR))


def decision_of(stdout):
    """`(decision, reason)` from one hook's stdout, or raise ValueError.

    Silence is an allow - that is how every hook here says it has nothing to
    object to. Anything printed must be a decision; a hook that prints
    something else did not answer, and calling that an allow would turn a
    broken hook into a green row."""
    text = stdout.strip()
    if not text:
        return "allow", ""
    data = json.loads(text)
    out = data.get("hookSpecificOutput") or {}
    decision = out.get("permissionDecision")
    if decision in RANK:
        return decision, out.get("permissionDecisionReason", "")
    if data.get("decision") == "block":
        return "deny", data.get("reason", "")
    if not out and set(data) <= {"systemMessage", "suppressOutput", "continue"}:
        return "allow", data.get("systemMessage", "")
    raise ValueError("no decision in hook output: %r" % (text[:200],))


def combine(decisions):
    """Deny over ask over allow; no hook at all is an allow."""
    return max(decisions, key=lambda d: RANK[d]) if decisions else "allow"


# --- fixtures: one git project per tier -------------------------------------------
_GIT = ["git", "-c", "user.email=corpus@example.invalid", "-c", "user.name=corpus",
        "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _git(root, *argv):
    return subprocess.run(_GIT + list(argv), cwd=root, check=True,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def _plan(head, phase_status):
    """A manifest whose done task records `head` and whose second phase declares
    the demo hook - pending at warn, running at deny."""
    task_status = "in_progress" if phase_status == "in_progress" else "pending"
    return {"meta": {"version": 3, "developmentBranch": "main"},
            "phases": [
                {"id": "P1", "title": "done", "status": "done",
                 "tasks": [{"id": "P1.1", "title": "done", "status": "done",
                            "commit": head, "files": [DEMO]}]},
                {"id": "P2", "title": "r", "status": phase_status,
                 "tasks": [{"id": "P2.1", "title": "r", "status": task_status,
                            "files": [DEMO]}]}]}


def build_project(parent, tier):
    """A git project at `tier`'s evidence. Three commits, so HEAD~2 exists and a
    reset to it orphans the commit the manifest records."""
    root = os.path.join(parent, tier)
    os.makedirs(root)
    _git(root, "init", "-q")
    _write(root, ".gitignore", ".claude/\n")
    _write(root, "README.md", "fixture\n")
    _write(root, "notes.md", "notes\n")
    _write(root, ".env", "CLIENT_URL=https://example.invalid\n")
    _write(root, DEMO, "VERSION = 1\n")
    _write(root, OTHER_HOOK, "X = 1\n")
    _write(root, "src/app.py", "A = 1\n")
    _write(root, JOURNAL, "{}\n")
    for n in range(3):
        _write(root, "src/history.txt", "%d\n" % n)
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "c%d" % n)
    _write(root, "notes.md", "notes, edited and not committed\n")
    if tier != "observe":
        head = _git(root, "rev-parse", "HEAD")
        status = "in_progress" if tier == "deny" else "pending"
        _write(root, MANIFEST, json.dumps(_plan(head, status), indent=2) + "\n")
    return root


def fixtures():
    parent = os.path.realpath(_harness.fixture_root("audit-hooks-"))
    scratch = os.path.join(parent, "scratch")
    os.makedirs(scratch)
    _write(scratch, "msg.txt", "a message\n")
    return {"scratch": scratch,
            "projects": dict((t, build_project(parent, t)) for t in TIERS)}


# --- running a row ------------------------------------------------------------------
_BIG = "".join("VALUE_%d = %d\n" % (n, n) for n in range(120))


def _fill(value, root, scratch):
    if isinstance(value, dict):
        return dict((k, _fill(v, root, scratch)) for k, v in value.items())
    if not isinstance(value, str):
        return value
    return (value.replace("{ROOT}", root).replace("{PLUGIN}", PLUGIN_DIR)
            .replace("{TMP}", scratch).replace("{BIGCONTENT}", _BIG))


def _hook_env(root, home):
    """The caller's environment minus the session's own variables, which would
    point a hook at the real project, plus the fixture as the project."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    env["CLAUDE_PROJECT_DIR"] = root
    env["HOME"] = home
    env["USERPROFILE"] = home
    return env


def row_tiers(row):
    return tuple(CLASSES[row["class"]].get("tiers", TIERS))


def run_row(row, tier, fx, entries):
    """{"verdict", "hooks": [{"hook", "decision", "reason"}], "error"} for one
    row at one tier. `error` is set when any hook could not answer; the verdict
    is then None, never a guessed allow."""
    root = fx["projects"][tier]
    payload = {"tool_name": row["tool"],
               "tool_input": _fill(row["input"], root, fx["scratch"]),
               "session_id": "corpus-%s-%s" % (row["id"], tier),
               "cwd": root, "hook_event_name": "PreToolUse"}
    if row.get("agent_id"):
        payload["agent_id"] = row["agent_id"]
    home = os.path.join(fx["scratch"], "home-%s-%s" % (row["id"], tier))
    os.makedirs(home, exist_ok=True)
    hooks = []
    for command in commands_for(row["tool"], entries):
        argv = launcher_argv(command)
        name = argv[2] if len(argv) > 2 else command
        proc = subprocess.run(argv, input=json.dumps(payload), cwd=root,
                              env=_hook_env(root, home), capture_output=True,
                              text=True, timeout=60)
        if proc.returncode != 0:
            return {"verdict": None, "hooks": hooks,
                    "error": "%s could not run: exit %d, %s"
                             % (name, proc.returncode, proc.stderr.strip()[-300:])}
        try:
            decision, reason = decision_of(proc.stdout)
        except ValueError as exc:
            return {"verdict": None, "hooks": hooks,
                    "error": "%s could not run: %s" % (name, exc)}
        hooks.append({"hook": name, "decision": decision, "reason": reason})
    if not hooks:
        return {"verdict": None, "hooks": hooks,
                "error": "no PreToolUse hook is registered for %s" % row["tool"]}
    return {"verdict": combine([h["decision"] for h in hooks]), "hooks": hooks,
            "error": None}


def observe_all(fx, entries, rows=ROWS):
    """{(row id, tier): run_row(...)} over every row at every tier it is
    defined at. Rows run concurrently: each is one tool call with its own
    session id, so none reads another's state."""
    jobs = [(row, tier) for row in rows for tier in row_tiers(row)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda job: run_row(job[0], job[1], fx, entries),
                                jobs))
    return dict(((row["id"], tier), res) for (row, tier), res in zip(jobs, results))


# --- grading ------------------------------------------------------------------------
def recorded(row, tier):
    """The verdict this table records for `row` at `tier`: its own `today`
    while it is marked known-divergence, its class's verdict otherwise."""
    if "today" in row:
        return row["today"][tier]
    return CLASSES[row["class"]]["verdict"][tier]


def row_faults(row, observed):
    """Every tier at which `observed` disagrees with the recorded verdict, or a
    hook could not answer; empty when the row holds."""
    faults = []
    for tier in row_tiers(row):
        got = observed.get((row["id"], tier))
        if got is None:
            faults.append("%s: never run" % tier)
        elif got["error"]:
            faults.append("%s: %s" % (tier, got["error"]))
        elif got["verdict"] != recorded(row, tier):
            refusals = ["%s: %s" % (h["hook"], h["reason"][:160])
                        for h in got["hooks"] if h["decision"] != "allow"]
            faults.append("%s: recorded %s, hooks answered %s %s"
                          % (tier, recorded(row, tier), got["verdict"], refusals))
    return faults


def red_rows(rows, observed):
    return sorted(row["id"] for row in rows if row_faults(row, observed))


def flipped(row, tier):
    """`row` with its recorded verdict at `tier` changed to another verdict."""
    other = "allow" if recorded(row, tier) != "allow" else "deny"
    today = dict((t, recorded(row, t)) for t in row_tiers(row))
    today[tier] = other
    copy = dict(row)
    copy["today"] = today
    return copy


def _verdict_word(decided):
    return decided.split(" ", 1)[0]


# --- the cases ----------------------------------------------------------------------
KNOWN_DIVERGENCE = ("b02", "b03o", "b17s", "b10", "g06")
OPERATOR_DECIDED = ("b06", "b10", "g06")


def _shape_cases(check):
    ids = [row["id"] for row in ROWS]
    check("hk0a every row id is unique", len(ids) == len(set(ids)),
          sorted(i for i in ids if ids.count(i) > 1))
    check("hk0b every row names a class the table defines",
          all(row["class"] in CLASSES for row in ROWS),
          [row["id"] for row in ROWS if row["class"] not in CLASSES])
    check("hk0c every class has at least one row",
          set(CLASSES) == set(row["class"] for row in ROWS),
          sorted(set(CLASSES) - set(row["class"] for row in ROWS)))
    bad = ["%s %s" % (name, cls["verdict"]) for name, cls in sorted(CLASSES.items())
           if set(cls["verdict"]) != set(cls.get("tiers", TIERS))
           or not set(cls["verdict"].values()) <= set(RANK)]
    check("hk0d every class names one verdict for each of its tiers, from "
          "allow/ask/deny", not bad, bad)


def _unit_cases(check):
    check("hk6a silence from a hook is an allow", decision_of("")[0] == "allow")
    ask = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "ask",
                                             "permissionDecisionReason": "r"}})
    check("hk6b a permissionDecision is read as printed", decision_of(ask) == ("ask", "r"))
    ok, err = _harness.attempt(decision_of, "not json")
    check("hk6c output that is not a decision raises rather than reading as an "
          "allow", not ok, err)
    ok, err = _harness.attempt(decision_of, json.dumps({"hookSpecificOutput": {}}))
    check("hk6d a JSON object with no decision in it raises too", not ok, err)
    check("hk6e deny wins over ask and allow, ask over allow",
          combine(["allow", "deny", "ask"]) == "deny"
          and combine(["allow", "ask"]) == "ask" and combine(["allow"]) == "allow",
          [combine(["allow", "deny", "ask"]), combine(["allow", "ask"])])


def _matcher_cases(check, entries):
    tools = sorted(set(row["tool"] for row in ROWS))
    matchers = [m for m, _cmds in entries]
    check("hk5a hooks.json registers PreToolUse matchers at all", matchers, entries)
    for matcher in matchers:
        hit = [t for t in tools if re.fullmatch(matcher, t)]
        reason = OUT_OF_SCOPE_MATCHERS.get(matcher, "")
        check("hk5 PreToolUse matcher %r is exercised by a row (%s) or declared "
              "out of scope with a reason" % (matcher, ", ".join(hit) or "none"),
              bool(hit) != bool(reason.strip()),
              "exercised AND declared out of scope" if hit and reason
              else "neither exercised nor declared")
    stale = sorted(set(OUT_OF_SCOPE_MATCHERS) - set(matchers))
    check("hk5b every out-of-scope declaration names a matcher hooks.json "
          "registers", not stale, stale)


def _contract_cases(check, observed):
    for row in ROWS:
        faults = row_faults(row, observed)
        check("hk1 %s (%s, %s) gets its recorded combined verdict at %s"
              % (row["id"], row["tool"], row["class"], "/".join(row_tiers(row))),
              not faults, "; ".join(faults))

    for name in sorted(CLASSES):
        members = [row for row in ROWS if row["class"] == name and "today" not in row]
        split = {}
        for row in members:
            for tier in row_tiers(row):
                got = observed.get((row["id"], tier)) or {}
                split.setdefault(tier, set()).add(got.get("verdict"))
        want = CLASSES[name]["verdict"]
        uneven = dict((t, sorted(map(str, v))) for t, v in split.items()
                      if v != {want[t]})
        check("hk2 class %s: every unmarked row, whichever tool (%s), gets the "
              "class verdict at every tier"
              % (name, ", ".join(sorted(set(r["tool"] for r in members)))),
              members and not uneven, uneven or "no unmarked row")

    marked = sorted(row["id"] for row in ROWS if "today" in row)
    check("hk2a the rows marked known-divergence are exactly %s"
          % ", ".join(sorted(KNOWN_DIVERGENCE)),
          marked == sorted(KNOWN_DIVERGENCE), marked)
    for row in ROWS:
        if "today" not in row:
            continue
        cls = CLASSES[row["class"]]
        differs = [t for t in row_tiers(row) if row["today"][t] != cls["verdict"][t]]
        twins = [r["id"] for r in ROWS if r["class"] == row["class"]
                 and r["tool"] != row["tool"] and "today" not in r]
        check("hk2b %s is marked known-divergence with a basis, differs from its "
              "class at %s, and has a twin of another tool that holds the "
              "class verdict (%s)"
              % (row["id"], "/".join(differs) or "no tier",
                 ", ".join(twins) or "none"),
              differs and row.get("contradicts", "").strip() and twins,
              "a mark that agrees with its class outlived its fix" if not differs
              else "no basis" if not row.get("contradicts", "").strip()
              else "no twin")


def _decision_cases(check):
    decided = sorted(row["id"] for row in ROWS if "decided" in row)
    check("hk3a exactly %s carry an operator-decided verdict"
          % ", ".join(OPERATOR_DECIDED), decided == sorted(OPERATOR_DECIDED), decided)
    for row in ROWS:
        if "decided" not in row:
            continue
        word = _verdict_word(row["decided"])
        cls = CLASSES[row["class"]]["verdict"]
        check("hk3 %s's decided verdict (%s) is dated, names who decided, and is "
              "its class's verdict at every tier" % (row["id"], word),
              word in RANK and re.search(r"\b\d{4}-\d{2}-\d{2}\b", row["decided"])
              and OPERATOR_DECISION in row["decided"]
              and all(cls[t] == word for t in row_tiers(row)),
              row["decided"])


def _flip_cases(check, observed):
    baseline = red_rows(ROWS, observed)
    for row in ROWS:
        outcomes = []
        for tier in row_tiers(row):
            rows = [flipped(r, tier) if r is row else r for r in ROWS]
            outcomes.append((tier, red_rows(rows, observed)))
        check("hk4 flipping %s's recorded verdict at any one tier turns exactly "
              "%s red" % (row["id"], row["id"]),
              row["id"] not in baseline
              and all(red == sorted(set(baseline) | {row["id"]})
                      for _tier, red in outcomes),
              outcomes)


def _cases(check):
    _shape_cases(check)
    _unit_cases(check)
    with open(HOOKS_JSON, encoding="utf-8") as fh:
        entries = pre_tool_entries(json.load(fh))
    _matcher_cases(check, entries)
    _decision_cases(check)
    fx = fixtures()
    observed = observe_all(fx, entries)
    _contract_cases(check, observed)
    _flip_cases(check, observed)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_hooks.py --selftest\n")
    raise SystemExit(2)
