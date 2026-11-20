#!/usr/bin/env python3
"""
The browser install's shell, run against stubs of the system it drives.

    tools/check-browser-install.py                 # the check, over the committed action
    tools/check-browser-install.py --action PATH   # ...over another copy of it
    tools/check-browser-install.py --selftest      # this file's own cases

WHY THIS EXISTS. `.github/actions/browser-install/action.yml` is shell that only a
GitHub runner executes, and the way it fails is quiet: a bug on the path that
restores the system packages' set falls into the fallback, which fetches every file
from the archive again, warns once and leaves the job green. That is the regression
the cached set was written to remove - minutes of apt on a slow mirror - and it can
come back with every gate green. So the action's own `run:` blocks are read out of the
committed file (never a copy of the shell) and executed here, against stubs of the
system they drive (`STUBS`, and the shell stubs `sudo`, `apt-config` and `node`) that
keep a ledger of who owns each path.

WHAT A STEP CAN START. This runs in the lint slice and under the sweep, on a
developer's machine, so a line added to the action must not be able to reach that
machine. The promise: a step's shell starts a program only by a bare name, and that
name finds a stub or a real tool in `ALLOWED_TOOLS` - nothing else. PATH alone cannot
hold that, because the shell has ways to start a program that never consult it. It
is held twice where a construction can hold it and by reading alone where none can,
and the selftest shows which half holds what, each red without the other:
  * BY READING, before anything runs. `run_script` hands every script to
    `script_problems` first, and a script it refuses is not started at all; `sd8`
    reports the same reading for every step a case runs. The reader takes the shell
    subset the action is written in and refuses every shape it does not read. It
    judges a word by the value bash hands on after quote removal, in one place
    (`_bash_reading`), so a quoted `-v` is the option `-v` to it as it is to bash; a
    word whose value reading cannot know - it carries an expansion, or an unquoted
    character bash expands - is refused wherever a rule needs its value, unless the
    rule allows exactly that expansion as the whole word. Every command word must be
    a bare name - a stub, an allowed tool, a function the script defines, or a
    builtin on `BUILTINS` called within the family of calls its row describes - so a
    word holding a `/` (absolute, relative or built from a variable), a word an
    expansion produces, and `command`, `exec`, `env`, `hash`, `enable`, `source`,
    `.`, `builtin` and `trap` are refused for not being on the list, not one
    spelling at a time; and no function may take a name on that list, because a
    call written before the definition runs the builtin. A script may assign only
    lowercase names, so no `PATH=`, `IFS=`, `PS4=` or `LD_PRELOAD=`, and no
    assignment may prefix a command. A redirection writes only to `/dev/null`, to
    `"$GITHUB_OUTPUT"` written as exactly that expansion, or to another descriptor.
    Every form that evaluates text as code or starts what the reader cannot follow
    is refused: arithmetic, an array subscript, `${x@P}`, `${!x}`, process
    substitution, a backquote, a here-document, `&`, a `{name}` written against a
    redirection, and an `eval` of anything but one double-quoted substitution of
    the apt-config stub with nothing beside it. `sd7` adds that no line names an
    absolute path but `/dev/null`.
  * BY CONSTRUCTION, for what does run (`_prelude`). PATH is the fixture's `bin/`
    and read-only, as is every other variable of the step's environment, so the
    variables the stubs read cannot be pointed elsewhere; `BASH_CMDS` and
    `BASH_ALIASES` are unset and read-only; and every builtin not on `BUILTINS` is
    disabled before the script's first line, `enable` last, so `command -p`,
    `exec`, `hash -p`, `enable -f`, `source` and `builtin` do not exist to be
    called. The `sudo` stub starts only a name it finds in `bin/`; every stub that
    writes refuses a path outside the fixture root; stdin is closed. A refused
    request, and a name the shell cannot find, is written to the fixture's refusal
    ledger, and every case that runs a step is red when that ledger is not empty,
    whatever the step did with the exit code (`_refusals`). Each `bk` row names the
    prelude lines that hold it and runs again with them taken out, where it must
    reach outside, so the line credited with a hold is the line shown holding: on
    bash 3.2 `command -p` is held both by the disabled builtin and by the read-only
    PATH, and the command hash array does not exist, so `bk11` shows nothing there.
What stays outside that, so a green run here says nothing about it. The list comes
from reading the bash manual's sections on command search and execution, the
builtins, the shell variables, the expansions and the restricted shell for every way
to start a program or to evaluate text as code, and from the cases' own runs:
  * the reader is not bash. `bp10` and `bq1` pin what it refuses, also under every
    quoting `bq1` tries; `bp11` and `bq2` that it reads each shape the action has,
    bare and respelled; `bq3` that bash, running those shapes, starts nothing off
    the vocabulary. A shape neither table carries is not seen, and neither is a
    quoting `bq1` does not try: it respells only a word written bare, so a reserved
    word, an assignment, a function's name, a `for` name and a word holding an
    expansion keep their spelling, and a backslash outside quotes is refused
    outright rather than read.
  * what reading alone holds, because no construction can: a command word naming a
    program by a path (`bx7`, `bx8`), the text an `eval` runs (`bx12`, `bq5`,
    `bq6`), a function defined after a call of the builtin it names (`bq7`), and
    `printf -v` through a subscript (`bx13`, `bq4`). Past the reader `bq5`-`bq7`
    start a program on bash 3.2; there `bq4` shows bash taking the quoted `-v` as
    the option and refusing the subscripted name, and whether a bash evaluates the
    subscript is what `bq4` prints on it. The prelude cannot stop bash starting a
    program by its
    path; a restricted shell would, but it also refuses the action's own
    redirections (the manual's RESTRICTED SHELL section).
  * `sd7` reads a line's text, not its words: a `/` written as a quoted piece of
    its own is not an absolute path to it. Such a command word is still refused for
    not being a bare name; such an argument reaches only a stub or an allowed tool,
    which the item on what a tool is given to read covers.
  * `node`, which starts the real node on a harness evaluating the `-e` code in a
    `vm` context whose `require` returns JSON under the fixture root and nothing
    else. A `vm` context is not a security boundary: it stops an ordinary edit
    (`require('fs')`), not code written to escape it.
  * what an allowed tool or a stub is given to read: each writes only its standard
    output or under the fixture, but `ls "$HOME/../.."` lists a directory outside.
  * a step that does not end: STEP_TIMEOUT ends the step's shell, not every process
    the shell started.
  * on bash 3.2 (macOS's own), a name not found whose stderr the step discards:
    that bash has no `command_not_found_handle`, so the only channel there is its
    own "command not found" line, which `2>/dev/null` hides. The name still does
    not run, and the reader refuses it before the step starts. bash 4 and later,
    which every runner has, record it either way.

WHAT THE CASES HOLD, by id (the gate prints each):
  * `bi` - the system packages' step. A full hit asks the archive for nothing, index
    included, and a hit that fetches anything is RED, not a warning (`bi1`); a miss
    fetches the closure once (`bi2`); a partial set fetches what apt says it lacks and
    nothing else (`bi3`-`bi5`); a set apt cannot install from falls back exactly once
    (`bi6`, `bi7`), and the step is red only when the fallback fails too (`bi8`,
    `bi9`). Every path of the set ends the runner user's, so the cache can save it,
    and no runner-user write lands under a directory root made (`bi10`): the first
    version of the action created `lists/partial` as the runner user under a
    `lists/` that `sudo cp -a` had given root, and the runner refused it with
    "Permission denied".
  * `sp` - the seed decision, one case per branch of the `plan` step.
  * `sk` - the cache keys: the `pins` step's (`sk1`-`sk3`) and the system packages'
    key the `sysdeps` step writes from the dry run and dpkg's answers (`sk4`).
  * `sd` - the wiring the decision rests on, read off the steps' keys: each cache is
    keyed by the output the step writing its key writes, the seed's lookups name the
    same path and key as the restores, the plan reads their answers, every step
    after the plan installs only when the plan says so, the steps no case runs are
    where they must be, an image lacking nothing asks for no set, `seed` defaults to
    false, no script names an absolute path (`sd7`), and the reader refuses nothing
    in a step a case runs (`sd8`).

The selftest holds the parser of the action, runs every case over the committed
action, and then breaks a copy of the action once per property and requires the case
that holds it to go red - so a case that could not fail is itself a red case here.
Its `bx` rows append a line reaching outside the fixture to a copy of the action and
require the case red, refused by the half the row names, with the file outside
untouched; its `bk` rows run a line past the reader, against the construction alone,
and require that file untouched too, and touched once the row's hold is taken out.
Its `bq` rows hold the reader to bash's reading: every bare word of the reader's
tables is respelled in quotings bash reads the same way (`bq1`, `bq2`), every shape
the action has is run under bash's own trace (`bq3`), and each shape the reader once
accepted while bash read it otherwise is run past the reader and as a step
(`bq4`-`bq7`). That file sits in a scratch directory of its own, so a check that
lost its confinement touches nothing else.

WHAT THE STUBS CANNOT SEE, so a green run here says nothing about it:
  * apt's real resolution - versions, `Pre-Depends`, alternatives, multi-arch,
    `--no-install-recommends` - and dpkg's real reading of a `.deb`. The stub apt
    resolves a fixed index by name and size, and a file is unreadable when its bytes
    start with a marker.
  * the kernel's permission checks. Ownership is a ledger the stubs consult, written
    from what the runner showed (`cp -a` hands the destination its source's owner;
    root's directories refuse the runner user), so a rule the runner enforces and
    the ledger does not model is invisible - the apt sandbox user, a umask, ACLs.
  * GitHub's cache service: whether a key is found, which branch's entries a run
    may read, the path being part of an entry's version, `lookup-only`, a save that
    another job reserved first. The `sd` cases read the steps' keys as text; nothing
    here evaluates a `${{ }}` expression or an `if:` the way the runner does, so an
    expression the runner reads otherwise than its text says is not seen.
  * the steps not run here: `npm ci` and `npx playwright install chromium`, which
    need the network; `sd4` reads that each is there, and where. The dry run's
    output is a line written from playwright-core's source, not captured from an
    image, and dpkg's answer is the fixture's list. A real CI run is still the only
    evidence for those, and for timings.
  * the `seed` input's `description` and `required`, and the order of the steps
    beyond what `sd3` and `sd4` read.
  * the workflow that calls the action: the `continue-on-error` and the warning step
    a seed's job carries are ci.yml's, and gate-parity.py reads that side.

IT RUNS ON A POSIX HOST. The stubs are shell scripts bash must execute through a
colon-separated PATH, beside the real tools ALLOWED_TOOLS names; on a host without
those, every case that runs a step is red as "could not run here" (the verify.sh step
says why that is red rather than skipped), and the selftest records the cases that
need it as skipped there, naming why.

Exit codes: 0 every case held - 1 a case failed or could not run - 2 usage error.
"""
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
ACTION_REL = os.path.join(".github", "actions", "browser-install", "action.yml")

# GitHub's `shell: bash`, as its documentation spells the command it runs.
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
# Where the allowed real tools (ALLOWED_TOOLS) are looked up, and nowhere else, so
# neither a developer's PATH nor the sweep's shims decide which binary is linked. A
# step's own PATH is the fixture's `bin/` alone.
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
STEP_TIMEOUT = 120
# What a stub exits with when it refuses, a code none of them otherwise returns.
REFUSED_EXIT = 99

USAGE = "usage: check-browser-install.py [--action PATH | --selftest]\n"


