#!/usr/bin/env python3
"""Record the README demo GIF: the plan gate refusing an unplanned edit.

WHY THIS EXISTS. Every other artifact in this repo shows the product at rest — a
rendered report, a screenshot of the panel. The thing the product actually IS, an
edit being refused, cannot be shown by a still: the refusal is an event.

WHAT IS REAL HERE. Every line of output in the GIF is captured from the plugin's own
code at record time. `audit-status.py` renders the plan; `require-plan.py` is fed the
same PreToolUse JSON Claude Code sends it and its stdout is the deny message you see.
Nothing is typed out by hand into a mock terminal. If the gate's wording changes, the
next recording says the new wording, and if the gate stops denying, this script fails
rather than shipping a GIF of something that no longer happens.

FIXTURES ARE GENERATED, NEVER STORED — same rule as the screenshot capture. The demo
project is built in a temp dir and thrown away, so the recording cannot drift from a
fixture nobody can rebuild.

    python3 tools/capture-demo-gif.py [--out docs/screenshots/demo-gate.gif] [--check]

--check runs the whole capture and asserts the outputs are what the GIF claims (the
in-plan edit is allowed, the out-of-plan edit is denied, the deny names the file and
the way out) but writes no file. Run it in CI; run the capture when the gate's
wording changes.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, "plugins", "audit", "hooks")
SCRIPTS = os.path.join(REPO, "plugins", "audit", "scripts")
PY = sys.executable

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import _loader  # noqa: E402  (reachable now that SCRIPTS is on the path)


def resolve_script(basename):
    """The absolute path of `basename` WHEREVER it sits under the scripts tree.

    NOT A COPY OF THE RESOLUTION RULE, AND THAT IS THE WHOLE POINT OF THE FUNCTION.
    `capture-screenshots.mjs` had to grow its own index because `.mjs` cannot import
    Python; this file is Python, so it asks the module that already owns the answer and
    inherits all three of `script_path()`'s refusals unchanged — nothing found (naming
    the basename and how many files were searched), two files claiming the name (naming
    both), a value carrying a directory separator (naming the value). A second Python
    walk here would be a fifth statement of one rule with nothing comparing it to the
    other four.

    IT IS STILL A NAMED FUNCTION rather than an inline call, so that this file has one
    place where "which script" is decided, exactly as the JavaScript tool does, and so a
    reader meeting either tool finds the same shape.

    WHY IT REPLACED A JOIN. Joining the SCRIPTS constant with a filename looks one
    directory too high the moment that script is filed under a domain folder, and the fix
    that suggests itself — inserting the folder's name into the join — hard-codes a label
    into a consumer. The folders under the scripts tree are labels, not namespaces. No
    such join is left in this file, and `test__refs.py` asserts that.

    The `require-plan.py` join below is deliberately left alone: the hooks tree is not
    being reorganised, it is flat by design and has to stay reachable from a launcher
    that knows only its directory, so a resolver there would buy nothing.
    """
    return _loader.script_path(basename)

# The report's own dark tokens. The GIF and the product should look like one thing,
# and these are the values `render-report.py` ships, not an approximation of them.
BG, SURFACE, TEXT = "#0a1120", "#111a2b", "#e6edf6"
MUTED, ACCENT, DENY, OK, WARN = "#93a4bd", "#2dd4bf", "#f87171", "#34d399", "#fbbf24"
BORDER = "#1f2b40"

FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)


def _font(size):
    from PIL import ImageFont
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    raise SystemExit("no monospace font found; tried:\n  " + "\n  ".join(FONT_CANDIDATES))


# --- building the demo project, and capturing what the gate says about it ------
def build_fixture(d):
    """A minimal but honest plan: one phase running, one task covering one file.

    The gate's behaviour depends entirely on this shape — a phase `in_progress` is
    what makes it deny rather than warn — so the fixture is the demo's premise and
    is written out here rather than described in a caption."""
    os.makedirs(os.path.join(d, ".claude"), exist_ok=True)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    subprocess.run(["git", "-C", d, "init", "-q"], capture_output=True)
    manifest = {
        "meta": {"version": 2, "repo": "acme-store", "title": "ACME Store security audit",
                 "manifestPath": "audit-plan.json"},
        "phases": [{
            "id": "P2", "title": "Input validation", "status": "in_progress",
            "desiredOutcome": "Every request payload is validated before it reaches "
                              "business logic.",
            "tasks": [
                {"id": "P2.1", "title": "Validate the checkout payload",
                 "status": "in_progress", "model": "sonnet", "risk": "med",
                 "files": ["src/checkout.ts"]},
                {"id": "P2.2", "title": "Sanitize the product-search query",
                 "status": "pending", "model": "opus", "risk": "high",
                 "files": ["src/search.ts"]}]}],
        "bugs": []}
    with open(os.path.join(d, "audit-plan.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    with open(os.path.join(d, ".claude", "audit.config.json"), "w", encoding="utf-8") as fh:
        json.dump({"manifestPath": "audit-plan.json"}, fh)
    for name in ("checkout.ts", "billing.ts"):
        with open(os.path.join(d, "src", name), "w", encoding="utf-8") as fh:
            fh.write("export function %s() {}\n" % name[:-3])


def fire_gate(d, rel, new_body, session):
    """Feed require-plan.py the PreToolUse payload Claude Code would send.

    Returns the deny reason, or None when the edit was allowed — which is what an
    allow looks like from the outside: nothing at all."""
    payload = {"session_id": session, "cwd": d, "tool_name": "Edit",
               "tool_input": {"file_path": os.path.join(d, rel),
                              "old_string": "export function %s() {}" % rel.split("/")[-1][:-3],
                              "new_string": new_body}}
    out = subprocess.run([PY, os.path.join(HOOKS, "require-plan.py")],
                         input=json.dumps(payload), capture_output=True, text=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=d))
    if not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    except Exception:
        return out.stdout.strip()


def capture(d):
    """Run the real commands and collect their real output."""
    status = subprocess.run([PY, resolve_script("audit-status.py"),
                             os.path.join(d, "audit-plan.json")],
                            capture_output=True, text=True).stdout.rstrip("\n")
    inplan = fire_gate(d, "src/checkout.ts",
                       "export function checkout(payload: unknown) {\n"
                       "  assertCheckoutPayload(payload);\n}", "demo-a")
    big = "\n".join("  const step%d = compute(%d);" % (i, i) for i in range(1, 95))
    outplan = fire_gate(d, "src/billing.ts",
                        "export function billing(c: Customer) {\n%s\n}" % big, "demo-b")
    return {"status": status, "inplan": inplan, "outplan": outplan}


def _wrap(text, width):
    """Wrap while keeping each paragraph's own indent.

    The hand-rolled version split on spaces, which turns a two-space indent into two
    empty tokens and drops it — so the deny message's numbered list lost the indent on
    exactly the items long enough to wrap, i.e. the ones a reader most needs lined up."""
    import textwrap
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        indent = para[:len(para) - len(para.lstrip())]
        out.extend(textwrap.wrap(
            para.strip(), width=width, initial_indent=indent,
            subsequent_indent=indent + "   ", break_long_words=False,
            break_on_hyphens=False) or [para])
    return out


def build_script(cap, cols):
    """The recording, as a list of (kind, text, colour) steps.

    `type` steps animate a character at a time; `out` steps appear whole, the way a
    terminal actually behaves."""
    s = []
    s.append(("type", "audit-status.py audit-plan.json", ACCENT))
    for line in cap["status"].split("\n"):
        col = TEXT
        if line.strip().startswith("READY NOW"):
            col = OK
        elif line.strip().startswith("RESUMABLE"):
            col = WARN
        elif line.strip().startswith("AUDIT"):
            col = ACCENT
        s.append(("out", line, col))
    s.append(("gap", "", TEXT))

    s.append(("cmt", "# an edit the plan covers - P2.1 owns src/checkout.ts", MUTED))
    s.append(("type", "edit src/checkout.ts   # PreToolUse -> require-plan", ACCENT))
    if cap["inplan"] is None:
        s.append(("out", "(no output - the gate stays out of the way)", OK))
    else:
        for line in _wrap(cap["inplan"], cols):
            s.append(("out", line, DENY))
    s.append(("gap", "", TEXT))

    s.append(("cmt", "# an edit no task covers, while a phase is running", MUTED))
    s.append(("type", "edit src/billing.ts    # PreToolUse -> require-plan", ACCENT))
    if cap["outplan"] is None:
        s.append(("out", "(allowed - the gate did NOT deny)", DENY))
    else:
        for line in _wrap(cap["outplan"], cols):
            s.append(("out", line, DENY if line.startswith("[require-plan]") else TEXT))
    return s


def render(script, cols, rows, out_path):
    from PIL import Image, ImageDraw
    font = _font(15)
    fw = font.getlength("M")
    lh = 22
    pad, titleh = 18, 34
    W = int(pad * 2 + fw * cols)
    H = int(pad * 2 + titleh + lh * rows)

    def frame(lines, cursor_on):
        img = Image.new("RGB", (W, H), BG)
        dr = ImageDraw.Draw(img)
        dr.rectangle([0, 0, W, titleh], fill=SURFACE)
        dr.line([(0, titleh), (W, titleh)], fill=BORDER)
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            dr.ellipse([16 + i * 18, 12, 26 + i * 18, 22], fill=c)
        dr.text((76, 9), "audit - plan-first gate", font=font, fill=MUTED)
        y = titleh + pad
        for text, col, prompt in lines[-rows:]:
            x = pad
            if prompt:
                dr.text((x, y), "$", font=font, fill=OK)
                x += fw * 2
            dr.text((x, y), text, font=font, fill=col)
            y += lh
        if cursor_on and lines:
            last = lines[-1]
            x = pad + (fw * 2 if last[2] else 0) + fw * len(last[0])
            yy = titleh + pad + lh * (min(len(lines), rows) - 1)
            dr.rectangle([x, yy + 2, x + fw - 1, yy + lh - 5], fill=ACCENT)
        return img

    frames, durs = [], []
    lines = []
    for kind, text, col in script:
        if kind == "gap":
            lines.append(("", TEXT, False))
            frames.append(frame(lines, False)); durs.append(120)
        elif kind == "cmt":
            lines.append((text, col, False))
            frames.append(frame(lines, False)); durs.append(420)
        elif kind == "type":
            lines.append(("", ACCENT, True))
            # Three characters a frame. One-per-frame tripled the file for motion
            # nobody can see at 30fps, and the GIF is a README asset before it is a
            # typing demo.
            for i in range(3, len(text) + 3, 3):
                lines[-1] = (text[:i], col, True)
                frames.append(frame(lines, True))
                durs.append(70)
            frames.append(frame(lines, False)); durs.append(320)
        else:
            lines.append((text, col, False))
            frames.append(frame(lines, False)); durs.append(55)
    # Hold on the refusal. It is the point of the recording, and a loop that snaps
    # away from it the moment it lands shows everything except the thing it is for.
    frames.append(frame(lines, False)); durs.append(3600)

    # disposal=1 (leave the previous frame in place) rather than 2 (repaint the
    # whole canvas): this recording only ever APPENDS lines, so every frame is the
    # previous one plus a strip at the bottom, and the encoder can ship the strip.
    # With disposal=2 each frame is a full 900x752 image and the file was 3.8MB.
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=durs, loop=0, optimize=True, disposal=1)
    return W, H, len(frames)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "screenshots", "demo-gate.gif"))
    ap.add_argument("--check", action="store_true",
                    help="capture and assert, write nothing")
    ap.add_argument("--cols", type=int, default=96)
    args = ap.parse_args(argv)

    d = tempfile.mkdtemp(prefix="audit-demo-gif-")
    try:
        build_fixture(d)
        cap = capture(d)

        # The recording is only worth shipping if it still shows what it claims.
        problems = []
        if cap["inplan"] is not None:
            problems.append("the in-plan edit was DENIED; the demo claims it is allowed")
        if not cap["outplan"]:
            problems.append("the out-of-plan edit was ALLOWED; there is no refusal to record")
        else:
            if "src/billing.ts" not in cap["outplan"]:
                problems.append("the refusal does not name the file it refused")
            if "#no-plan" not in cap["outplan"]:
                problems.append("the refusal does not name a way out")
        if "P2.1" not in cap["status"] or "READY NOW" not in cap["status"]:
            problems.append("the status render is not the one the demo shows")
        for p in problems:
            sys.stderr.write("FAIL: %s\n" % p)
        if problems:
            return 1

        print("  gate allowed the in-plan edit (silently)")
        print("  gate refused the out-of-plan edit, naming the file and the way out")
        if args.check:
            print("\nOK: demo preconditions hold")
            return 0

        script = build_script(cap, args.cols)
        rows = sum(1 for k, _, _ in script if k != "type") + \
            sum(1 for k, _, _ in script if k == "type") + 1
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        w, h, n = render(script, args.cols, rows, args.out)
        print("  wrote %s (%dx%d, %d frames, %d KB)"
              % (os.path.relpath(args.out, REPO), w, h, n,
                 os.path.getsize(args.out) // 1024))
        print("\nOK: demo GIF captured")
        return 0
    finally:
        # F155, AND THE ANSWER HERE IS THE PLAIN CALL - said rather than left for
        # the next reader to work out again. `build_fixture()` initialises a
        # repository and never writes an object into one: no `add`, no `commit`,
        # and the hooks the capture drives only read. A repository nothing was
        # staged into holds no read-only loose object, so there is nothing for
        # windows to refuse to unlink and the careful removal would be a demand
        # with no failure behind it.
        #
        # THE PREMISE IS ENFORCED AND NOT MERELY RECORDED, which is the difference
        # between this and an exemption written in prose:
        # `_suite.unsafe_removal_violations()` asks for a staging or committing
        # verb as well as an initialising one, so the day `build_fixture()` learns
        # to stage or commit, this file becomes a finding and this comment stops
        # being the thing anybody has to trust.
        shutil.rmtree(d, ignore_errors=True)


# --- selftest -----------------------------------------------------------------
# THE ONE `.py` UNDER tools/ THAT CARRIED NO CASES. `--check` already asserts the
# expensive half - it runs the real capture and refuses to ship a recording of
# something the product no longer does - but it says nothing about the pure text and
# colour logic BELOW that capture, which is where this file's one recorded bug was.
def _cases(check):

    # `_wrap`'s docstring names the defect it exists to fix: a hand-rolled split on
    # spaces turned a two-space indent into two empty tokens and dropped it, so the
    # deny message's numbered list lost its indent on exactly the items long enough
    # to wrap. Both halves of that are asserted, because the short line never broke.
    short = _wrap("  2. short", 40)
    long_ = _wrap("  2. a numbered item long enough that it has to wrap onto a "
                  "second line and then a third", 40)
    check("w0 an indented line that does NOT wrap keeps its indent: %r"
          % (short,),
          short == ["  2. short"])
    check("w1 THE PAIR, and the half that actually broke: a WRAPPING indented "
          "paragraph keeps the indent on every line. w0 passed on the broken "
          "version too, so asserting it alone asserted nothing: %r" % (long_,),
          long_[0].startswith("  2.")
          and all(ln.startswith("  ") for ln in long_) and len(long_) > 1)
    check("w2 a blank line survives as one, so two paragraphs do not become one",
          _wrap("a\n\nb", 40) == ["a", "", "b"])
    huge = "plugins/audit/scripts/manifest/validate-manifest.py"
    check("w3 a token longer than the width is NOT broken - a path split across "
          "two lines is a path a reader cannot copy: %r" % (_wrap(huge, 20),),
          huge in _wrap(huge, 20))
    check("w4 a whitespace-only paragraph is one empty line rather than being "
          "dropped or duplicated",
          _wrap("   ", 40) == [""])

    cap = {"status": "AUDIT plan\nREADY NOW  P2.1\nRESUMABLE P3\nplain line",
           "inplan": None,
           "outplan": "[require-plan] src/billing.ts is not covered\n  use #no-plan"}
    steps = build_script(cap, 96)
    colours = dict((text.strip(), col) for kind, text, col in steps
                   if kind == "out" and text.strip())
    check("b0 the status render is coloured by PREFIX, and all four answers "
          "differ - one shared colour would make three of these vacuous",
          colours.get("AUDIT plan") == ACCENT
          and colours.get("READY NOW  P2.1") == OK
          and colours.get("RESUMABLE P3") == WARN
          and colours.get("plain line") == TEXT)

    denied = dict(cap)
    denied["inplan"] = "[require-plan] src/checkout.ts refused"
    other = build_script(denied, 96)
    # NOT a length comparison, which was the first thing written here: both branches
    # append exactly one step, so length is the one thing that does NOT differ. What
    # differs is the step itself, and that is what a reader of the GIF sees.
    check("b1 THE INVERTED PAIR: two fixtures differing only in whether the "
          "in-plan edit was denied produce different recordings - the demo "
          "claims that edit is ALLOWED, so the branch that says so has to be "
          "the one a None takes",
          other != steps
          and any(col == DENY and "checkout" in text
                  for _k, text, col in other)
          and any(col == OK and "stays out of the way" in text
                  for _k, text, col in steps))

    kinds = set(k for k, _t, _c in steps)
    check("b2 every step is a (kind, text, colour) triple of a kind render() "
          "knows - a fourth kind would draw nothing and say nothing: %r"
          % (sorted(kinds),),
          all(len(step) == 3 for step in steps)
          and kinds <= set(["type", "out", "cmt", "gap"]))

    real = resolve_script("audit-status.py")
    check("r0 a basename resolves to the file WHEREVER it sits under the scripts "
          "tree - a join against the scripts root would look one directory too "
          "high for anything under a domain folder: %s"
          % (os.path.relpath(real, REPO),),
          os.path.isfile(real)
          and os.path.join("scripts", "status") in real)

    try:
        resolve_script("no-such-script-in-this-tree.py")
        found = "returned a path"
    except ImportError as exc:
        found = "ImportError" if "no script named" in str(exc) else str(exc)[:40]
    except Exception as exc:
        found = type(exc).__name__
    check("r1 a basename that names nothing FAILS LOUD rather than resolving to "
          "something plausible - the three refusals are inherited from "
          "`_loader.script_path`, not restated here (got %s)" % (found,),
          found == "ImportError")

    try:
        resolve_script(os.path.join("status", "audit-status.py"))
        sep = "accepted a path"
    except ValueError as exc:
        sep = "ValueError" if "directory sep" in str(exc) else str(exc)[:40]
    except Exception as exc:
        sep = type(exc).__name__
    check("r2 ...and a value carrying a directory separator is refused too, "
          "because the folders under the scripts tree are labels and not "
          "namespaces (got %s)" % (sep,),
          sep == "ValueError")


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    # `safe_stdio()` first, as every `.py` under scripts/ and hooks/ does - the AST
    # lint that enforces it does not scan tools/, and this file prints a deny message
    # captured from the product, which is exactly the kind of text a legacy code page
    # cannot spell.
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
