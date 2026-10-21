#!/usr/bin/env python3
"""
The cases for `_surface_digest.py` - which UI a committed screenshot is a picture OF.

THE EDITS ARE MADE TO A COPY OF THE SCRIPTS TREE AND THE DIGEST IS TAKEN BY A CHILD
OF THAT COPY. The digest is over what two modules assemble at import, so there is no
function to hand a fixture string to: the only honest way to ask "what does the page
become when `_ui_theme.py` changes" is to change it somewhere and import it fresh. The
copy is made once and edited in place, each edit undone before the next, so every
case compares against the same base and none inherits another's change.

The children differ in `PYTHONHASHSEED` on purpose. A set serialised into the page
unsorted is stable inside one process and different in the next, so two runs sharing a
seed would not have seen it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402
import _surface_digest as M                        # noqa: E402
import _report_ui                                  # noqa: E402
import _panel_page                                 # noqa: E402


def _copy_plugin(dest):
    """A copy of what the pages import from the plugin, under `dest`; returns its scripts dir."""
    plugin = os.path.join(dest, "plugin")
    shutil.copytree(_output.SCRIPTS_DIR, os.path.join(plugin, "scripts"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    # `hooks/` because `_panel_settings` loads the hooks' config while the panel page
    # is being assembled, and `.claude-plugin/` because that is where the version is.
    for name in (".claude-plugin", "hooks"):
        shutil.copytree(os.path.join(_output.PLUGIN_ROOT, name),
                        os.path.join(plugin, name),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return os.path.join(plugin, "scripts")


def _ask(scripts, seed="0"):
    """`(exit status, parsed JSON)` from the copy's own `_surface_digest.py --json`."""
    # No bytecode is written, because a file edited and restored inside one second
    # at the same length (a token digit flipped and flipped back) keeps the stamp a
    # cached `.pyc` is trusted by, and the next child would digest the EDITED page.
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable,
                           os.path.join(scripts, "_surface_digest.py"), "--json"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                          timeout=120)
    out = done.stdout.decode("utf-8")
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = {"error": "no JSON: %r %r" % (out[:200], done.stderr.decode("utf-8")[-300:]),
                  "digests": {}, "unassigned": []}
    return done.returncode, parsed


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _edited(path, change, base):
    """Run `change(text)` over the file, return what it wrote; the caller restores `base`."""
    text = change(base)
    _write(path, text)
    return text


def _moved(digests, base):
    """The surfaces whose digest is not the base's, sorted."""
    return sorted(s for s in base if digests.get(s) != base[s])