# --- reading the action ----------------------------------------------------------
# A READER FOR THE SUBSET action.yml IS WRITTEN IN, not a YAML parser: scalars,
# one-level mappings (`env:`, `with:`) and literal block scalars (`run: |`). Any other
# shape inside a step is a problem with its line, never a step read as empty, because
# a step read as empty would run nothing and pass.
def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _scalar(value):
    """A plain or quoted scalar's text."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _block(lines, i, key_indent):
    """(the lines of a value nested under a key at `key_indent`, next index)."""
    body = []
    while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > key_indent):
        body.append(lines[i])
        i += 1
    return body, i


def read_step(lines):
    """(step dict, problem) for one item of `steps:`, its first key already
    re-indented to the depth of the others; exactly one is None."""
    key_indent = _indent(lines[0])
    step = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if _indent(line) != key_indent:
            return None, "a line at a depth no key of the step has: %r" % (line,)
        key, sep, rest = line.strip().partition(":")
        if not sep:
            return None, "a step line that is not `key: value`: %r" % (line,)
        rest = rest.strip()
        if key in step:
            return None, "the step carries `%s` twice" % (key,)
        body, i = _block(lines, i + 1, key_indent)
        if rest in ("|", "|-"):
            while body and not body[-1].strip():
                body.pop()
            if not body:
                return None, "`%s: |` holds no lines" % (key,)
            cut = _indent(next(b for b in body if b.strip()))
            step[key] = "\n".join(b[cut:] if b.strip() else "" for b in body) + "\n"
        elif rest == "":
            mapping = {}
            for inner in body:
                text = inner.strip()
                if not text or text.startswith("#"):
                    continue
                name, isep, value = text.partition(":")
                if not isep or value.strip() in ("", "|", "|-", ">", ">-"):
                    return None, ("`%s:` holds a line that is not a scalar "
                                  "`key: value`: %r" % (key, inner))
                mapping[name.strip()] = _scalar(value)
            if not mapping:
                return None, "`%s:` holds nothing" % (key,)
            step[key] = mapping
        elif rest[0] in "|>":
            return None, ("`%s: %s` is a block scalar this reader does not read"
                          % (key, rest))
        elif body and any(b.strip() for b in body):
            return None, "`%s` has a value and nested lines" % (key,)
        else:
            step[key] = _scalar(rest)
    return step, None


def read_steps(text):
    """{"steps": [dict], "problem": str or None} for an action's `runs.steps`.

    A comment line at the steps' own depth or shallower is a YAML comment between
    steps; one deeper than that inside a `run: |` block is a line of the script,
    which is how YAML reads it too."""
    lines = text.splitlines()
    runs = next((i for i, ln in enumerate(lines) if ln.rstrip() == "runs:"), None)
    if runs is None:
        return {"steps": [], "problem": "no top-level `runs:`"}
    head = next((i for i in range(runs + 1, len(lines))
                 if lines[i].strip() == "steps:"), None)
    if head is None:
        return {"steps": [], "problem": "`runs:` holds no `steps:`"}
    base = _indent(lines[head])
    items, depth = [], None
    for line in lines[head + 1:]:
        if not line.strip():
            if items:
                items[-1].append(line)
            continue
        ind = _indent(line)
        if line.lstrip().startswith("#") and (depth is None or ind <= depth):
            continue
        if ind <= base:
            break
        if depth is None:
            depth = ind
        if ind < depth:
            return {"steps": [], "problem": "a line shallower than the steps: %r"
                    % (line,)}
        if ind == depth:
            if not line.lstrip().startswith("- "):
                return {"steps": [], "problem": "a line at the steps' depth that "
                        "opens no step: %r" % (line,)}
            items.append([" " * (ind + 2) + line.lstrip()[2:]])
        else:
            items[-1].append(line)
    if not items:
        return {"steps": [], "problem": "`steps:` holds no step"}
    steps = []
    for n, item in enumerate(items):
        step, problem = read_step(item)
        if problem is not None:
            return {"steps": [], "problem": "step %d: %s" % (n + 1, problem)}
        steps.append(step)
    ids = [s["id"] for s in steps if "id" in s]
    twice = sorted(set(i for i in ids if ids.count(i) > 1))
    if twice:
        return {"steps": [], "problem": "step id(s) used twice: %s" % (", ".join(twice),)}
    return {"steps": steps, "problem": None}


def step_by_id(steps, sid):
    return next((s for s in steps if s.get("id") == sid), None)


def read_inputs(text):
    """{input: {key: value}} for an action's top-level `inputs:`, scalars as
    text; a key holding a block (`description: >-`) is read as present with no
    text, since no case reads a description."""
    lines = text.splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.rstrip() == "inputs:"), None)
    if head is None:
        return {}
    inputs, name, name_indent, key_indent = {}, None, None, None
    for line in lines[head + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = _indent(line)
        if ind == 0:
            break
        if name_indent is None:
            name_indent = ind
        if ind == name_indent:
            name, key_indent = line.strip().rstrip(":"), None
            inputs[name] = {}
            continue
        if key_indent is None:
            key_indent = ind
        if ind == key_indent:
            key, _sep, value = line.strip().partition(":")
            value = value.strip()
            inputs[name][key] = "" if value[:1] in ("|", ">") else _scalar(value)
    return inputs


def read_action(text):
    """{"steps", "inputs", "problem"}: what every case is handed."""
    got = read_steps(text)
    return {"steps": got["steps"], "inputs": read_inputs(text), "problem": got["problem"]}


# --- the stubs ---------------------------------------------------------------------
# Each stub is a two-line shell script in the fixture's `bin/` that runs THIS file
# with `--stub NAME`, so the stubs' code is one module with the check and has no file
# of its own to drift from it. Ownership is a ledger (`owners.json` in the fixture),
# because the stubs run as one real user and must behave as root under `sudo` and as
# the runner user otherwise. A path with no entry is the runner user's: HOME, and
# whatever the cache restored.
#
# EVERY STUB THAT WRITES WRITES ONLY UNDER THE FIXTURE ROOT (`_inside_fixture`), and
# one asked to write elsewhere, or asked for a shape the action does not use, writes
# the request to the refusal ledger and exits REFUSED_EXIT. Every case reads that
# ledger, so a refusal is red even where the step swallows the exit code.
def _stub_root():
    return os.environ["STUB"]


def _inside_fixture(path):
    """True when `path`, links resolved, lies under the fixture root (never the
    root itself): the one place a stub may write."""
    root = os.path.realpath(os.environ["FIXTURE_ROOT"])
    return os.path.realpath(os.path.abspath(path)).startswith(root + os.sep)


def _refuse(what):
    """REFUSED_EXIT, with `what` in the refusal ledger and on stderr."""
    with io.open(os.environ["STUB_REFUSED"], "a", encoding="utf-8") as fh:
        fh.write(what + "\n")
    sys.stderr.write("check-browser-install: refused %s\n" % (what,))
    return REFUSED_EXIT


def _outside(name, paths):
    """REFUSED_EXIT for the first of `paths` outside the fixture, else None."""
    for path in paths:
        if not _inside_fixture(path):
            return _refuse("%s writing %s, outside the fixture" % (name, path))
    return None


def _caller():
    return os.environ.get("STUB_USER", "runner")


def _owners():
    try:
        with io.open(os.path.join(_stub_root(), "owners.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (IOError, OSError, ValueError):
        return {}


def _owner(path):
    return _owners().get(os.path.abspath(path).rstrip("/") or "/", "runner")


def _record(path, who):
    data = _owners()
    data[os.path.abspath(path).rstrip("/")] = who
    with io.open(os.path.join(_stub_root(), "owners.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, sort_keys=True))


def _writable(directory):
    return _caller() == "root" or _owner(directory) == _caller()


def _log(line):
    with io.open(os.path.join(_stub_root(), "log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _apt_index(lists):
    """{package: (file, size, [dependency])} from the first `*_Packages*` index in
    `lists`, or None when there is none."""
    names = sorted(n for n in os.listdir(lists) if "_Packages" in n) \
        if os.path.isdir(lists) else []
    if not names:
        return None
    index = {}
    with io.open(os.path.join(lists, names[0]), encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if parts:
                deps = parts[3].split(",") if len(parts) > 3 else []
                index[parts[0]] = (parts[1], int(parts[2]), [d for d in deps if d])
    return index


def _apt_closure(index, pkgs, installed):
    """(the packages an install of `pkgs` needs, the first it cannot locate)."""
    closure, todo = [], list(pkgs)
    while todo:
        name = todo.pop(0)
        if name in installed or name in closure:
            continue
        if name not in index:
            return closure, name
        closure.append(name)
        todo.extend(index[name][2])
    return closure, None


def stub_apt_get(argv):
    """apt-get as the action uses it, modelled on apt's source: a `.deb` in the
    archives directory whose size matches the index is taken as downloaded, one
    whose size does not is deleted and queued (pkgAcqArchive::QueueNext);
    `--print-uris` prints the queue only, `--download-only` fetches it, and
    `--no-download` refuses while it is not empty."""
    opts, flags, words = {}, set(), []
    i = 0
    while i < len(argv):
        if argv[i] == "-o":
            key, _sep, value = argv[i + 1].partition("=")
            opts[key] = value
            i += 2
            continue
        (flags.add if argv[i].startswith("-") else words.append)(argv[i])
        i += 1
    stub = _stub_root()
    lists = opts.get("Dir::State::Lists", os.path.join(stub, "sys", "lists"))
    archives = opts.get("Dir::Cache::Archives", os.path.join(stub, "sys", "archives"))
    down = os.path.exists(os.path.join(stub, "archive", "down"))
    refused = _outside("apt-get", (lists, archives))
    if refused is not None:
        return refused
    cmd, pkgs = words[0], words[1:]
    if cmd == "update":
        if down:
            _log("update-refused")
            print("E: Failed to fetch http://stub/dists/noble/InRelease")
            return 100
        if not _writable(lists):
            print("E: Could not open lock file %slock - open (13: Permission denied)"
                  % (lists,))
            return 100
        dest = os.path.join(lists, "stub_dists_noble_main_binary-amd64_Packages")
        shutil.copyfile(os.path.join(stub, "archive", "index"), dest)
        _record(dest, _caller())
        _log("update")
        return 0
    if cmd != "install":
        print("stub apt-get: a command the action does not use: %r" % (cmd,))
        return 2
    index = _apt_index(lists)
    if index is None:
        print("E: Unable to locate package %s" % (pkgs[0],))
        return 100
    with io.open(os.path.join(stub, "installed"), encoding="utf-8") as fh:
        installed = set(fh.read().split())
    closure, unknown = _apt_closure(index, pkgs, installed)
    if unknown is not None:
        print("E: Unable to locate package %s" % (unknown,))
        return 100
    queue = []
    for name in closure:
        fname, size, _deps = index[name]
        path = os.path.join(archives, fname)
        if os.path.exists(path):
            if os.path.getsize(path) == size:
                continue
            os.remove(path)
            _log("dropped-short %s" % (fname,))
        queue.append((fname, size))
    if "--print-uris" in flags:
        for fname, size in queue:
            print("'http://stub/pool/%s' %s %d MD5Sum:00" % (fname, fname, size))
        return 0
    if "--download-only" in flags:
        for fname, _size in queue:
            src = os.path.join(stub, "archive", "pool", fname)
            if down or not os.path.exists(src):
                _log("fetch-failed %s" % (fname,))
                print("E: Failed to fetch http://stub/pool/%s  404  Not Found" % (fname,))
                return 100
            if not _writable(archives):
                print("E: Could not open file %s - open (13: Permission denied)"
                      % (fname,))
                return 100
            shutil.copyfile(src, os.path.join(archives, fname))
            _record(os.path.join(archives, fname), _caller())
            _log("fetch %s" % (fname,))
        return 0
    if "--no-download" in flags:
        if queue:
            print("E: Can't download %s with --no-download" % (queue[0][0],))
            return 100
        for name in closure:
            with io.open(os.path.join(archives, index[name][0]), encoding="utf-8") as fh:
                if fh.read().startswith("CORRUPT"):
                    _log("install-failed %s" % (index[name][0],))
                    print("dpkg-deb: error: '%s' is not a Debian format archive"
                          % (index[name][0],))
                    return 100
        _log("install %s" % (" ".join(closure),))
        return 0
    print("stub apt-get: an install in no mode the action uses")
    return 2


def stub_mkdir(argv):
    """mkdir [-p] DIR...: a missing component is made only in a directory the
    caller may write, and is the caller's."""
    targets = [a for a in argv if not a.startswith("-")]
    refused = _outside("mkdir", targets)
    if refused is not None:
        return refused
    for target in targets:
        target = os.path.abspath(target)
        missing, cur = [], target
        while not os.path.isdir(cur):
            missing.append(cur)
            cur = os.path.dirname(cur)
        for path in reversed(missing):
            if not _writable(os.path.dirname(path)):
                sys.stderr.write("mkdir: cannot create directory '%s': Permission "
                                 "denied\n" % (path,))
                return 1
            os.mkdir(path)
            _record(path, _caller())
    return 0


def stub_cp(argv):
    """cp [-a|-p|-R] SRC... DIR, as GNU cp does it for the shapes the action has
    used: a source spelled `D/.` copies D's contents and, under -a, gives DIR D's
    owner (the runner showed this: after `sudo cp -a lists/. set/lists/` the runner
    user could not make a directory in set/lists). What root copies with ownership
    preserved is its source's owner's; anything else is the caller's."""
    flags = "".join(a[1:] for a in argv if a.startswith("-") and not a.startswith("--"))
    words = [a for a in argv if not a.startswith("-")]
    recursive = any(f in flags for f in "aRr")
    preserve = any(f in flags for f in "ap")
    srcs, dst = words[:-1], words[-1]
    refused = _outside("cp", (dst,))
    if refused is not None:
        return refused
    if not os.path.isdir(dst):
        sys.stderr.write("cp: the stub copies into a directory only: %s\n" % (dst,))
        return 1

    def owner_for(src):
        return _owner(src) if preserve and _caller() == "root" else _caller()

    def put(src, target):
        if not _writable(os.path.dirname(target)):
            sys.stderr.write("cp: cannot create '%s': Permission denied\n" % (target,))
            return 1
        if os.path.isdir(src):
            if not recursive:
                sys.stderr.write("cp: -r not specified; omitting directory '%s'\n"
                                 % (src,))
                return 1
            if not os.path.isdir(target):
                os.mkdir(target)
            _record(target, owner_for(src))
            for name in sorted(os.listdir(src)):
                if put(os.path.join(src, name), os.path.join(target, name)):
                    return 1
            return 0
        shutil.copyfile(src, target)
        _record(target, owner_for(src))
        return 0

    for src in srcs:
        if not os.path.exists(src):
            sys.stderr.write("cp: cannot stat '%s': No such file or directory\n" % (src,))
            return 1
        if src.rstrip("/").endswith("/.") and os.path.isdir(src):
            if not recursive:
                sys.stderr.write("cp: -r not specified; omitting directory '%s'\n"
                                 % (src,))
                return 1
            if "a" in flags and _caller() == "root":
                _record(dst, _owner(src.rstrip("/")[:-2]))
            for name in sorted(os.listdir(src)):
                if put(os.path.join(src, name), os.path.join(dst, name)):
                    return 1
        elif put(src, os.path.join(dst, os.path.basename(src.rstrip("/")))):
            return 1
    return 0


def stub_chown(argv):
    """chown [-R] UID:GID PATH...: root only. The stub knows one other user, the
    runner, whose numeric id is this process's own."""
    args = [a for a in argv if not a.startswith("-")]
    spec, paths = args[0], args[1:]
    refused = _outside("chown", paths)
    if refused is not None:
        return refused
    if _caller() != "root":
        sys.stderr.write("chown: changing ownership: Operation not permitted\n")
        return 1
    who = "runner" if spec.split(":")[0] == str(os.getuid()) else "uid%s" % (spec,)
    for top in paths:
        for dirpath, dirnames, filenames in os.walk(top):
            _record(dirpath, who)
            for name in dirnames + filenames:
                _record(os.path.join(dirpath, name), who)
    return 0


def stub_rm(argv):
    """rm [-r|-R] [-f] PATH...: every path is checked before any is removed, so a
    refused one removes nothing. Removing from a directory the caller may not
    write is refused as the kernel refuses it."""
    flags = "".join(a[1:] for a in argv if a.startswith("-") and a != "--")
    targets = [a for a in argv if not a.startswith("-")]
    refused = _outside("rm", targets)
    if refused is not None:
        return refused
    for target in targets:
        path = os.path.abspath(target)
        if not os.path.lexists(path):
            if "f" in flags:
                continue
            sys.stderr.write("rm: cannot remove '%s': No such file or directory\n"
                             % (target,))
            return 1
        if not _writable(os.path.dirname(path)):
            sys.stderr.write("rm: cannot remove '%s': Permission denied\n" % (target,))
            return 1
        if os.path.isdir(path) and not os.path.islink(path):
            if "r" not in flags and "R" not in flags:
                sys.stderr.write("rm: cannot remove '%s': Is a directory\n" % (target,))
                return 1
            shutil.rmtree(path)
        else:
            os.remove(path)
    return 0


def _bre(pattern):
    """A POSIX basic regular expression as Python's `re` spells it, for what the
    action's scripts use: `\\(...\\)` groups, bracket expressions, `.`, `*`, `^`
    and `$`. Every other character is literal, as BRE reads it."""
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            out.append(nxt if nxt in "(){}" else re.escape(nxt))
            i += 2
        elif char == "[":
            j = i + 1 + (pattern[i + 1:i + 2] == "^")
            end = pattern.find("]", j + (pattern[j:j + 1] == "]"))
            if end < 0:
                return None
            body = pattern[i + 1:end]
            out.append("[%s]" % (body.replace("\\", "\\\\").replace("[", "\\["),))
            i = end + 1
        else:
            out.append(char if char in ".*^$" else re.escape(char))
            i += 1
    return "".join(out)


def _sed_parts(script):
    """`script` split at each `/` no backslash escapes."""
    parts, cur, i = [], [], 0
    while i < len(script):
        if script[i] == "\\" and i + 1 < len(script):
            cur.append(script[i:i + 2])
            i += 2
            continue
        if script[i] == "/":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(script[i])
        i += 1
    return parts + ["".join(cur)]


