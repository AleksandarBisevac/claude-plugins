#!/usr/bin/env python3
"""
The cases for `_skill_places.py` - the one answer to "where does a named skill live",
asked by the launcher that loads a task's skills into a session and by
`/audit:doctor`'s check of the names a plan uses.

What is pinned is the order and the refusals, each with a fixture that tells the
right reading from the wrong one: the same name written into the personal AND the
project directory with different bodies, so a resolver that took the wrong one of the
two returns the other's path; a plugin skill of the same bare name beside them, so a
`plugin:skill` that fell back to them is visible.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import hashlib
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _skill_places as M                          # noqa: E402


def _put(base, name, body="body\n"):
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return path


def _cases(check):
    root = _harness.fixture_root("skill-places")
    tree = os.path.join(root, "tree")
    home = os.path.join(root, "home")
    plugin = os.path.join(root, "plugin")
    personal = _put(os.path.join(home, "skills"), "both", "PERSONAL\n")
    project = _put(os.path.join(tree, ".claude", "skills"), "both", "PROJECT\n")
    _put(os.path.join(home, "skills"), "only-personal")
    _put(os.path.join(tree, ".claude", "skills"), "only-project")
    own = _put(os.path.join(plugin, "skills"), "both", "PLUGIN\n")
    own_only = _put(os.path.join(plugin, "skills"), "only-plugin")

    def where(name, running="house"):
        return M.resolve_skill(name, tree, home, plugin, running)

    check("sp1 the places of a bare name are the personal skills, then the project's, "
          "then the running plugin's - Claude Code's documented 'personal over "
          "project', with the plugin last",
          M.skill_places("both", tree, home, plugin, "house")
          == ([personal, project, own], None))
    got = where("both")
    check("sp2 a name held by all three resolves to the PERSONAL copy: %r" % (got,),
          got["path"] == personal and got["source"] == "personal"
          and got["problem"] is None)
    check("sp3 ...and with the personal copy gone the project's is next, then the "
          "plugin's: the order is one a missing file walks down, not a pick",
          (os.remove(personal), where("both")["path"])[1] == project
          and (os.remove(project), where("both")["path"])[1] == own)
    check("sp4 a name only the project holds, and one only the plugin holds, resolve "
          "from there",
          where("only-project")["source"] == "project"
          and where("only-plugin")["path"] == own_only
          and where("only-plugin")["source"] == "plugin")
    check("sp5 a name that is nowhere resolves to NO path and says every place "
          "looked in, in order: %r" % (where("ghost"),),
          where("ghost")["path"] is None and where("ghost")["problem"] is None
          and len(where("ghost")["places"]) == 3
          and where("ghost")["places"][0].startswith(home))

    # --- plugin:skill -----------------------------------------------------------
    _put(os.path.join(home, "skills"), "only-plugin", "SHADOW\n")
    _put(os.path.join(tree, ".claude", "skills"), "only-plugin", "SHADOW\n")
    q = where("house:only-plugin")
    check("sp6 `plugin:skill` resolves from that plugin alone, although a personal "
          "and a project skill of the same bare name exist: %r" % (q,),
          q["path"] == own_only and q["source"] == "plugin")
    other = where("elsewhere:only-plugin")
    check("sp7 ...and another plugin's name resolves to nothing, with the shadows "
          "left unused: %r" % (other,),
          other["path"] is None and other["places"] == [])
    check("sp8 a running plugin whose name could not be read matches no qualified "
          "name",
          where("house:only-plugin", running=None)["path"] is None)

    # --- the names that are no skill name ---------------------------------------
    bad = [where(n)["problem"] for n in ("../escape", "a/b", ".hidden", "", "a:", ":b",
                                         "a:b:c")]
    check("sp9 a name that could leave the skills directories or is empty is a "
          "PROBLEM, never a path: %r" % (bad,), all(bad))

    # --- no second mode: the scan inventory widens nothing ---------------------
    gone = where("scanned")
    check("sp10 a bare name no directory holds is NOT found, however many other "
          "installed plugins ship it: there is one answer and no wider mode: %r"
          % (gone,),
          gone["found"] is False and gone["path"] is None and gone["source"] is None
          and gone["problem"] is None and len(gone["places"]) == 3)
    try:
        M.resolve_skill("scanned", tree, home, plugin, "house", inventory={})
        widened = True
    except TypeError:
        widened = False
    check("sp11 ...and the resolver takes no inventory argument, so a caller cannot "
          "ask for a second answer", not widened)
    seen_sources = set(where(n)["source"] for n in (
        "only-project", "only-personal", "only-plugin", "house:only-plugin", "scanned"))
    check("sp12 the only sources the resolver ever names are the three tiers (or "
          "none, for a name nothing holds): %r" % (sorted(seen_sources, key=str),),
          seen_sources == set(["project", "personal", "plugin", None]))

    # --- which copy is graded for a clone ---------------------------------------
    link = os.path.join(root, "link-to-tree")
    linked = False
    try:
        os.symlink(tree, link)
        linked = True
    except (OSError, NotImplementedError, AttributeError):
        pass
    via_link = os.path.join(link, ".claude", "skills", "only-project", "SKILL.md")
    direct = where("only-project")["path"]
    check("sp17 `same_file` is one file through a symlink, two files apart, and "
          "never true when either path is missing",
          (not linked or M.same_file(via_link, direct))
          and not M.same_file(direct, where("only-personal")["path"])
          and not M.same_file(None, direct) and not M.same_file(direct, ""))

    def entry(travels, path):
        return {"travels": travels, "travelsBasis": "SCAN", "path": path}
    personal_hit = where("only-personal")
    stands = M.loaded_verdict(entry(True, personal_hit["path"]), personal_hit)
    retold = M.loaded_verdict(entry(True, direct), personal_hit)
    unlisted = M.loaded_verdict(None, personal_hit)
    check("sp18 the scan's verdict stands only for the loaded file; about another "
          "copy, or with no copy listed, the loaded personal copy is graded by its "
          "tier and does not travel, naming its path: %r"
          % ((stands, retold, unlisted),),
          stands == {"travels": True, "basis": "SCAN", "graded": "scan"}
          and retold["travels"] is False and retold["graded"] == "tier"
          and personal_hit["path"] in retold["basis"]
          and unlisted == retold)
    nowhere = where("ghost")
    check("sp19 with nothing resolved the scan's copy is the only one the name can "
          "mean, and with neither there is nothing to grade: %r"
          % ((M.loaded_verdict(entry(False, "/x/SKILL.md"), nowhere),
              M.loaded_verdict(None, nowhere)),),
          M.loaded_verdict(entry(False, "/x/SKILL.md"), nowhere)
          == {"travels": False, "basis": "SCAN", "graded": "scan"}
          and M.loaded_verdict(None, nowhere) is None)
    # THE AGREEMENT, pinned rather than claimed in a comment: the tier grade here
    # and the scan's grade for the same tier are two implementations of one rule.
    import _panel_discovery
    decl = {"problem": None, "enabled": set(), "marketplaces": set(),
            "present": False}
    scan_source = {"personal": "user", "project": "project", "plugin": "plugin"}
    pairs = []
    # The plugin tier is asked through the qualified name: the bare one is
    # shadowed by the personal and project copies written above.
    for name in ("only-personal", "only-project", "house:only-plugin"):
        hit = where(name)
        bare = name.split(":")[-1]
        mine = M.loaded_verdict(None, hit)["travels"]
        theirs = _panel_discovery.grade_entry(
            bare, scan_source[hit["source"]], hit["path"], decl,
            set([bare]), plugin)["travels"]
        pairs.append((hit["source"], mine, theirs))
    check("sp20 each tier the resolver names is graded as the machine scan grades "
          "the same tier - a personal copy never travels, a project or the "
          "running plugin's own does: %r" % (pairs,),
          pairs == [("personal", False, False), ("project", True, True),
                    ("plugin", True, True)])

    # --- the running plugin's name ----------------------------------------------
    manifest = os.path.join(plugin, ".claude-plugin", "plugin.json")
    os.makedirs(os.path.dirname(manifest))
    check("sp14 an unreadable plugin.json gives no name rather than a guess",
          M.plugin_name(plugin) is None)
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write('{"name": "house"}')
    check("sp15 ...and a readable one gives its name", M.plugin_name(plugin) == "house")
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write('{"name": 7}')
    check("sp16 ...a name that is not a string is none", M.plugin_name(plugin) is None)


# --- the pinned bytes ---------------------------------------------------------------
def _write(path, data):
    """`data` (bytes) at `path`, its directory made."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _lines_digest(folder):
    """The directory digest computed here, apart from the module: SHA-256 over the
    sorted lines `<relative posix path> <sha256 of the file>`, a file holding no
    NUL byte read with each CRLF taken as LF. Two computations, so a case that
    compares them is not a value compared with itself."""
    lines = []
    for here, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(here, name)
            with open(full, "rb") as fh:
                data = fh.read()
            if b"\0" not in data:
                data = data.replace(b"\r\n", b"\n")
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            lines.append("%s %s\n" % (rel, hashlib.sha256(data).hexdigest()))
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


