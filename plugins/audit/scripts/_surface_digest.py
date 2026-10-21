#!/usr/bin/env python3
"""
Which UI a committed screenshot is a picture OF: one digest per surface, taken
over the text the page receives and over nothing else.

WHY THIS IS NOT IN `_output.py`, where the digest used to live. The old digest hashed
the raw bytes of every source a surface is assembled from, plus the whole of
`_ui_theme.py`. A docstring edit in that file moved every picture, and the only
repair was to re-shoot all of them. A page cannot tell a docstring from a token: the
page is the stylesheet and the script it was handed. So the digest is taken over
those - the report's `CSS + "\\0" + SCRIPT`, the panel's `UI_HTML` - and a source that
shapes the page moves it exactly as far as it shapes the page, however many files
the shaping passes through.

The assembled strings live above the anchor (`_report_ui` and `_panel_page` are
layers `_deps.LAYERS` states), and a lower layer may not import a higher one, so the
digest cannot sit beside `ui_surface_sources()`. That stays in the anchor: which
files a surface is assembled from is a question about the directory, and this one is
about what they assemble into.

TWO THINGS ARE NORMALISED BEFORE HASHING, because both would otherwise move a
digest without a pixel moving. The panel bakes the plugin's version into its page,
and a release bump must not ask for the report's or the panel's pictures back on
that account alone - the sidecar already records the version it was shot at and a
separate rule compares it. And nothing may depend on the order a set iterates in:
the assembled text is checked, in the suite, to be identical across interpreter
runs with different hash seeds, which is what a set serialised unsorted into the
text would fail.

A digest this module cannot stand behind is an `error`, never a value: the same
shape the old digest had (`digests`, `unassigned`, `error`), so a caller that
compared against it still reads one answer.

This module carries no `--selftest` of its own; its cases live in
`tests/test__surface_digest.py`. Run as a command it prints the answer
as JSON (`--json`), which is how `_refs` - a lower layer, forbidden the import -
asks for it.

Exit codes (as a command): 0 digests printed - 1 digests unavailable (the JSON says
why) - 2 usage error.
"""
import hashlib
import json
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _report_ui  # noqa: E402  (the report's stylesheet and script, as the page gets them)
import _panel_page  # noqa: E402  (the panel's page, as the browser gets it)

# What stands for the plugin's version inside a digested text. A fixed string, so two
# builds of one UI digest alike; it is also not a version, so a text that really did
# carry it as a literal would read the same either way.
VERSION_TOKEN = "<plugin-version>"


def surface_texts():
    """`{surface: text}` - what each surface's page receives, version not yet taken out.

    The report is its stylesheet and its script joined by a NUL: two members with a
    separator no stylesheet or script contains, so a byte moved from the end of one to
    the start of the other changes the text instead of cancelling out. The panel is
    one page. Everything else the report prints is data the renderer fills in from a
    plan, which is what the screenshot fixtures vary and these pictures are not OF.
    """
    return {"report": _report_ui.CSS + "\0" + _report_ui.SCRIPT,
            "panel": _panel_page.UI_HTML}


def without_version(text, version):
    """`text` with the quoted JSON form of `version` replaced by the fixed token.

    The panel bakes `json.dumps(version)` into its page, so that spelling - the
    quoted one - is the one replaced. An unquoted `3.4.0` elsewhere in a text is
    prose and stays: replacing it would let an edit to a sentence hide behind a
    version number. An empty version (plugin.json unreadable) replaces nothing,
    because `"".replace` would insert the token between every character.
    """
    if not version:
        return text
    return text.replace(json.dumps(version), json.dumps(VERSION_TOKEN))


def digest_of(text):
    """The hex SHA-256 of `text` as UTF-8. One spelling, so a caller cannot hash another."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def surface_digests(version=None):
    """`{"digests": {surface: hex}, "unassigned": [...], "error": None|str}`.

    `unassigned` and the walk's own errors come from `_output.ui_surface_sources()`:
    a `ui/` part no surface claims is a part no picture's digest covers, and a tree
    that cannot be walked is not a tree that is unchanged. Both are still true with
    the digest taken over assembled text - a part filed under no surface is not
    assembled into any page, which is the silence the walk exists to report.

    `version` is the one to take out of the text; `None` asks the plugin's own.
    """
    found = _output.ui_surface_sources()
    if found["error"]:
        return {"digests": {}, "unassigned": found["unassigned"],
                "error": found["error"]}
    texts = surface_texts()
    missing = [s for s in _output.UI_SURFACES if s not in texts]
    if missing:
        return {"digests": {}, "unassigned": found["unassigned"],
                "error": "no assembled text for %s, so no digest can stand for the "
                         "page it receives" % (", ".join(missing),)}
    ver = _output.plugin_version() if version is None else version
    return {"digests": dict((s, digest_of(without_version(texts[s], ver)))
                            for s in _output.UI_SURFACES),
            "unassigned": found["unassigned"], "error": None}


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--json" in sys.argv[1:]:
        answer = surface_digests()
        sys.stdout.write(json.dumps(answer, sort_keys=True) + "\n")
        raise SystemExit(1 if answer["error"] else 0)
    print(__doc__.strip())