def _sed_replace(text, match):
    """A sed replacement: `\\N` the group, `&` the match, `\\c` the character."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append((match.group(int(nxt)) or "") if nxt.isdigit() else nxt)
            i += 2
            continue
        out.append(match.group(0) if text[i] == "&" else text[i])
        i += 1
    return "".join(out)


def stub_sed(argv):
    """sed as the action uses it, `sed -n 's/RE/REPL/p'` over stdin: the first
    match on each line replaced and that line printed. Any other shape is
    refused - a file operand, `-i`, a `w` command - so no sed here writes."""
    parts = _sed_parts(argv[1]) if len(argv) == 2 and argv[0] == "-n" else []
    regex = (_bre(parts[1]) if len(parts) == 4 and parts[0] == "s" and parts[3] == "p"
             else None)
    if regex is None:
        return _refuse("sed %s" % (" ".join(argv),))
    compiled = re.compile(regex)
    lines = sys.stdin.buffer.read().decode("utf-8", "replace").splitlines()
    for line in lines:
        match = compiled.search(line)
        if match:
            sys.stdout.write(line[:match.start()] + _sed_replace(parts[2], match)
                             + line[match.end():] + "\n")
    return 0


# What `npx playwright install-deps --dry-run chromium` prints on a runner that is
# not root, as node_modules/playwright-core/lib/server/registry/dependencies.js
# builds it (`installDependenciesLinux`, `transformCommandsForRoot`): written from
# that source, not captured from a run. The image lacks libA and libB; libD it has.
_DRY_RUN = ('sudo -- sh -c "apt-get update&& apt-get install -y '
            '--no-install-recommends libA libB libD"\n')


def stub_npx(argv):
    """npx as the `sysdeps` step uses it, and nothing else: the dry run."""
    if argv != ["playwright", "install-deps", "--dry-run", "chromium"]:
        return _refuse("npx %s" % (" ".join(argv),))
    sys.stdout.write(_DRY_RUN)
    return 0


def stub_dpkg_query(argv):
    """`dpkg-query -W -f='${Status}' PKG`, answered from the fixture's list of
    installed packages."""
    if len(argv) != 3 or argv[:2] != ["-W", "-f=${Status}"]:
        return _refuse("dpkg-query %s" % (" ".join(argv),))
    with io.open(os.path.join(_stub_root(), "installed"), encoding="utf-8") as fh:
        installed = set(fh.read().split())
    if argv[2] in installed:
        sys.stdout.write("install ok installed")
        return 0
    sys.stderr.write("dpkg-query: no packages found matching %s\n" % (argv[2],))
    return 1


STUBS = {"apt-get": stub_apt_get, "mkdir": stub_mkdir, "cp": stub_cp,
         "chown": stub_chown, "rm": stub_rm, "sed": stub_sed, "npx": stub_npx,
         "dpkg-query": stub_dpkg_query}

# THE REAL TOOLS A STEP MAY START, each linked into the fixture's `bin/` by name from
# SYSTEM_PATH. Every one reads its input and writes its standard output, and nothing
# else: a tool that can write a file (sed's `-i`, tee, touch) is a stub or absent.
ALLOWED_TOOLS = (
    ("ls", "lists a directory: the install step's test for a restored index"),
    ("id", "prints the runner user's ids, for the chown that hands the set over"),
    ("tr", "a filter: the dry run's quotes stripped"),
    ("wc", "a filter: the dry run's packages counted for the log"),
    ("cut", "a filter: the key's hash cut to its first sixteen characters"),
    ("sha256sum", "a filter: the hash of the missing list in the system packages' key"),
)

# The stubs written as shell rather than served by STUBS, so a name the reader takes.
SHELL_STUBS = ("sudo", "apt-config", "node")

# THE BUILTINS A STEP MAY CALL, each with why, and every other builtin is disabled
# before a step's first line (`_prelude`). A builtin that could start a program, read
# a file as code or evaluate a value as code is absent from this list rather than
# refused by name, and the ones here that take such an argument are held by the reader
# to the family of calls its row describes (`_builtin_call_problem`), asked of each
# word's value after quote removal. No function may take one of these names.
BUILTINS = (
    ("echo", "prints a step's log lines and the outputs it writes"),
    ("printf", "formats a line; the reader holds its format to a value known by reading "
               "that does not begin with `-`, however it is quoted, so it is never "
               "`-v`, which assigns through a name bash evaluates"),
    ("exit", "ends a step with its status, as each of the action's failures does"),
    ("set", "sets the positional parameters the install step counts; the reader holds "
            "it to a first word whose value is `--`, so no option turns on tracing or "
            "exporting"),
    ("eval", "reads the system's list directory out of the apt-config stub; the reader "
             "holds it to one word that is exactly one double-quoted command "
             "substitution calling that stub and nothing else, whose output is this "
             "file's own text"),
    ("[", "tests with -z, -n or -d, or compares with = or !=, each operator's value "
          "known by reading and each operand a word bash cannot split, so no value "
          "becomes an operator"),
    ("true", "a status: the dpkg-query of a package the image lacks is not a failure"),
)

# sudo starts, as root, only a name it finds in the fixture's `bin/`; anything else
# - a path, an option, a name that is neither a stub nor an allowed tool - is
# refused, so `sudo` is never a way past the PATH.
_SUDO = """#!/bin/sh
name=$1
case "$name" in
  ""|-*|*/*) ;;
  *)
    if [ -f "$STUB_BIN/$name" ] && [ -x "$STUB_BIN/$name" ]; then
      shift
      STUB_USER=root
      export STUB_USER
      exec "$STUB_BIN/$name" "$@"
    fi
    ;;
esac
printf 'sudo %s\\n' "$*" >> "$STUB_REFUSED"
printf 'check-browser-install: refused sudo %s\\n' "$*" >&2
exit 99
"""

# node runs only on this harness: the `-e` code is evaluated in a `vm` context whose
# `require` returns a JSON file under the fixture root and refuses every other name,
# and whose `process` carries `exit` and a copy of `env`. A `vm` context is not a
# security boundary - code written to escape it can - so this stops an ordinary edit
# (`require('fs')`, `require('child_process')`), not a hostile one.
_NODE_HARNESS = r"""'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const root = fs.realpathSync(process.env.FIXTURE_ROOT);
function refuse(what) {
  fs.appendFileSync(process.env.STUB_REFUSED, 'node ' + what + '\n');
  process.stderr.write('check-browser-install: refused node ' + what + '\n');
  process.exit(99);
}
const args = process.argv.slice(2);
if (args.length !== 2 || args[0] !== '-e') refuse(JSON.stringify(args));
function confined(name) {
  if (typeof name !== 'string' || !/^\.\.?\/.*\.json$/.test(name))
    refuse('require(' + JSON.stringify(name) + ')');
  const real = fs.realpathSync(path.resolve(name));
  if (!real.startsWith(root + path.sep))
    refuse('require(' + JSON.stringify(name) + '), outside the fixture');
  return JSON.parse(fs.readFileSync(real, 'utf8'));
}
const EXIT = {};
let code = 0;
const sandbox = {
  require: confined,
  console: {
    log: (...a) => process.stdout.write(a.join(' ') + '\n'),
    error: (...a) => process.stderr.write(a.join(' ') + '\n'),
  },
  process: {
    exit: (c) => { code = c === undefined ? 0 : c; throw EXIT; },
    env: Object.assign({}, process.env),
  },
};
try { vm.runInNewContext(args[1], sandbox); } catch (e) { if (e !== EXIT) throw e; }
process.exitCode = code;
"""


# --- the fixtures ---------------------------------------------------------------
# The packages the image lacks are libA and libB; libA needs libC, which the image
# lacks too, and libB needs libD, which the image has. So the closure is three files,
# and a dependency missing from the set is told apart from a named package missing.
PKGS = {
    "libA": ("libA_1.deb", ["libC"]),
    "libB": ("libB_1.deb", ["libD"]),
    "libC": ("libC_1.deb", []),
}
MISSING = "libA libB"
ALL = ["libA_1.deb", "libB_1.deb", "libC_1.deb"]
SET_REL = os.path.join(".cache", "chromium-sysdeps")


def _deb_bytes(name):
    return ("deb:%s:" % (name,)).ljust(64, "x")


def _write(path, text):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _exec_script(path, text):
    _write(path, text)
    os.chmod(path, 0o755)


def _index_text(packages):
    return "".join("%s %s %d %s\n" % (p, f, len(_deb_bytes(f)), ",".join(deps))
                   for p, (f, deps) in sorted(packages.items()))


def allowed_tools():
    """({name: real path}, [names not found]) for ALLOWED_TOOLS, looked up in
    SYSTEM_PATH alone."""
    found = [(name, shutil.which(name, path=SYSTEM_PATH)) for name, _why in ALLOWED_TOOLS]
    return (dict((n, p) for n, p in found if p is not None),
            sorted(n for n, p in found if p is None))


def build_base(root):
    """What every case's root holds: `bin/` - the stubs and the allowed tools,
    which is the whole of a step's PATH - `home/`, the runner's HOME, and
    `stub/` with the refusal ledger, the log, the installed packages and the
    ownership ledger. Called inside the caller's try, so a failure here still
    removes the root."""
    stub = os.path.join(root, "stub")
    binp = os.path.join(root, "bin")
    for d in (stub, os.path.join(root, "home"), binp):
        os.makedirs(d)
    for name in sorted(STUBS):
        _exec_script(os.path.join(binp, name),
                     '#!/bin/sh\nexec "$STUB_PY" "$STUB_SELF" --stub %s "$@"\n' % (name,))
    _exec_script(os.path.join(binp, "sudo"), _SUDO)
    _exec_script(os.path.join(binp, "apt-config"),
                 "#!/bin/sh\necho \"sys_lists='$STUB/sys/lists/'\"\n")
    if shutil.which("node") is not None:
        _write(os.path.join(stub, "node-harness.js"), _NODE_HARNESS)
        _exec_script(os.path.join(binp, "node"),
                     '#!/bin/sh\nexec "$STUB_NODE" "$STUB/node-harness.js" "$@"\n')
    tools, _missing = allowed_tools()
    for name, real in sorted(tools.items()):
        os.symlink(real, os.path.join(binp, name))
    for name, text in (("refused", ""), ("log", ""), ("installed", "libD\n"),
                       ("owners.json", "{}")):
        _write(os.path.join(stub, name), text)


def build_fixture(root, restored, drop=(), truncate=(), corrupt=(), stale=False,
                  down=False):
    """`root` as build_base leaves it, plus the archive, the system's apt
    directories (root's, as on the runner) and, when `restored`, the restored set
    in the runner's HOME."""
    build_base(root)
    stub = os.path.join(root, "stub")
    home = os.path.join(root, "home")
    for d in (os.path.join(stub, "archive", "pool"), os.path.join(stub, "sys", "lists"),
              os.path.join(stub, "sys", "archives")):
        os.makedirs(d)
    _write(os.path.join(stub, "owners.json"), json.dumps(dict(
        (os.path.join(stub, "sys", d), "root") for d in ("lists", "archives"))))
    archive = dict(PKGS)
    if stale:            # the archive moved libA on since the set was fetched
        archive["libA"] = ("libA_2.deb", ["libC"])
    _write(os.path.join(stub, "archive", "index"), _index_text(archive))
    for _p, (fname, _deps) in sorted(archive.items()):
        _write(os.path.join(stub, "archive", "pool", fname), _deb_bytes(fname))
    if down:
        _write(os.path.join(stub, "archive", "down"), "")
    if restored:
        saved = os.path.join(home, SET_REL)
        os.makedirs(os.path.join(saved, "debs"))
        os.makedirs(os.path.join(saved, "lists"))
        _write(os.path.join(saved, "lists", "stub_dists_noble_main_binary-amd64_Packages"),
               _index_text(PKGS))
        for name, (fname, _deps) in sorted(PKGS.items()):
            if name in drop:
                continue
            text = _deb_bytes(fname)
            if name in truncate:
                text = text[:-5]
            if name in corrupt:
                text = "CORRUPT".ljust(len(text), "x")
            _write(os.path.join(saved, "debs", fname), text)


def posix_problem():
    """Why the stubbed steps cannot run on this host, or None."""
    if os.pathsep != ":" or os.name != "posix":
        return ("the stubs are shell scripts bash executes through a colon-separated "
                "PATH, which this host (os.name %r) does not give" % (os.name,))
    if shutil.which("bash") is None:
        return "no bash on PATH, and the action's steps are `shell: bash`"
    missing = allowed_tools()[1]
    if missing:
        return ("the allowed tool(s) %s are not in %s, so a step that needs one "
                "could not find it" % (", ".join(missing), SYSTEM_PATH))
    return None


# A NAME THE SHELL CANNOT FIND IS A RED CASE, never a skipped command. bash 4 and
# later call `command_not_found_handle`, which writes the name to the refusal ledger
# even where the step discards stderr; it is exported, so a bash the step starts
# inherits it. bash 3.2 (macOS's own) has no such hook, so there the only channel is
# bash's own "command not found" line, which a step's `2>/dev/null` hides. The name
# still does not run either way: PATH holds nothing but `bin/`.
#
# THEN THE SHELL IS NARROWED BEFORE THE SCRIPT'S FIRST LINE: every variable of the
# step's environment is read-only (PATH among them, and the ones the stubs read), the
# command hash's array is unset and read-only, and every builtin BUILTINS does not
# name is disabled, `enable` last so none can be turned back on. A disabled builtin's
# name is looked up in PATH like any other, finds nothing, and is a not-found line.
# The handler ends with `(exit 127)` because `return` is one of the disabled.
_PRELUDE = """\
command_not_found_handle() {
  printf 'not found: %s\\n' "$1" >> "$STUB_REFUSED"
  printf 'check-browser-install: %s is neither a stub nor an allowed tool\\n' "$1" >&2
  (exit 127)
}
export -f command_not_found_handle
readonly -f command_not_found_handle
readonly BASH_CMDS BASH_ALIASES @ENV@
for b in $(compgen -b); do
  case " @KEEP@ enable " in
    *" $b "*) ;;
    *) enable -n "$b" ;;
  esac
done
enable -n enable
"""


def _prelude(env, drop=()):
    """The lines run before a step's script, for a step given `env`, less the lines
    of `_PRELUDE` that `drop` names - each of which must be there once."""
    names = sorted(env)
    odd = [n for n in names if not re.match(r"[A-Za-z_][A-Za-z0-9_]*\Z", n)]
    if odd:
        raise ValueError("a step's environment names %r, which no shell variable is"
                         % (odd,))
    template = _PRELUDE
    for line in drop:
        if template.count(line) != 1:
            raise ValueError("the prelude holds %r %d time(s), not once"
                             % (line, template.count(line)))
        template = template.replace(line, "")
    return (template.replace("@ENV@", " ".join(names))
            .replace("@KEEP@", " ".join(n for n, _why in BUILTINS)))


def run_script(script, env, cwd):
    """{"code", "out", "refused"} for one step's script: the reader's refusal,
    with the script never started, or the run `_run_bash` reports."""
    problems = script_problems(script)
    if problems:
        refused = ["unread: %s" % (p,) for p in problems]
        return {"code": None, "refused": refused,
                "out": "\n".join(["check-browser-install: the step was not run"]
                                 + _refusals({"refused": refused}))}
    return _run_bash(script, env, cwd)


def _run_bash(script, env, cwd, drop=(), trace=False):
    """{"code", "out", "refused"} for one script under GitHub's bash flags, the
    prelude first and stdin closed, past the reader: the exit code (None when the
    step did not finish), the combined output, and every request a stub refused
    or a name the shell did not find. Only `run_script` and the selftest call this:
    the selftest's `bk` rows show the construction holding without the reader, and
    take out the prelude's lines `drop` names to show the same line reaching past it;
    its `bq` rows ask bash, by `trace`, which commands it started."""
    path = os.path.join(cwd, "step.sh")
    _write(path, _prelude(env, drop) + ("set -x\n" if trace else "") + script)
    try:
        done = subprocess.run([shutil.which("bash")] + list(BASH_FLAGS) + [path],
                              env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=STEP_TIMEOUT)
        code, out = done.returncode, done.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, out = None, "the step did not finish in %ds" % (STEP_TIMEOUT,)
    with io.open(env["STUB_REFUSED"], encoding="utf-8") as fh:
        refused = [ln for ln in fh.read().splitlines() if ln.strip()]
    refused += ["not found: %s" % (ln.strip(),) for ln in out.splitlines()
                if ln.rstrip().endswith(": command not found")]
    return {"code": code, "out": out, "refused": refused}


def _refusals(result):
    """The refusals of one run, each worded as a reason the case is red."""
    return [("the reader refused the step, so it was not run: %s" % (r[len("unread: "):],))
            if r.startswith("unread: ")
            else "the step reached what no stub serves: %s" % (r,)
            for r in result["refused"]]


# --- reading a step's shell ---------------------------------------------------------
# A READER FOR THE SHELL SUBSET THE ACTION IS WRITTEN IN, not a bash parser, for the
# same reason as the YAML reader above: every shape it does not read is a problem
# with its text, never a script read as harmless. It finds every command word - at the
# top, in a function body, inside each `$( )` - and what it reads is a positive rule:
# a command word is a bare name on the vocabulary, a variable assigned is the
# script's own (lowercase), a redirection goes where `_redirection_problem` says.
#
# A WORD IS JUDGED BY WHAT BASH HANDS ON, not by how it is written. `_word` reads each
# word into the parts bash reads it as - unquoted text, single-quoted text, a
# double-quoted string, an expansion - and `_bash_reading` is the one place those parts
# become what every rule asks about: the value left after quote removal, or None where
# reading cannot know it (an expansion, or an unquoted character bash expands); the
# one expansion the word is, when it is exactly that and nothing else; and whether it
# can become more or fewer than one argument. A rule asks those, never the spelling,
# so `'-v'` is the option `-v` to it as it is to bash. Only what bash itself recognises
# by spelling is read by spelling (`plain`): a reserved word, an assignment, a
# function's name and a `for` name are each recognised by bash only when written
# unquoted, and the reader recognises them the same way. The selftest's `bq1` and
# `bq2` respell every bare word of the reader's tables to hold that.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OWN_NAME = re.compile(r"[a-z_][a-z0-9_]*\Z")
_BARE = re.compile(r"(?:\[|[A-Za-z0-9_][A-Za-z0-9_+-]*)\Z")
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")
_REDIRECTION = re.compile(r"([0-9]*)(>>|>&|>\||>|<<|<&|<>|<)")
_FD_NAME = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}\Z")
_WORD_END = " \t\n;&|()<>"
_SPECIAL_PARAMS = "#*@?123456789"
_OPENS = ("if", "while", "until", "{")
_CLOSES = {"fi": ("if",), "done": ("for", "while", "until"), "}": ("{",),
           "esac": ("case",)}
_KEEP_CMD = ("then", "elif", "else", "do", "!")
_NOT_READ = ("function", "select", "coproc", "time", "[[", "]]", "((", "))", "in",
             "let", "declare", "typeset", "local")
_TEST_UNARY = ("-z", "-n", "-d")
_TEST_BINARY = ("=", "!=")


# Inside double quotes a backslash is removed only before these; before any other
# character bash keeps it, so `"\-v"` is the three characters `\-v`.
_DQ_ESCAPES = '$`"\\'


def _quoted_double(text, i):
    """(pieces, index after the closing quote, problem) for the `"` at i. A piece is
    ("lit", text after bash's backslash removal) or ("exp", expansion)."""
    pieces, j = [], i + 1
    while j < len(text):
        char = text[j]
        if char == '"':
            return pieces, j + 1, None
        if char == "\\":
            nxt = text[j + 1:j + 2]
            if nxt != "\n":          # a backslash-newline is a line joined: both go
                pieces.append(("lit", nxt if nxt and nxt in _DQ_ESCAPES else "\\" + nxt))
            j += 2
            continue
        if char == "$":
            got, j, problem = _dollar(text, j)
            if problem is not None:
                return pieces, j, problem
            pieces.append(("exp", got))
            continue
        if char == "`":
            return pieces, j, "a backquoted command substitution"
        if char == "\n":
            return pieces, j, "a double-quoted string running past its line"
        pieces.append(("lit", char))
        j += 1
    return pieces, j, "a double-quoted string that never closes"


def _expansion(kind, name=None, operator=None, subs=()):
    """An expansion as a word's parts carry it: "sub" (a `$( )`, its token list in
    `subs`) or "param" (`name`, with `operator` None for `$name` and `${name}`), and
    the token lists of every command substitution inside it."""
    return {"kind": kind, "name": name, "operator": operator, "subs": list(subs)}


def _pieces_subs(pieces):
    return [s for kind, piece in pieces if kind == "exp" for s in piece["subs"]]


def _braced(text, i):
    """(expansion, index after `}`, problem) for a `${` whose name starts at i:
    `${name}`, `${name:-word}` or `${name:+word}` and nothing else, since every
    other operator either evaluates arithmetic or reads a value as a name."""
    name = _IDENT.match(text, i)
    if name is None:
        return None, i, "a parameter expansion this reader does not read: %r" % (
            text[i - 2:i + 10],)
    j = name.end()
    if text[j:j + 1] == "}":
        return _expansion("param", name.group(0)), j + 1, None
    if text[j:j + 2] not in (":-", ":+"):
        return None, j, "a parameter expansion operator this reader does not read: %r" % (
            text[i - 2:j + 3],)
    operator, subs, j = text[j:j + 2], [], j + 2
    while j < len(text) and text[j] != "}":
        char = text[j]
        if char == "$":
            got, j, problem = _dollar(text, j)
            got = got["subs"] if got is not None else []
        elif char == '"':
            got, j, problem = _quoted_double(text, j)
            got = _pieces_subs(got)
        elif char == "'":
            end = text.find("'", j + 1)
            got, j, problem = [], end + 1, (None if end > 0 and "\n" not in text[j:end]
                                            else "a single quote that never closes")
        elif char in "`\\\n":
            got, problem = [], "%r inside a parameter expansion" % (char,)
        else:
            got, j, problem = [], j + 1, None
        if problem is not None:
            return None, j, problem
        subs.extend(got)
    if j >= len(text):
        return None, j, "a parameter expansion that never closes"
    return _expansion("param", name.group(0), operator, subs), j + 1, None


def _dollar(text, i):
    """(expansion, index after it, problem) for the `$` at i. A command
    substitution's token list is read by the parser as commands of their own."""
    nxt = text[i + 1:i + 2]
    if nxt == "(":
        if text[i + 2:i + 3] == "(":
            return None, i, "an arithmetic expansion"
        tokens, j, problem = _lex(text, i + 2, True)
        return _expansion("sub", subs=[tokens]), j, problem
    if nxt == "{":
        return _braced(text, i + 2)
    name = _IDENT.match(text, i + 1)
    if name is not None:
        return _expansion("param", name.group(0)), name.end(), None
    if nxt and nxt in _SPECIAL_PARAMS:
        return _expansion("param", nxt), i + 2, None
    return None, i, "a `$` this reader does not read: %r" % (text[i:i + 3],)


def _expands_unquoted(unquoted):
    """True when the word's unquoted characters (each quoted one written as NUL)
    can make bash expand it - a pattern, a brace list, a home directory - so that no
    value is known by reading. A `[` or `{` with nothing after it to close it is
    left as it is by bash, which is how `[` stands as a command word."""
    if any(c in unquoted for c in "*?~"):
        return True
    for opening, closing in ("[]", "{}"):
        at = unquoted.find(opening)
        if at >= 0 and closing in unquoted[at + 1:]:
            return True
    return False


def _bash_reading(parts):
    """What bash hands on for a word read into `parts` - ("lit", unquoted text),
    ("sq", text), ("dq", pieces) or ("exp", expansion) - as {"value": the text after
    quote removal, or None when an expansion or an unquoted character bash expands
    makes it unknowable by reading; "sole": the expansion, when the word is exactly
    one double-quoted expansion and nothing else; "split": True when bash can make
    it more or fewer than one argument}. Every rule asks this, never the spelling."""
    value, split = [], False
    for kind, part in parts:
        if kind == "exp":
            value, split = None, True
        elif kind == "dq":
            if value is not None and all(k == "lit" for k, _p in part):
                value.append("".join(p for _k, p in part))
            else:
                value = None
        elif value is not None:
            value.append(part)
    if _expands_unquoted("".join(p if k == "lit" else "\0" for k, p in parts)):
        value, split = None, True
    sole = None
    if len(parts) == 1 and parts[0][0] == "dq" and len(parts[0][1]) == 1 \
            and parts[0][1][0][0] == "exp":
        sole = parts[0][1][0][1]
    return {"value": None if value is None else "".join(value), "sole": sole,
            "split": split}


def _word(text, i):
    """(word, index after it, problem). A word is `_bash_reading`'s answer for it,
    plus {"text": its spelling, for messages; "plain": True when it is nothing but
    unquoted literal characters, which is how bash itself recognises a reserved word,
    an assignment and a function's name; "subs": the token lists of its command
    substitutions}."""
    start, parts = i, []
    while i < len(text) and text[i] not in _WORD_END:
        char = text[i]
        if char == "'":
            end = text.find("'", i + 1)
            if end < 0 or "\n" in text[i:end]:
                return None, i, "a single quote that never closes on its line"
            parts.append(("sq", text[i + 1:end]))
            i = end + 1
        elif char == '"':
            got, i, problem = _quoted_double(text, i)
            if problem is not None:
                return None, i, problem
            parts.append(("dq", got))
        elif char == "$":
            got, i, problem = _dollar(text, i)
            if problem is not None:
                return None, i, problem
            parts.append(("exp", got))
        elif char in "\\`":
            return None, i, ("a backslash outside quotes" if char == "\\"
                             else "a backquoted command substitution")
        else:
            if parts and parts[-1][0] == "lit":
                parts[-1] = ("lit", parts[-1][1] + char)
            else:
                parts.append(("lit", char))
            i += 1
    subs = [s for kind, part in parts
            for s in (part["subs"] if kind == "exp"
                      else _pieces_subs(part) if kind == "dq" else [])]
    word = _bash_reading(parts)
    word.update({"text": text[start:i], "plain": [k for k, _p in parts] == ["lit"],
                 "subs": subs})
    return word, i, None


def _shown(word):
    """A word as a message names it: its value when reading knows it."""
    return word["text"] if word["value"] is None else word["value"]


def _lex(text, i, nested):
    """(tokens, index after them, problem) from i to the end, or - `nested`, inside
    a `$( )` - to the `)` closing it. A token is ("word", word), ("op", text),
    ("redir", (fd, operator, target word)) or ("nl", "\\n")."""
    tokens, depth = [], 0
    while i < len(text):
        char = text[i]
        if char in " \t":
            i += 1
            continue
        if char == "\n":
            tokens.append(("nl", "\n"))
            i += 1
            continue
        if char == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        redir = _REDIRECTION.match(text, i)
        if redir is not None:
            j = redir.end()
            while j < len(text) and text[j] in " \t":
                j += 1
            target, j, problem = _word(text, j)
            if problem is not None:
                return tokens, j, problem
            if not target["text"]:
                return tokens, j, "a redirection with no target"
            tokens.append(("redir", (redir.group(1), redir.group(2), target)))
            i = j
            continue
        two = text[i:i + 2]
        if text[i:i + 3] == ";;&" or two in (";&", "|&", "&>") or (char == "&"
                                                                    and two != "&&"):
            return tokens, i, "%r, a form this reader does not read" % (text[i:i + 3],)
        if two in ("&&", "||", ";;"):
            tokens.append(("op", two))
            i += 2
            continue
        if char in ";|":
            tokens.append(("op", char))
            i += 1
            continue
        if char == "(":
            depth += 1
            tokens.append(("op", char))
            i += 1
            continue
        if char == ")":
            if nested and depth == 0:
                return tokens, i + 1, None
            depth -= 1
            tokens.append(("op", char))
            i += 1
            continue
        word, i, problem = _word(text, i)
        if problem is not None:
            return tokens, i, problem
        if text[i:i + 1] in ("<", ">") and _FD_NAME.match(word["text"]):
            return tokens, i, ("a `%s` against a redirection, which bash 4.1 and later "
                               "read as a descriptor assigned to that name (the bash "
                               "manual's REDIRECTION section)" % (word["text"],))
        tokens.append(("word", word))
    if nested:
        return tokens, i, "a command substitution that never closes"
    return tokens, i, None


def _redirection_problem(fd, operator, target):
    """Why a redirection is refused, or None: only to another descriptor, to
    `/dev/null`, or appended to the step's output file, whose path the step's
    read-only environment fixes."""
    if fd not in ("", "1", "2"):
        return "a redirection of descriptor %s" % (fd,)
    if operator == ">&" and target["value"] in ("1", "2"):
        return None
    if operator in (">", ">>") and (target["value"] == "/dev/null"
                                    or _is_param(target["sole"], "GITHUB_OUTPUT")):
        return None
    return "a redirection %s%s %s, which goes nowhere this reader allows" % (
        fd, operator, target["text"])


def _is_param(expansion, name):
    """True when `expansion` is the plain value of the parameter `name`."""
    return (expansion is not None and expansion["kind"] == "param"
            and expansion["name"] == name and expansion["operator"] is None)


def _innermost(stack):
    """The construct opened last and not yet closed, or None."""
    return stack[-1] if stack else None


def _parse(tokens, nested=False):
    """{"calls": [(name, [argument words])], "defs": [function names], "problems"}
    for one token list, its substitutions read as command lists of their own."""
    calls, defs, problems, stack = [], [], [], []
    state, call, i = "cmd", None, 0

    def read_subs(word):
        for sub in word["subs"]:
            got = _parse(sub, True)
            calls.extend(got["calls"])
            defs.extend(got["defs"])
            problems.extend(got["problems"])

    while i < len(tokens):
        kind, value = tokens[i]
        i += 1
        if kind == "nl" or (kind == "op" and value in (";", "&&", "||", "|")):
            if state == "pattern" and value in ("\n", "|"):
                continue
            if state in ("for_name", "for_in", "case_word", "case_in", "pattern") \
                    or (state == "cmd" and value not in ("\n", ";")):
                problems.append("%r where this reader expects a command or a word"
                                % (value,))
            state, call = "cmd", None
            continue
        if kind == "op" and value == ";;":
            if _innermost(stack) == "case" and state in ("cmd", "args", "after",
                                                         "assign"):
                state, call = "pattern", None
            else:
                problems.append("`;;` outside a `case`")
            continue
        if kind == "op" and value == ")" and state == "pattern":
            state = "cmd"
            continue
        if kind == "op":
            problems.append("%r: a subshell or a parenthesis this reader does not read"
                            % (value,))
            continue
        if kind == "redir":
            fd, operator, target = value
            read_subs(target)
            problem = _redirection_problem(fd, operator, target)
            if problem is None and state not in ("args", "after"):
                problem = "a redirection before the command it belongs to"
            if problem is not None:
                problems.append(problem)
            continue
        word = value
        read_subs(word)
        text = word["text"]
        reserved = word["plain"] and state == "cmd"
        if reserved and text in _OPENS + _KEEP_CMD:
            if text in _OPENS:
                stack.append(text)
            continue
        if reserved and text in _CLOSES or (state == "pattern" and word["plain"]
                                            and text == "esac"):
            if not stack or stack[-1] not in _CLOSES[text]:
                problems.append("`%s` closing nothing it can close" % (text,))
            else:
                stack.pop()
            state = "after"
            continue
        if reserved and text in ("for", "case"):
            if nested and text == "case":
                problems.append("a `case` inside a command substitution")
            stack.append(text)
            state = "for_name" if text == "for" else "case_word"
            continue
        if reserved and text in _NOT_READ:
            problems.append("`%s`, a form this reader does not read" % (text,))
            continue
        if state == "cmd" and tokens[i:i + 2] == [("op", "("), ("op", ")")]:
            if word["plain"] and _OWN_NAME.match(text):
                defs.append(text)
            else:
                problems.append("a function named %r, not a lowercase name" % (text,))
            i += 2
            continue
        if state == "cmd":
            assigned = _ASSIGNMENT.match(text)
            if assigned is not None:
                if not _OWN_NAME.match(assigned.group(1)):
                    problems.append("an assignment to %s, a name the script does not "
                                    "own (it assigns only lowercase names)"
                                    % (assigned.group(1),))
                state = "assign"
                continue
            if word["value"] is None or not _BARE.match(word["value"]):
                problems.append("a command word that is not a bare name: %r"
                                % (_shown(word),))
                state, call = "args", None
                continue
            call = (word["value"], [])
            calls.append(call)
            state = "args"
            continue
        if state == "args":
            if call is not None:
                call[1].append(word)
        elif state == "assign":
            problems.append("an assignment prefixing the command %r" % (text,))
            state, call = "args", None
        elif state == "after":
            problems.append("a word after a closing keyword: %r" % (text,))
        elif state == "for_name":
            if not (word["plain"] and _OWN_NAME.match(text)):
                problems.append("a `for` over %r, not a lowercase name" % (text,))
            state = "for_in"
        elif state in ("for_in", "case_in"):
            if text != "in":
                problems.append("%r where `in` belongs" % (text,))
            state = "for_words" if state == "for_in" else "pattern"
        elif state == "case_word":
            state = "case_in"
    if stack:
        problems.append("`%s` never closed" % (stack[-1],))
    return {"calls": calls, "defs": defs, "problems": problems}


def _builtin_call_problem(name, args):
    """Why a call of a builtin on BUILTINS is refused, or None: the family its row
    allows, asked of each word's `_bash_reading` and never of its spelling."""
    shown = [_shown(a) for a in args]
    values = [a["value"] for a in args]
    if name == "set" and values[:1] != ["--"]:
        return "`set %s`, where only `set --` is read" % (" ".join(shown),)
    if name == "printf" and (not args or values[0] is None or values[0].startswith("-")):
        return ("a `printf` whose format is not a value known by reading that cannot be "
                "an option: %r" % (shown,))
    if name == "eval":
        sole = args[0]["sole"] if len(args) == 1 else None
        inner = (_parse(sole["subs"][0]) if sole is not None and sole["kind"] == "sub"
                 else {"calls": [], "problems": ["not one command substitution"]})
        if not ([c[0] for c in inner["calls"]] == ["apt-config"] and not inner["problems"]):
            return "an `eval` of anything but the apt-config stub's output: %r" % (shown,)
    if name == "[":
        inner = args[:-1] if values[-1:] == ["]"] else None
        unary = (inner is not None and len(inner) == 2 and values[0] in _TEST_UNARY
                 and not inner[1]["split"])
        binary = (inner is not None and len(inner) == 3 and values[1] in _TEST_BINARY
                  and not inner[0]["split"] and not inner[2]["split"])
        if not (unary or binary):
            return "a `[` test of a shape the reader does not read: %r" % (shown,)
    return None


def command_word_problems(script):
    """[problem] for one script: [] when every command it can start is a bare name
    on the vocabulary, called the way its row allows."""
    tokens, _end, problem = _lex(script, 0, False)
    if problem is not None:
        return [problem]
    got = _parse(tokens)
    tools = set(n for n, _why in ALLOWED_TOOLS)
    builtins = set(n for n, _why in BUILTINS)
    vocabulary = set(STUBS) | set(SHELL_STUBS) | tools | builtins
    known = vocabulary | set(got["defs"])
    # A function takes a name from the moment its definition runs, so a call written
    # before it - or reached when the definition is not - still runs the builtin or the
    # stub; no function may take a name the vocabulary holds, and a builtin's call is
    # always held to its row.
    problems = list(got["problems"]) + [
        "a function named %r, a name a stub, an allowed tool or a builtin on BUILTINS "
        "already holds" % (name,) for name in got["defs"] if name in vocabulary]
    for name, args in got["calls"]:
        if name not in known:
            problems.append("`%s` is not a stub, an allowed tool, a builtin on "
                            "BUILTINS or a function the script defines" % (name,))
        elif name in builtins:
            problem = _builtin_call_problem(name, args)
            if problem is not None:
                problems.append(problem)
    return problems


def script_problems(script):
    """Why the reader refuses to run `script` - its command words, and every line
    naming an absolute path (`sd7`'s reading) - or [] when nothing it can start
    is outside the stubs and the allowed tools."""
    absolute = ["a line naming an absolute path: %s" % (line,)
                for _step, line in _absolute_path_lines([{"run": script}])]
    return command_word_problems(script) + absolute


# --- the cases ----------------------------------------------------------------------
def _stub_env(root, extra=None):
    """A step's whole environment: PATH is the fixture's `bin/` and nothing else."""
    stub = os.path.join(root, "stub")
    env = {"PATH": os.path.join(root, "bin"), "HOME": os.path.join(root, "home"),
           "TMPDIR": root, "FIXTURE_ROOT": root, "STUB": stub,
           "STUB_BIN": os.path.join(root, "bin"),
           "STUB_REFUSED": os.path.join(stub, "refused"),
           "STUB_PY": sys.executable, "STUB_SELF": os.path.abspath(__file__),
           "LC_ALL": "C"}
    node = shutil.which("node")
    if node is not None:
        env["STUB_NODE"] = node
    env.update(extra or {})
    return env


def _log_lines(root):
    with io.open(os.path.join(root, "stub", "log"), encoding="utf-8") as fh:
        return [ln.split() for ln in fh.read().splitlines() if ln.strip()]


def _set_state(root):
    """(paths of the set not the runner user's, apt's lock and partial/ left in it)."""
    saved = os.path.join(root, "home", SET_REL)
    with io.open(os.path.join(root, "stub", "owners.json"), encoding="utf-8") as fh:
        owners = json.load(fh)
    not_runner = sorted(os.path.relpath(p, saved) for p, who in owners.items()
                        if (p == saved or p.startswith(saved + os.sep))
                        and os.path.exists(p) and who != "runner")
    leftovers = sorted(os.path.relpath(os.path.join(dp, n), saved)
                       for dp, dns, fns in os.walk(saved) for n in dns + fns
                       if n in ("partial", "lock")) if os.path.isdir(saved) else []
    return not_runner, leftovers


def _observed(code, out, log, not_runner, leftovers):
    def count(word):
        return sum(1 for words in log if words[0] == word)
    return {"ok": code == 0, "update": count("update"),
            "fetched": sorted(w[1] for w in log if w[0] == "fetch"),
            "install": count("install"), "warnings": out.count("::warning::"),
            "errors": out.count("::error::"), "leftovers": leftovers,
            "update_refused": count("update-refused"), "not_runner": not_runner}


def _install_case(fixture, says=None, **want):
    """A case running the system packages' step over `fixture`, holding each
    observation `want` names and, when `says` is given, that line in its output."""
    def run_case(action):
        step = step_by_id(action["steps"], "sysdeps-install")
        if step is None or "run" not in step:
            return False, "the action has no `sysdeps-install` step with a `run:`"
        root = tempfile.mkdtemp(prefix="browser-install-")
        try:
            build_fixture(root, **fixture)
            result = run_script(step["run"], _stub_env(root, {"MISSING": MISSING}), root)
            code, out = result["code"], result["out"]
            if code is None:
                return False, out
            not_runner, leftovers = _set_state(root)
            got = _observed(code, out, _log_lines(root), not_runner, leftovers)
        finally:
            shutil.rmtree(root)
        bad = _refusals(result) + [
            "%s: want %r, got %r" % (k, v, got[k]) for k, v in sorted(want.items())
            if got[k] != v]
        if says is not None and says not in out:
            bad.append("the output lacks %r" % (says,))
        return not bad, "%s\nexit %r\n%s" % ("; ".join(bad), code, out.rstrip())
    return run_case


def _plan_case(env, want_install, says):
    """A case running the `plan` step; `says` None means the step prints nothing,
    which is what a job that is not a seed must do."""
    def run_case(action):
        step = step_by_id(action["steps"], "plan")
        if step is None or "run" not in step:
            return False, "the action has no `plan` step with a `run:`"
        root = tempfile.mkdtemp(prefix="browser-install-plan-")
        try:
            build_base(root)
            out_file = os.path.join(root, "github-output")
            _write(out_file, "")
            full = _stub_env(root, dict({"GITHUB_OUTPUT": out_file, "SEED": "true",
                                         "BROWSER_SEEN": "", "SYSDEPS_SEEN": "",
                                         "MISSING": MISSING}, **env))
            result = run_script(step["run"], full, root)
            with io.open(out_file, encoding="utf-8") as fh:
                outputs = fh.read().splitlines()
        finally:
            shutil.rmtree(root)
        code, out = result["code"], result["out"]
        said = out.strip() == "" if says is None else says in out
        ok = (code == 0 and outputs == ["install=%s" % (want_install,)] and said
              and not result["refused"])
        return ok, "exit %r, outputs %r, output %r%s" % (
            code, outputs, out, "".join("; " + r for r in _refusals(result)))
    return run_case


_LOCK_PIN = "9.8.7"


def run_pins(steps, image_os, image_version, lock=None):
    """(exit code, {output: value}, output) of the `pins` step on a scratch root
    holding a package-lock.json that pins playwright-core at `_LOCK_PIN`. A
    refusal makes the exit code None, with the refusals as the output."""
    step = step_by_id(steps, "pins")
    if step is None or "run" not in step:
        return None, {}, "the action has no `pins` step with a `run:`"
    if shutil.which("node") is None:
        return None, {}, "no node on PATH, and the step reads the lockfile with it"
    root = tempfile.mkdtemp(prefix="browser-install-pins-")
    try:
        build_base(root)
        out_file = os.path.join(root, "github-output")
        _write(out_file, "")
        _write(os.path.join(root, "package-lock.json"), json.dumps(
            lock if lock is not None else
            {"packages": {"node_modules/playwright-core": {"version": _LOCK_PIN}}}))
        env = dict((k, v) for k, v in step.get("env", {}).items() if "${{" not in v)
        env.update({"GITHUB_OUTPUT": out_file, "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"})
        if image_os is not None:
            env["ImageOS"] = image_os
        if image_version is not None:
            env["ImageVersion"] = image_version
        result = run_script(step["run"], _stub_env(root, env), root)
        with io.open(out_file, encoding="utf-8") as fh:
            outputs = dict(ln.split("=", 1) for ln in fh.read().splitlines() if "=" in ln)
    finally:
        shutil.rmtree(root)
    if result["refused"]:
        return None, outputs, "\n".join(_refusals(result) + [result["out"]])
    return result["code"], outputs, result["out"]


def _case_sk1(action):
    steps = action["steps"]
    a = run_pins(steps, "ubuntu24", "20261111.370.1")
    b = run_pins(steps, "ubuntu24", "20261116.376.1")
    if a[0] is None or b[0] is None:
        return False, a[2] if a[0] is None else b[2]
    version = step_by_id(steps, "pins").get("env", {}).get("BROWSER_CACHE_VERSION")
    ok = (a[0] == 0 and b[0] == 0 and a[1] == b[1]
          and a[1].get("sysdeps-prefix") == "chromium-sysdeps-ubuntu24-X64"
          and a[1].get("browser-key") == "playwright-browsers-Linux-X64-%s-v%s"
          % (_LOCK_PIN, version)
          and "20261111.370.1" in a[2])
    return ok, "%r\n%r" % (a, b)


def _case_sk2(action):
    code, outputs, out = run_pins(action["steps"], None, "20261111.370.1")
    if code is None:
        return False, out
    return code != 0 and outputs == {} and "ImageOS" in out, \
        "exit %r, outputs %r, output %r" % (code, outputs, out)


def _case_sk3(action):
    code, outputs, out = run_pins(action["steps"], "ubuntu24", "1", lock={"packages": {}})
    if code is None:
        return False, out
    return code != 0 and outputs == {} and "playwright-core" in out, \
        "exit %r, outputs %r, output %r" % (code, outputs, out)


_SYSDEPS_PREFIX = "chromium-sysdeps-ubuntu24-X64"
_SYSDEPS_ENV = {"PREFIX": "${{ steps.pins.outputs.sysdeps-prefix }}",
                "VERSION": "${{ steps.pins.outputs.version }}"}


def run_sysdeps(steps, installed):
    """(run_script's result, {output: value}) of the `sysdeps` step with the
    image holding `installed`, its env given what the `pins` step writes."""
    step = step_by_id(steps, "sysdeps")
    if step is None or "run" not in step:
        return {"code": None, "out": "the action has no `sysdeps` step with a `run:`",
                "refused": []}, {}
    root = tempfile.mkdtemp(prefix="browser-install-sysdeps-")
    try:
        build_base(root)
        _write(os.path.join(root, "stub", "installed"), " ".join(installed) + "\n")
        out_file = os.path.join(root, "github-output")
        _write(out_file, "")
        result = run_script(step["run"], _stub_env(root, {
            "PREFIX": _SYSDEPS_PREFIX, "VERSION": "v1", "GITHUB_OUTPUT": out_file}), root)
        with io.open(out_file, encoding="utf-8") as fh:
            outputs = dict(ln.split("=", 1) for ln in fh.read().splitlines() if "=" in ln)
    finally:
        shutil.rmtree(root)
    return result, outputs


def _case_sk4(action):
    """Two images lacking different packages: each writes the list it lacks and a
    key whose every part is read - prefix, the list's hash, the version."""
    step = step_by_id(action["steps"], "sysdeps") or {}
    bad = [] if step.get("env") == _SYSDEPS_ENV else [
        "the step's env is %r, not what the pins step writes (%r)"
        % (step.get("env"), _SYSDEPS_ENV)]
    keys = []
    for installed, missing in ((["libD"], "libA libB"), (["libB", "libD"], "libA")):
        result, outputs = run_sysdeps(action["steps"], installed)
        want = {"missing": missing, "key": "%s-%s-v1" % (
            _SYSDEPS_PREFIX, hashlib.sha256(missing.encode("ascii")).hexdigest()[:16])}
        bad += _refusals(result)
        if result["code"] != 0 or outputs != want:
            bad.append("image holding %s: exit %r, outputs %r, want %r\n%s"
                       % (installed, result["code"], outputs, want, result["out"]))
        keys.append(outputs.get("key"))
    if len(set(keys)) != len(keys):
        bad.append("two different missing lists gave one key: %r" % (keys,))
    return not bad, "; ".join(bad) or "keys %r" % (keys,)


def _cache_steps(steps):
    """(the seed's lookups, the restores that save) - read by what each step uses."""
    lookups = [s for s in steps if s.get("uses", "").startswith("actions/cache/restore@")]
    restores = [s for s in steps if s.get("uses", "").startswith("actions/cache@")]
    return lookups, restores


# The key each cache path is stored under, as the step writing it names it: sk1
# reads the pins step writing `browser-key`, and sk4 the sysdeps step writing `key`.
# The set's path is the one the install step's `d` names under HOME (the bi cases).
SET_PATH = "~/.cache/chromium-sysdeps"
CACHE_KEYS = {"~/.cache/ms-playwright": "${{ steps.pins.outputs.browser-key }}",
              SET_PATH: "${{ steps.sysdeps.outputs.key }}"}


def _case_sd1(action):
    lookups, restores = _cache_steps(action["steps"])
    bad = []
    if len(lookups) != 2:
        bad.append("%d lookup step(s), not one per cache" % (len(lookups),))
    if sorted(r.get("with", {}).get("path") for r in restores) != sorted(CACHE_KEYS):
        bad.append("the restores name %r, not one each of %r"
                   % ([r.get("with", {}).get("path") for r in restores], sorted(CACHE_KEYS)))
    for cache in lookups + restores:
        w = cache.get("with", {})
        if w.get("path") in CACHE_KEYS and w.get("key") != CACHE_KEYS[w["path"]]:
            bad.append("%s keys %s by %r, not %r" % (cache.get("id") or cache.get("name"),
                                                     w["path"], w.get("key"),
                                                     CACHE_KEYS[w["path"]]))
    for look in lookups:
        w = look.get("with", {})
        same = [r for r in restores
                if r.get("with", {}).get("path") == w.get("path")
                and r.get("with", {}).get("key") == w.get("key")]
        if w.get("lookup-only") != "true":
            bad.append("%s is not lookup-only" % (look.get("id"),))
        if "inputs.seed == 'true'" not in look.get("if", ""):
            bad.append("%s does not run on a seed alone" % (look.get("id"),))
        if len(same) != 1:
            bad.append("%s names a path and key no single restore names (%r)"
                       % (look.get("id"), w))
    return not bad, "; ".join(bad) or "lookups %r" % ([s.get("id") for s in lookups],)


def _case_sd2(action):
    steps = action["steps"]
    plan = step_by_id(steps, "plan")
    want = {"SEED": "${{ inputs.seed }}",
            "BROWSER_SEEN": "${{ steps.seen-browser.outputs.cache-hit }}",
            "SYSDEPS_SEEN": "${{ steps.seen-sysdeps.outputs.cache-hit }}",
            "MISSING": "${{ steps.sysdeps.outputs.missing }}"}
    got = (plan or {}).get("env", {})
    lookups, _restores = _cache_steps(steps)
    ids = sorted(s.get("id") for s in lookups)
    ok = plan is not None and got == want and ids == ["seen-browser", "seen-sysdeps"]
    return ok, "plan env %r, lookup ids %r" % (got, ids)


def _case_sd3(action):
    steps = action["steps"]
    plan = step_by_id(steps, "plan")
    if plan is None:
        return False, "the action has no `plan` step"
    after = steps[steps.index(plan) + 1:]
    unguarded = [s.get("name") or s.get("id") or s.get("run", "")[:60] for s in after
                 if "steps.plan.outputs.install == 'true'" not in s.get("if", "")]
    return bool(after) and not unguarded, \
        "%d step(s) after the plan; not guarded by its answer: %r" % (len(after), unguarded)


def _command_steps(steps, command):
    """The indices of the steps whose script is `command` alone, comments aside."""
    return [i for i, s in enumerate(steps)
            if [ln.strip() for ln in s.get("run", "").splitlines()
                if ln.strip() and not ln.strip().startswith("#")] == [command]]


def _case_sd4(action):
    """The two steps no case runs (they need the network) still exist where they
    must: `npm ci` before the dry run that calls npx, the Chromium install after
    the plan, whose guard sd3 then reads."""
    steps = action["steps"]
    npm = _command_steps(steps, "npm ci")
    chromium = _command_steps(steps, "npx playwright install chromium")
    sysdeps, plan = step_by_id(steps, "sysdeps"), step_by_id(steps, "plan")
    ok = (len(npm) == 1 and len(chromium) == 1 and None not in (sysdeps, plan)
          and npm[0] < steps.index(sysdeps) and chromium[0] > steps.index(plan))
    return ok, "npm ci at %r, Chromium at %r, sysdeps at %r, plan at %r" % (
        npm, chromium, sysdeps and steps.index(sysdeps), plan and steps.index(plan))


_MISSING_GUARD = "steps.sysdeps.outputs.missing != ''"


def _case_sd5(action):
    """An image lacking nothing asks for no set: the set's lookup, its restore and
    the install step each carry the guard."""
    steps = action["steps"]
    _lookups, restores = _cache_steps(steps)
    want = ([step_by_id(steps, "seen-sysdeps"), step_by_id(steps, "sysdeps-install")]
            + [r for r in restores if r.get("with", {}).get("path") == SET_PATH])
    unguarded = [s and (s.get("id") or s.get("name")) for s in want
                 if s is None or _MISSING_GUARD not in s.get("if", "")]
    return len(want) == 3 and not unguarded, \
        "steps that must carry %r and do not (None: the step is missing): %r" % (
            _MISSING_GUARD, unguarded)


def _case_sd6(action):
    seed = action["inputs"].get("seed", {})
    return seed.get("default") == "false", "the `seed` input reads %r" % (seed,)


# A WORD STARTING WITH `/` in a step's script: an executable named by its absolute
# path, which no PATH confinement stops, or a host path a builtin redirection or a
# stub's argument would write. Preceded by a word character, `$`, `}`, `~`, `.`, `*`,
# `/`, `\` or `-` it is the middle of a word - `"$d/debs"`, `~/.cache`, a sed
# script - and not a path of its own.
_ABSOLUTE = re.compile(r"(?<![\w$}~.*/\\-])/[\w.]")
_ABSOLUTE_ALLOWED = re.compile(r"/dev/null\b")