# A skill directory: its SKILL.md and a sibling under a subdirectory, each with
# a line break, and a file holding a NUL byte, whose CRLF is data.
_SKILL = {"SKILL.md": b"---\nname: pinned\ndescription: d\n---\nbody line\nmore\n",
          "scripts/helper.py": b"print('a')\nprint('b')\n",
          "assets/blob.bin": b"\x00\x01\r\n\x02"}


def _skill_dir(base, name, files=None, crlf=False):
    """`<base>/<name>/` holding `files` (default `_SKILL`); with `crlf` every
    text file is written with CRLF line ends, as a converting checkout leaves it."""
    folder = os.path.join(base, name)
    for rel, data in sorted((files or _SKILL).items()):
        if crlf and b"\0" not in data:
            data = data.replace(b"\n", b"\r\n")
        _write(os.path.join(folder, *rel.split("/")), data)
    return folder


def _digest_cases(check, root):
    """The digest of a skill's DIRECTORY: every file, line ends read alike, and no
    answer for a directory that cannot be read whole."""
    base = os.path.join(root, "digest")
    lf = _skill_dir(base, "lf")
    got = M.skill_digest(lf)
    check("sp21 the digest is SHA-256 over the sorted `<relative posix path> "
          "<sha256>` lines of every file under the skill's directory, a "
          "subdirectory's file included: %r" % (got,),
          got["problem"] is None and got["digest"] == _lines_digest(lf)
          and got["files"] == len(_SKILL))
    crlf = _skill_dir(base, "crlf", crlf=True)
    with open(os.path.join(crlf, "SKILL.md"), "rb") as fh:
        converted = b"\r\n" in fh.read()
    check("sp22 a checkout that converted line endings answers the SAME digest as "
          "the one that pinned it (the copy here was checked to hold CRLF: %r)"
          % (converted,),
          converted and M.skill_digest(crlf)["digest"] == got["digest"])
    binary = _skill_dir(base, "bin", dict(_SKILL, **{
        "assets/blob.bin": b"\x00\x01\n\x02"}))
    check("sp23 ...but a file holding a NUL byte is data, its CRLF a byte like any "
          "other: the same blob with LF in place of CRLF is another digest",
          M.skill_digest(binary)["digest"] not in (None, got["digest"]))
    sibling = _skill_dir(base, "sib", dict(_SKILL, **{
        "scripts/helper.py": b"print('a')\nprint('c')\n"}))
    added = _skill_dir(base, "add", dict(_SKILL, **{"notes.md": b"x\n"}))
    renamed = _skill_dir(base, "ren", dict(
        [(k, v) for k, v in _SKILL.items() if k != "scripts/helper.py"],
        **{"scripts/helper2.py": _SKILL["scripts/helper.py"]}))
    body = _skill_dir(base, "body", dict(_SKILL, **{
        "SKILL.md": _SKILL["SKILL.md"].replace(b"body line", b"body lime")}))
    seen = [M.skill_digest(d)["digest"] for d in (sibling, added, renamed, body)]
    check("sp24 one changed byte in a sibling file, a file added, a file renamed and "
          "one changed byte in SKILL.md are each another digest - the directory is "
          "what is hashed, not SKILL.md alone: %r" % (seen,),
          None not in seen and len(set(seen + [got["digest"]])) == 5)

    outside = _write(os.path.join(root, "outside", "secret.md"), b"elsewhere\n")
    linked = _skill_dir(base, "linkout")
    lnk_dir = _skill_dir(base, "linkdir")
    try:
        os.symlink(outside, os.path.join(linked, "leak.md"))
        os.symlink(os.path.join(lnk_dir, "scripts"), os.path.join(lnk_dir, "again"))
        links = True
    except (OSError, NotImplementedError, AttributeError):
        links = False
    out_ans = M.skill_digest(linked)
    dir_ans = M.skill_digest(lnk_dir)
    check("sp25 a link leading out of the directory, or a link to a directory, has "
          "NO digest - the third answer, with the reason: %r" % ((out_ans, dir_ans),),
          not links or (out_ans["digest"] is None and "leak.md" in out_ans["problem"]
                        and dir_ans["digest"] is None and "again" in dir_ans["problem"]))
    many = M.skill_digest(lf, max_files=len(_SKILL) - 1)
    big = M.skill_digest(lf, max_bytes=8)
    check("sp26 a directory with more files, or more bytes, than a skill holds has "
          "no digest, and says which bound it passed: %r" % ((many, big),),
          many["digest"] is None and "files" in many["problem"]
          and big["digest"] is None and "bytes" in big["problem"])
    gone = M.skill_digest(os.path.join(base, "nothing-here"))
    check("sp27 a directory that is not there has no digest and says so: %r" % (gone,),
          gone["digest"] is None and gone["problem"])
    locked = _skill_dir(base, "locked")
    shut = os.path.join(locked, "scripts", "helper.py")
    os.chmod(shut, 0)
    try:
        readable = os.access(shut, os.R_OK)
        shut_ans = M.skill_digest(locked)
    finally:
        os.chmod(shut, 0o644)
    check("sp28 a file that cannot be read gives the directory no digest, naming "
          "the file (skipped where the platform or the user reads it anyway: %r): %r"
          % (readable, shut_ans),
          readable or (shut_ans["digest"] is None and "helper.py" in shut_ans["problem"]))
    return got["digest"]


