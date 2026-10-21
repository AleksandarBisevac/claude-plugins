#!/usr/bin/env python3
"""
The cases for `_claude_home.py` - Claude Code's own install records, read in one
place so `/audit:version` and `/audit:doctor` cannot come to read them apart.

Both files are undocumented, so what is pinned is the fail-open contract: a record
that is missing, malformed or shaped differently comes back as None beside a
sentence naming why, never as an empty answer that reads like "nothing
installed". No case reads the real Claude home: every home is a fixture tree.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import argparse
import contextlib
import io
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _claude_home as M                           # noqa: E402
import _loader                                     # noqa: E402

V = _loader.load_script("audit-version.py", modname="audit_version_for_home")


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(doc, str):
            fh.write(doc)
        else:
            json.dump(doc, fh)


def _home(root, source="./plugins/audit", sha="a" * 40):
    home = os.path.join(root, "claude-home")
    clone = os.path.join(home, "plugins", "marketplaces", "qg")
    _write(os.path.join(clone, ".claude-plugin", "marketplace.json"),
           {"plugins": [{"name": "audit", "source": source}]})
    _write(os.path.join(home, "plugins", "known_marketplaces.json"),
           {"qg": {"installLocation": clone}})
    cache = os.path.join(home, "plugins", "cache", "qg", "audit", "1.0.0")
    os.makedirs(cache)
    _write(os.path.join(home, "plugins", "installed_plugins.json"),
           {"version": 2, "plugins": {"audit@qg": [
               {"scope": "project", "projectPath": "/elsewhere",
                "installPath": "/somewhere/else", "gitCommitSha": "b" * 40},
               {"scope": "user", "installPath": cache, "version": "1.0.0",
                "gitCommitSha": sha}]}})
    return home, cache, clone


def _cases(check):
    root = _harness.fixture_root("claude-home-")
    home, cache, clone = _home(root)

    rec, why = M.install_record(cache, home)
    check("ch1 the install record is the one naming THIS copy's path, carrying "
          "its marketplace and recorded commit - not the first record for the "
          "plugin, which names another project's copy: %r" % ((rec, why),),
          rec is not None and rec["marketplace"] == "qg"
          and rec["gitCommitSha"] == "a" * 40 and why == "")
    miss, why = M.install_record(os.path.join(root, "unrecorded"), home)
    check("ch2 a copy no record names is None beside a sentence saying so: %r"
          % ((miss, why),),
          miss is None and "records no install" in why)
    gone, why = M.install_record(cache, os.path.join(root, "no-home"))
    check("ch3 FAIL-OPEN: a home with no installed_plugins.json is None beside "
          "the read's own reason, never an empty record: %r" % ((gone, why),),
          gone is None and "could not be read" in why)
    _write(os.path.join(root, "torn", "plugins", "installed_plugins.json"), "{ no")
    torn, why = M.install_record(cache, os.path.join(root, "torn"))
    check("ch4 ...and a malformed one says it is not JSON: %r" % ((torn, why),),
          torn is None and "not JSON" in why)

    got = M.marketplace_source(home, "qg")
    check("ch5 the marketplace source is the clone known_marketplaces.json names "
          "and the plugin's directory inside it, normalised to a git pathspec: %r"
          % (got,),
          got == (clone, "plugins/audit", ""))
    unknown = M.marketplace_source(home, "nope")
    check("ch6 a marketplace the record does not know is None beside why: %r"
          % (unknown,),
          unknown[0] is None and "nope" in unknown[2])
    home_root, _c, _cl = _home(os.path.join(root, "rooted"), source=".")
    check("ch7 a plugin published at the clone's root is the empty subdirectory, "
          "which archives the whole commit rather than a directory named '.': %r"
          % (M.marketplace_source(home_root, "qg"),),
          M.marketplace_source(home_root, "qg")[1] == "")

    moved = [name for name in ("claude_home", "marketplace_of",
                               "marketplace_facts", "installed_copies",
                               "read_json", "PLUGIN_NAME")
             if getattr(V, name, None) is not getattr(M, name)]
    check("ch8 `/audit:version` reads through THIS module rather than a copy of "
          "it - every reader it names is this module's own object, so the two "
          "commands cannot come to read the records apart: %r" % (moved,),
          moved == [])

    _usage_cases(check, root)


def _usage_error(home, project, version, plugin_root, argv=("verify",)):
    """The stderr a hooked parser prints for `argv`, and its exit code.

    Looked up by name so the cases fail as ASSERTIONS where the hook is absent,
    not as an exception that would hide which case it was."""
    hook = getattr(M, "attach_usage_hint", None)
    parser = argparse.ArgumentParser(prog="helper.py")
    parser.add_argument("action", choices=("take", "compare"))
    if hook is not None:
        hook(parser, env={"CLAUDE_CONFIG_DIR": home, "CLAUDE_PROJECT_DIR": project},
             version=version, plugin_root=plugin_root)
    err = io.StringIO()
    code = None
    with contextlib.redirect_stderr(err):
        try:
            parser.parse_args(list(argv))
        except SystemExit as exc:
            code = exc.code
    return err.getvalue(), code


def _install_home(root, entries):
    home = os.path.join(root, "claude-home")
    _write(os.path.join(home, "plugins", "installed_plugins.json"),
           {"version": 2, "plugins": {"audit@qg": entries}})
    return home


def _usage_cases(check, root):
    proj = os.path.join(root, "this-project")
    other = os.path.join(root, "other-project")
    running = os.path.join(root, "cache", "audit", "3.1.0")
    newer = os.path.join(root, "cache", "audit", "3.2.0")
    user_copy = os.path.join(root, "cache", "audit", "3.5.0")
    foreign = os.path.join(root, "cache", "audit", "9.0.0")
    for path in (proj, os.path.join(proj, "sub"), other):
        os.makedirs(path, exist_ok=True)

    # A newer project-scope copy beside the running one. The user-scope copy is
    # newer still and another project's copy is newest of all, so a chooser that
    # takes the highest version, or ignores projectPath, names the wrong copy.
    home = _install_home(os.path.join(root, "u1"), [
        {"scope": "project", "projectPath": other, "installPath": foreign,
         "version": "9.0.0"},
        {"scope": "user", "installPath": user_copy, "version": "3.5.0"},
        {"scope": "project", "projectPath": proj, "installPath": newer,
         "version": "3.2.0"},
        {"scope": "user", "installPath": running, "version": "3.1.0"}])
    text, code = _usage_error(home, proj, "3.1.0", running)
    check("ch9 an unknown subcommand's usage error still exits 2 and keeps "
          "argparse's own message, then names this copy's version AND path, the "
          "newer project copy's version, path and scope, and /reload-plugins: %r"
          % (text,),
          code == 2 and "invalid choice: 'verify'" in text
          and "this copy: audit 3.1.0 at %s" % (running,) in text
          and "audit 3.2.0 at %s (project scope" % (newer,) in text
          and "/reload-plugins" in text and "does not document" in text)
    check("ch10 the project-scope copy recorded for THIS project is chosen before "
          "a newer user-scope copy, and another project's copy is never named: %r"
          % (text,),
          text.count(newer) == 1 and user_copy not in text and foreign not in text
          and "9.0.0" not in text and "3.5.0" not in text)
    sub, _code = _usage_error(home, os.path.join(proj, "sub"), "3.1.0", running)
    check("ch11 ...a project directory below the recorded projectPath is the same "
          "project, so its copy still applies: %r" % (sub,),
          "audit 3.2.0 at %s (project scope" % (newer,) in sub)
    elsewhere, _code = _usage_error(home, other + "-not", "3.1.0", running)
    check("ch12 a project no project-scope record names falls back to the user "
          "scope, never to another project's copy - even one whose path is a "
          "prefix of this one's: %r" % (elsewhere,),
          "audit 3.5.0 at %s (user scope" % (user_copy,) in elsewhere
          and foreign not in elsewhere)

    # allow twins: no newer copy, and records that cannot be read.
    same = _install_home(os.path.join(root, "u2"), [
        {"scope": "user", "installPath": running, "version": "3.1.0"}])
    plain, code = _usage_error(same, proj, "3.1.0", running)
    check("ch13 with only this version installed the usage error carries this "
          "copy's version and names no newer copy and no /reload-plugins: %r"
          % (plain,),
          code == 2 and "this copy: audit 3.1.0 at %s" % (running,) in plain
          and "no newer copy applies" in plain and "/reload-plugins" not in plain)
    torn = os.path.join(root, "u3", "claude-home")
    _write(os.path.join(torn, "plugins", "installed_plugins.json"), "{ no")
    bad, code = _usage_error(torn, proj, "3.1.0", running)
    check("ch14 FAIL-OPEN: an unreadable installed_plugins.json still yields the "
          "usage error and this copy's version, plus 'install records could not "
          "be read' and the undocumented basis - never a silent 'no newer copy': "
          "%r" % (bad,),
          code == 2 and "this copy: audit 3.1.0" in bad
          and "install records could not be read" in bad
          and "does not document" in bad and "no newer copy" not in bad)
    odd = _install_home(os.path.join(root, "u4"), [
        "not-a-record", {"scope": "project", "projectPath": 7, "version": None}])
    shaped, code = _usage_error(odd, proj, "3.1.0", running)
    check("ch15 ...and records of an unexpected shape cost the hint's answer, "
          "never the usage error: %r" % (shaped,),
          code == 2 and "this copy: audit 3.1.0" in shaped
          and "no installed copy applies" in shaped)

    stamp = _loader.load_script("stamp-verification.py",
                                modname="stamp_verification_for_home")
    keep = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR")}
    err = io.StringIO()
    try:
        os.environ["CLAUDE_CONFIG_DIR"] = _install_home(os.path.join(root, "u5"), [
            {"scope": "project", "projectPath": proj, "installPath": newer,
             "version": "999.0.0"}])
        os.environ["CLAUDE_PROJECT_DIR"] = proj
        with contextlib.redirect_stderr(err):
            rc = stamp.main(["verify"])
    finally:
        for key, value in keep.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check("ch16 stamp-verification.py, the reported case, carries the hook: an "
          "unknown action exits 2 naming this copy's version and the newer "
          "installed copy for this project: %r" % (err.getvalue(),),
          rc == 2 and "this copy: audit %s" % (_output.plugin_version(),) in err.getvalue()
          and "audit 999.0.0 at %s" % (newer,) in err.getvalue())


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__claude_home.py --selftest\n")
    raise SystemExit(2)
