#!/usr/bin/env python3
"""
The panel's markup/CSS/JS, off disk as real files — stdlib only.

panel-server.py used to carry its whole page as one 3,765-line raw-string literal
assigned to UI_HTML: ~4 lines of head, ~820 lines of CSS inside `<style>...</style>`, ~28 lines of
HTML body markup, ~2,913 lines of JS inside `<script>...</script>`. Nothing in that
literal is Python — no editor highlighted it, no linter looked at it, and a diff on it
read as one indistinguishable wall of text regardless of which layer actually changed.

The three layers now live as real, editor-highlightable files under `ui/`:

  * `ui/panel.css` — everything between `<style>` and `</style>` (the
    `/*__THEME_TOKENS__*/` placeholder included; panel-server.py's substitution
    chain fills it in after this module hands back the assembled string).
  * `ui/panel.js`  — everything between `<script>` and `</script>` (every
    `__*__` placeholder included, same reason).
  * `ui/panel.html` — the rest of the original literal (the `<!doctype ...>` head
    and the body markup), with the CSS and JS block replaced by two insertion
    markers, `/*@CSS@*/` and `/*@JS@*/`, sitting exactly where those blocks sat,
    still inside their own `<style>`/`<script>` tags.

`raw_template()` reads the three files and splices css/js back into the markers,
returning the EXACT string the old literal held before panel-server.py's own
`.replace()` chain (THEME_TOKENS, LABELS, SETTINGS, FIELD_HELP, COMP_HELP,
CFG_ENUMS) runs on it — that chain is untouched and still lives in panel-server.py.
Byte-for-byte: this module does not touch `__AUDIT_TOKEN__`/`__AUDIT_PROJECT__`
either, since those are filled in per-request, not at import.

The result is cached in a module global — the assets are read once per process,
the same "read once, keep serving from memory" contract UI_HTML always had.
"""
import io
import os

_UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")

CSS_MARK = "/*@CSS@*/"
JS_MARK = "/*@JS@*/"

_cache = None