def _absolute_path_lines(steps):
    """[(step, line)] for every script line naming an absolute path but
    `/dev/null`; comment lines are skipped."""
    return [(s.get("id") or s.get("name") or "step %d" % (n + 1,), line.strip())
            for n, s in enumerate(steps) for line in s.get("run", "").splitlines()
            if not line.strip().startswith("#")
            and _ABSOLUTE.search(_ABSOLUTE_ALLOWED.sub("", line))]


def _case_sd7(action):
    found = _absolute_path_lines(action["steps"])
    return not found, "lines naming an absolute path: %r" % (found,)


# The steps a case runs, which are what this check starts; the others are `sd4`'s.
RUN_STEPS = ("pins", "sysdeps", "plan", "sysdeps-install")


def _case_sd8(action):
    bad = []
    for sid in RUN_STEPS:
        step = step_by_id(action["steps"], sid)
        if step is None or "run" not in step:
            bad.append("the action has no `%s` step with a `run:`" % (sid,))
            continue
        bad += ["%s: %s" % (sid, p) for p in command_word_problems(step["run"])]
    return not bad, "; ".join(bad)


# One row per case: (id, what it holds, the function judging the parsed steps). The
# ids are what the gate and the selftest print first on each line.
CASES = [
    ("bi1", "full hit: the archive is asked for nothing, index included, the set "
     "installs, and a hit that fetches anything is red",
     _install_case(dict(restored=True), not_runner=[], ok=True, update=0, fetched=[],
                   install=1, warnings=0, leftovers=[],
                   says="the restored set holds every file the install needs")),
    ("bi2", "miss: a fresh index and every file of the closure are fetched once, then "
     "installed", _install_case(dict(restored=False), not_runner=[], ok=True, update=1,
                                fetched=ALL, install=1, warnings=0, leftovers=[],
                                says="no restored set")),
    ("bi3", "partial set, a named package missing: that file alone is fetched, no index",
     _install_case(dict(restored=True, drop=("libA",)), not_runner=[], ok=True,
                   update=0, fetched=["libA_1.deb"], install=1, warnings=0,
                   says="so the archive is asked for these and nothing else: libA_1.deb")),
    ("bi4", "partial set, a dependency (not a named package) missing: that file alone "
     "is fetched", _install_case(dict(restored=True, drop=("libC",)), not_runner=[],
                                 ok=True, update=0, fetched=["libC_1.deb"], install=1,
                                 warnings=0, says="nothing else: libC_1.deb")),
    ("bi5", "a truncated .deb: apt's size check drops it, it alone is fetched, no "
     "fallback", _install_case(dict(restored=True, truncate=("libB",)), not_runner=[],
                               ok=True, update=0, fetched=["libB_1.deb"], install=1,
                               warnings=0, says="nothing else: libB_1.deb")),
    ("bi6", "a .deb of the right size dpkg cannot read: the fallback runs once, warns "
     "once and the step passes",
     _install_case(dict(restored=True, corrupt=("libB",)), not_runner=[], ok=True,
                   update=1, fetched=ALL, install=1, warnings=1, errors=0, leftovers=[],
                   says="installing from the restored set failed")),
    ("bi7", "a stale restored index: fetching what it lacks fails, the fallback runs "
     "once and passes",
     _install_case(dict(restored=True, drop=("libA",), stale=True), not_runner=[],
                   ok=True, update=1, fetched=["libA_2.deb", "libB_1.deb", "libC_1.deb"],
                   install=1, warnings=1,
                   says="fetching the files the restored set lacks failed")),
    ("bi8", "the fallback failing: the step is red, having fallen back exactly once",
     _install_case(dict(restored=True, corrupt=("libB",), down=True), ok=False,
                   update=0, update_refused=1, install=0, warnings=1, errors=1,
                   says="the fallback's fetch from the archive failed too")),
    ("bi9", "a miss with the archive down: red, and no fallback on top of the miss",
     _install_case(dict(restored=False, down=True), ok=False, update_refused=1,
                   warnings=0, errors=1)),
    ("bi10", "ownership: every write to the set is root's and the set ends the runner "
     "user's, so no runner-user write lands under a root directory and the cache can "
     "save it", _install_case(dict(restored=False), ok=True, not_runner=[], errors=0,
                              update=1, install=1)),
    ("sp1", "not a seed: the install runs, and the step says nothing about a seed",
     _plan_case({"SEED": "false"}, "true", None)),
    ("sp2", "a seed, an entry for both keys: nothing installs",
     _plan_case({"BROWSER_SEEN": "true", "SYSDEPS_SEEN": "true"}, "false",
                "nothing is installed and nothing is saved")),
    ("sp3", "a seed, no browser entry: the install runs",
     _plan_case({"BROWSER_SEEN": "false", "SYSDEPS_SEEN": "true"}, "true",
                "no entry exists for the browser key,")),
    ("sp4", "a seed, no system packages' entry: the install runs",
     _plan_case({"BROWSER_SEEN": "true", "SYSDEPS_SEEN": "false"}, "true",
                "no entry exists for the system packages' key,")),
    ("sp5", "a seed, neither entry: the install runs and names both",
     _plan_case({"BROWSER_SEEN": "false", "SYSDEPS_SEEN": "false"}, "true",
                "no entry exists for the browser key and the system packages' key")),
    ("sp6", "a seed on an image lacking nothing, with a browser entry: nothing "
     "installs, and no system packages' key is asked for",
     _plan_case({"BROWSER_SEEN": "true", "SYSDEPS_SEEN": "", "MISSING": ""}, "false",
                "nothing is installed")),
    ("sk1", "two image versions of one distribution give one key; the version is "
     "logged, not keyed, and the browser key carries the lockfile's pin", _case_sk1),
    ("sk2", "no ImageOS exported: the step is red and writes no key", _case_sk2),
    ("sk3", "a lockfile pinning no playwright-core: the step is red and writes no key",
     _case_sk3),
    ("sk4", "the system packages' key: two images lacking different packages each "
     "write the list they lack and a key of the prefix, that list's hash and the "
     "version", _case_sk4),
    ("sd1", "each cache is keyed by what the step writing its key writes, and each "
     "seed lookup is lookup-only, runs on a seed alone, and names the path and key "
     "of exactly one restore", _case_sd1),
    ("sd2", "the plan reads the seed input and both lookups' answers", _case_sd2),
    ("sd3", "every step after the plan installs or restores only when the plan says "
     "so", _case_sd3),
    ("sd4", "the steps no case runs exist where they must: `npm ci` before the dry "
     "run, the Chromium install after the plan", _case_sd4),
    ("sd5", "the set's lookup, its restore and its install each run only on an image "
     "that lacks a package", _case_sd5),
    ("sd6", "the `seed` input defaults to false, so only a caller that says so seeds",
     _case_sd6),
    ("sd7", "no step's script names an absolute path (but /dev/null), so nothing is "
     "reached past the PATH the stubs confine", _case_sd7),
    ("sd8", "every command word of every step a case runs is a bare name of a stub, an "
     "allowed tool, a function the script defines or a listed builtin in the shape "
     "its row allows, so the reader that gates each run refuses none of them",
     _case_sd8),
]
STRUCTURAL = ("sd1", "sd2", "sd3", "sd4", "sd5", "sd6", "sd7", "sd8")


