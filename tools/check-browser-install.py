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
committed file (never a copy of the shell) and executed here, against stubs of sudo,
apt-get, apt-config, mkdir, cp and chown that keep a ledger of who owns each path.

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
  * `sk` - the cache keys the `pins` step writes.
  * `sd` - the wiring the decision rests on, read off the steps' keys: the seed's
    lookups name the same path and key as the restores, the plan reads their answers,
    and every step after the plan installs only when the plan says so.

The selftest holds the parser of the action, runs every case over the committed
action, and then breaks a copy of the action once per property and requires the case
that holds it to go red - so a case that could not fail is itself a red case here.

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
    here evaluates a `${{ }}` expression or an `if:` the way the runner does.
  * the steps not run here: `npm ci`, `npx playwright install chromium`, and the
    dry run that names the packages the image lacks, which need the network and the
    image. A real CI run is still the only evidence for those, and for timings.

IT RUNS ON A POSIX HOST. The stubs are shell scripts bash must execute through a
colon-separated PATH; on a host without that the check says it could not run, and the
selftest records the cases that need it as skipped there, naming why.

Exit codes: 0 every case held - 1 a case failed or could not run - 2 usage error.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
ACTION_REL = os.path.join(".github", "actions", "browser-install", "action.yml")

# GitHub's `shell: bash`, as its documentation spells the command it runs.
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
# The directories a step finds its ordinary tools in; the stubs go in front, so a
# real sudo, apt-get or dpkg on the host is never reached.
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
STEP_TIMEOUT = 120

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


# --- the stubs ---------------------------------------------------------------------
# Each stub is a two-line shell script in the fixture's `bin/` that runs THIS file
# with `--stub NAME`, so the stubs' code is one module with the check and has no file
# of its own to drift from it. Ownership is a ledger (`owners.json` in the fixture),
# because the stubs run as one real user and must behave as root under `sudo` and as
# the runner user otherwise. A path with no entry is the runner user's: HOME, and
# whatever the cache restored.
def _stub_root():
    return os.environ["STUB"]


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
    for target in [a for a in argv if not a.startswith("-")]:
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


STUBS = {"apt-get": stub_apt_get, "mkdir": stub_mkdir, "cp": stub_cp,
         "chown": stub_chown}


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


def build_fixture(restored, drop=(), truncate=(), corrupt=(), stale=False, down=False):
    """A scratch root: `bin/` with the stubs, `home/` (the runner's HOME, holding
    the restored set when `restored`), and `stub/` - the archive, the system's apt
    directories (root's, as on the runner), the ledger and the log."""
    root = tempfile.mkdtemp(prefix="browser-install-")
    stub = os.path.join(root, "stub")
    home = os.path.join(root, "home")
    binp = os.path.join(root, "bin")
    for d in (os.path.join(stub, "archive", "pool"), os.path.join(stub, "sys", "lists"),
              os.path.join(stub, "sys", "archives"), home, binp):
        os.makedirs(d)
    for name in sorted(STUBS):
        _exec_script(os.path.join(binp, name),
                     '#!/bin/sh\nexec "$STUB_PY" "$STUB_SELF" --stub %s "$@"\n' % (name,))
    _exec_script(os.path.join(binp, "sudo"), '#!/bin/sh\nSTUB_USER=root exec "$@"\n')
    _exec_script(os.path.join(binp, "apt-config"),
                 "#!/bin/sh\necho \"sys_lists='$STUB/sys/lists/'\"\n")
    _write(os.path.join(stub, "installed"), "libD\n")
    _write(os.path.join(stub, "log"), "")
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
    return root


def posix_problem():
    """Why the stubbed steps cannot run on this host, or None."""
    if os.pathsep != ":" or os.name != "posix":
        return ("the stubs are shell scripts bash executes through a colon-separated "
                "PATH, which this host (os.name %r) does not give" % (os.name,))
    if shutil.which("bash") is None:
        return "no bash on PATH, and the action's steps are `shell: bash`"
    return None


