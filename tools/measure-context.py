#!/usr/bin/env python3
"""Measure the prose each step of the audit pipeline loads before it does any work,
at a git ref or in a plugin tree.

WHY THIS EXISTS. A recorded pipeline run says what a run COST; it cannot say what the
plugin will make the next run read, because a recording is fixed at the commit it ran.
This answers the static half: for each entry on the pipeline's real path it lists the
files that load before the first useful action, with their sizes, so a change to the
prose can be priced before anyone pays for a run - and so the figure that rotted in a
document can be re-derived by a command instead.

WHAT "LOADED" MEANS HERE, rule by rule:

  * a COMMAND loads its body (the frontmatter is metadata, not prompt) and every file
    named as `${CLAUDE_PLUGIN_ROOT}/<path>` in the first paragraph of the body that
    tells the model to Read such a file and says `first`. Later paragraphs are a
    subcommand's own instructions or a conditional read ("only if the human asks"),
    and a mention without that prefix is a cross-reference - neither is counted;
  * an AGENT loads its body (its system prompt), the body of every skill its
    frontmatter preloads under `skills:`, and the project's CLAUDE.md;
  * ALWAYS ON, in every session where the plugin is enabled: the listing - the name
    and description (and a skill's `when_to_use`) of every command, agent and skill -
    and the project's CLAUDE.md. A command or skill whose frontmatter sets
    `disable-model-invocation: true` is left out of the listing and counted as
    withheld: the skills documentation's table gives that flag "Description not in
    context" (quoted in docs/research/token-efficiency-audit.md, the R4 section).

CLAUDE.md is the PROJECT's file, not the plugin's, so it is measured only when one is
handed over with `--claude-md`; without it the report says it is not measured rather
than counting it as nothing. The per-task part of a step - a brief, a hand-back, a
tool result - is not prose the plugin ships and is not measured here; a recorded
session's `tools/stream-cost.py` reading is where those appear.

BYTES ARE MEASURED; TOKENS ARE AN ESTIMATE, bytes divided by `--bytes-per-token` (the
conventional 4 unless given), and every token column says so. Markdown full of code
spans tokenizes denser than prose, so the default understates; a recorded session's
cache writes against the bytes that produced them are the calibration, and
`tools/stream-cost.py` prints that ratio per write.

SECTIONS. `--sections` cuts each file `/audit:run` reads first into sections - a
heading and the lines up to the next, or a declared line range for a file that is one
heading - and sums them by the four classes the design document sorts them into
(`SECTION_CLASSES`). A section the table does not name is printed `unclassified`, and
a copy whose headings or line count no longer match the table says so, so a stale
table reads as a gap rather than as a smaller class.

Usage:  python3 tools/measure-context.py --ref v3.1.0 --ref main [--claude-md FILE] [--json]
        python3 tools/measure-context.py --ref <ref> --sections
        python3 tools/measure-context.py --tree <plugin root> [--claude-md FILE]
        python3 tools/measure-context.py --gate [--ref <ref> | --tree <plugin root>]
        python3 tools/measure-context.py --selftest
Exit codes: 0 measured, or under --gate every entry within its ceiling - 1 a file a
step loads is missing at that ref, or under --gate a breach - 2 usage error or a ref
that does not resolve.

THE GATE. `--gate` holds `ENTRY_CEILINGS` - the pipeline-cost design's ceilings on
what each pipeline entry loads before any work - and `AGENT_CEILINGS`, reading the
same `total` line the report prints, so the gate and the measurement cannot measure
two different things. A gated command that reads a file under `reference/` first, or
names one anywhere in its body (a `see reference/...` pointer), breaches whatever its
size: no pipeline command makes the main loop read reference prose, and this is the
check that holds it. A command outside the pipeline is not gated and may point there.
CI and `tools/verify.sh` run it.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
PLUGIN_REL = "plugins/audit"
DEFAULT_BYTES_PER_TOKEN = 4.0
ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}/"

# The pipeline's real path: the commands that run work and the agents they dispatch,
# and the planning verbs a session calls before it runs anything. Sign-off is measured
# through the command that re-runs it on its own, so the phase run form at sign-off is
# the run form plus whatever that command reads first which the run form has not.
# A verb entry measures what its command loads, by the up-front rule below: while a
# command reads the same files whatever its verb, its verb entries equal it, and they
# part only when the reads do.
SIGNOFF_COMMAND = "commands/review.md"
PIPELINE = (
    ("/audit:run", "command", "commands/run.md"),
    ("/audit:next", "command", "commands/next.md"),
    ("/audit:resume", "command", "commands/resume.md"),
    ("/audit:phase", "command", "commands/phase.md"),
    ("/audit:phase add", "command", "commands/phase.md"),
    ("/audit:task add", "command", "commands/task.md"),
    ("/audit:phase run form, before sign-off", "command", "commands/phase.md"),
    ("/audit:phase run form, at sign-off", "at sign-off", "commands/phase.md"),
    ("sign-off (/audit:review)", "command", SIGNOFF_COMMAND),
    ("executor", "agent", "agents/audit-executor.md"),
    ("reviewer", "agent", "agents/audit-reviewer.md"),
)
# The most bytes each agent's start may load. An agent's start is written once and read
# by every request that agent makes, so a sentence added there is paid per request; the
# ceiling is the design document's target for the trimmed prompts, whose procedure
# moved into `drive-phase.py submit`. `mc19` in this file's selftest holds the shipped
# tree under it, so a prompt that grows past one fails the sweep rather than a review.
# The prompt is the one lever on an agent's start taken. Leaving out the project's
# CLAUDE.md saves cents and drops the rules the benchmark found separate a run that
# breaks things from one that does not; preloading skills writes the same content the
# first request's Skill call does and saves no request, and a plugin agent cannot know a
# project's skills; a longer agent cache bridges nothing between requests seconds apart
# and raises every agent write's rate (docs/research/pipeline-cost-design.md prices each).
AGENT_CEILINGS = {"executor": 9000, "reviewer": 7000}
# The most bytes each pipeline entry may load before any work - its command body
# plus every file it reads first, the same `total` line the report prints - from the
# pipeline-cost design's T2 table. The main loop is the dearest place in the pipeline
# to hold a byte, because every one of its requests reads it again, so these are
# small: a command body is the step driver's loop and the verb's own section, and
# the rule each step needs is printed by the driver at that step. A gated entry that
# reads a file under `reference/` first, or names one in its body, breaches whatever
# its size, since that read is the cost this ceiling exists to keep out; `--gate` exits 1 on any breach, and
# `mc24` holds the shipped tree under it in the sweep.
ENTRY_CEILINGS = (
    ("/audit:phase run form, before sign-off", 4000),
    ("/audit:phase add", 8000),
    ("/audit:task add", 8000),
    ("/audit:run", 4000),
    ("/audit:next", 4000),
    ("/audit:resume", 4000),
    ("sign-off (/audit:review)", 6000),
)
REFERENCE_DIR = "reference/"
# The entries that run work.
RUN_ENTRIES = ("/audit:run", "/audit:next", "/audit:resume", "/audit:phase",
               "/audit:phase run form, before sign-off", "/audit:phase run form, at sign-off",
               "sign-off (/audit:review)")

# --- the section classes ---------------------------------------------------------
# Each section of a reference file the run reads first, sorted into one of four classes
# by docs/research/pipeline-cost-design.md, where it cuts reference prose by section:
# `keep` is always read, `conditional` is read when its condition holds, `elsewhere`
# belongs to another command or to sign-off, `maintainer` explains what a script
# enforces. A section is a heading of
# one to three `#` with every line up to the next one; a file that is one heading is
# classed by line ranges instead, declared for the line count they were cut at.
SECTION_CLASS_NAMES = ("keep", "conditional", "elsewhere", "maintainer")
SECTION_CLASSES = {
    "reference/orchestrator.md": {"headings": {
        "Audit orchestrator — shared execution logic": "keep",
        "At a glance": "keep",
        "Preflight": "keep",
        "Non-negotiable guardrails": "keep",
        "Readiness rule": "conditional",
        "Concurrency lock": "keep",
        "Branch-per-phase": "elsewhere",
        "Keeping a failed run's record (audit-state commits)": "conditional",
        "ADO echo (best-effort, linked items only)": "conditional",
        "Answering one question about the trail": "conditional",
        "The third place": "elsewhere",
        "What a red full run teaches": "elsewhere",
        "Quarantine: `meta.muted`": "elsewhere",
        "Resume after interruption": "elsewhere",
        "Progress output": "keep",
        "Dry-run / preview": "conditional",
        "Reporting": "keep"}},
    "reference/manifest-conventions.md": {"headings": {
        "Manifest conventions": "keep",
        "Locating the manifest": "keep",
        "Edit-and-revalidate rule": "keep",
        "Concurrency lock": "keep",
        "ID allocation": "elsewhere",
        "Status enums": "keep",
        "New task template": "elsewhere",
        "New phase template": "elsewhere",
        "Phase priority (`phase.priority`)": "elsewhere",
        "Areas (`meta.areas`)": "keep",
        "Proposals (parked phases)": "elsewhere",
        "Decisions (`decisions[]`)": "conditional",
        "Task outputs (`task.outputs`)": "keep",
        "fileIndex maintenance": "keep",
        "Immutable history": "keep",
        "Moving a task (`/audit:task move`)": "elsewhere",
        "The operator's words go in unchanged": "keep",
        "Tamper evidence and completion records": "maintainer"}},
    "reference/execute-task.md": {"lines": 714, "ranges": (
        (1, 383, "keep"), (384, 447, "conditional"), (448, 455, "keep"),
        (456, 483, "conditional"), (484, 507, "keep"), (508, 571, "maintainer"),
        (572, 599, "conditional"), (600, 638, "maintainer"), (639, 670, "keep"),
        (671, 690, "conditional"), (691, 701, "keep"), (702, 712, "conditional"),
        (713, 714, "keep"))},
}
_HEADING_RE = re.compile(r"^#{1,3} ")

_READ_RE = re.compile(r"\bRead\s+`" + re.escape(ROOT_VAR))
_FIRST_RE = re.compile(r"\bfirst\b", re.IGNORECASE)
_ROOTED_RE = re.compile(r"`" + re.escape(ROOT_VAR) + r"([^`]+)`")
# A reference path a body names anywhere, rooted or bare: the shape a `see ...`
# pointer takes, which the up-front rule above does not count as a read.
_POINTER_RE = re.compile(r"\breference/[\w./-]*\w")


# --- where the files come from ---------------------------------------------------
def _git(args):
    proc = subprocess.run(["git", "-C", REPO] + args, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout


def git_source(ref):
    """(source, problem). A source reads plugin-relative paths at `ref`; `problem` is
    why the ref cannot be read, and then the source is None."""
    code, out = _git(["rev-parse", "--verify", "-q", "%s^{commit}" % ref])
    if code != 0:
        return None, "ref %r does not resolve to a commit in this repository" % ref
    sha = out.decode("ascii").strip()
    code, out = _git(["ls-tree", "-r", "--name-only", sha, PLUGIN_REL + "/"])
    if code != 0:
        return None, "ref %r has no %s tree" % (ref, PLUGIN_REL)
    names = set(line[len(PLUGIN_REL) + 1:] for line in out.decode("utf-8").splitlines())

    def read(rel):
        if rel not in names:
            return None
        got, data = _git(["show", "%s:%s/%s" % (sha, PLUGIN_REL, rel)])
        return data if got == 0 else None
    return {"label": "%s (%s)" % (ref, sha[:12]), "read": read,
            "names": sorted(names)}, None


def tree_source(root):
    """A source over a plugin root on disk - an export, or a fixture."""
    names = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            names.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))

    def read(rel):
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()
    return {"label": "tree %s" % os.path.basename(os.path.normpath(root)), "read": read,
            "names": sorted(names)}


# --- line endings ------------------------------------------------------------------
# Every size above is a count of the bytes a checkout wrote, and a checkout under
# core.autocrlf=true writes CRLF for any text file whose attributes do not say eol=lf:
# one extra byte per line, enough to carry an entry over its ceiling on windows-latest
# alone. So the measurement is only platform-free while every tracked text file
# resolves to eol=lf, and this asks git - not a list of extensions - which do not.
def parse_ls_files_eol(raw):
    """`[(index_eol, attributes, path)]` from `git ls-files --eol -z` output. The
    attribute column may hold spaces (`text=auto eol=lf`); the path follows a tab."""
    rows = []
    for entry in raw.decode("utf-8", "replace").split("\0"):
        if "\t" not in entry:
            continue
        head, path = entry.split("\t", 1)
        fields = head.split()
        index_eol = fields[0][len("i/"):] if fields and fields[0].startswith("i/") else ""
        attrs = head[head.index("attr/") + len("attr/"):].strip() if "attr/" in head else ""
        rows.append((index_eol, attrs, path))
    return rows


def _checks_out_unchanged(attrs):
    """True when a checkout writes this file's bytes as the index holds them: eol=lf
    pins the ending, and -text turns conversion off altogether."""
    words = attrs.split()
    return "eol=lf" in words or "-text" in words


def unpinned_text_files(rows):
    """The paths git holds as text whose attributes leave the checkout's line endings
    to core.autocrlf. A file git detected as binary (`-text` in the index column) is
    never converted, so it is never one of them."""
    return sorted(path for index_eol, attrs, path in rows
                  if index_eol != "-text" and not _checks_out_unchanged(attrs))


def tracked_eol(root):
    """`(rows, problem)` for the repository at `root`; `problem` names why git could
    not answer, and then `rows` is None rather than an empty, all-clear list."""
    proc = subprocess.run(["git", "-C", root, "ls-files", "--eol", "-z"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return None, "git ls-files --eol exited %d: %s" % (
            proc.returncode, proc.stderr.decode("utf-8", "replace").strip())
    return parse_ls_files_eol(proc.stdout), None


# --- reading one markdown file ----------------------------------------------------
def split_frontmatter(data):
    """(fields, body bytes). Only the keys this tool reads are parsed, and only in the
    shapes the plugin writes them: `key: value`, quoted or not, and a list either as
    `[a, b]` or as indented `- a` lines."""
    text = data.decode("utf-8")
    if not text.startswith("---"):
        return {}, data
    end = text.find("\n---", 3)
    if end < 0:
        return {}, data
    head, rest = text[3:end], text[end + 4:]
    # The closing delimiter's own line ending belongs to the frontmatter, whichever of
    # the two a checkout wrote; only what follows it is the body.
    if rest.startswith("\r\n"):
        body = rest[2:]
    elif rest.startswith("\n"):
        body = rest[1:]
    else:
        body = rest
    fields, key = {}, None
    for line in head.splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key is not None:
            fields.setdefault(key, [])
            if isinstance(fields[key], list):
                fields[key].append(_unquote(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            fields[key] = [_unquote(v) for v in value[1:-1].split(",") if v.strip()]
        elif value:
            fields[key] = _unquote(value)
    return fields, body.encode("utf-8")


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value


def first_reads(body):
    """The plugin-relative paths a command body tells the model to read up front."""
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    for paragraph in re.split(r"\n\s*\n", text):
        if _READ_RE.search(paragraph) and _FIRST_RE.search(paragraph):
            seen = []
            for rel in _ROOTED_RE.findall(paragraph):
                if rel not in seen:
                    seen.append(rel)
            return seen
    return []


def reference_pointers(body):
    """Every reference path a command body names, in first-seen order. A model
    handed `see reference/x.md` reads it as often as not, so a pointer costs the
    main loop what a read does, and the up-front rule cannot see one."""
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    seen = []
    for rel in _POINTER_RE.findall(text):
        if rel not in seen:
            seen.append(rel)
    return seen


# --- what each step loads ----------------------------------------------------------
def _row(part, rel, data):
    return {"part": part, "path": rel, "bytes": None if data is None else len(data)}


def entry_rows(source, kind, rel, claude_md):
    """The rows one pipeline entry loads, in order. A row whose file is missing at the
    source has `bytes` None - reported as missing, never as zero."""
    data = source["read"](rel)
    if data is None:
        return [_row("definition", rel, None)]
    fields, body = split_frontmatter(data)
    if kind in ("command", "at sign-off"):
        rows = [_row("command body", rel, body)]
        rows.extend(_row("read first", path, source["read"](path)) for path in first_reads(body))
        if kind == "at sign-off":
            loaded = set(r["path"] for r in rows)
            signoff = source["read"](SIGNOFF_COMMAND)
            if signoff is None:
                return rows + [_row("read at sign-off", SIGNOFF_COMMAND, None)]
            rows.extend(_row("read at sign-off", path, source["read"](path))
                        for path in first_reads(split_frontmatter(signoff)[1])
                        if path not in loaded)
        return rows
    rows = [_row("system prompt", rel, body)]
    skills = fields.get("skills") or []
    for name in skills if isinstance(skills, list) else [skills]:
        skill_rel = "skills/%s/SKILL.md" % name
        skill = source["read"](skill_rel)
        rows.append(_row("preloaded skill", skill_rel,
                         None if skill is None else split_frontmatter(skill)[1]))
    if claude_md is not None:
        rows.append({"part": "CLAUDE.md", "path": claude_md["name"],
                     "bytes": claude_md["bytes"]})
    return rows


def _model_invocable(kind, fields):
    """False for a command or skill the model cannot invoke, whose description the
    host keeps out of context. Agents carry no such flag."""
    if kind == "agents":
        return True
    flag = fields.get("disable-model-invocation")
    return not (isinstance(flag, str) and flag.strip().lower() == "true")


def listing(source):
    """{"commands": n, "agents": n, "skills": n, "bytes": n, "withheld": n} - what the
    plugin adds to every session's listing: name and description of each, and a
    skill's `when_to_use`. `withheld` counts the commands and skills left out because
    the model cannot invoke them, so a smaller figure says why it is smaller."""
    counts = {"commands": 0, "agents": 0, "skills": 0, "bytes": 0, "withheld": 0}
    for rel in source["names"]:
        parts = rel.split("/")
        if len(parts) == 2 and parts[0] == "commands" and parts[1].endswith(".md"):
            kind, name = "commands", "audit:" + parts[1][:-3]
        elif len(parts) == 2 and parts[0] == "agents" and parts[1].endswith(".md"):
            kind, name = "agents", None
        elif len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
            kind, name = "skills", None
        else:
            continue
        fields, _body = split_frontmatter(source["read"](rel) or b"")
        if not _model_invocable(kind, fields):
            counts["withheld"] += 1
            continue
        name = fields.get("name") or name or parts[1]
        text = name + (fields.get("description") or "") + (fields.get("when_to_use") or "")
        counts[kind] += 1
        counts["bytes"] += len(text.encode("utf-8"))
    return counts


def measure(source, claude_md=None):
    """Everything one source loads, by entry, plus the always-on part."""
    entries = []
    for label, kind, rel in PIPELINE:
        rows = entry_rows(source, kind, rel, claude_md)
        known = [r["bytes"] for r in rows if r["bytes"] is not None]
        loaded = set(r["path"] for r in rows)
        data = source["read"](rel) if kind != "agent" else None
        pointers = [p for p in reference_pointers(split_frontmatter(data)[1])
                    if p not in loaded] if data is not None else []
        entries.append({"entry": label, "rows": rows, "bytes": sum(known),
                        "missing": [r["path"] for r in rows if r["bytes"] is None],
                        "pointers": pointers})
    return {"label": source["label"], "entries": entries, "listing": listing(source),
            "claudeMd": claude_md}


def ceiling_breaches(measured):
    """`[(entry, bytes, ceiling), ...]` - every agent whose start loads more than
    `AGENT_CEILINGS` allows, or loads a file that is missing. Empty is the one
    answer that holds; an agent the measurement lacks is a breach, never a pass."""
    found = dict((e["entry"], e) for e in measured["entries"])
    out = []
    for name in sorted(AGENT_CEILINGS):
        entry = found.get(name)
        if entry is None or entry["missing"] or entry["bytes"] > AGENT_CEILINGS[name]:
            out.append((name, None if entry is None else entry["bytes"],
                        AGENT_CEILINGS[name]))
    return out


def entry_ceiling_breaches(measured):
    """`[(entry, bytes, ceiling, why), ...]` - every gated pipeline entry that
    loads more than `ENTRY_CEILINGS` allows, reads a reference file first, names
    one in its body, or loads a file that is missing. An entry the measurement lacks is a breach,
    never a pass; empty is the one answer that holds."""
    found = dict((e["entry"], e) for e in measured["entries"])
    out = []
    for name, ceiling in ENTRY_CEILINGS:
        entry = found.get(name)
        if entry is None:
            out.append((name, None, ceiling, "not measured"))
            continue
        why = []
        if entry["missing"]:
            why.append("loads %s, which is missing" % ", ".join(entry["missing"]))
        reads = [r["path"] for r in entry["rows"] if r["part"] != "command body"
                 and r["path"].startswith(REFERENCE_DIR)]
        if reads:
            why.append("reads %s first" % ", ".join(reads))
        if entry.get("pointers"):
            why.append("names %s in its body" % ", ".join(entry["pointers"]))
        if entry["bytes"] > ceiling:
            why.append("%d bytes, over a ceiling of %d" % (entry["bytes"], ceiling))
        if why:
            out.append((name, entry["bytes"], ceiling, "; ".join(why)))
    return out


def gate_breaches(measured):
    """What `--gate` refuses: every pipeline entry past its T2 ceiling and every
    agent start past its own, as `(entry, bytes, ceiling, why)`."""
    agents = [(name, size, ceiling, "the agent's start is %s bytes, over %d"
               % ("missing" if size is None else size, ceiling))
              for name, size, ceiling in ceiling_breaches(measured)]
    return entry_ceiling_breaches(measured) + agents


def render_gate(measured, breaches):
    """The gate's own report: each gated entry against its ceiling, then the
    verdict naming every breach."""
    found = dict((e["entry"], e) for e in measured["entries"])
    lines = ["measure-context --gate over %s [bytes: what the entry loads before any "
             "work, against its ceiling]" % (measured["label"],)]
    for name, ceiling in list(ENTRY_CEILINGS) + sorted(AGENT_CEILINGS.items()):
        entry = found.get(name)
        lines.append("  %-42s %8s / %d" % (name, "-" if entry is None
                                            else entry["bytes"], ceiling))
    if not breaches:
        lines.append("GATE OK: every entry within its ceiling, and no gated command "
                     "reads or names a reference file")
    for name, _size, _ceiling, why in breaches:
        lines.append("BREACH %s: %s" % (name, why))
    return "\n".join(lines)


def file_sections(rel, data):
    """[(section, class, bytes)] for one file under SECTION_CLASSES, and a problem or
    None. Each line counts with its newline, the empty one after a final newline
    included, so a file's sections sum to one byte more than its size when it ends in
    one - the expression the classification was taken with. A section the table does
    not class is `unclassified`, never dropped."""
    lines = data.decode("utf-8").split("\n")
    spec = SECTION_CLASSES.get(rel) or {}

    def size(a, b):
        return sum(len(line.encode("utf-8")) + 1 for line in lines[a:b])
    if "ranges" in spec:
        if len(lines) != spec["lines"]:
            return ([("lines 1-%d" % len(lines), "unclassified", size(0, len(lines)))],
                    "line ranges declared for %d lines, and this copy has %d: not applied"
                    % (spec["lines"], len(lines)))
        return [("lines %d-%d" % (a, z), kind, size(a - 1, z))
                for a, z, kind in spec["ranges"]], None
    heads = [i for i, line in enumerate(lines) if _HEADING_RE.match(line)]
    named = spec.get("headings") or {}
    out = []
    if not heads or heads[0] > 0:
        out.append(("(before the first heading)", "unclassified",
                    size(0, heads[0] if heads else len(lines))))
    for k, i in enumerate(heads):
        title = lines[i].lstrip("#").strip()
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        out.append((title, named.get(title, "unclassified"), size(i, end)))
    missing = [t for t in named if t not in set(s[0] for s in out)]
    problem = ("classed headings not in this copy: %s" % ", ".join(missing)) if missing else None
    return out, problem


def sections(source, entry="/audit:run"):
    """{"entry", "files": [{path, rows, sums, problem, bytes}], "sums"} - every file
    `entry` reads first, cut into sections and summed by class."""
    label, kind, rel = next(p for p in PIPELINE if p[0] == entry)
    files, sums = [], dict((k, 0) for k in SECTION_CLASS_NAMES + ("unclassified",))
    for row in entry_rows(source, kind, rel, None):
        if row["part"] not in ("read first", "read at sign-off"):
            continue
        data = source["read"](row["path"])
        if data is None:
            files.append({"path": row["path"], "rows": [], "sums": {}, "bytes": None,
                          "problem": "not there"})
            continue
        rows, problem = file_sections(row["path"], data)
        mine = dict((k, 0) for k in sums)
        for _title, kind_of, size in rows:
            mine[kind_of] += size
            sums[kind_of] += size
        files.append({"path": row["path"], "rows": rows, "sums": mine, "bytes": len(data),
                      "problem": problem})
    return {"entry": label, "files": files, "sums": sums}


def render_sections(label, cut, per):
    names = SECTION_CLASS_NAMES + ("unclassified",)
    lines = ["", "== %s: %s reads first, by section [bytes; each line with its newline]"
             % (label, cut["entry"])]
    for item in cut["files"]:
        if item["bytes"] is None:
            lines.append("  %s: MISSING" % item["path"])
            continue
        lines.append("  %s (%d bytes)" % (item["path"], item["bytes"]))
        for title, kind, size in item["rows"]:
            lines.append("    %-12s %8d  %s" % (kind, size, title))
        if item["problem"]:
            lines.append("    NOTE: %s" % item["problem"])
        lines.append("    %s" % "  ".join("%s %d" % (k, item["sums"][k]) for k in names))
    whole = sum(cut["sums"].values())
    lines.append("  class sums: %s  total %d (~%d tok)"
                 % ("  ".join("%s %d" % (k, cut["sums"][k]) for k in names), whole,
                    _tok(whole, per)))
    return lines


def contributors(measured):
    """{path: {"bytes": n, "loadedBy": [entry, ...]}} - each file once."""
    out = {}
    for entry in measured["entries"]:
        for row in entry["rows"]:
            if row["bytes"] is None or row["part"] == "CLAUDE.md":
                continue
            slot = out.setdefault(row["path"], {"bytes": row["bytes"], "loadedBy": []})
            if entry["entry"] not in slot["loadedBy"]:
                slot["loadedBy"].append(entry["entry"])
    return out


# --- rendering ----------------------------------------------------------------------
def _tok(size, per):
    return int(round(size / per))


def render(measured_list, per, top):
    lines = ["measure-context [bytes measured; ~tok = bytes / %g, an estimate]" % per]
    for measured in measured_list:
        lines.append("")
        lines.append("== %s" % measured["label"])
        lst = measured["listing"]
        lines.append("always on, every session where the plugin is enabled:")
        lines.append("  %-26s %-40s %8d %8s"
                     % ("listing", "%d commands, %d agents, %d skills"
                        % (lst["commands"], lst["agents"], lst["skills"]),
                        lst["bytes"], "~%d" % _tok(lst["bytes"], per)))
        lines.append("  %-26s %d command(s) or skill(s) set disable-model-invocation: "
                     "not in the listing" % ("", lst["withheld"]))
        cmd = measured["claudeMd"]
        if cmd is None:
            lines.append("  %-26s not measured: it is the project's file - pass --claude-md"
                         % "CLAUDE.md")
        else:
            lines.append("  %-26s %-40s %8d %8s" % ("CLAUDE.md", cmd["name"], cmd["bytes"],
                                                   "~%d" % _tok(cmd["bytes"], per)))
        lines.append("per entry, before any work:")
        for entry in measured["entries"]:
            lines.append("  %s" % entry["entry"])
            for row in entry["rows"]:
                size = row["bytes"]
                lines.append("    %-24s %-40s %8s %8s"
                             % (row["part"], row["path"],
                                "MISSING" if size is None else "%d" % size,
                                "" if size is None else "~%d" % _tok(size, per)))
            lines.append("    %-24s %-40s %8d %8s" % ("total", "", entry["bytes"],
                                                     "~%d" % _tok(entry["bytes"], per)))
    lines.append("")
    lines.extend(_compare(measured_list, per, top))
    return "\n".join(lines)


def _compare(measured_list, per, top):
    tables = [contributors(m) for m in measured_list]
    paths = sorted(set(p for t in tables for p in t),
                   key=lambda p: (-max(t.get(p, {}).get("bytes", 0) for t in tables), p))
    head = "  %-34s" % "file" + "".join(" %12s" % m["label"].split(" ")[0]
                                         for m in measured_list)
    if len(measured_list) == 2:
        head += " %9s" % "delta"
    lines = ["largest contributors, each file once [bytes]:", head + "  loaded by"]
    for path in paths[:top]:
        sizes = [t.get(path, {}).get("bytes") for t in tables]
        line = "  %-34s" % path + "".join(" %12s" % ("-" if s is None else s) for s in sizes)
        if len(sizes) == 2:
            line += " %+9d" % ((sizes[1] or 0) - (sizes[0] or 0))
        owners = []
        for t in tables:
            for name in t.get(path, {}).get("loadedBy", []):
                if name not in owners:
                    owners.append(name)
        lines.append(line + "  " + ", ".join(owners))
    return lines


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", action="append", default=[],
                    help="a git ref to measure; repeat to compare")
    ap.add_argument("--tree", help="a plugin root on disk to measure instead of a ref")
    ap.add_argument("--claude-md", help="the project's CLAUDE.md, counted where it loads")
    ap.add_argument("--bytes-per-token", type=float, default=DEFAULT_BYTES_PER_TOKEN)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--sections", action="store_true",
                    help="also cut each file /audit:run reads first into sections, summed "
                         "by class")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 when an entry passes its ceiling or a gated command "
                         "reads or names a reference file; with no --ref or --tree, "
                         "measures this repository's plugin tree")
    args = ap.parse_args(argv)
    if args.gate and not args.ref and not args.tree:
        args.tree = os.path.join(REPO, PLUGIN_REL)
    if not args.ref and not args.tree:
        print("measure-context: name what to measure: --ref <ref> (repeatable) or "
              "--tree <plugin root>", file=sys.stderr)
        return 2
    if args.bytes_per_token <= 0:
        print("measure-context: --bytes-per-token must be positive", file=sys.stderr)
        return 2
    claude_md = None
    if args.claude_md:
        try:
            with open(args.claude_md, "rb") as fh:
                claude_md = {"name": os.path.basename(args.claude_md), "bytes": len(fh.read())}
        except OSError as exc:
            print("measure-context: cannot read --claude-md: %s" % exc, file=sys.stderr)
            return 2
    sources = []
    for ref in args.ref:
        source, problem = git_source(ref)
        if problem:
            print("measure-context: %s" % problem, file=sys.stderr)
            return 2
        sources.append(source)
    if args.tree:
        if not os.path.isdir(args.tree):
            print("measure-context: --tree is not a directory", file=sys.stderr)
            return 2
        sources.append(tree_source(args.tree))
    measured = [measure(s, claude_md) for s in sources]
    if args.gate:
        breached = False
        for one in measured:
            breaches = gate_breaches(one)
            breached = breached or bool(breaches)
            print(render_gate(one, breaches))
        return 1 if breached else 0
    cuts = [sections(s) for s in sources] if args.sections else []
    if args.as_json:
        shown = {"bytesPerToken": args.bytes_per_token, "measured": measured,
                 "contributors": [contributors(m) for m in measured]}
        if cuts:
            shown["sections"] = cuts
        print(json.dumps(shown, indent=2, sort_keys=True))
    else:
        text = render(measured, args.bytes_per_token, args.top)
        for source, cut in zip(sources, cuts):
            text += "\n" + "\n".join(render_sections(source["label"], cut,
                                                     args.bytes_per_token))
        print(text)
    missing = [(m["label"], e["entry"], p) for m in measured for e in m["entries"]
               for p in e["missing"]]
    for label, entry, path in missing:
        print("measure-context: %s: %s loads %s, which is not there" % (label, entry, path),
              file=sys.stderr)
    return 1 if missing else 0


# --- selftest ------------------------------------------------------------------
_FX_ROOT = "${CLAUDE_PLUGIN_ROOT}/"


def _fx_write(root, rel, text):
    path = os.path.join(root, rel.replace("/", os.sep))
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    # newline="" writes the bytes the size below counts: a text-mode default turns
    # every "\n" into "\r\n" on Windows, and the reader measures the file in binary.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def _fx_plugin(root, executor_skills=True):
    """A plugin tree whose every size is known. `run.md` names four reference files in
    four different ways, and only the first two are an up-front read."""
    sizes = {}
    body = ("# run\n\nRead `%sreference/a.md` and `%sreference/b.md` first - it never "
            "signs off, so it does not read `reference/c.md`.\n\nLater: Read `%sreference/d.md` "
            "first when a tracker is configured.\n" % (_FX_ROOT, _FX_ROOT, _FX_ROOT))
    _fx_write(root, "commands/run.md", "---\ndescription: 'Run one task.'\n"
              "argument-hint: '<id>'\n---\n" + body)
    sizes["run body"] = len(body.encode("utf-8"))
    for name, text in (("a", "A" * 1000), ("b", "B" * 300), ("c", "C" * 5000),
                       ("d", "D" * 7000)):
        sizes[name] = _fx_write(root, "reference/%s.md" % name, text)
    # A conditional read placed BEFORE the up-front one: a rule that took the first Read
    # paragraph without asking for `first` would load `c.md` here instead of `a.md`.
    _fx_write(root, "commands/next.md",
              "---\ndescription: x\n---\nRead `%sreference/c.md` only if the human asks."
              "\n\nRead `%sreference/a.md` first.\n" % (_FX_ROOT, _FX_ROOT))
    # The phase run form reads `a.md` first and sign-off reads `a.md` and `s.md`: at
    # sign-off the run form adds `s.md` alone, since `a.md` is already loaded.
    _fx_write(root, "commands/phase.md", "---\ndescription: x\n---\nRead `%sreference/a.md` "
              "first.\n" % _FX_ROOT)
    _fx_write(root, "commands/review.md", "---\ndescription: x\n---\nRead `%sreference/s.md` "
              "and `%sreference/a.md` first.\n" % (_FX_ROOT, _FX_ROOT))
    sizes["s"] = _fx_write(root, "reference/s.md", "S" * 900)
    task_body = "# task\n\nRead `%sreference/b.md` FIRST.\n" % _FX_ROOT
    _fx_write(root, "commands/task.md", "---\ndescription: x\n---\n" + task_body)
    sizes["task body"] = len(task_body.encode("utf-8"))
    agent_body = "You execute one task.\n"
    head = "---\nname: audit-executor\ndescription: 'Executes.'\n"
    if executor_skills:
        head += "skills:\n  - house-style\n"
    _fx_write(root, "agents/audit-executor.md", head + "---\n" + agent_body)
    sizes["executor body"] = len(agent_body.encode("utf-8"))
    _fx_write(root, "agents/audit-reviewer.md",
              "---\nname: audit-reviewer\ndescription: Reviews.\n---\nReview.\n")
    skill_body = "Write it this way.\n"
    _fx_write(root, "skills/house-style/SKILL.md",
              "---\nname: house-style\ndescription: The dialect.\nwhen_to_use: Always.\n---\n"
              + skill_body)
    sizes["skill body"] = len(skill_body.encode("utf-8"))
    return sizes


def _entry(measured, label):
    return next(e for e in measured["entries"] if e["entry"] == label)


def _cases(check):
    import tempfile
    from _suite import remove_tree
    scratch = tempfile.mkdtemp(prefix="measure-context-")
    try:
        sizes = _fx_plugin(scratch)
        measured = measure(tree_source(scratch))
        run = _entry(measured, "/audit:run")
        reads = [r["path"] for r in run["rows"] if r["part"] == "read first"]
        check("mc1 a command loads its body and the files its up-front Read paragraph "
              "names, in order: %r" % (reads,), reads == ["reference/a.md", "reference/b.md"])
        later = [r["path"] for r in _entry(measured, "/audit:next")["rows"]
                 if r["part"] == "read first"]
        check("mc2 THE OVER-FIRE TWIN: a file the body says it does NOT read, a file a later "
              "paragraph reads on a condition, and a conditional read placed before the "
              "up-front one are not counted - counting every mention, or the first Read "
              "paragraph whatever it says, would load them: %r" % ((reads, later),),
              "reference/c.md" not in reads and "reference/d.md" not in reads
              and later == ["reference/a.md"])
        check("mc3 the entry's total is its body plus those files, to the byte (%d)"
              % run["bytes"],
              run["bytes"] == sizes["run body"] + sizes["a"] + sizes["b"]
              and not run["missing"])

        exe = _entry(measured, "executor")
        parts = [(r["part"], r["path"], r["bytes"]) for r in exe["rows"]]
        check("mc4 an agent loads its system prompt and every skill its frontmatter preloads, "
              "the skill counted by its body: %r" % (parts,),
              parts == [("system prompt", "agents/audit-executor.md", sizes["executor body"]),
                        ("preloaded skill", "skills/house-style/SKILL.md", sizes["skill body"])])
        on_disk = os.path.getsize(os.path.join(scratch, "commands", "run.md"))
        written = len(("---\ndescription: 'Run one task.'\nargument-hint: '<id>'\n---\n"
                       ).encode("utf-8")) + sizes["run body"]
        check("mc28 the fixture writes the bytes it reports: a file with line endings is "
              "the same size on disk as the text handed to it - a text-mode write turns "
              "each newline into two bytes on Windows, which every byte case above would "
              "then read as a miscount (%d on disk, %d written)" % (on_disk, written),
              on_disk == written)
        crlf = split_frontmatter(b"---\r\ndescription: 'Run.'\r\n---\r\n\r\nbody\r\n")
        lf = split_frontmatter(b"---\ndescription: 'Run.'\n---\n\nbody\n")
        check("mc29 a CRLF checkout's frontmatter parses as an LF one does, and its closing "
              "line ending is not counted in the body - while a blank line that opens the "
              "body is, in both, so stripping every leading newline goes red here: %r"
              % ((crlf, lf),),
              crlf == ({"description": "Run."}, b"\r\nbody\r\n")
              and lf == ({"description": "Run."}, b"\nbody\n"))

        lst = measured["listing"]
        want = (len("audit:run" + "Run one task.")
                + sum(len(name + "x") for name in ("audit:next", "audit:phase", "audit:review",
                                                         "audit:task"))
                + len("audit-executor" + "Executes.") + len("audit-reviewer" + "Reviews.")
                + len("house-style" + "The dialect." + "Always."))
        check("mc5 the always-on listing is the name and description of every command, agent "
              "and skill, plus a skill's when_to_use - counted, not guessed (%d)" % lst["bytes"],
              lst["bytes"] == want and (lst["commands"], lst["agents"], lst["skills"]) == (5, 2, 1))

        check("mc6 without --claude-md the project's CLAUDE.md is NOT counted as nothing - "
              "no agent row claims it and the report says it was not measured",
              all(r["part"] != "CLAUDE.md" for e in measured["entries"] for r in e["rows"])
              and "not measured" in render([measured], DEFAULT_BYTES_PER_TOKEN, 5))
        given = measure(tree_source(scratch), {"name": "CLAUDE.md", "bytes": 777})
        check("mc7 ...and with it, it is counted in every agent and in no command - a command "
              "inherits it from the session, an agent loads it again",
              all(any(r["part"] == "CLAUDE.md" and r["bytes"] == 777 for r in e["rows"])
                  for e in given["entries"] if e["entry"] in ("executor", "reviewer"))
              and not any(r["part"] == "CLAUDE.md" for e in given["entries"]
                          if e["entry"].startswith(("/", "sign-off")) for r in e["rows"]))

        os.remove(os.path.join(scratch, "reference", "b.md"))
        gone = measure(tree_source(scratch))
        run = _entry(gone, "/audit:run")
        check("mc8 a file a step loads that is not there is reported MISSING and named, never "
              "measured as zero bytes: %r" % (run["missing"],),
              run["missing"] == ["reference/b.md"]
              and "MISSING" in render([gone], DEFAULT_BYTES_PER_TOKEN, 5))
        old_out, sys.stdout = sys.stdout, io.StringIO()
        old_err, sys.stderr = sys.stderr, io.StringIO()
        try:
            code_missing = main(["--tree", scratch])
            code_bad_ref = main(["--ref", "no-such-ref-anywhere"])
            code_nothing = main([])
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        check("mc9 exit codes: a missing file is 1, a ref that does not resolve and a call "
              "that names nothing to measure are 2: %r"
              % ((code_missing, code_bad_ref, code_nothing),),
              (code_missing, code_bad_ref, code_nothing) == (1, 2, 2))
    finally:
        remove_tree(scratch)

    small = tempfile.mkdtemp(prefix="measure-context-a-")
    large = tempfile.mkdtemp(prefix="measure-context-b-")
    try:
        _fx_plugin(small, executor_skills=False)
        _fx_plugin(large, executor_skills=False)
        _fx_write(large, "reference/a.md", "A" * 1600)
        pair = [measure(tree_source(small)), measure(tree_source(large))]
        line = [l for l in _compare(pair, DEFAULT_BYTES_PER_TOKEN, 5)
                if l.strip().startswith("reference/a.md")]
        check("mc10 two sources side by side carry each file's growth as a delta: %r" % (line,),
              len(line) == 1 and "+600" in line[0])
        none = _entry(pair[0], "executor")
        check("mc11 an agent whose frontmatter preloads nothing gets no skill row, rather "
              "than a row guessed from the plugin's own skills",
              [r["part"] for r in none["rows"]] == ["system prompt"])
    finally:
        remove_tree(small)
        remove_tree(large)

    quiet = tempfile.mkdtemp(prefix="measure-context-q-")
    try:
        _fx_plugin(quiet)
        _fx_write(quiet, "commands/bug.md", "---\ndescription: 'File a bug.'\n"
                  "disable-model-invocation: true\n---\nbody\n")
        _fx_write(quiet, "skills/hush/SKILL.md", "---\nname: hush\ndescription: Hush.\n"
                  "disable-model-invocation: true\n---\nbody\n")
        # The twin: the key present and false. A rule that withheld on the key's mere
        # presence would drop this one too.
        _fx_write(quiet, "commands/status.md", "---\ndescription: 'Show status.'\n"
                  "disable-model-invocation: false\n---\nbody\n")
        held = measure(tree_source(quiet))
        lst = held["listing"]
        shown = render([held], DEFAULT_BYTES_PER_TOKEN, 5)
        check("mc13 a command or skill whose frontmatter sets disable-model-invocation: true "
              "is left out of the always-on listing and counted as withheld, and one that "
              "sets it false is listed: %r" % (lst,),
              lst["bytes"] == want + len("audit:status" + "Show status.")
              and (lst["commands"], lst["agents"], lst["skills"], lst["withheld"])
              == (6, 2, 1, 2)
              and "2 command(s) or skill(s) set disable-model-invocation" in shown)
    finally:
        remove_tree(quiet)

    verbs = tempfile.mkdtemp(prefix="measure-context-v-")
    try:
        sizes = _fx_plugin(verbs)
        got = measure(tree_source(verbs))
        rows = dict((e["entry"], [(r["part"], r["path"]) for r in e["rows"]])
                    for e in got["entries"])
        totals = dict((e["entry"], e["bytes"]) for e in got["entries"])
        at = rows["/audit:phase run form, at sign-off"]
        check("mc14 the phase run form at sign-off is the run form plus what sign-off reads "
              "first that the run form has not loaded - a file both read is counted once: %r"
              % (at,),
              at == rows["/audit:phase run form, before sign-off"]
              + [("read at sign-off", "reference/s.md")]
              and totals["/audit:phase run form, at sign-off"]
              == totals["/audit:phase run form, before sign-off"] + sizes["s"])
        check("mc15 the planning verbs are entries of their own: `/audit:task add` is the task "
              "command's body and what it reads first, and `/audit:phase add` is what the phase "
              "command loads while its reads do not depend on the verb: %r"
              % ((rows["/audit:task add"], totals["/audit:task add"]),),
              rows["/audit:task add"] == [("command body", "commands/task.md"),
                                          ("read first", "reference/b.md")]
              and totals["/audit:task add"] == sizes["task body"] + sizes["b"]
              and rows["/audit:phase add"] == rows["/audit:phase"]
              and rows["/audit:phase run form, before sign-off"] == rows["/audit:phase"])

        heads = ("# Audit orchestrator — shared execution logic\nintro\n## At a glance\nxx\n"
                 "## Readiness rule\nyyy\n## Something new\nz\n")
        _fx_write(verbs, "reference/orchestrator.md", heads)
        ranged = "".join("line %d\n" % n for n in range(1, 714))
        _fx_write(verbs, "reference/execute-task.md", ranged)
        _fx_write(verbs, "commands/run.md", "---\ndescription: x\n---\nRead "
                  "`%sreference/orchestrator.md` and `%sreference/execute-task.md` first.\n"
                  % (_FX_ROOT, _FX_ROOT))
        cut = sections(tree_source(verbs))
        orch = cut["files"][0]

        def width(text):
            return len(text.encode("utf-8")) + 1
        keep = (width("# Audit orchestrator — shared execution logic") + width("intro")
                + width("## At a glance") + width("xx"))
        want_orch = {"keep": keep, "conditional": width("## Readiness rule") + width("yyy"),
                     "elsewhere": 0, "maintainer": 0,
                     "unclassified": width("## Something new") + width("z") + width("")}
        lines = ranged.split("\n")
        want_exe = dict((k, 0) for k in want_orch)
        for a, z, kind in SECTION_CLASSES["reference/execute-task.md"]["ranges"]:
            want_exe[kind] += sum(width(x) for x in lines[a - 1:z])
        check("mc16 --sections sums each file /audit:run reads first by class - a heading's "
              "section up to the next heading, a one-heading file by its declared line "
              "ranges - and a heading the table does not class is printed unclassified "
              "rather than dropped: %r" % ((orch["sums"], cut["files"][1]["sums"]),),
              orch["sums"] == want_orch and cut["files"][1]["sums"] == want_exe
              and cut["files"][1]["problem"] is None
              and orch["problem"] is not None and "Preflight" in orch["problem"]
              and sum(cut["sums"].values()) == sum(want_orch.values()) + sum(want_exe.values()))
        _fx_write(verbs, "reference/execute-task.md", ranged + "one more\n")
        moved = sections(tree_source(verbs))["files"][1]
        check("mc17 THE LINE-COUNT TWIN: a copy whose line count is not the one the ranges were "
              "cut at is not classed by them - every byte is unclassified and the report "
              "says why - where applying them would class shifted lines: %r"
              % ((moved["sums"], moved["problem"]),),
              moved["sums"]["unclassified"] == moved["bytes"] + 1
              and not any(moved["sums"][k] for k in SECTION_CLASS_NAMES)
              and "not applied" in (moved["problem"] or "")
              and "NOTE: line ranges declared for 714 lines"
              in "\n".join(render_sections("x", sections(tree_source(verbs)), 4.0)))
    finally:
        remove_tree(verbs)

    pinned, problem = git_source("7b489337c06d")
    if problem:
        check("mc18 the design document's reference commit is readable here (%s): a clone "
              "too shallow to hold it cannot check the classification" % problem, False)
    else:
        sums = sections(pinned)["sums"]
        check("mc18 AT THE COMMIT THE CLASSIFICATION WAS TAKEN AT the class sums are the design "
              "document's, with nothing unclassified: %r" % (sums,),
              sums == {"keep": 77811, "conditional": 27767, "elsewhere": 25037,
                       "maintainer": 23089, "unclassified": 0})

    shipped = measure(tree_source(os.path.join(REPO, PLUGIN_REL)))
    check("mc19 the agents' starts in this tree stay within their ceilings, measured: %r"
          % ([(e["entry"], e["bytes"]) for e in shipped["entries"]
              if e["entry"] in AGENT_CEILINGS],),
          ceiling_breaches(shipped) == [])
    scratch = tempfile.mkdtemp(prefix="measure-context-ceiling-")
    try:
        _fx_plugin(scratch, executor_skills=False)
        within = ceiling_breaches(measure(tree_source(scratch)))
        _fx_write(scratch, "agents/audit-reviewer.md",
                  "---\nname: audit-reviewer\ndescription: Reviews.\n---\n"
                  + "R" * (AGENT_CEILINGS["reviewer"] + 1))
        over = ceiling_breaches(measure(tree_source(scratch)))
        os.remove(os.path.join(scratch, "agents", "audit-executor.md"))
        gone = ceiling_breaches(measure(tree_source(scratch)))
    finally:
        remove_tree(scratch)
    check("mc20 THE RED TWIN: a reviewer one byte past its ceiling is named with its size, "
          "the executor within its own is not, and an agent whose prompt is missing is a "
          "breach rather than a zero; the small fixture breaches nothing: %r"
          % ((within, over, gone),),
          within == []
          and over == [("reviewer", AGENT_CEILINGS["reviewer"] + 1,
                        AGENT_CEILINGS["reviewer"])]
          and [b[0] for b in gone] == ["executor", "reviewer"])

    _gate_cases(check, shipped)
    _eol_cases(check)


def _eol_fixture(root, attributes):
    """`(rows, problem)` of a scratch repository holding a markdown file, a JSON file,
    a shell script and a binary image, under `attributes`."""
    for rel, data in ((".gitattributes", attributes.encode("ascii")),
                      ("a.md", b"# a\n\nprose\n"), ("d.json", b"{\"k\": 1}\n"),
                      ("b.sh", b"echo b\n"), ("img.png", b"\x89PNG\r\n\x1a\n\x00\x00\x01")):
        with open(os.path.join(root, rel), "wb") as fh:
            fh.write(data)
    for args in (["init", "-q"], ["-c", "core.autocrlf=false", "add", "-A"]):
        proc = subprocess.run(["git", "-C", root] + args, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return None, "git %s exited %d" % (" ".join(args), proc.returncode)
    return tracked_eol(root)


def _eol_cases(check):
    import tempfile
    from _suite import remove_tree
    raw = (b"i/lf    w/lf    attr/text=auto eol=lf \tdocs/a b.md\0"
           b"i/-text w/-text attr/text=auto eol=lf \timg.png\0"
           b"i/lf    w/crlf  attr/                 \tplan.json\0"
           b"i/lf    w/lf    attr/text eol=crlf    \twin.bat\0")
    rows = parse_ls_files_eol(raw)
    check("mc30 a `git ls-files --eol -z` record keeps an attribute column holding a "
          "space and a path holding one, and the text files whose checkout is left to "
          "core.autocrlf - no attribute, or one pinning CRLF - are named, the binary "
          "and the eol=lf ones are not: %r" % ((rows, unpinned_text_files(rows)),),
          rows[0] == ("lf", "text=auto eol=lf", "docs/a b.md")
          and rows[2] == ("lf", "", "plan.json")
          and unpinned_text_files(rows) == ["plan.json", "win.bat"])
    narrow_dir = tempfile.mkdtemp(prefix="measure-context-eol-")
    wide_dir = tempfile.mkdtemp(prefix="measure-context-eol-")
    try:
        # The rule this tree carried before every text type was pinned: one extension.
        narrow, narrow_problem = _eol_fixture(narrow_dir, "*.sh text eol=lf\n")
        wide, wide_problem = _eol_fixture(wide_dir, "* text=auto eol=lf\n")
    finally:
        remove_tree(narrow_dir)
        remove_tree(wide_dir)
    # THE RED TWIN: a per-extension pin leaves markdown and JSON to autocrlf, which is
    # the windows-latest checkout that grew the shipped prose past its ceilings.
    check("mc31 THE RED TWIN: under a pin that names one extension, the markdown, the "
          "JSON and the attributes file itself are named as checking out to whatever "
          "core.autocrlf says, and the binary image is not: %r"
          % ((narrow, narrow_problem),),
          narrow_problem is None
          and unpinned_text_files(narrow) == [".gitattributes", "a.md", "d.json"])
    # THE ALLOW TWIN, for the over-fire direction: a check that named every text file,
    # or every file, regardless of attributes goes red here.
    check("mc32 THE ALLOW TWIN: under `* text=auto eol=lf` nothing is named, though git "
          "still holds every text file and detects the image as binary: %r"
          % ((wide, wide_problem),),
          wide_problem is None and unpinned_text_files(wide) == []
          and sorted(r[2] for r in wide if r[0] != "-text")
          == [".gitattributes", "a.md", "b.sh", "d.json"]
          and [r[2] for r in wide if r[0] == "-text"] == ["img.png"])
    real, problem = tracked_eol(REPO)
    text = [r[2] for r in real or [] if r[0] != "-text"]
    check("mc33 every text file this repository tracks checks out with LF on every "
          "platform - its attributes say eol=lf - so a windows checkout measures the "
          "bytes a POSIX one does; the census is not empty and holds the shipped "
          "markdown and the committed JSON: unpinned=%r (%s)"
          % (unpinned_text_files(real or []), problem or "%d text files" % len(text)),
          problem is None and unpinned_text_files(real) == []
          and any(p.endswith(".md") for p in text)
          and any(p.endswith(".json") for p in text))


def _fx_lean(root):
    """A plugin tree whose pipeline commands read no reference file first and
    whose every body is far inside its ceiling - the shape the gate allows."""
    _fx_plugin(root, executor_skills=False)
    for rel in ("commands/run.md", "commands/next.md", "commands/phase.md",
                "commands/review.md", "commands/task.md", "commands/resume.md"):
        _fx_write(root, rel, "---\ndescription: x\n---\nRun `drive-phase.py next`, "
                  "do what it prints, and run it again.\n")


def _gate_run(scratch):
    """`(breaches, code, printed)` of the gate over the tree at `scratch`."""
    breaches = gate_breaches(measure(tree_source(scratch)))
    old_out, sys.stdout = sys.stdout, io.StringIO()
    old_err, sys.stderr = sys.stderr, io.StringIO()
    try:
        code = main(["--gate", "--tree", scratch])
        printed = sys.stdout.getvalue() + sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return breaches, code, printed


def _gate_cases(check, shipped):
    import tempfile
    from _suite import remove_tree
    gated = dict(ENTRY_CEILINGS) if isinstance(globals().get("ENTRY_CEILINGS"),
                                                tuple) else {}
    if "gate_breaches" not in globals():
        for label in ("mc21", "mc22", "mc23", "mc24"):
            check("%s the ceiling gate exists (gate_breaches)" % (label,), False)
        return
    scratch = tempfile.mkdtemp(prefix="measure-context-gate-")
    try:
        _fx_lean(scratch)
        lean, lean_code, _p = _gate_run(scratch)
        _fx_write(scratch, "commands/phase.md", "---\ndescription: x\n---\n"
                  + "P" * (gated.get("/audit:phase run form, before sign-off", 0) + 1))
        fat, fat_code, fat_printed = _gate_run(scratch)
        _fx_lean(scratch)
        _fx_write(scratch, "commands/run.md", "---\ndescription: x\n---\nRead "
                  "`%sreference/a.md` first.\n" % (_FX_ROOT,))
        reads, _c, _p = _gate_run(scratch)
        _fx_lean(scratch)
        os.remove(os.path.join(scratch, "commands", "resume.md"))
        gone, gone_code, _p = _gate_run(scratch)
        # A pointer is a reference path the body NAMES without a `Read ... first`
        # paragraph - "see `reference/x.md`" - which the up-front rule cannot
        # see and which a model follows anyway.
        _fx_lean(scratch)
        _fx_write(scratch, "commands/next.md", "---\ndescription: x\n---\nRun "
                  "`drive-phase.py next`. The rule is stated in "
                  "`reference/conventions.md` - see it.\n")
        _fx_write(scratch, "commands/review.md", "---\ndescription: x\n---\nRun "
                  "it. What each step checks is `%sreference/signoff.md`.\n"
                  % (_FX_ROOT,))
        pointed, pointed_code, pointed_printed = _gate_run(scratch)
        # THE ALLOW TWIN for the pointer rule: a body outside the pipeline may
        # point at reference prose (bug.md and layout.md read it on purpose),
        # and a pipeline body may say the word without naming a path.
        _fx_lean(scratch)
        _fx_write(scratch, "commands/bug.md", "---\ndescription: x\n---\nRead "
                  "`%sreference/conventions.md` FIRST; see "
                  "`reference/conventions.md` for the rest.\n" % (_FX_ROOT,))
        _fx_write(scratch, "commands/run.md", "---\ndescription: x\n---\nRun "
                  "`drive-phase.py next`; no reference prose is read here.\n")
        unpointed, unpointed_code, _p = _gate_run(scratch)
    finally:
        remove_tree(scratch)
    check("mc25 a gated command body that NAMES a reference path - a `see` pointer "
          "or a rooted path, with no `Read ... first` paragraph - breaches, naming "
          "the path, and --gate exits 1 printing it: %r"
          % ((pointed, pointed_code),),
          sorted(b[0] for b in pointed) == ["/audit:next", "sign-off (/audit:review)"]
          and any("reference/conventions.md" in b[3] for b in pointed)
          and any("reference/signoff.md" in b[3] for b in pointed)
          and pointed_code == 1 and "reference/conventions.md" in pointed_printed)
    check("mc26 ALLOW: a command outside the pipeline that points at reference "
          "prose, and a pipeline body that says the word without a path, breach "
          "nothing - widening the rule to every command, or to the bare word, is "
          "what this goes red on: %r" % ((unpointed, unpointed_code),),
          unpointed == [] and unpointed_code == 0)
    check("mc21 THE ALLOW TWIN: a tree whose pipeline commands read no reference file "
          "first and stay inside every ceiling breaches nothing, and --gate exits 0 over "
          "it: %r" % ((lean, lean_code),), lean == [] and lean_code == 0)
    fat_names = [b[0] for b in fat]
    check("mc22 a phase body one byte past the run form's ceiling is named with its size "
          "and the ceiling, the verb whose ceiling is higher is not, and --gate exits 1 "
          "printing the breach: %r" % ((fat, fat_code),),
          "/audit:phase run form, before sign-off" in fat_names
          and "/audit:phase add" not in fat_names and fat_code == 1
          and "/audit:phase run form, before sign-off" in fat_printed
          and any(b[1] == gated.get("/audit:phase run form, before sign-off", 0) + 1
                  for b in fat))
    check("mc23 a gated command that reads a reference file first breaches whatever its "
          "size, naming the file - the rule is that no pipeline command makes the main "
          "loop read reference prose - and an entry whose command is missing is a breach "
          "rather than a zero: %r" % ((reads, gone, gone_code),),
          [b[0] for b in reads] == ["/audit:run"]
          and "reference/a.md" in reads[0][3]
          and [b[0] for b in gone] == ["/audit:resume"] and gone_code == 1)
    breaches = gate_breaches(shipped)
    check("mc24 the shipped tree holds the ceilings the pipeline-cost design sets for each "
          "entry, and no gated command reads or names a reference file: %r"
          % ([(e["entry"], e["bytes"]) for e in shipped["entries"]
              if e["entry"] in gated] + breaches,),
          gated and breaches == [])

    head, problem = git_source("HEAD")
    if problem:
        check("mc12 HEAD of this checkout is readable as a source (%s)" % problem, False)
        return
    real = measure(head)
    # The pipeline's own commands read no reference file first any more, so the
    # anti-vacuity half reads commands OUTSIDE the pipeline that still do: a rule
    # that quietly stopped matching would read every pipeline entry as cheap, and
    # the gate above as green over nothing.
    outside = dict((rel, first_reads(split_frontmatter(head["read"](rel) or b"")[1]))
                   for rel in ("commands/bug.md", "commands/layout.md"))
    check("mc12 ON THE REAL PROSE at HEAD the up-front rule still finds the reference "
          "files the commands outside the pipeline read first, and every file a "
          "pipeline entry loads is there: %r" % (outside,),
          "reference/manifest-conventions.md" in outside["commands/bug.md"]
          and "reference/orchestrator.md" in outside["commands/layout.md"]
          and not any(e["missing"] for e in real["entries"]))
    finder = globals().get("reference_pointers")
    named = finder(split_frontmatter(head["read"]("commands/bug.md") or b"")[1]) \
        if finder else None
    check("mc27 ON THE REAL PROSE at HEAD the pointer rule finds the `see` pointer "
          "commands/bug.md carries outside the pipeline, so mc24's empty answer over "
          "the pipeline is a rule that still matches, not one that matches nothing: "
          "%r" % (named,),
          named is not None and "reference/manifest-conventions.md" in named)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from_here = os.path.join(REPO, "plugins", "audit", "scripts")
    if from_here not in sys.path:
        sys.path.insert(0, from_here)
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