def run_cases(text, only=None):
    """[{"id", "what", "ok", "detail"}] for `text` (an action.yml), one per case -
    `only` narrows to those ids. A host that cannot run the stubs, or an action
    that does not read, is one failing row per case asked for, never an empty list."""
    rows = [c for c in CASES if only is None or c[0] in only]
    parsed = read_action(text)
    if parsed["problem"] is not None:
        return [{"id": cid, "what": what, "ok": False,
                 "detail": "the action could not be read: %s" % (parsed["problem"],)}
                for cid, what, _fn in rows]
    host = posix_problem()
    out = []
    for cid, what, fn in rows:
        if host is not None and cid not in STRUCTURAL:
            out.append({"id": cid, "what": what, "ok": False,
                        "detail": "could not run here: %s" % (host,)})
            continue
        ok, detail = fn(parsed)
        out.append({"id": cid, "what": what, "ok": bool(ok), "detail": detail})
    return out


def render(rows, stream=None):
    stream = stream or sys.stdout
    for row in rows:
        stream.write("%s %s %s\n" % ("PASS" if row["ok"] else "FAIL", row["id"],
                                     row["what"]))
        if not row["ok"]:
            stream.write("    %s\n" % (row["detail"].replace("\n", "\n    "),))
    held = sum(1 for r in rows if r["ok"])
    stream.write("browser install: %d of %d cases held%s\n"
                 % (held, len(rows), "" if held == len(rows) and rows else " - RED"))
    return 0 if rows and held == len(rows) else 1