def run_script(script, env, cwd):
    """(exit code, combined output) of one step's script under GitHub's bash flags."""
    path = os.path.join(cwd, "step.sh")
    _write(path, script)
    try:
        done = subprocess.run([shutil.which("bash")] + list(BASH_FLAGS) + [path],
                              env=env, cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=STEP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "the step did not finish in %ds" % (STEP_TIMEOUT,)
    return done.returncode, done.stdout.decode("utf-8", "replace")


# --- the cases ----------------------------------------------------------------------
def _stub_env(root, extra=None):
    env = {"PATH": os.path.join(root, "bin") + ":" + SYSTEM_PATH,
           "HOME": os.path.join(root, "home"), "TMPDIR": root,
           "STUB": os.path.join(root, "stub"), "STUB_PY": sys.executable,
           "STUB_SELF": os.path.abspath(__file__), "LC_ALL": "C"}
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
    def run_case(steps):
        step = step_by_id(steps, "sysdeps-install")
        if step is None or "run" not in step:
            return False, "the action has no `sysdeps-install` step with a `run:`"
        root = build_fixture(**fixture)
        try:
            code, out = run_script(step["run"], _stub_env(root, {"MISSING": MISSING}),
                                   root)
            if code is None:
                return False, out
            not_runner, leftovers = _set_state(root)
            got = _observed(code, out, _log_lines(root), not_runner, leftovers)
        finally:
            shutil.rmtree(root)
        bad = ["%s: want %r, got %r" % (k, v, got[k]) for k, v in sorted(want.items())
               if got[k] != v]
        if says is not None and says not in out:
            bad.append("the output lacks %r" % (says,))
        return not bad, "%s\nexit %r\n%s" % ("; ".join(bad), code, out.rstrip())
    return run_case


def _plan_case(env, want_install, says):
    """A case running the `plan` step; `says` None means the step prints nothing,
    which is what a job that is not a seed must do."""
    def run_case(steps):
        step = step_by_id(steps, "plan")
        if step is None or "run" not in step:
            return False, "the action has no `plan` step with a `run:`"
        root = tempfile.mkdtemp(prefix="browser-install-plan-")
        try:
            out_file = os.path.join(root, "github-output")
            _write(out_file, "")
            full = dict({"PATH": SYSTEM_PATH, "GITHUB_OUTPUT": out_file, "SEED": "true",
                         "BROWSER_SEEN": "", "SYSDEPS_SEEN": "", "MISSING": MISSING},
                        **env)
            code, out = run_script(step["run"], full, root)
            with io.open(out_file, encoding="utf-8") as fh:
                outputs = fh.read().splitlines()
        finally:
            shutil.rmtree(root)
        said = out.strip() == "" if says is None else says in out
        ok = code == 0 and outputs == ["install=%s" % (want_install,)] and said
        return ok, "exit %r, outputs %r, output %r" % (code, outputs, out)
    return run_case


_LOCK_PIN = "9.8.7"


def run_pins(steps, image_os, image_version, lock=None):
    """(exit code, {output: value}, output) of the `pins` step on a scratch root
    holding a package-lock.json that pins playwright-core at `_LOCK_PIN`."""
    step = step_by_id(steps, "pins")
    if step is None or "run" not in step:
        return None, {}, "the action has no `pins` step with a `run:`"
    node = shutil.which("node")
    if node is None:
        return None, {}, "no node on PATH, and the step reads the lockfile with it"
    root = tempfile.mkdtemp(prefix="browser-install-pins-")
    try:
        out_file = os.path.join(root, "github-output")
        _write(out_file, "")
        _write(os.path.join(root, "package-lock.json"), json.dumps(
            lock if lock is not None else
            {"packages": {"node_modules/playwright-core": {"version": _LOCK_PIN}}}))
        env = dict((k, v) for k, v in step.get("env", {}).items() if "${{" not in v)
        env.update({"PATH": os.path.dirname(node) + ":" + SYSTEM_PATH,
                    "GITHUB_OUTPUT": out_file, "RUNNER_OS": "Linux",
                    "RUNNER_ARCH": "X64", "HOME": root})
        if image_os is not None:
            env["ImageOS"] = image_os
        if image_version is not None:
            env["ImageVersion"] = image_version
        code, out = run_script(step["run"], env, root)
        with io.open(out_file, encoding="utf-8") as fh:
            outputs = dict(ln.split("=", 1) for ln in fh.read().splitlines() if "=" in ln)
    finally:
        shutil.rmtree(root)
    return code, outputs, out


def _case_sk1(steps):
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


def _case_sk2(steps):
    code, outputs, out = run_pins(steps, None, "20261111.370.1")
    if code is None:
        return False, out
    return code != 0 and outputs == {} and "ImageOS" in out, \
        "exit %r, outputs %r, output %r" % (code, outputs, out)


def _case_sk3(steps):
    code, outputs, out = run_pins(steps, "ubuntu24", "1", lock={"packages": {}})
    if code is None:
        return False, out
    return code != 0 and outputs == {} and "playwright-core" in out, \
        "exit %r, outputs %r, output %r" % (code, outputs, out)


def _cache_steps(steps):
    """(the seed's lookups, the restores that save) - read by what each step uses."""
    lookups = [s for s in steps if s.get("uses", "").startswith("actions/cache/restore@")]
    restores = [s for s in steps if s.get("uses", "").startswith("actions/cache@")]
    return lookups, restores


def _case_sd1(steps):
    lookups, restores = _cache_steps(steps)
    bad = []
    if len(lookups) != 2:
        bad.append("%d lookup step(s), not one per cache" % (len(lookups),))
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


def _case_sd2(steps):
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


def _case_sd3(steps):
    plan = step_by_id(steps, "plan")
    if plan is None:
        return False, "the action has no `plan` step"
    after = steps[steps.index(plan) + 1:]
    unguarded = [s.get("name") or s.get("id") or s.get("run", "")[:60] for s in after
                 if "steps.plan.outputs.install == 'true'" not in s.get("if", "")]
    return bool(after) and not unguarded, \
        "%d step(s) after the plan; not guarded by its answer: %r" % (len(after), unguarded)


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
    ("sd1", "each seed lookup is lookup-only, runs on a seed alone, and names the path "
     "and key of exactly one restore", _case_sd1),
    ("sd2", "the plan reads the seed input and both lookups' answers", _case_sd2),
    ("sd3", "every step after the plan installs or restores only when the plan says "
     "so", _case_sd3),
]
STRUCTURAL = ("sd1", "sd2", "sd3")


