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
    and the project's CLAUDE.md.

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

Usage:  python3 tools/measure-context.py --ref v3.1.0 --ref main [--claude-md FILE] [--json]
        python3 tools/measure-context.py --tree <plugin root> [--claude-md FILE]
        python3 tools/measure-context.py --selftest
Exit codes: 0 measured - 1 a file a step loads is missing at that ref - 2 usage error
or a ref that does not resolve.
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

# The pipeline's real path: the commands that run work and the agents they dispatch.
# Sign-off is measured through the command that re-runs it on its own.
PIPELINE = (
    ("/audit:run", "command", "commands/run.md"),
    ("/audit:next", "command", "commands/next.md"),
    ("/audit:phase", "command", "commands/phase.md"),
    ("sign-off (/audit:review)", "command", "commands/review.md"),
    ("executor", "agent", "agents/audit-executor.md"),
    ("reviewer", "agent", "agents/audit-reviewer.md"),
)

_READ_RE = re.compile(r"\bRead\s+`" + re.escape(ROOT_VAR))
_FIRST_RE = re.compile(r"\bfirst\b", re.IGNORECASE)
_ROOTED_RE = re.compile(r"`" + re.escape(ROOT_VAR) + r"([^`]+)`")


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
    body = rest[1:] if rest.startswith("\n") else rest
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
    if kind == "command":
        rows = [_row("command body", rel, body)]
        rows.extend(_row("read first", path, source["read"](path)) for path in first_reads(body))
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


def listing(source):
    """{"commands": n, "agents": n, "skills": n, "bytes": n} - what the plugin adds to
    every session's listing: name and description of each, and a skill's
    `when_to_use`."""
    counts = {"commands": 0, "agents": 0, "skills": 0, "bytes": 0}
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
        entries.append({"entry": label, "rows": rows, "bytes": sum(known),
                        "missing": [r["path"] for r in rows if r["bytes"] is None]})
    return {"label": source["label"], "entries": entries, "listing": listing(source),
            "claudeMd": claude_md}


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
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
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
    if args.as_json:
        print(json.dumps({"bytesPerToken": args.bytes_per_token, "measured": measured,
                          "contributors": [contributors(m) for m in measured]},
                         indent=2, sort_keys=True))
    else:
        print(render(measured, args.bytes_per_token, args.top))
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
    with open(path, "w", encoding="utf-8") as fh:
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
    for rel in ("commands/phase.md", "commands/review.md"):
        _fx_write(root, rel, "---\ndescription: x\n---\nnothing up front\n")
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

        lst = measured["listing"]
        want = (len("audit:run" + "Run one task.")
                + sum(len(name + "x") for name in ("audit:next", "audit:phase", "audit:review"))
                + len("audit-executor" + "Executes.") + len("audit-reviewer" + "Reviews.")
                + len("house-style" + "The dialect." + "Always."))
        check("mc5 the always-on listing is the name and description of every command, agent "
              "and skill, plus a skill's when_to_use - counted, not guessed (%d)" % lst["bytes"],
              lst["bytes"] == want and (lst["commands"], lst["agents"], lst["skills"]) == (4, 2, 1))

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

    head, problem = git_source("HEAD")
    if problem:
        check("mc12 HEAD of this checkout is readable as a source (%s)" % problem, False)
        return
    real = measure(head)
    named = dict((e["entry"], [r["path"] for r in e["rows"] if r["part"] == "read first"])
                 for e in real["entries"])
    check("mc12 ON THE REAL PROSE at HEAD the up-front rule finds the reference files every "
          "pipeline command reads, and every file it names is there - a rule that quietly "
          "stopped matching would read as a cheap pipeline: %r" % (named,),
          all("reference/orchestrator.md" in named[label] for label, kind, _rel in PIPELINE
              if kind == "command")
          and "reference/phase-signoff.md" in named["sign-off (/audit:review)"]
          and "reference/phase-signoff.md" not in named["/audit:run"]
          and not any(e["missing"] for e in real["entries"]))


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