def main(argv):
    if argv[:1] == ["--stub"] and len(argv) >= 2 and argv[1] in STUBS:
        return STUBS[argv[1]](argv[2:])
    if argv == ["--selftest"]:
        return _selftest()
    path = os.path.join(REPO, ACTION_REL)
    if len(argv) == 2 and argv[0] == "--action":
        path = argv[1]
    elif argv:
        sys.stderr.write(USAGE)
        return 2
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError) as exc:
        sys.stdout.write("browser install: the action could not be read: %s\n" % (exc,))
        return 1
    sys.stdout.write("browser install: %s\n" % (path,))
    return render(run_cases(text))


# --- selftest -------------------------------------------------------------------
# A COPY OF THE ACTION BROKEN ONCE PER PROPERTY. Each row names the text it replaces
# (which must occur exactly once, or the row is red as "not applied" - a mutation that
# never landed proves nothing), what replaces it, and the cases that must go red.
_FIRST_PROBE_FETCH = (
    '            sudo mkdir -p "$d/debs/partial" "$d/lists/partial" &&\n'
    '            sudo apt-get update &&\n'
    '            eval "$(apt-config shell sys_lists Dir::State::Lists/d)" &&\n'
    '            sudo cp -p "$sys_lists"*_* "$d/lists/" &&\n',
    '            mkdir -p "$d/debs/partial" "$d/lists" &&\n'
    '            sudo apt-get update &&\n'
    '            eval "$(apt-config shell sys_lists Dir::State::Lists/d)" &&\n'
    '            sudo cp -a "$sys_lists/." "$d/lists/" &&\n'
    '            sudo rm -rf "$d/lists/lock" "$d/lists/partial" &&\n'
    '            mkdir -p "$d/lists/partial" &&\n')
_PARTIAL_FETCH = ('              apt_set install -y --download-only '
                  '--no-install-recommends $MISSING ||\n')
_APPEND_AT = '        sudo chown -R "$(id -u):$(id -g)" "$d"\n'
MUTATIONS = [
    ("bm1", "the first probe's archive path (runner-user mkdir under a root `lists/`)",
     [_FIRST_PROBE_FETCH], ["bi2", "bi10"], "Permission denied"),
    ("bm2", "a hit that cannot see its own index fetches everything, with no warning",
     [('ls "$d/lists/"*_Packages*', 'ls "$d/lists/"*_Release*')], ["bi1"], None),
    ("bm3", "a hit that falls back - green, with one warning",
     [('--print-uris $MISSING); then\n', '--print-uris $MISSING) || [ -n "$d" ]; then\n')],
     ["bi1"], None),
    ("bm4", "no fallback", [('        if [ -n "$why" ]; then\n',
                             '        if [ -n "" ]; then\n')], ["bi6", "bi7"], None),
    ("bm5", "the fallback fetching twice",
     [('          echo "the fallback installed the system packages from a fresh fetch"\n',
       '          fetch_all\n'
       '          echo "the fallback installed the system packages from a fresh fetch"\n')],
     ["bi6"], None),
    ("bm6", "a partial set fetching everything",
     [(_PARTIAL_FETCH, '              fetch_all ||\n')], ["bi3", "bi4"], None),
    ("bm7", "a partial set's failed fetch being fatal",
     [(_PARTIAL_FETCH + '                why="fetching the files the restored set '
       'lacks failed"\n', _PARTIAL_FETCH.replace(" ||\n", "\n"))], ["bi7"], None),
    ("bm8", "the fallback's failure tolerated",
     [('the fallback\'s fetch from the archive failed too"\n            exit 1',
       'the fallback\'s fetch from the archive failed too"\n            exit 0')],
     ["bi8"], None),
    ("bm9", "the set never handed to the runner user",
     [(_APPEND_AT, '')], ["bi2", "bi10"], None),
    ("bm10", "the seed test inverted",
     [('if [ "$SEED" != "true" ]; then', 'if [ "$SEED" = "true" ]; then')],
     ["sp1", "sp2"], None),
    ("bm11", "the browser lookup's answer ignored",
     [('[ "$BROWSER_SEEN" = "true" ] || lacking="the browser key"\n', '')],
     ["sp3", "sp5"], None),
    ("bm12", "the system packages' key asked of an image that lacks nothing",
     [('if [ -n "$MISSING" ] && [ "$SYSDEPS_SEEN" != "true" ]; then',
       'if [ "$SYSDEPS_SEEN" != "true" ]; then')], ["sp6"], None),
    ("bm13", "the image's version back in the system packages' key",
     [('sysdeps-prefix=chromium-sysdeps-$ImageOS-$RUNNER_ARCH',
       'sysdeps-prefix=chromium-sysdeps-$ImageOS-${ImageVersion:-}-$RUNNER_ARCH')],
     ["sk1"], None),
    ("bm14", "a lookup naming another path than its restore",
     [('        path: ~/.cache/ms-playwright\n'
       '        key: ${{ steps.pins.outputs.browser-key }}\n'
       '        lookup-only: true\n',
       '        path: ~/.cache/ms-playwright/chromium\n'
       '        key: ${{ steps.pins.outputs.browser-key }}\n'
       '        lookup-only: true\n')], ["sd1"], None),
    ("bm15", "the plan reading one lookup's answer for both",
     [('SYSDEPS_SEEN: ${{ steps.seen-sysdeps.outputs.cache-hit }}',
       'SYSDEPS_SEEN: ${{ steps.seen-browser.outputs.cache-hit }}')], ["sd2"], None),
    ("bm16", "the Chromium install running whatever the plan says",
     [("    - if: ${{ steps.plan.outputs.install == 'true' }}\n"
       "      shell: bash\n"
       "      run: |\n"
       "        # install: Chromium",
       "    - shell: bash\n"
       "      run: |\n"
       "        # install: Chromium")], ["sd3"], None),
    ("bm17", "the system packages' key changed the same way in its lookup and restore",
     [("        path: ~/.cache/chromium-sysdeps\n"
       "        key: ${{ steps.sysdeps.outputs.key }}\n"
       "        lookup-only: true\n",
       "        path: ~/.cache/chromium-sysdeps\n"
       "        key: ${{ steps.pins.outputs.version }}\n"
       "        lookup-only: true\n"),
      ("        path: ~/.cache/chromium-sysdeps\n"
       "        key: ${{ steps.sysdeps.outputs.key }}\n",
       "        path: ~/.cache/chromium-sysdeps\n"
       "        key: ${{ steps.pins.outputs.version }}\n")], ["sd1"], None),
    ("bm18", "the `npm ci` step deleted",
     [("    - shell: bash\n      run: |\n"
       "        # install: JavaScript dev dependencies (npm ci)\n        npm ci\n\n", "")],
     ["sd4"], None),
    ("bm19", "the Chromium install step deleted",
     [("    - if: ${{ steps.plan.outputs.install == 'true' }}\n      shell: bash\n"
       "      run: |\n        # install: Chromium (fetched only when the restored build "
       "is not the pinned one)\n        npx playwright install chromium\n\n", "")],
     ["sd4"], None),
    ("bm20", "the install step's guard for an image lacking nothing dropped",
     [("    - id: sysdeps-install\n      if: ${{ steps.plan.outputs.install == 'true' "
       "&& steps.sysdeps.outputs.missing != '' }}\n",
       "    - id: sysdeps-install\n      if: ${{ steps.plan.outputs.install == 'true' }}\n")],
     ["sd5"], None),
    ("bm21", "the `seed` input defaulting to true",
     [('    default: "false"\n', '    default: "true"\n')], ["sd6"], None),
    ("bm22", "the system packages' key replaced by a constant",
     [('echo "key=$PREFIX-$(printf \'%s\' "$missing" | sha256sum | cut -c1-16)-$VERSION"',
       'echo "key=constant"')], ["sk4"], None),
    ("bm23", "an executable named by its absolute path",
     [(_APPEND_AT, _APPEND_AT + "        /usr/bin/true\n")], ["sd7"], None),
]


# A STEP REACHING PAST THE STUBS, appended to a copy of the action. Each row's
# `outside` is a file in a scratch directory of its own, beside the fixture roots and
# in none of them, so even a check that lost its confinement could touch nothing but
# that file. The row holds four things at once: the case named goes red, the half
# the row names refused it - the reader, with the problem the row quotes, before the
# step started, or a stub while it ran - the file outside is as it was, and the case
# is green on the committed action. Naming the half is what makes each row fail
# when that half is weakened, rather than staying green on the other one.
#
# A command word built to reach a real tool climbs out of the fixture by more `..`
# than any temporary directory is deep (one more at `/` stays at `/`), so a reader
# that let it through would really start that tool, on the file outside.
_APPEND_PINS = '        echo "version=v$BROWSER_CACHE_VERSION" >> "$GITHUB_OUTPUT"\n'
_CLIMB = "../" * 24
_OUT = '"$HOME/../../{outside_name}'
CONFINEMENT = [
    ("bx1", "an appended `sudo touch` reaching outside by a relative path, which the "
     "reader passes and the sudo stub refuses", _APPEND_AT,
     'sudo touch %s/made"' % (_OUT,), "bi1", "stub", None),
    ("bx2", "an appended `sudo rm -rf <outside>` naming an absolute path", _APPEND_AT,
     'sudo rm -rf "{victim}"', "bi1", "reader", "a line naming an absolute path"),
    ("bx3", "an appended `sudo rm -rf` reaching outside by a relative path, which "
     "the rm stub refuses", _APPEND_AT, 'sudo rm -rf %s/victim"' % (_OUT,), "bi1",
     "stub", None),
    ("bx4", "an appended command that is neither a stub nor an allowed tool, its "
     "failure swallowed", _APPEND_AT, 'touch "$HOME/unstubbed" || true', "bi1",
     "reader", "`touch` is not a stub"),
    ("bx5", "node asked to write outside, by a path the reader cannot see", _APPEND_PINS,
     'node -e "require(\'fs\').writeFileSync([process.env.HOME, \'..\', \'..\', '
     '\'{outside_name}\', \'made\'].join(\'/\'), \'x\')"', "sk1", "stub", None),
    ("bx6", "an appended `command -p rm -rf <outside>`, which looks the name up in the "
     "system's default path", _APPEND_AT, 'command -p rm -rf %s/victim"' % (_OUT,),
     "bi1", "reader", "`command` is not a stub"),
    ("bx7", "a command word naming a real tool by a relative path", _APPEND_AT,
     '%susr/bin/touch %s/made"' % (_CLIMB, _OUT), "bi1", "reader",
     "a command word that is not a bare name"),
    ("bx8", "a command word built from a variable", _APPEND_AT,
     '"$HOME/%susr/bin/touch" %s/made"' % (_CLIMB, _OUT), "bi1", "reader",
     "a command word that is not a bare name"),
    ("bx9", "an appended `exec`", _APPEND_AT, 'exec rm -rf %s/victim"' % (_OUT,), "bi1",
     "reader", "`exec` is not a stub"),
    ("bx10", "a `PATH=` line pointing a stub's name at the real tool", _APPEND_AT,
     'PATH="$HOME/%susr/bin:$HOME/%sbin"; rm -rf %s/victim"' % (_CLIMB, _CLIMB, _OUT),
     "bi1", "reader", "an assignment to PATH"),
    ("bx11", "a redirection writing outside by a path built from a variable",
     _APPEND_AT, 'echo x > %s/made"' % (_OUT,), "bi1", "reader", "a redirection >"),
    ("bx12", "an `eval` of text naming a real tool by a relative path", _APPEND_AT,
     'eval "%susr/bin/touch %s/made\\""' % (_CLIMB, _OUT.replace('"', '\\"')), "bi1",
     "reader", "an `eval` of anything but"),
    ("bx13", "`printf -v` through an array subscript, which bash evaluates as code",
     _APPEND_AT, "printf -v 'a[$(%susr/bin/touch %s/made\")]' x" % (_CLIMB, _OUT),
     "bi1", "reader", "a `printf` whose format"),
]