def run_cases(text, only=None):
    """[{"id", "what", "ok", "detail"}] for `text` (an action.yml), one per case -
    `only` narrows to those ids. A host that cannot run the stubs, or an action
    that does not read, is one failing row per case asked for, never an empty list."""
    rows = [c for c in CASES if only is None or c[0] in only]
    parsed = read_steps(text)
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
        ok, detail = fn(parsed["steps"])
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
MUTATIONS = [
    ("bm1", "the first probe's archive path (runner-user mkdir under a root `lists/`)",
     [_FIRST_PROBE_FETCH], ["bi2", "bi10"], "Permission denied"),
    ("bm2", "a hit that cannot see its own index fetches everything, with no warning",
     [('ls "$d/lists/"*_Packages*', 'ls "$d/lists/"*_Release*')], ["bi1"], None),
    ("bm3", "a hit that falls back - green, with one warning",
     [('--print-uris $MISSING); then\n', '--print-uris $MISSING) || [ -n "$d" ]; then\n')],
     ["bi1"], None),
    ("bm4", "no fallback", [('        if [ -n "$why" ]; then\n',
                             '        if false; then\n')], ["bi6", "bi7"], None),
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
     [('        sudo chown -R "$(id -u):$(id -g)" "$d"\n', '')], ["bi2", "bi10"], None),
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
          and set(STRUCTURAL) <= set(ids))


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


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