# --- template assembly --------------------------------------------------------
def _read(name):
    with io.open(os.path.join(_UI_DIR, name), "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _cr_violations(assets):
    """Given [(name, text), ...], return the names whose text carries a "\\r".

    The three ui/ assets are read with newline="" on purpose (see module
    docstring) — no line-ending translation happens on the read, so a CRLF
    checkout (e.g. windows-latest CI with autocrlf rewriting the repo) shows
    up here as a literal "\\r" in the loaded text. This is a pure function of
    the given (name, text) pairs — no filesystem access — so a test can feed
    it fixture content directly, without touching the module's own _UI_DIR."""
    return [name for name, text in assets if "\r" in text]


def raw_template(cache=True):
    """Return the pre-substitution UI_HTML string, assembled from ui/panel.*.

    `cache=False` forces a fresh read+splice (used by the selftest, which mutates
    the marker count to prove the exactly-once check can fail)."""
    global _cache
    if cache and _cache is not None:
        return _cache
    skeleton = _read("panel.html")
    css = _read("panel.css")
    js = _read("panel.js")
    out = skeleton.replace(CSS_MARK, css, 1).replace(JS_MARK, js, 1)
    if cache:
        _cache = out
    return out


# The placeholders panel-server.py substitutes AFTER raw_template() returns —
# some at import (baked once into the module-level UI_HTML), one per request.
_IMPORT_TIME_PLACEHOLDERS = (
    "/*__THEME_TOKENS__*/", "__LABELS__", "__SETTINGS__", "__FIELD_HELP__",
    "__COMP_HELP__", "__CFG_ENUMS__",
)
_REQUEST_TIME_PLACEHOLDERS = ("__AUDIT_TOKEN__", "__AUDIT_PROJECT__")


# --- selftest -----------------------------------------------------------------
def _selftest():
    ok = bad = 0

    def check(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s" % name)

    # --- the three asset files exist and decode as utf-8 ------------------------
    names = ("panel.html", "panel.css", "panel.js")
    for name in names:
        path = os.path.join(_UI_DIR, name)
        try:
            with io.open(path, "r", encoding="utf-8", newline="") as fh:
                fh.read()
            readable = True
        except (IOError, OSError, UnicodeDecodeError):
            readable = False
        check("%s exists and decodes as utf-8" % name, readable)

    skeleton = _read("panel.html")
    css = _read("panel.css")
    js = _read("panel.js")
    template = raw_template(cache=False)

    # --- each insertion marker appears exactly once in the skeleton -------------
    check("the CSS marker appears exactly once in panel.html",
          skeleton.count(CSS_MARK) == 1)
    check("the JS marker appears exactly once in panel.html",
          skeleton.count(JS_MARK) == 1)

    # --- mutation proof: doubling a marker must fail the exactly-once case ------
    doubled = skeleton.replace(CSS_MARK, CSS_MARK + CSS_MARK, 1)
    check("mutation proof: a doubled CSS marker is caught by the same check "
          "that just passed (doubled count is %d, not 1)" % doubled.count(CSS_MARK),
          doubled.count(CSS_MARK) != 1)

    # --- every __*__ placeholder panel-server.py substitutes is present ---------
    for ph in _IMPORT_TIME_PLACEHOLDERS + _REQUEST_TIME_PLACEHOLDERS:
        check("assembled template still carries %s (panel-server.py's own "
              "substitution chain fills it in, unmodified)" % ph, ph in template)

    # --- exactly one <style> and one <script> block in the assembled string -----
    check("exactly one <style> block", template.count("<style>") == 1
          and template.count("</style>") == 1)
    check("exactly one <script> block", template.count("<script>") == 1
          and template.count("</script>") == 1)
    style_span = template[template.index("<style>") + len("<style>"):
                           template.index("</style>")]
    check("the CSS lives inside the <style> block, not beside it", style_span == css)
    script_span = template[template.index("<script>") + len("<script>"):
                            template.index("</script>")]
    check("the JS lives inside the <script> block, not beside it", script_span == js)

    # --- CSS brace balance, via _ui_theme's existing lints -----------------------
    import _ui_theme as _theme
    check("panel.css braces balance", css.count("{") == css.count("}"))
    check("no declaration in panel.css is left unterminated",
          not _theme.unterminated_css_decls(css))

    # --- nothing in ui/ escapes the flat CI selftest glob (scripts/*.py) --------
    ui_pyfiles = [f for f in os.listdir(_UI_DIR) if f.endswith(".py")]
    check("scripts/ui/ contains no .py files: %r" % (ui_pyfiles,), not ui_pyfiles)

    # --- LF contract: none of the loaded ui/ assets (nor the assembled ------
    # template) carry a "\r" — a CRLF checkout (e.g. windows-latest CI without
    # a .gitattributes eol=lf pin) would shift every cross-line selftest pin.
    real_assets = [("panel.html", skeleton), ("panel.css", css), ("panel.js", js),
                   ("raw_template()", template)]
    real_cr = _cr_violations(real_assets)
    check("no \\r (CRLF) in any loaded ui/ asset or the assembled template "
          "(found in: %r)" % (real_cr,), not real_cr)

    # --- fixture red-proof: a CRLF asset IS named by the same helper ------------
    fixture_assets = [("panel.html", "<html>\r\n<body></body>\r\n</html>"),
                       ("panel.css", "body { color: red; }\n"),
                       ("panel.js", "console.log(1);\n")]
    fixture_cr = _cr_violations(fixture_assets)
    check("fixture proof: a CRLF panel.html is named by the CR check "
          "(got %r, want ['panel.html'])" % (fixture_cr,),
          fixture_cr == ["panel.html"])

    # --- caching: repeat calls return the identical cached string ---------------
    a = raw_template()
    b = raw_template()
    check("raw_template() caches — repeat calls return the SAME object",
          a is b)
    check("cache=False bypasses the cache and still matches",
          raw_template(cache=False) == a)

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    from _output import safe_stdio      # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