# THE CONSTRUCTION ALONE: each line is run past the reader (`_run_bash`) on a fixture
# of its own and must leave the file outside as it was, so the prelude is shown
# holding without the reader's help. Every line here is one the reader refuses too.
# Each row names the prelude lines that hold it, and the same line is run again with
# those taken out, where it must reach the file outside - so a row whose hold is not
# the line it names, or whose escape this bash does not have, says so instead of
# passing for a reason of its own. A row with a fifth field asks bash first whether
# it has what the escape uses (a script that exits 0 when it does); on a bash without
# it the control is not required to reach, and the row says that.
_HOLD_DISABLE = '    *) enable -n "$b" ;;\n'
_HOLD_READONLY = "readonly BASH_CMDS BASH_ALIASES @ENV@\n"
_HOLD_UNSET = "unset BASH_CMDS BASH_ALIASES\n"
_HOLD_ENABLE = "enable -n enable\n"
_HAS_CMDS = 'BASH_CMDS[zz]=/x; [ "$(hash -t zz 2>/dev/null)" = /x ]'
CONSTRUCTION = [
    ("bk1", "`command -p`", 'command -p touch "{made}"', (_HOLD_DISABLE, _HOLD_READONLY)),
    ("bk2", "`builtin command -p`", 'builtin command -p touch "{made}"',
     (_HOLD_DISABLE, _HOLD_READONLY)),
    ("bk3", "`exec` of an absolute path", 'exec /usr/bin/touch "{made}"', (_HOLD_DISABLE,)),
    ("bk4", "`hash -p` pointing a stub's name at a real tool",
     'hash -p /usr/bin/touch ls; ls "{made}"', (_HOLD_DISABLE,)),
    ("bk5", "a `PATH=` assignment", 'PATH=/usr/bin:/bin; touch "{made}"',
     (_HOLD_READONLY,)),
    ("bk6", "a `PATH=` prefixing a command", 'PATH=/usr/bin:/bin touch "{made}"',
     (_HOLD_READONLY,)),
    ("bk7", "`enable` turning a builtin back on", 'enable command; command -p touch "{made}"',
     (_HOLD_ENABLE, _HOLD_READONLY)),
    ("bk8", "`source` of a file outside", 'source "{sourced}"', (_HOLD_DISABLE,)),
    ("bk9", "`.` of a file outside", '. "{sourced}"', (_HOLD_DISABLE,)),
    ("bk10", "`trap` running text on exit", "trap 'echo x > \"{made}\"' EXIT",
     (_HOLD_DISABLE,)),
    ("bk11", "the command hash written through BASH_CMDS",
     'BASH_CMDS[ls]=/usr/bin/touch; ls "{made}"', (_HOLD_READONLY,),
     _HAS_CMDS),
    ("bk12", "a variable the sudo stub reads, pointed at the real tools",
     'STUB_BIN=/usr/bin sudo touch "{made}"', (_HOLD_READONLY,)),
]

# THE SHAPES THE READER ONCE ACCEPTED WHILE BASH READ THEM OTHERWISE: (id, what, the
# line, the problem the reader must refuse it for, or None - a line bash may print
# instead of starting the program, which is still bash taking the shape the way the
# escape needs). Each reaches outside by a relative path, never an absolute one, so
# the reader cannot refuse it for the absolute-path line instead of the rule the row
# is about; `_escape_cases` runs each past the reader and as a step.
_TOUCH_OUT = '%susr/bin/touch "$HOME/../../{outside_name}/made"' % (_CLIMB,)
ESCAPES = [
    ("bq4", "a `printf` whose first word is a single-quoted `-v`, which bash takes as "
     "the option, and a name whose subscript runs a program",
     "printf '-v' 'a[$(%s)]' y" % (_TOUCH_OUT,), "a `printf` whose format",
     "not a valid identifier"),
    ("bq5", "an `eval` whose word is the allowed substitution with text after it inside "
     "the same quotes", 'eval "$(apt-config shell s D/d); %s #)"'
     % (_TOUCH_OUT.replace('"', '\\"'),), "an `eval` of anything but", None),
    ("bq6", "an `eval` whose word is the allowed substitution followed by a variable",
     "v='; %s #'\neval \"$(apt-config shell s D/d)$v)\"" % (_TOUCH_OUT,),
     "an `eval` of anything but", None),
    ("bq7", "a builtin called before a function of the same name is defined, which bash "
     "runs as the builtin", "x='%s'\neval \"$x\"\neval() {{ true; }}" % (_TOUCH_OUT,),
     "a function named", None),
]


def mutate(text, edits):
    """(mutated text, problem): each anchor must occur exactly once."""
    for anchor, replacement in edits:
        n = text.count(anchor)
        if n != 1:
            return None, "anchor found %d time(s), so the mutation was not applied: %r" \
                % (n, anchor[:80])
        text = text.replace(anchor, replacement)
    return text, None


_FIXTURE_ACTION = """\
name: x
runs:
  using: composite
  steps:
    - id: one
      shell: bash
      env:
        A: "1"
        B: ${{ steps.x.outputs.y }}
      run: |
        # a script line that reads like a comment
        echo one

        echo two
    # a YAML comment between steps
    - name: "two: quoted"
      if: ${{ inputs.seed == 'true' }}
      uses: actions/cache/restore@v6
      with:
        path: ~/.cache/x
        lookup-only: true
"""


def _parser_cases(check):
    got = read_steps(_FIXTURE_ACTION)
    steps = got["steps"]
    check("bp1 the reader takes each step's keys, a literal `run:` block with its "
          "blank line and its comment-shaped script line, and an `env:` mapping with "
          "a quoted value unquoted: %r" % (got,),
          got["problem"] is None and len(steps) == 2
          and steps[0]["run"] == ("# a script line that reads like a comment\n"
                                  "echo one\n\necho two\n")
          and steps[0]["env"] == {"A": "1", "B": "${{ steps.x.outputs.y }}"}
          and steps[1]["name"] == "two: quoted"
          and steps[1]["with"]["lookup-only"] == "true"
          and "a YAML comment" not in steps[0]["run"])

    folded = read_steps(_FIXTURE_ACTION.replace("      run: |\n", "      run: >\n"))
    twice = read_steps(_FIXTURE_ACTION.replace("    - name:", "    - id: one\n      name:"))
    check("bp2 a shape the reader does not read - a folded `run:`, a step id used "
          "twice, no `runs:` at all - is a named problem, never a step read as "
          "empty: %r / %r / %r" % (folded["problem"], twice["problem"],
                                   read_steps("name: x\n")["problem"]),
          folded["problem"] and "block scalar" in folded["problem"]
          and folded["steps"] == []
          and twice["problem"] and "used twice" in twice["problem"]
          and read_steps("name: x\n")["problem"])

    rows = run_cases("name: x\n", only=["bi1", "sd1"])
    check("bp3 an action that does not read fails every case asked for, naming why, "
          "rather than running none of them: %r" % (rows,),
          [r["id"] for r in rows] == ["bi1", "sd1"]
          and not any(r["ok"] for r in rows)
          and all("could not be read" in r["detail"] for r in rows))

    with io.open(os.path.join(REPO, ACTION_REL), encoding="utf-8") as fh:
        real = read_steps(fh.read())
    ids = [s.get("id") for s in real["steps"] if s.get("id")]
    check("bp4 the committed action reads, and holds the steps the cases run: %r / %r"
          % (real["problem"], ids),
          real["problem"] is None
          and set(["pins", "sysdeps", "seen-browser", "seen-sysdeps", "plan",
                   "sysdeps-install"]) <= set(ids))

    ids = [c[0] for c in CASES]
    check("bp5 every case id is unique, and every id a mutation row expects red is a "
          "case: %r" % ([m[3] for m in MUTATIONS],),
          len(ids) == len(set(ids))
          and all(set(m[3]) <= set(ids) for m in MUTATIONS)
          and all(row[4] in ids for row in CONFINEMENT)
          and set(STRUCTURAL) <= set(ids))

    inputs = read_inputs("name: x\ninputs:\n  seed:\n    description: >-\n"
                         "      two: lines\n      of text\n    default: \"false\"\n"
                         "  other:\n    required: true\nruns:\n  using: composite\n")
    check("bp6 the inputs reader takes each input's scalar keys, a block "
          "description as present with no text, and stops at the next top-level "
          "key: %r" % (inputs,),
          inputs == {"seed": {"description": "", "default": "false"},
                     "other": {"required": "true"}})

    words = set(w for s in real["steps"] for ln in s.get("run", "").splitlines()
                if not ln.strip().startswith("#") for w in re.findall(r"[\w-]+", ln))
    unused = [n for n, _why in ALLOWED_TOOLS if n not in words or n in STUBS]
    check("bp8 every allowed real tool is one a step of the committed action names, "
          "and none is also a stub - so the list shrinks when the action stops "
          "needing a tool (unused or doubled: %r)" % (unused,),
          ALLOWED_TOOLS and not unused)

    lines = _absolute_path_lines([{"id": "a", "run": (
        "# /usr/bin in a comment\nx=$(ls 2>/dev/null)\nd=\"$HOME/.cache\"\n"
        "sed -n 's/.*--x//p' ~/.y\ncd /tmp\n/usr/bin/sudo rm \"$d\"\n"
        "echo x >/etc/y\nprintf '%s' /dev/nullx\n")}])
    check("bp7 the absolute-path reader names a command, an argument and a "
          "redirection target written as an absolute path - /dev/null alone "
          "excepted, and a lookalike of it not - and no comment, `$HOME/...`, `~/...`"
          " or sed script: %r" % (lines,),
          [ln for _s, ln in lines] == ["cd /tmp", '/usr/bin/sudo rm "$d"',
                                        "echo x >/etc/y", "printf '%s' /dev/nullx"])

    called = set()
    for sid in RUN_STEPS:
        tokens, _end, _problem = _lex((step_by_id(real["steps"], sid) or {}).get("run", ""),
                                      0, False)
        called |= set(c[0] for c in _parse(tokens)["calls"])
    spare = [n for n, _why in BUILTINS
             if n not in called or n in STUBS or n in SHELL_STUBS
             or n in dict(ALLOWED_TOOLS)]
    check("bp9 every builtin BUILTINS keeps is one a step the cases run calls, and "
          "none is also a stub or a tool - so the list shrinks when the action stops "
          "calling one, and the prelude disables it again (unused or doubled: %r)"
          % (spare,), BUILTINS and not spare)

    _reader_cases(check)


# THE READER'S TWO DIRECTIONS. Each refused line carries the problem it must be
# refused for, so a line refused for some other reason is red here; each read line
# is a shape the committed action has, so a rule widened until it fires on one of
# them is red here too.
_READER_REFUSED = (
    ("command -p rm x", "`command` is not a stub"),
    ("exec rm x", "`exec` is not a stub"),
    ("env rm x", "`env` is not a stub"),
    ("hash -p x rm", "`hash` is not a stub"),
    ("enable -f x y", "`enable` is not a stub"),
    ("source x", "`source` is not a stub"),
    (". x", "not a bare name: '.'"),
    ("builtin command x", "`builtin` is not a stub"),
    ("trap 'x' EXIT", "`trap` is not a stub"),
    ("../bin/rm x", "not a bare name"),
    ('"$X/rm" x', "not a bare name"),
    ("$X x", "not a bare name"),
    ("$(echo rm) x", "not a bare name"),
    ("BASH_CMDS[ls]=x", "not a bare name"),
    ("PATH=x", "an assignment to PATH"),
    ("x=1 rm y", "an assignment prefixing"),
    ("f() { x=1; }; IFS=y", "an assignment to IFS"),
    ("set -x", "`set -x`"),
    ("printf -v x y", "a `printf` whose format"),
    ("printf '-v' x y", "a `printf` whose format"),
    ("printf -- x", "a `printf` whose format"),
    ('printf "$x" y', "a `printf` whose format"),
    ('eval "$x"', "an `eval` of anything but"),
    ('eval "$(apt-config shell s D/d); rm x #)"', "an `eval` of anything but"),
    ('eval "$(apt-config shell s D/d)$x"', "an `eval` of anything but"),
    ('eval x"$(apt-config shell s D/d)"', "an `eval` of anything but"),
    ('eval "$(apt-config shell s D/d)" x', "an `eval` of anything but"),
    ("eval $(apt-config shell s D/d)", "an `eval` of anything but"),
    ('eval "$(apt-config shell s D/d; rm x)"', "an `eval` of anything but"),
    ("eval() { true; }", "a function named 'eval'"),
    ("sudo() { true; }", "a function named 'sudo'"),
    ("echo x {y}>/dev/null", "a `{y}` against a redirection"),
    ("set -- x >'/tmp/y'", "a redirection >"),
    ('echo x >"$HOME"', "a redirection >"),
    ('echo x >"$GITHUB_OUTPUT"x', "a redirection >"),
    ('[ -v "$x" ]', "a `[` test"),
    ('[ $x = "y" ]', "a `[` test"),
    ("[ -n x* ]", "a `[` test"),
    ("[ -n {a,b} ]", "a `[` test"),
    ("echo $((1))", "an arithmetic expansion"),
    ('echo "${x@P}"', "a parameter expansion operator"),
    ('echo "${!x}"', "a parameter expansion this reader"),
    ("echo ${x[0]}", "a parameter expansion operator"),
    ("rm <(x)", "a redirection with no target"),
    ("echo `x`", "a backquoted"),
    ("rm x &", "a form this reader does not read"),
    ("echo x > y", "a redirection >"),
    ("cat <<EOF", "a redirection <<"),
    ("(rm x)", "a subshell"),
    ("f() { /bin/rm x; }", "not a bare name"),
    ("echo $(case x in a) rm;; esac)", "never closed"),
    ("function f { rm; }", "`function`"),
    ("[[ x ]]", "`[[`"),
    ("if rm; then", "`if` never closed"),
)
_READER_READ = (
    'v=$(node -e "require(\'./x.json\');process.exit(1)")',
    'if [ -z "${ImageOS:-}" ]; then\n  echo "x" >&2\n  exit 1\nfi',
    'echo "a ${v:-(none)} b" >> "$GITHUB_OUTPUT"',
    'case "$out" in\n  *--x*) ;;\n  *) printf \'%s\\n\' "$out" >&2; exit 1 ;;\nesac',
    "w=$(printf '%s\\n' \"$out\" | sed -n 's/.*--x//p' | tr -d '\"')",
    'for p in $w; do\n  s=$(dpkg-query -W -f=\'${Status}\' "$p" 2>/dev/null || true)\n'
    '  [ "$s" = "y" ] || m="$m $p"\ndone',
    'x="${x:+$x and }the key\'s"',
    'f() {\n  sudo apt-get -o A="$d/x/" "$@"\n}\ng() {\n  sudo rm -rf "$d" &&\n'
    '    eval "$(apt-config shell s D/d)" &&\n    f install\n}\nd=x\ng',
    'if [ -d "$d" ] && ls "$d/"*_P* >/dev/null 2>&1; then\n'
    '  if ! u=$(sudo apt-get --print-uris $M); then\n    set -- $u\n    echo "$# $*"\n'
    '  fi\nelif [ -z "$w" ] && ! ls; then\n  echo y\nfi',
    'sudo chown -R "$(id -u):$(id -g)" "$d"',
    'if [ "$SEED" != "true" ]; then\n  echo "install=true" >> "$GITHUB_OUTPUT"\n'
    '  exit 0\nfi',
)


def _reader_cases(check):
    wrong = []
    for line, says in _READER_REFUSED:
        problems = command_word_problems(line)
        if not any(says in p for p in problems):
            wrong.append((line, says, problems))
    check("bp10 the reader refuses each shape that starts a program past the stubs or "
          "evaluates text as code, for the reason given, and reads every shape the "
          "action has (refused for another reason, or not at all: %r)" % (wrong,),
          not wrong)
    misread = [(line, got) for line, got in
               ((ln, command_word_problems(ln)) for ln in _READER_READ) if got]
    check("bp11 the reader reads, with no problem, a line of each shape the "
          "committed action has (refused: %r)" % (misread,), not misread)
    _respelling_cases(check)