def _pin_cases(check, root):
    """The one reader: match, mismatch, not found, could not be read - each with
    the path it read and both digests - and the stop's words."""
    tree = os.path.join(root, "ptree")
    home = os.path.join(root, "phome")
    plugin = os.path.join(root, "pplugin")
    skills = os.path.join(tree, ".claude", "skills")
    folder = _skill_dir(skills, "pinned")
    pinned = M.skill_digest(folder)["digest"]
    pin = {"sha256": pinned, "source": "vendored from upstream at abc123"}

    def ask(name, value=None):
        return M.pin_verdict(name, value or pin, tree, home, plugin, "house")

    ok = ask("pinned")
    check("sp29 the project copy with no personal copy beside it matches its pin, "
          "naming the path it read and both digests: %r" % (ok,),
          ok["answer"] == "match" and ok["path"] == os.path.join(folder, "SKILL.md")
          and ok["pinned"] == pinned and ok["found"] == pinned)
    _write(os.path.join(folder, "SKILL.md"),
           _SKILL["SKILL.md"].replace(b"more", b"mOre"))
    changed = ask("pinned")
    check("sp30 one changed byte in SKILL.md is a MISMATCH with the found digest "
          "beside the pinned one: %r" % (changed,),
          changed["answer"] == "mismatch" and changed["found"] not in (None, pinned)
          and changed["pinned"] == pinned
          and changed["path"] == os.path.join(folder, "SKILL.md"))
    _write(os.path.join(folder, "SKILL.md"), _SKILL["SKILL.md"])
    _write(os.path.join(folder, "scripts", "helper.py"), b"print('A')\nprint('b')\n")
    sib = ask("pinned")["answer"]
    _write(os.path.join(folder, "scripts", "helper.py"), _SKILL["scripts/helper.py"])
    _write(os.path.join(folder, "extra.md"), b"new\n")
    extra = ask("pinned")["answer"]
    os.remove(os.path.join(folder, "extra.md"))
    back = ask("pinned")["answer"]
    check("sp31 a changed sibling file and an added file are each a mismatch, and "
          "with the bytes restored the pin matches again: %r" % ((sib, extra, back),),
          (sib, extra, back) == ("mismatch", "mismatch", "match"))
    personal = _skill_dir(os.path.join(home, "skills"), "pinned", dict(_SKILL, **{
        "SKILL.md": _SKILL["SKILL.md"] + b"shadow\n"}))
    shadow = ask("pinned")
    os.rename(personal, personal + ".off")
    check("sp32 a personal copy shadowing the pinned project copy is the copy "
          "judged - the one a session loads - and is a mismatch naming the "
          "personal path: %r" % (shadow,),
          shadow["answer"] == "mismatch"
          and shadow["path"] == os.path.join(personal, "SKILL.md"))
    ghost = ask("ghost")
    other = ask("elsewhere:pinned")
    check("sp33 a pinned name found nowhere is NOT FOUND - never a pass - with no "
          "found digest and the places looked in; another plugin's skill is the "
          "same answer, with nowhere to look: %r" % ((ghost, other),),
          ghost["answer"] == "not-found" and ghost["found"] is None
          and ghost["path"] is None and len(ghost["places"]) == 3
          and other["answer"] == "not-found" and other["places"] == [])
    linked = _skill_dir(skills, "linked")
    try:
        os.symlink(os.path.join(root, "outside"), os.path.join(linked, "out"))
        unread = M.pin_verdict("linked", pin, tree, home, plugin, "house")
    except (OSError, NotImplementedError, AttributeError):
        unread = None
    check("sp34 a pinned skill whose directory cannot be read whole COULD NOT BE "
          "READ, its own answer, with the path and no found digest: %r" % (unread,),
          unread is None or (unread["answer"] == "unreadable"
                             and unread["found"] is None and unread["problem"]
                             and unread["path"] == os.path.join(linked, "SKILL.md")))

    words = [M.stop_words(v) for v in (changed, ghost) + ((unread,) if unread else ())]
    check("sp35 a stop names the skill, the path read (or the places looked in), the "
          "pinned digest and the found one, and says what to do - restore the "
          "pinned bytes or re-pin after reviewing the diff - never dropping the "
          "pin: %r" % (words,),
          all("pinned" in w and pinned in w and "restore" in w.lower()
              and "re-pin" in w and "review" in w for w in words)
          and changed["found"] in words[0] and changed["path"] in words[0]
          and "none" in words[1] and ghost["places"][0] in words[1]
          and not any(re.search(r"(remove|drop|delete|unset)\b[^.]{0,30}\bpin", w,
                                re.I) for w in words))

    pins = {"pinned": pin}
    _write(os.path.join(folder, "SKILL.md"), _SKILL["SKILL.md"] + b"x")
    stops = M.pin_stops(["pinned", "free", "ghost"], pins, tree, home, plugin)
    check("sp36 over a task's names, only a PINNED name is asked: the changed "
          "pinned skill stops, an unpinned name found nowhere is untouched: %r"
          % (stops,),
          [s["name"] for s in stops] == ["pinned"])
    check("sp37 ALLOW: no pins at all, and a pin for a skill the names do not "
          "hold, ask nothing and stop nothing",
          M.pin_stops(["pinned", "free"], {}, tree, home, plugin) == []
          and M.pin_stops(["free"], pins, tree, home, plugin) == [])
    try:
        M.require_pins(["pinned"], {"meta": {"skillPins": pins}}, tree, home, plugin)
        raised = None
    except M.PinStop as exc:
        raised = str(exc)
    _write(os.path.join(folder, "SKILL.md"), _SKILL["SKILL.md"])

    def handed(names, manifest):
        """The names `require_pins` hands back, or the stop it raised as a value:
        a stop over a matching pin is this case's failure, not the block's."""
        try:
            return M.require_pins(names, manifest, tree, home, plugin)
        except M.PinStop as exc:
            return "raised: %s" % (exc,)
    kept = handed(["pinned", "free"], {"meta": {"skillPins": pins}})
    bare = handed(["pinned"], {"meta": {}})
    check("sp38 `require_pins` raises the stop (a ValueError, the drive's stop) "
          "naming the skill, and hands the names back unchanged when every pin "
          "matches or the plan pins nothing: %r" % ((raised, kept, bare),),
          raised is not None and "pinned" in raised and issubclass(M.PinStop, ValueError)
          and kept == ["pinned", "free"] and bare == ["pinned"])
    bad = M.pin_shape_problems({"../x": {"sha256": pinned}, "ok": {"sha256": "ABC"},
                                "two": "deadbeef", "three": {"source": "s"},
                                "four": {"sha256": pinned, "extra": 1}})
    good = M.pin_shape_problems({"pinned": pin, "house:pinned": {"sha256": pinned}})
    check("sp39 a pin for a name that is no skill name, a digest that is not one, "
          "a value that is no object or a key the pin does not have are each a "
          "problem, naming the pin; well-formed pins are none: %r" % ((bad, good),),
          len(bad) == 5 and all(any(n in p for p in bad)
                                for n in ("../x", "ok", "two", "three", "four"))
          and good == [] and M.pin_shape_problems(None) == []
          and len(M.pin_shape_problems([])) == 1)


# The reader's surface. A module without it fails each case by name rather than
# raising out of the block before any case ran.
_PIN_API = ("skill_digest", "pin_verdict", "stop_words", "pin_stops", "require_pins",
            "PinStop", "pin_shape_problems")


def _pinned_cases(check):
    missing = [name for name in _PIN_API if not hasattr(M, name)]
    if missing:
        for n in range(21, 40):
            check("sp%d the pin reader is there to be asked (missing: %s)"
                  % (n, ", ".join(missing)), False)
        return
    root = _harness.fixture_root("skill-pins")
    _digest_cases(check, root)
    _pin_cases(check, root)


def _selftest():
    def body(check):
        _harness.stage(check, "sp-block", _cases)
        _harness.stage(check, "pin-block", _pinned_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__skill_places.py --selftest\n")
    raise SystemExit(2)