def _cases(check):
    tmp = tempfile.mkdtemp(prefix="audit-surfdig-")
    try:
        scripts = _copy_plugin(tmp)
        theme = os.path.join(scripts, "_ui_theme.py")
        theme_base = _read(theme)

        code0, base = _ask(scripts, "1")
        code1, again = _ask(scripts, "2")
        base_d = base["digests"]

        # --- the task's own case, in one piece: prose, token, and two runs -------
        prose = _edited(theme, lambda t: t.replace('"""', '"""\nEdited prose.', 1)
                        + "\n# a comment no page receives\n", theme_base)
        _, prose_run = _ask(scripts, "3")
        _write(theme, theme_base)

        token_text = _edited(theme, lambda t: t.replace("--bg:#f5f7fb;",
                                                        "--bg:#f5f7fc;", 1), theme_base)
        _, token_run = _ask(scripts, "4")
        _write(theme, theme_base)
        check("a prose-only edit of _ui_theme.py leaves both surface digests unchanged, "
              "a token value edit changes them, and two interpreter runs give the same "
              "digest - the three halves of one claim, each aimed at a different wrong "
              "implementation: a digest over the file's bytes fails the first, one that "
              "ignores the token layer fails the second, an unsorted set in the text "
              "fails the third (the two runs below differ in PYTHONHASHSEED). "
              "Exit codes %r, prose edit landed %r, token edit landed %r; base %r, "
              "second run %r, prose edit %r, token edit %r"
              % ((code0, code1), prose != theme_base, token_text != theme_base,
                 base_d, again["digests"], prose_run["digests"],
                 token_run["digests"]),
              code0 == 0 and code1 == 0 and sorted(base_d) == sorted(_output.UI_SURFACES)
              and prose != theme_base and token_text != theme_base
              and base["error"] is None
              and again["digests"] == base_d
              and prose_run["digests"] == base_d
              and _moved(token_run["digests"], base_d) == sorted(_output.UI_SURFACES))

        # --- sd2: the version is a token, not a digest input ---------------------
        manifest = os.path.join(os.path.dirname(scripts), ".claude-plugin", "plugin.json")
        manifest_base = _read(manifest)
        live_version = _output.plugin_version()
        _write(manifest, json.dumps(dict(json.loads(manifest_base), version="9.9.9")))
        _, bumped = _ask(scripts, "5")
        _write(manifest, manifest_base)
        panel_hits = M.surface_texts()["panel"].count(json.dumps(live_version))
        check("sd2 a version bump moves neither digest, and the panel page really does "
              "carry the quoted version it is bumping (%d occurrence(s)) - without "
              "that second half the first would pass on a digest that never saw a "
              "version at all: %r" % (panel_hits, bumped["digests"]),
              live_version != "" and panel_hits == 1
              and bumped["digests"] == base_d)

        # --- sd3: a source that shapes the page moves THAT surface's digest -------
        found = _output.ui_surface_sources(scripts)
        own = dict((s, [r for r in found["sources"][s]
                        if _output.ui_surfaces_of(r) == (s,) and r.endswith((".js", ".css"))])
                   for s in _output.UI_SURFACES)
        shared = [r for r in found["sources"]["panel"]
                  if _output.ui_surfaces_of(r) == _output.UI_SURFACES and r.endswith(".js")]
        moved = {}
        for label, rel in (("report", own["report"][0]), ("panel", own["panel"][0]),
                           ("shared", shared[0])):
            path = os.path.join(found["root"], *rel.split("/"))
            text = _read(path)
            _write(path, text + "\n/* a byte the page receives */\n")
            _, run = _ask(scripts, "6")
            _write(path, text)
            moved[label] = _moved(run["digests"], base_d)
        check("sd3 a part only the report assembles moves the report's digest and not "
              "the panel's, a panel part the other way, and a shared part both - the "
              "separation that makes this a rule and not a nuisance: %r" % (moved,),
              moved == {"report": ["report"], "panel": ["panel"],
                        "shared": sorted(_output.UI_SURFACES)})

        # --- sd4: an unplaced part, and an unwalkable tree, are reported ----------
        stray = os.path.join(found["root"], "widgets", "thing.js")
        os.makedirs(os.path.dirname(stray))
        _write(stray, "const w = 1;\n")
        code_stray, stray_run = _ask(scripts, "7")
        shutil.rmtree(os.path.dirname(stray))
        check("sd4 a part under a directory no surface claims is REPORTED beside the "
              "digests and moves neither - a part no page assembles is a part whose "
              "change no picture could ever be red about, and must not read as agreement: "
              "%r" % ((code_stray, stray_run["unassigned"]),),
              code_stray == 0 and stray_run["unassigned"] == ["widgets/thing.js"]
              and stray_run["digests"] == base_d)

        hidden = found["root"] + "-away"
        os.rename(found["root"], hidden)
        code_gone, gone_run = _ask(scripts, "8")
        os.rename(hidden, found["root"])
        check("sd5 a scripts tree whose `ui/` is gone yields NO digests and a non-zero "
              "exit with the reason in what the child wrote - the pages are assembled at "
              "import, so the missing part stops the child before it can answer, and a "
              "digest of whatever was left would be stable, comparable and about nothing: "
              "%r" % ((code_gone, gone_run["error"]),),
              code0 == 0 and code_gone != 0 and gone_run["digests"] == {}
              and "shell.css" in (gone_run["error"] or ""))

        # --- sd6: what is digested is what the modules assemble -------------------
        texts = M.surface_texts()
        check("sd6 the report's text is its stylesheet, a NUL, then its script, and the "
              "panel's is its page - the spec of what 'the page receives' means, kept "
              "as a case so the composition cannot drift unnoticed: %r"
              % ({"report": len(texts["report"]), "panel": len(texts["panel"])},),
              texts["report"] == _report_ui.CSS + "\0" + _report_ui.SCRIPT
              and texts["panel"] == _panel_page.UI_HTML
              and sorted(texts) == sorted(_output.UI_SURFACES)
              and _report_ui.CSS.count("\0") == 0 and _report_ui.SCRIPT.count("\0") == 0)

        # --- sd7: the normaliser, alone -------------------------------------------
        quoted = 'const V = %s; const prose = "see 3.4.0 notes";' % json.dumps("3.4.0")
        out = M.without_version(quoted, "3.4.0")
        check("sd7 only the QUOTED version is replaced - an unquoted `3.4.0` in prose "
              "stays, so an edit to a sentence cannot hide behind a version number - and "
              "an empty version replaces nothing rather than inserting the token "
              "between every character: %r" % (out,),
              out == 'const V = %s; const prose = "see 3.4.0 notes";'
              % json.dumps(M.VERSION_TOKEN)
              and M.without_version(quoted, "") == quoted)

        # --- sd8: no digest is a plain hex string of a different thing ------------
        check("sd8 the two digests are 64 lowercase hex characters and differ from "
              "each other - a digest that returned one constant for both surfaces "
              "would pass every 'unchanged' case above: %r" % (base_d,),
              sorted(base_d) == sorted(_output.UI_SURFACES)
              and all(re.match(r"^[0-9a-f]{64}$", v) for v in base_d.values())
              and len(set(base_d.values())) == len(base_d))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__surface_digest.py --selftest\n")
    raise SystemExit(2)