# --- respelling the reader's tables -------------------------------------------------
# A RULE WRITTEN AGAINST A WORD'S SPELLING is told apart from one written against its
# value by writing the word again in a quoting bash reads the same way. Every field of
# a table line that is written bare - at the top or inside a command substitution,
# itself unquoted and unexpanded, made of characters no quoting changes the meaning
# of - is respelled; a reserved word, an
# assignment, a function's name, a `for` name and a descriptor written against a
# redirection are not, because bash itself reads those by their spelling. The fields
# are found by a scanner of this section's own, not by the reader's lexer, so a lexer
# that misplaces a word does not also choose which words the case varies.
_RESPELL_RESERVED = ("if", "then", "else", "elif", "fi", "do", "done", "case", "esac",
                     "for", "while", "until", "in", "function", "select", "time",
                     "coproc", "{", "}", "!", "[[", "]]")
_RESPELL_FIELD = re.compile(r"(?:[A-Za-z0-9_.,:%+@/=!-]+|\[|\])\Z")
_RESPELL_KINDS = ("sq", "dq", "pieces", "mixed")
_DELIMITERS = " \t\n;&|()<>"


def _respell(word, kind):
    """`word` written again in `kind`'s quoting; bash's value for it is `word`."""
    if kind == "sq":
        return "'%s'" % (word,)
    if kind == "dq":
        return '"%s"' % (word,)
    if kind == "pieces":
        return "'%s''%s'" % (word[:1], word[1:])
    if kind == "mixed":
        return '%s"%s"' % (word[:1], word[1:])
    return "\\" + word


def _closing_brace(line, i):
    """The index after the `}` closing a `${` whose body starts at i."""
    depth, quote = 1, None
    while i < len(line):
        char, step = line[i], 1
        if quote is not None:
            if char == "\\" and quote == '"':
                step = 2
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "\\":
            step = 2
        elif line.startswith("${", i):
            depth, step = depth + 1, 2
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += step
    return len(line)


def _fields_in(line, i, nested):
    """([(start, end, bare)], index after them) for each field from i - to the `)`
    closing a command substitution when `nested` - and each field inside every
    `$( )` it meets, at any depth. A field is bare when no character of it is quoted,
    escaped or expanded; an arithmetic `$(( ))` is passed over whole."""
    fields, start, bare, quote, depth = [], None, True, None, 0
    while i < len(line):
        char = line[i]
        if quote == "'":
            quote, i = (None if char == "'" else quote), i + 1
            continue
        opened = line[i:i + 2] if line.startswith(("$(", "${"), i) else None
        if line.startswith("$((", i):
            end = line.find("))", i)
            i, bare = (len(line) if end < 0 else end + 2), False
            continue
        if quote == '"':
            if opened == "$(":
                inner, i = _fields_in(line, i + 2, True)
                fields += inner
            elif opened == "${":
                i = _closing_brace(line, i + 2)
            else:
                quote = None if char == '"' else quote
                i += 2 if char == "\\" else 1
            continue
        if nested and char == ")" and depth == 0:
            if start is not None:
                fields.append((start, i, bare))
            return fields, i + 1
        if char in _DELIMITERS:
            if start is not None:
                fields.append((start, i, bare))
            start, depth, i = None, depth + {"(": 1, ")": -1}.get(char, 0), i + 1
            continue
        if start is None and char == "#":
            end = line.find("\n", i)
            i = len(line) if end < 0 else end
            continue
        if start is None:
            start, bare = i, True
        if opened == "$(":
            inner, i = _fields_in(line, i + 2, True)
            fields, bare = fields + inner, False
        elif opened == "${":
            i, bare = _closing_brace(line, i + 2), False
        elif char in "'\"":
            quote, bare, i = char, False, i + 1
        else:
            bare = bare and char not in "\\$`"
            i += 2 if char == "\\" else 1
    if start is not None:
        fields.append((start, len(line), bare))
    return fields, len(line)


def _respellable(line):
    """[(start, end)] of each field of `line` a respelling may rewrite, in order."""
    spans, before = [], None
    for start, end, bare in sorted(_fields_in(line, 0, False)[0]):
        word = line[start:end]
        if (bare and _RESPELL_FIELD.match(word) and word not in _RESPELL_RESERVED
                and not _ASSIGNMENT.match(word) and line[end:end + 1] not in ("(", "<", ">")
                and before not in ("for", "select", "function")):
            spans.append((start, end))
        before = word
    return spans


def _respelled(line, kinds):
    """[(word, kind, line)]: each respellable field of `line` respelled alone, once per
    kind, then every respellable field at once, once per kind (word None)."""
    spans = _respellable(line)
    one = [(line[s:e], kind, line[:s] + _respell(line[s:e], kind) + line[e:])
           for s, e in spans for kind in kinds]
    whole = []
    for kind in kinds:
        text = line
        for s, e in reversed(spans):
            text = text[:s] + _respell(text[s:e], kind) + text[e:]
        whole.append((None, kind, text))
    return one + (whole if spans else [])


def _respelling_cases(check):
    tried, wrong = 0, []
    for line, says in _READER_REFUSED:
        for word, kind, text in _respelled(line, _RESPELL_KINDS + ("backslash",)):
            tried += 1
            want = (says, "a backslash outside quotes") if kind == "backslash" else (says,)
            problems = command_word_problems(text)
            if not any(w in p for p in problems for w in want):
                wrong.append((text, says, problems))
    check("bq1 each shape the reader refuses is still refused, for the reason given, "
          "when a bare word of it is written in single quotes, double quotes, adjacent "
          "quoted pieces or after a backslash - quotings bash reads the same way - so no "
          "rule judges a word by its spelling (%d respellings; refused otherwise or not "
          "at all: %r)" % (tried, wrong), tried and not wrong)
    tried, wrong = 0, []
    for line in _READER_READ:
        for word, kind, text in _respelled(line, _RESPELL_KINDS):
            tried += 1
            problems = command_word_problems(text)
            if problems:
                wrong.append((text, problems))
    check("bq2 each shape the action has is read with no problem, as it is bare, when a "
          "bare word of it - or every bare word at once - is written in single quotes, "
          "double quotes or adjacent quoted pieces (%d respellings; refused: %r)"
          % (tried, wrong), tried and not wrong)


_TRACE_KEYWORDS = ("case", "for")


def _started(out, root):
    """[(raw trace line, word)] for each command bash's trace shows it running, the
    fixture root written ROOT; word is None for an assignment and the keyword for a
    traced `case` or `for`."""
    real = os.path.realpath(root)
    rows = []
    for line in out.replace(real, "ROOT").replace(root, "ROOT").splitlines():
        traced = re.match(r"\++ (.*)", line)
        if traced is None:
            continue
        body = traced.group(1)
        if _ASSIGNMENT.match(body):
            rows.append((line, None))
            continue
        try:
            first = shlex.split(body)[:1]
        except ValueError:
            first = body.split(" ")[:1]
        rows.append((line, first[0] if first else ""))
    return rows


def _traced(line, root):
    """bash's own account of `line`, run after the prelude against the stubs: its
    exit and the commands its trace shows it running."""
    build_base(root)
    env = _stub_env(root, {"GITHUB_OUTPUT": os.path.join(root, "github-output"),
                           "SEED": "false", "M": "libA", "ImageOS": "ubuntu24"})
    result = _run_bash(line + "\n", env, root, trace=True)
    return result["code"], _started(result["out"], root)


def _traced_read_cases(check):
    """`bq3`: an accepted shape is a statement about bash, not about the reader."""
    vocabulary = (set(STUBS) | set(SHELL_STUBS) | set(n for n, _w in ALLOWED_TOOLS)
                  | set(n for n, _w in BUILTINS) | set(_TRACE_KEYWORDS))
    outside, differs, runs = [], [], 0
    for line in _READER_READ:
        defined = set(re.findall(r"([a-z_][a-z0-9_]*)\(\)", line))
        seen = None
        for _word, kind, text in [(None, "bare", line)] + [
                r for r in _respelled(line, _RESPELL_KINDS) if r[0] is None]:
            root = tempfile.mkdtemp(prefix="browser-install-trace-")
            try:
                code, started = _traced(text, root)
            finally:
                shutil.rmtree(root)
            runs += 1
            outside += [(text, raw) for raw, word in started
                        if word is not None and word not in vocabulary | defined]
            # Sorted: the members of a pipeline start at once, so their trace lines
            # interleave differently from run to run; what is compared is which
            # commands ran, with which arguments, and how often.
            got = (code, sorted(raw for raw, _w in started))
            if seen is None:
                seen = got
            elif got != seen:
                differs.append((kind, text, seen, got))
    check("bq3 each shape the action has, and each respelling of it, run after the "
          "prelude against the stubs: bash's own trace shows it starting nothing but a "
          "stub, an allowed tool, a builtin on BUILTINS or a function it defines, and "
          "each respelling runs the same commands to the same exit as the bare line "
          "(%d runs; started outside that: %r; run differently: %r)"
          % (runs, outside, differs), runs and not outside and not differs)


def _bash_version():
    done = subprocess.run([shutil.which("bash"), "--norc", "--noprofile", "-c",
                           'echo "$BASH_VERSION"'], stdout=subprocess.PIPE,
                          stdin=subprocess.DEVNULL)
    return done.stdout.decode("utf-8", "replace").strip() or "unknown"


def _escape_cases(check):
    """ESCAPES' rows, each on two fixtures and two scratch directories of its own,
    removed in `finally`: past the reader, where bash's reading is the row's, and
    through `run_script`, where the reader refuses the line before it starts."""
    version = _bash_version()
    for cid, what, line, says, or_says in ESCAPES:
        dirs = []
        try:
            outside, names = _outside_files()
            dirs.append(outside)
            root = tempfile.mkdtemp(prefix="browser-install-escape-")
            dirs.append(root)
            build_base(root)
            script = line.format(**names) + "\n"
            past = _run_bash(script, _stub_env(root), root)
            reached = not _outside_intact(names)
            outside2, names2 = _outside_files()
            dirs.append(outside2)
            root2 = tempfile.mkdtemp(prefix="browser-install-escape-")
            dirs.append(root2)
            build_base(root2)
            script2 = line.format(**names2) + "\n"
            gated = run_script(script2, _stub_env(root2), root2)
            intact = _outside_intact(names2)
            problems = script_problems(script2)
            refused = any(says in p for p in problems)
            bash_read = reached or (or_says is not None and or_says in past["out"])
            if reached:
                seen = ("starts the program on bash %s, so the construction does not "
                        "hold it and the reader is its only hold" % (version,))
            elif bash_read:
                seen = ("says %r on bash %s: it takes the shape as the escape needs, "
                        "and this bash starts nothing from it" % (or_says, version))
            else:
                seen = "starts nothing on bash %s, so the row shows no escape" % (version,)
            check("%s %s: past the reader bash %s; the reader refuses it for %r and, "
                  "run as a step, the file outside is as it was (refused: %r, outside "
                  "intact: %r)" % (cid, what, seen, says, refused, intact),
                  bash_read and refused and intact and gated["code"] is None,
                  "past the reader:\n%s\nreader: %r" % (past["out"], problems))
        finally:
            for d in dirs:
                shutil.rmtree(d)


def _cases(check):
    import _harness            # on sys.path once `_suite` is imported by `_selftest`

    _parser_cases(check)
    with io.open(os.path.join(REPO, ACTION_REL), encoding="utf-8") as fh:
        text = fh.read()
    host = posix_problem()
    if host is not None:
        _harness.skip(check, "bc0 the committed action against the stubs, and each "
                      "mutation of it", host, True)
        for row in run_cases(text, only=STRUCTURAL):
            check("%s %s" % (row["id"], row["what"]), row["ok"], row["detail"])
        return
    rows = run_cases(text)
    for row in rows:
        check("%s %s (the committed action)" % (row["id"], row["what"]), row["ok"],
              row["detail"])
    green = set(r["id"] for r in rows if r["ok"])
    for mid, what, edits, expect, says in MUTATIONS:
        broken, problem = mutate(text, edits)
        if problem is not None:
            check("%s %s: NOT APPLIED" % (mid, what), False, problem)
            continue
        got = run_cases(broken, only=expect)
        red = [r["id"] for r in got if not r["ok"]]
        said = says is None or any(says in r["detail"] for r in got)
        check("%s %s: %s go red, each green on the committed action%s (red: %r)"
              % (mid, what, ", ".join(expect),
                 "" if says is None else ", and the run says %r" % (says,), red),
              red == list(expect) and set(expect) <= green and said,
              "\n".join("%s: %s" % (r["id"], r["detail"]) for r in got))
    _confinement_cases(check, text, green)
    _construction_cases(check)
    _traced_read_cases(check)
    _escape_cases(check)


def _outside_files():
    """(scratch directory no fixture root contains, {"victim", "made", "sourced",
    "outside_name"}): a file holding "kept", a path that must stay absent, and a
    script that would write that path if anything ran it."""
    outside = tempfile.mkdtemp(prefix="browser-install-outside-")
    names = {"victim": os.path.join(outside, "victim"),
             "made": os.path.join(outside, "made"),
             "sourced": os.path.join(outside, "sourced.sh"),
             "outside_name": os.path.basename(outside)}
    _write(names["victim"], "kept")
    _write(names["sourced"], 'echo x > "%s"\n' % (names["made"],))
    return outside, names


def _outside_intact(names):
    if not os.path.isfile(names["victim"]) or os.path.lexists(names["made"]):
        return False
    with io.open(names["victim"], encoding="utf-8") as fh:
        return fh.read() == "kept"


def _confinement_cases(check, text, green):
    """CONFINEMENT's rows, each against a scratch directory of its own that no
    fixture root contains, removed in `finally` whatever the row did."""
    for cid, what, anchor, line, case, half, says in CONFINEMENT:
        outside, names = _outside_files()
        try:
            appended = line.format(**names)
            broken, problem = mutate(text, [(anchor, anchor + "        %s\n" % (appended,))])
            if problem is not None:
                check("%s %s: NOT APPLIED" % (cid, what), False, problem)
                continue
            got = run_cases(broken, only=[case])
            intact = _outside_intact(names)
            red = [r["id"] for r in got if not r["ok"]]
            if half == "reader":
                refused = all("the reader refused" in r["detail"] and says in r["detail"]
                              for r in got)
            else:
                refused = all("reached what no stub serves" in r["detail"]
                              and "the reader refused" not in r["detail"] for r in got)
            check("%s %s: %s goes red, refused by the %s%s, green on the committed "
                  "action, and the file outside the fixture is as it was (red: %r, "
                  "outside intact: %r)" % (cid, what, case, half,
                                           "" if says is None else " saying %r" % (says,),
                                           red, intact),
                  red == [case] and case in green and intact and refused,
                  "\n".join("%s: %s" % (r["id"], r["detail"]) for r in got))
        finally:
            shutil.rmtree(outside)


def _reaches(line, drop=()):
    """({"code", "out"}, True when `line` - run past the reader on a fixture of its
    own, the prelude less `drop` - changed the file outside), both scratch
    directories removed in `finally`."""
    outside, names = _outside_files()
    root = tempfile.mkdtemp(prefix="browser-install-construction-")
    try:
        build_base(root)
        result = _run_bash(line.format(**names) + "\n", _stub_env(root), root, drop)
        return result, not _outside_intact(names)
    finally:
        shutil.rmtree(root)
        shutil.rmtree(outside)


def _bash_has(script):
    """True when `script`, run by a plain bash, exits 0."""
    return subprocess.run([shutil.which("bash"), "--norc", "--noprofile", "-c", script],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def _hold_names(holds):
    return " and ".join(repr(h.strip()) for h in holds)


def _construction_cases(check):
    """CONSTRUCTION's rows: each line run past the reader with the whole prelude,
    where the file outside must stay as it was, and again with the lines the row
    names as its hold taken out, where it must not."""
    version = _bash_version()
    for row in CONSTRUCTION:
        cid, what, line, holds = row[:4]
        has = _bash_has(row[4]) if len(row) > 4 else True
        result, reached = _reaches(line)
        try:
            control, unheld = _reaches(line, holds)
        except ValueError as exc:      # a hold the row names is not in the prelude
            check("%s %s: the hold the row names is not in the prelude" % (cid, what),
                  False, str(exc))
            continue
        alone = ("; each alone taken out, it reaches outside: %s" % ", ".join(
            "%s %r" % (h.strip(), _reaches(line, (h,))[1]) for h in holds)
            if len(holds) > 1 else "")
        check("%s %s, run past the reader: the construction alone leaves the file "
              "outside the fixture as it was (exit %r), and with %s taken out the same "
              "line %s on bash %s%s"
              % (cid, what, result["code"], _hold_names(holds),
                 "reaches it" if unheld else (
                     "reaches nothing either" if has else
                     "reaches nothing, because this bash lacks what it uses"),
                 version, alone),
              not reached and result["code"] != 0 and script_problems(line)
              and (unheld or not has),
              "%s\nreader: %r\nwith the hold taken out:\n%s"
              % (result["out"], script_problems(line), control["out"]))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    run(_cases)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
