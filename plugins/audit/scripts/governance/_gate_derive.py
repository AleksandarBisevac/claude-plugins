#!/usr/bin/env python3
"""
_gate_derive.py -- the gate helpers' one home, and a pure derive().

`is_shared_key`, `path_scoped_sibling` and `repointed` used to live inside
`audit-task.py`, which is where a TASK's own narrow gate is derived. A PHASE's
sign-off gate needs the identical questions asked one level up -- "is this
entry a `buildCommands` key rather than a command", "which sibling task's gate
carries this project's own path-scoped spelling", "the same entries with the
paths swapped" -- and an entry point cannot import another entry point, so a
phase-level derivation could only ever have copied the three. Moving them here
gives both callers one body apiece instead of two that could drift, and gives
the new phase-level derivation a floor to stand on that owes nothing to
`audit-task.py`'s own concerns (flags, `--gate`/`--gate-clear`, a caller-
validated `--failing-from` row). `audit-task.py` keeps thin aliases so no
caller and no existing case had to change its spelling.

`derive()` is the phase-level answer: what `meta.phaseGate.mode` computes for
ONE phase's sign-off gate, replacing only the part of the wide default that is
not `meta.phaseGate.always`. It is PURE -- every observation it needs (a
listing's exit code and paths, the installed version's answer, which paths
changed since the phase's `baseRef`, the newest red phase-scope row's named
failures, the plan gate's exempt verdict per touched file) arrives through
`facts`, supplied by the caller. That is what lets its cases run with no
subprocess and no git: a fixture is a dict, not a checkout.
"""

import os
import re
import shlex
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

import _manifest_io as _mio          # noqa: E402  (gate_entries: whose gate
#                                       measures a task, and whether it is the
#                                       task's own -- the union this reads)
import _manifest_vocab as _vocab     # noqa: E402  (PHASE_GATE_BASIS: the words
#                                       this derivation's basis is drawn from,
#                                       so a phase's testGateBasis and this
#                                       function's own reasons cannot disagree)
import _manifest_phases as _phases   # noqa: E402  (gate_entry_paths,
#                                       is_suite_path, tests_add_path,
#                                       phase_gate_default -- the one filename
#                                       bound and the one default, asked here
#                                       instead of re-derived. `_manifest_rules`
#                                       is NOT imported: its `tests_add_path` is
#                                       only a re-export of `_phases`' own, and
#                                       calling the re-export would put this
#                                       module a layer above where its real
#                                       edges land)
import _evidence_io                  # noqa: E402  (subject_key: the one
#                                       reading of "which row is THIS phase's",
#                                       asked here rather than re-derived from
#                                       a row's raw scope/phaseId pair)
import _runner_collects              # noqa: E402  (collects: which runner takes
#                                       a path - asked, never guessed from a
#                                       file name, so a fix task's paths reach
#                                       the runner that will run them)


# THE SAME ALIAS `audit-task.py` HELD before these bodies moved: `_phases.
# gate_entry_paths` asked of a gate entry rather than of a `tests.add` one.
# Kept under this name because `path_scoped_sibling` below is its PRE-MOVE
# body, unchanged, and reads it under this name.
_gate_entry_paths = _phases.gate_entry_paths


# --- moved from audit-task.py; `repointed` since reads each command's slot ------
def is_shared_key(entry, build):
    """True when the entry is a `meta.buildCommands` KEY rather than a command.

    Asked of the declaration and never of the shape. `commands/init.md` has
    entries resolve through `meta.buildCommands` wherever the scope is SHARED
    and be literal commands wherever it differs per task, so what makes an entry
    wide is that the manifest declares it -- not that it looks short. A key
    someone spelled `e2e.spec` would otherwise read as path-scoped on its
    punctuation alone.
    """
    return isinstance(build, dict) and entry in build


def path_scoped_sibling(phase, build):
    """`(entries, taskId)` for the first task in this phase whose `tests.gate`
    carries a path-scoped entry, or `(None, None)`.

    THE PLAN IS THE ONLY RECORD OF THE RUNNER'S SPELLING. `commands/init.md`
    step 5.3 says it plainly: nothing persists how this project narrows a gate
    except the gates themselves, so a task added later reads the shape off its
    siblings rather than re-detecting it. Which makes the sibling EVIDENCE and
    not a resemblance -- that entry was accepted by this project's runner once,
    so the same entry with different paths in it is a command that can run.

    Document order, and the id comes back with the entries because the operator
    has to be able to go and read the gate the shape was taken from.
    """
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        tests = task.get("tests")
        entries = (tests.get("gate") or []) if isinstance(tests, dict) else []
        entries = [e for e in entries if isinstance(e, str) and e.strip()]
        if any(not is_shared_key(e, build) and _gate_entry_paths(e)
               for e in entries):
            return entries, task.get("id")
    return None, None


# `resolve_shape`'s `source` return is this literal string whenever the shape
# came from the DECLARED template (the schema's
# meta.phaseGate.derived.spelling, the FIRST source tried) rather than from a
# sibling's own gate entry, so a caller can tell the two apart without
# inventing a second flag. Every caller that needs a shape asks
# `resolve_shape`; none picks `path_scoped_sibling` on its own, which is
# pinned by test__gate_derive.py's os3.
SPELLING_SOURCE = "meta.phaseGate.derived.spelling"


def resolve_shape(phase, build, derived_cfg):
    """`(shape, source, lines)` -- where THIS phase's path-scoped shape comes
    from: `meta.phaseGate.derived.spelling` FIRST (`source` is
    `SPELLING_SOURCE`), a sibling task's own path-scoped gate entry SECOND
    (`source` is that task's id), or `(None, None, ...)` when neither exists.

    THE RECORDED SPELLING WINS ON PURPOSE: it is the one place the project
    wrote down how its gate narrows, with the single slot the derivation
    fills. A sibling's entry is one task's own gate, whose slot the re-point
    has to read off its words (`_read_command`: each command's program and
    every option's argument told apart from the paths it hands its runner),
    where a template states it outright. A sibling is read only when no
    usable spelling exists.

    A `spelling` carrying no literal `{paths}` placeholder is IGNORED, with a
    printed reason (`lines`) rather than a silent fallback -- the schema says
    the derivation substitutes the placeholder with the resolved file list,
    and a template with nowhere to substitute into cannot do that. The sibling
    is then read, and the reason stays in `lines`.
    """
    derived_cfg = derived_cfg if isinstance(derived_cfg, dict) else {}
    spelling_tpl = derived_cfg.get("spelling")
    lines = []
    if isinstance(spelling_tpl, str) and spelling_tpl.strip():
        if "{paths}" in spelling_tpl:
            return [spelling_tpl], SPELLING_SOURCE, []
        lines.append("spelling: skipped - meta.phaseGate.derived.spelling "
                     "carries no {paths} placeholder")
    shape, owner = path_scoped_sibling(phase, build)
    if shape is not None:
        return shape, owner, lines
    return None, None, lines


def point_shape(shape, source, build, paths, by_kind=False):
    """`shape` pointed at `paths`, whichever source `resolve_shape` took it from.

    THE SPELLING IS FILLED, A SIBLING IS RE-POINTED: the schema's `{paths}`
    placeholder is not a path-shaped token `repointed` would recognize
    (`gate_entry_paths` only counts tokens that already look like a file), so
    a template is substituted with the shell-quoted paths, and a sibling's
    entries go through `repointed`. Asked by the phase-level derivation and by
    `/audit:task add` alike, so the two cannot read one shape two ways.

    `by_kind` hands each command only the paths its own slot takes, as
    `repointed` does. A template whose every `{paths}` command takes the same
    paths is substituted literally, byte for byte as written; one whose
    commands take different paths is rebuilt command by command.

    A TEMPLATE WITH NO `{paths}` WORD OF ITS OWN - the placeholder inside
    `sh -c '...'` quoting, or glued to an option (`--files={paths}`) - has no
    command whose slot can be located, so it is substituted literally, as it
    always was: every path, or with `by_kind` those its one mode
    (`_literal_mode`) takes. Answered with no entry only when `by_kind`
    leaves no path, as a located slot is.
    """
    if source == SPELLING_SOURCE:
        template = shape[0]
        tokens = _entry_tokens(template)
        commands = [_read_command(tokens, span, placeholder=True)
                    for span in _command_spans(tokens)]
        if not any(c["slot"] for c in commands):
            mode = _literal_mode(template)
            given = [p for p in paths
                     if not by_kind or _phases.slot_takes(p, mode)]
            if not given:
                return []
            return [template.replace(
                "{paths}", " ".join(shlex.quote(p) for p in given))]
        plan = [_given(c, paths, by_kind) for c in commands]
        handed = [p for p in plan if p is not None]
        if handed and handed[0] and all(p == handed[0] for p in handed):
            quoted = " ".join(shlex.quote(p) for p in handed[0])
            return [template.replace("{paths}", quoted)]
        rebuilt = _rebuilt(tokens, commands, plan)
        return [rebuilt] if rebuilt is not None else []
    return repointed(shape, build, paths, by_kind=by_kind)


def repointed(entries, build, paths, keep=(), by_kind=False):
    """`entries` with every path-scoped entry re-pointed at `paths`.

    THE FLAGS ARE KEPT AND ONLY THE SLOT MOVES: each simple command of an
    entry is read on its own (`_read_command`), its slot is the path words
    that are neither its program nor an option's argument, those words are
    dropped and this task's paths go in where the first of them stood. Every
    other word keeps its place and spelling, so a source-to-test flag, a `--`
    separator, a project selector and an option's argument (`--config
    jest.config.js`, `-c setup.cfg`, before the slot or after it) are carried
    through, and each command of `a && b` keeps its own program and slot.

    `by_kind` hands each command only the paths ITS slot takes
    (`_manifest_phases.slot_takes`, under that command's own mode): a command
    left with none is dropped with the separator in front of it, and an entry
    left with no command that has a slot is dropped - a path-scoped command
    with its path removed runs the whole suite, the opposite of narrowing.
    Without it every slot is handed every path, which is what a caller handing
    a task's `tests.add` paths asks: the derived gate runs every case the task
    promises to author.

    THE PROGRAM STAYS WHERE IT STANDS: a path an interpreter runs
    (`python3 tools/run.py <suites>`) is the spelling's own and not the slot,
    unless it is itself a suite (`python3 tests/test_a.py` runs the suite it
    names, so that path IS the slot). An entry whose commands hold no slot is
    the spelling's own and is copied through.

    A shared key and an entry naming no path are copied THROUGH rather than
    dropped: a gate of `["lint", "npm test -- <a suite>"]` narrows the suite and
    still lints, because only one of those two entries has a scope that differs
    per task. So is an entry in `keep` - a `meta.phaseGate.always` command the
    plan runs whole, whose own paths stay where they stand rather than being
    swapped for the task's.

    QUOTED FOR THE SHELL THE GATE RUNS IN: `run-test-gate.py` hands each entry
    to a POSIX shell, so every substituted path goes in through `shlex.quote`
    -- an ordinary path comes back byte for byte, and one holding a space or a
    quote stays one word instead of splitting into two the runner cannot
    open. The sibling's own words come from `_phases.shell_words`, the same
    reader `gate_entry_paths` -- and so `path_scoped_sibling` -- uses, so a
    path it already quoted is recognized and replaced rather than copied
    through, and every word that is not in the slot keeps the exact spelling
    it had, quotes and operators included.
    """
    out = []
    for entry in entries:
        if _carried(entry, build, keep):
            out.append(entry)
            continue
        tokens = _entry_tokens(entry)
        commands = [_read_command(tokens, span) for span in _command_spans(tokens)]
        if not any(c["slot"] for c in commands):
            out.append(entry)
            continue
        rebuilt = _rebuilt(tokens, commands,
                           [_given(c, paths, by_kind) for c in commands])
        if rebuilt is not None:
            out.append(rebuilt)
    return out


# --- one entry, its commands, each command's slot ---------------------------------
# The options that take the NEXT word as their argument, across the runners a
# gate entry names (pytest, jest, vitest, playwright, node, the Python
# interpreter). A path standing behind one is that option's argument - a
# config, a root, a report file - and never the slot, so it stays where it
# stands when the slot moves. An `=` form (`--config=jest.config.js`) carries
# its argument in the same word and is an option word whatever its name. An
# option this table lacks has the word behind it read as positional: a path
# there is read as the slot, which is how every option was read before.
_ARGUMENT_TAKING_WORDS = frozenset((
    # pytest
    "-c", "--config-file", "--rootdir", "--confcutdir", "-k", "-m", "-p",
    "-o", "--override-ini", "--basetemp", "--junitxml", "--junit-xml",
    "--cov", "--cov-config", "--cov-report", "--ignore", "--ignore-glob",
    "--deselect", "--log-file", "--tb", "--durations", "--maxfail", "-n",
    "--dist", "--html", "--import-mode", "--capture", "-W", "-r",
    # jest
    "--config", "--rootDir", "--roots", "--testPathPattern",
    "--testPathPatterns", "--testPathIgnorePatterns", "--testNamePattern",
    "-t", "--selectProjects", "--shard", "--maxWorkers", "-w",
    "--coverageDirectory", "--outputFile", "--reporters", "--testEnvironment",
    "--env", "--globalSetup", "--globalTeardown", "--setupFilesAfterEnv",
    "--testTimeout", "--cacheDirectory",
    # vitest
    "--root", "--dir", "--project", "--reporter", "--environment", "--pool",
    "--workspace", "--mode",
    # playwright
    "--grep", "-g", "--grep-invert", "--workers", "-j", "--output",
    "--retries", "--timeout", "--repeat-each", "--max-failures",
    # node and the Python interpreter
    "--require", "--import", "--loader", "--test-reporter",
    "--test-name-pattern", "-e", "-X",
))
# The words one of those runners spells with an argument and another reads
# BARE: vitest's `-w` (watch; jest's `--maxWorkers`), jest's `-o`
# (onlyChanged; pytest's `--override-ini`) and `-e` (expand; node's eval).
# The table is read without the runner it belongs to, so a word in both
# would swallow the suite behind it on the runner that reads it bare and
# send the gate wide. Left out, the word behind it is read as positional -
# a path there is the slot, which narrows - and the argument it takes where
# it takes one is a count, an ini override or code (`-w 4`, `-o key=value`),
# which is ordinarily no path and so not the slot. Add a word here, not by
# deleting it from the table above, so the reason stays beside it.
_BARE_IN_SOME_RUNNER = frozenset(("-w", "-o", "-e"))
OPTION_ARGUMENT_WORDS = _ARGUMENT_TAKING_WORDS - _BARE_IN_SOME_RUNNER
# A redirection operator standing alone takes the next word, the file it names.
_REDIRECT_OPERATOR = re.compile(r"^[0-9]*(?:>>?|<<?|>&|<&|&>>?|>\|)$")
# A list operator an unquoted word carries against it (`a;b`, `(cd`).
_GLUED_OPERATOR = re.compile(r"(&&|\|\||[;&|()])")


def _entry_tokens(entry):
    """`[(raw, value)]` - `_phases.shell_words` of `entry`, with a list
    operator written against an unquoted word split off it, so `a;b` is the
    two commands the shell reads. A redirection with its target attached
    (`2>&1`, `>out.log`) and any quoted word stay whole."""
    out = []
    for raw, value in _phases.shell_words(entry):
        if ("'" in raw or '"' in raw or _phases._is_list_operator(raw)
                or _phases._ATTACHED_REDIRECTION.match(raw)):
            out.append((raw, value))
            continue
        out.extend((part, part) for part in _GLUED_OPERATOR.split(raw) if part)
    return out


def _command_spans(tokens):
    """`[[token index, ...], ...]` - each simple command's tokens; a list
    operator ends one and belongs to none."""
    spans, current = [], []
    for i, (raw, _value) in enumerate(tokens):
        if _phases._is_list_operator(raw):
            if current:
                spans.append(current)
            current = []
        else:
            current.append(i)
    if current:
        spans.append(current)
    return spans


def _basename(word):
    return (word or "").replace("\\", "/").rsplit("/", 1)[-1]


def _read_command(tokens, span, placeholder=False):
    """`{"span", "words", "slot", "sources"}` for one simple command.

    `words` is its token indices less redirections and the file each names.
    `slot` is the indices of the words that hand its runner a path: the path
    words that are neither an option (`-x`, `--opt=value`), nor the argument
    of an option that takes one (`OPTION_ARGUMENT_WORDS`), nor the program an
    interpreter runs (`_manifest_phases._runs_first_path_as_program`, the
    shape check's own reading) unless that program is itself a suite. With
    `placeholder`, the slot is the template's `{paths}` words instead.

    `sources` is what THIS command's slot relates to tests: the extensions a
    related-tests runner resolves (`RELATED_SLOT_WORDS` said in this
    command, at a position that is no option's argument), else empty - a
    slot that takes suites alone. One command's mode says nothing about the
    next command's, nor about another entry's."""
    words, skip = [], False
    for i in span:
        raw = tokens[i][0]
        if skip:
            skip = False
        elif _REDIRECT_OPERATOR.match(raw):
            skip = True
        elif not _phases._ATTACHED_REDIRECTION.match(raw):
            words.append(i)
    values = [tokens[i][1] or "" for i in words]
    options, arguments, k = set(), set(), 0
    while k < len(values):
        value = values[k]
        if len(value) > 1 and value.startswith("-"):
            options.add(k)
            if "=" not in value and value in OPTION_ARGUMENT_WORDS \
                    and k + 1 < len(values):
                arguments.add(k + 1)
                k += 1
        k += 1
    positional = [k for k in range(len(values))
                  if k not in options and k not in arguments]
    if placeholder:
        slot = [k for k in positional if values[k] == "{paths}"]
    else:
        slot = [k for k in positional if _phases.shell_word_path(values[k])]
        if slot and _phases._runs_first_path_as_program(values[:slot[0]]) \
                and _phases.path_kind(_phases.shell_word_path(
                    values[slot[0]])) != "suite":
            slot = slot[1:]
    sources = frozenset()
    for k, value in enumerate(values):
        if k in arguments or value not in RELATED_SLOT_WORDS:
            continue
        runner = RELATED_SLOT_WORDS[value]
        if runner is None or any(_basename(w) == runner for w in values[:k]):
            sources = _phases.SCRIPT_MODULE_EXTENSIONS
    return {"span": span, "words": words, "slot": [words[k] for k in slot],
            "sources": sources}


def _given(command, paths, by_kind):
    """What one command's slot is handed: None for a command with no slot (it
    is copied as written), else the paths it takes - every one, or with
    `by_kind` those `_manifest_phases.slot_takes` admits under its mode."""
    if not command["slot"]:
        return None
    return [p for p in paths
            if not by_kind or _phases.slot_takes(p, command["sources"])]


def _rebuilt(tokens, commands, plan):
    """The entry with each command's slot replaced by its `plan` paths (None:
    the command as written; []: the command dropped with the separator in
    front of it), or None when no command with a slot is left."""
    def text(ci, indices):
        slot, given, words = commands[ci]["slot"], plan[ci], []
        for i in indices:
            if given and i in slot:
                if i == slot[0]:
                    words.extend(shlex.quote(p) for p in given)
                continue
            words.append(tokens[i][0])
        return words

    kept = [ci for ci, given in enumerate(plan) if given is None or given]
    if not any(plan[ci] for ci in kept):
        return None
    if len(kept) == len(commands):
        owner = dict((i, ci) for ci, c in enumerate(commands) for i in c["span"])
        out = []
        for i, (raw, _value) in enumerate(tokens):
            if i not in owner:
                out.append(raw)
            elif i == commands[owner[i]]["span"][0]:
                out.extend(text(owner[i], commands[owner[i]]["span"]))
        return " ".join(out)
    out = []
    for n, ci in enumerate(kept):
        if n:
            start = commands[ci - 1]["span"][-1] + 1 if ci else 0
            out.extend(raw for raw, _v in tokens[start:commands[ci]["span"][0]])
        out.extend(text(ci, commands[ci]["span"]))
    return " ".join(out)


def _placeholder_modes(template):
    """`(standalone, carried)` - the `sources` of each command of a recorded
    template that holds `{paths}` as a word of its own, and of each that
    carries it inside a word (`--files={paths}`). A quoted word carrying it
    (`sh -c 'cd api && pytest {paths}'`) is read as an entry of its own, so
    the command inside the quoting decides the mode."""
    tokens = _entry_tokens(template)
    standalone, carried = [], []
    for span in _command_spans(tokens):
        c = _read_command(tokens, span, placeholder=True)
        if c["slot"]:
            standalone.append(c["sources"])
            continue
        for i in c["words"]:
            raw, value = tokens[i][0], tokens[i][1] or ""
            if "{paths}" not in value:
                continue
            if "'" in raw or '"' in raw:
                inner = _placeholder_modes(value)
                carried.extend(inner[0] + inner[1])
            else:
                carried.append(c["sources"])
    return standalone, carried


def _literal_mode(template):
    """The ONE mode of a template filled by literal substitution: every
    command carrying `{paths}` receives the same text, so the paths it may
    hold are those each such command takes - its shared mode, and suites
    alone when the commands disagree or none can be read."""
    _standalone, carried = _placeholder_modes(template)
    if carried and all(m == carried[0] for m in carried):
        return carried[0]
    return frozenset()


def _literal_slot(entry, template):
    """The paths `entry` holds where a literally filled `template` holds
    `{paths}` - the text between the template's own words, the same text at
    every placeholder - or None when `entry` is not that template filled."""
    parts = template.split("{paths}")
    pattern = re.escape(parts[0]) + "(.*)" + "\\1".join(
        re.escape(p) for p in parts[1:])
    match = re.match(pattern + r"\Z", entry, re.S)
    if match is None:
        return None
    try:
        words = shlex.split(match.group(1))
    except ValueError:
        return None
    return [p for p in (_phases.shell_word_path(w) for w in words) if p]


def slot_reading(entry, template=None):
    """`[(slot paths, sources)]` for each simple command of a WRITTEN gate
    entry, as `_read_command` reads it - or, for a command the recorded
    `template` filled (its words in front of `{paths}` and behind it match),
    the paths between those words, so a path the template names itself is
    not in the slot and the same path written into it is. A template with no
    `{paths}` word of its own was filled literally, so an entry that is that
    template filled is read back by its text, under `_literal_mode`."""
    tokens = _entry_tokens(entry)
    shapes = []
    if isinstance(template, str) and "{paths}" in template \
            and not _placeholder_modes(template)[0]:
        slot = _literal_slot(entry, template)
        if slot is not None:
            return [(slot, _literal_mode(template))]
    if isinstance(template, str) and "{paths}" in template:
        t_tokens = _entry_tokens(template)
        for span in _command_spans(t_tokens):
            c = _read_command(t_tokens, span, placeholder=True)
            if c["slot"]:
                vals = [t_tokens[i][1] for i in c["words"]]
                at = c["words"].index(c["slot"][0])
                shapes.append((vals[:at], vals[at + 1:]))
    out = []
    for span in _command_spans(tokens):
        c = _read_command(tokens, span)
        slot = c["slot"]
        vals = [tokens[i][1] for i in c["words"]]
        for head, tail in shapes:
            end = len(vals) - len(tail)
            if end >= len(head) and vals[:len(head)] == head \
                    and vals[end:] == tail:
                slot = [i for i in c["words"][len(head):end]
                        if _phases.shell_word_path(tokens[i][1])]
                break
        out.append(([_phases.shell_word_path(tokens[i][1]) for i in slot],
                    c["sources"]))
    return out


# --- one path, one runner ---------------------------------------------------------
# A gate that names two runners (vitest for unit tests, playwright for e2e) was
# re-pointed by handing EVERY path to EVERY path-scoped entry: vitest was asked to
# run an e2e spec and playwright a unit test, each finds no tests, and the gate is
# red for a reason that has nothing to do with the work. `repointed_by_runner` asks
# `_runner_collects` which unit runner takes a path and gives it to that entry.
#
# playwright is not a runner `_runner_collects` can read, so it is the runner of
# the paths no unit runner takes AND that sit where e2e specs live - a path no
# runner claims is not guessed onto it.
UNIT_RUNNERS = ("vitest", "jest", "pytest")
E2E_RUNNER = "playwright"
E2E_SEGMENTS = ("e2e", "e2e-tests", "playwright")


def entry_runner(entry):
    """The test runner a gate entry invokes - `vitest`, `jest`, `pytest` or
    `playwright` - or None for an entry that names none (`npm test -- x`, a
    lint). Read off the entry's own words, through a package runner
    (`pnpm exec playwright`) or a module flag (`python3 -m pytest`) alike."""
    for _raw, value in _phases.shell_words(entry):
        base = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
        if base == "py.test":
            return "pytest"
        if base in UNIT_RUNNERS or base == E2E_RUNNER:
            return base
    return None


def entry_collector(entry):
    """What collects the tests of a gate entry for the task-start preflight: the
    entry's `entry_runner`, or `sweep` for an entry running the project's
    `sweep-selftests.py`, or None. Kept apart from `entry_runner` on purpose: the
    sweep is not a path-scoped runner, so handing it to the re-point above would
    count it as a second known runner and narrow gates that were never narrowed."""
    runner = entry_runner(entry)
    if runner in UNIT_RUNNERS:
        return runner
    for _raw, value in _phases.shell_words(entry):
        if (value or "").replace("\\", "/").rsplit("/", 1)[-1] == "sweep-selftests.py":
            return _runner_collects.SWEEP
    return None


def _e2e_like(path):
    parts = path.replace("\\", "/").split("/")
    return (any(seg in E2E_SEGMENTS for seg in parts[:-1])
            or ".e2e." in parts[-1])


def _runners_for(path, unit_runners, has_e2e, project, lister):
    """`(runners, note)` - which of the shape's runners take `path`, and the
    sentence saying why none does when none does."""
    if not _phases.is_suite_path(path):
        if has_e2e and _e2e_like(path):
            return [], ("%s is not a test file, and no runner in this gate can "
                        "run a helper under an e2e directory" % path)
        return list(unit_runners), None
    answers = [(r, _runner_collects.collects(path, r, project, lister=lister)["answer"])
               for r in unit_runners]
    taken = [r for r, a in answers if a == _runner_collects.COLLECTED]
    if taken:
        return taken, None
    if has_e2e and _e2e_like(path):
        if _phases.subject_of(path) is None:
            return [], ("%s sits under an e2e directory but is not named as a "
                        "test, and no runner in this gate can run a helper" % path)
        return [E2E_RUNNER], None
    return [r for r, a in answers if a != _runner_collects.NOT_COLLECTED] \
        or list(unit_runners), None


def _scoped_runners(entries, build, keep=()):
    """`[(entry, runner)]` for every path-scoped entry - one holding a slot
    (`_read_command`); a shared key, an entry in `keep` and an entry whose
    only paths are its program or an option's argument are not - `runner`
    None when it names no known one."""
    return [(e, entry_runner(e)) for e in entries
            if not _carried(e, build, keep) and _has_slot(e)]


def _has_slot(entry):
    """Whether any simple command of `entry` hands its runner a path."""
    tokens = _entry_tokens(entry)
    return any(_read_command(tokens, span)["slot"]
               for span in _command_spans(tokens))


def paths_by_runner(entries, build, paths, project, lister=None):
    """`({runner: [paths]}, notes)` - which of the gate's known runners takes each
    path. One known runner takes every suite path (there is nothing to tell apart,
    and a source file is not a test it could be refused); none gives `{}`. A path no
    runner takes is a note."""
    known = set(r for _e, r in _scoped_runners(entries, build) if r)
    if not known:
        return {}, []
    if len(known) == 1:
        return {next(iter(known)): [p for p in paths if _phases.is_suite_path(p)]}, []
    unit = [r for r in UNIT_RUNNERS if r in known]
    has_e2e = E2E_RUNNER in known
    given, notes = {}, []
    for path in paths:
        runners, why = _runners_for(path, unit, has_e2e, project, lister)
        if not runners:
            notes.append(why or "%s is taken by no runner in this gate" % path)
        for runner in runners:
            given.setdefault(runner, []).append(path)
    return given, notes


def repointed_by_runner(entries, build, paths, project, lister=None, keep=(),
                        by_kind=False):
    """`(entries, notes)` - `repointed`, but each path-scoped entry of a KNOWN
    runner is given only the paths that runner takes (`paths_by_runner`).

    NOTHING TO TELL APART MEANS THE OLD ANSWER: with fewer than two known runners
    in `entries` this is `repointed` and says nothing, so a one-runner project
    gets byte for byte what it always got. An entry naming no known runner
    (`npm test -- x`) keeps every path for the same reason.

    AN ENTRY LEFT WITH NO PATH IS DROPPED, never kept: a path-scoped command
    with its path removed runs the whole suite, which is the opposite of what
    narrowing asked for. Each drop, and each path no entry takes, is a note.
    An entry in `keep` is carried through as `repointed` carries it, and
    `by_kind` is `repointed`'s: each command is then handed, of its runner's
    paths, only those its own slot takes.
    """
    scoped = dict(_scoped_runners(entries, build, keep))
    if len(set(r for r in scoped.values() if r)) < 2:
        return repointed(entries, build, paths, keep, by_kind), []
    given, notes = paths_by_runner(entries, build, paths, project, lister)
    out = []
    for entry in entries:
        runner = scoped.get(entry)
        handed = (paths if runner is None else given.get(runner)) or []
        pointed = repointed([entry], build, handed, keep, by_kind) if handed \
            or runner is None else []
        if pointed:
            out.extend(pointed)
        elif runner is not None:
            notes.append("no %s entry kept: none of %s is a path %s takes"
                         % (runner, ", ".join(paths), runner))
        else:
            notes.append("%r not kept: none of %s is a path its slot takes"
                         % (entry, ", ".join(paths)))
    return out, notes


# --- which of a task's declared paths a slot takes ----------------------------------
# The word that puts ITS COMMAND's runner in a source-to-test mode: jest's
# `--findRelatedTests` (a flag; the command's positional paths are the
# sources) and vitest's `related` subcommand resolve each source through the
# import graph to the tests that cover it. Mapped to the runner the word
# belongs to, None where the option is spelled by no other tool. Read per
# simple command (`_read_command`) and never from what the slot holds or from
# an option's argument (`pytest -k related` is a filter, not the mode).
RELATED_SLOT_WORDS = {"--findRelatedTests": None, "related": "vitest"}


def _carried(entry, build, keep):
    """Whether a gate entry is resolved whole rather than pointed at paths: a
    `meta.buildCommands` key, or an entry in `keep` (the plan's always
    entries)."""
    return not isinstance(entry, str) or is_shared_key(entry, build) \
        or entry in keep


def _shape_modes(shape, source, build, keep=()):
    """The `sources` of every slot-holding command of the shape
    `resolve_shape` returned - a recorded template's `{paths}` commands (its
    one `_literal_mode` when no command holds `{paths}` as a word of its
    own), or a sibling's commands that hand their runner a path."""
    modes = []
    for entry in shape or ():
        if _carried(entry, build, keep):
            continue
        if source == SPELLING_SOURCE and not _placeholder_modes(entry)[0]:
            modes.append(_literal_mode(entry))
            continue
        tokens = _entry_tokens(entry)
        for span in _command_spans(tokens):
            c = _read_command(tokens, span,
                              placeholder=source == SPELLING_SOURCE)
            if c["slot"]:
                modes.append(c["sources"])
    return modes


def slot_takes_sources(shape, source, build, keep=()):
    """Whether any command of the shape `resolve_shape` returned has a slot
    that relates source files to their tests. Said in the basis sentence;
    which command takes which path is `taken_paths`'s question."""
    return any(_shape_modes(shape, source, build, keep))


def taken_paths(shape, source, build, paths, keep=()):
    """The `paths` some command of the shape has a slot for: each asked
    `_manifest_phases.slot_takes` under that command's own mode. A path no
    command takes is handed to none, and a derivation left with none has
    nothing to point at."""
    modes = _shape_modes(shape, source, build, keep)
    return [p for p in paths
            if any(_phases.slot_takes(p, mode) for mode in modes)]


def untaken_slot_paths(gate, files, shape, source, build, keep=()):
    """The declared `files` a gate's commands hand their slot that the
    command's own slot does not take (`_manifest_phases.slot_takes` under
    that command's mode, `slot_reading`), in the order the gate names them,
    once each - whatever the spelling, so a source-to-test slot handed a
    document, or one command of `a && b` handed a path only the other takes,
    is named. Read by position: an always entry or a shared key hands no slot,
    and a path the recorded template names itself is not in the slot while the
    same path written into it is. Only a declared path counts: the derivation
    was handed nothing else."""
    template = shape[0] if source == SPELLING_SOURCE and shape else None
    declared = [_vocab._strip_line_suffix(str(f)) for f in files or ()]
    out = []
    for entry in gate or ():
        if _carried(entry, build, keep):
            continue
        for slot, sources in slot_reading(entry, template):
            for path in slot:
                if path in declared and path not in out \
                        and not _phases.slot_takes(path, sources):
                    out.append(path)
    return out


# --- the newest red phase-scope row --------------------------------------------
def newest_red_phase_row(rows, phase_id):
    """The newest `scope: "phase"`, `status: "failed"` row for `phase_id`, or None.

    `_evidence_io.subject_key` is the one reading of "which row belongs to this
    phase" -- it refuses a row missing the id its own scope needs, the same
    filter `latest_by_subject` uses to decide what a pointer may name. `status`
    is added here because a phase whose newest run went green owes a derivation
    nothing further to narrow around: an OLD failure a later green run already
    superseded would understate a gate that has since been fixed.

    NEWEST BY THE MOMENT `ts` NAMES (`_evidence_io.newest_row`), never by its
    text: an offset or a fractional second orders apart from its spelling, and
    a tie goes to the row read later.
    """
    return _evidence_io.newest_row([
        row for row in (rows or [])
        if isinstance(row, dict) and row.get("status") == "failed"
        and _evidence_io.subject_key(row) == ("phase", str(phase_id))])


# --- the phase-level derivation --------------------------------------------------
# Pinned verbatim: the one sentence every NARROWED answer's basis carries,
# so a reader never has to guess whether a narrow gate came from more than the
# import graph and the recorded couplings -- and a widened version of it (one
# that also claimed, say, "and the files this phase touched") would be a claim
# this derivation cannot make, because `facts` never sees anything else.
BASIS_NARROWED = "selected by import graph and recorded couplings only"


def _touched_files(phase):
    """Every path any task in `phase` declares in `files`, in task/declaration
    order, deduplicated -- what the smoke arm and the coupling arm both ask
    "is every one of these exempt or a test" and "does this coupling's sources
    overlap" against.
    """
    out = []
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        for path in (task.get("files") or []):
            if isinstance(path, str) and path not in out:
                out.append(path)
    return out


def _tests_add_arm(phase, build):
    """Every path a TASK'S OWN gate names, read through `_mio.gate_entries` so
    a task falling back to its PHASE's wide gate (source `"phase"`) never
    contributes a path here -- that fallback is the wide gate already, and
    reading it as evidence of a narrow one would be the derivation citing
    itself.
    """
    paths = []
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        entries, source = _mio.gate_entries(phase, task)
        if source != "task":
            continue
        for entry in entries:
            if is_shared_key(entry, build):
                continue
            for path in _gate_entry_paths(entry):
                if path not in paths:
                    paths.append(path)
    return paths


def _coupling_arm(meta, touched):
    """Every `meta.coupling[].test` whose `sources` overlap `touched`, in
    declaration order. A coupling whose sources miss the phase's files adds
    nothing -- it was learned from a DIFFERENT change, and citing it here would
    narrow this phase's gate around evidence about another one.
    """
    touched_set = set(touched)
    out = []
    for entry in (meta.get("coupling") or []):
        if not isinstance(entry, dict):
            continue
        test = entry.get("test")
        sources = entry.get("sources")
        sources = sources if isinstance(sources, list) else []
        if (isinstance(test, str) and test.strip()
                and touched_set & set(sources) and test not in out):
            out.append(test)
    return out


def _full_listing_empty(facts):
    """True when `facts["fullListing"]` RAN, exited 0, and named ZERO suites.

    This is what makes `derived-empty` reachable at all (see `derive()`'s own
    note): `meta.phaseGate.derived.listing.all` is an ADDITIONAL shape source
    beside `path_scoped_sibling`, and unlike that one it CAN legitimately come
    back with nothing to narrow to -- an all-suites listing is free to name no
    suite (an empty project, a misspelled listing command). `full is None`
    (no listing configured, or it never ran) answers False, same as a listing
    that timed out or exited non-zero: none of those says "there is nothing to
    narrow to", only "this run cannot say".
    """
    full = facts.get("fullListing") if isinstance(facts, dict) else None
    full = full if isinstance(full, dict) else None
    if full is None or full.get("exit") != 0:
        return False
    paths = full.get("paths")
    return isinstance(paths, list) and len(paths) == 0


def version_distrust(derived, facts):
    """Why the machine's version answer cannot vouch for a recorded listing,
    as `None` (it can), `("failed", None, None)` (the version command could
    not be run, or exited non-zero) or `("mismatch", declared, current)`.

    The one reading of the two version checks, so the importers arm and the
    task-gate arm cannot drift on which answer counts. The verdict is data and
    each caller words its own skip line.
    """
    if facts.get("versionCheckFailed"):
        return ("failed", None, None)
    verified_on = derived.get("verifiedOn") if isinstance(derived, dict) else None
    declared = verified_on.get("answer") if isinstance(verified_on, dict) else None
    current = facts.get("versionAnswer")
    if declared != current:
        return ("mismatch", declared, current)
    return None


def output_lines(text):
    """One entry per non-blank line of a listing command's output, stripped."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def version_facts(derived, run):
    """`{versionAnswer}` or `{versionCheckFailed: True}` -- the version
    command in `derived.verifiedOn` run through `run(command)`, which returns
    `{exit, output}`. `{}` when no command is recorded. A command that did not
    exit 0 is its own fact, never an answer of `None`.
    """
    verified_on = derived.get("verifiedOn") if isinstance(derived, dict) else None
    command = verified_on.get("command") if isinstance(verified_on, dict) else None
    if not (isinstance(command, str) and command.strip()):
        return {}
    res = run(command)
    if res["exit"] == 0:
        return {"versionAnswer": res["output"].strip()}
    return {"versionCheckFailed": True}


def listing_command(template, paths):
    """`template` with `{paths}` replaced by the shell-quoted `paths`."""
    return template.replace("{paths}", " ".join(shlex.quote(p) for p in paths))


def listing_fact(res):
    """`{exit, paths}` for a listing command's `{exit, output}` result."""
    return {"exit": res["exit"], "paths": output_lines(res["output"])}


def _importers_arm(meta, facts):
    """`(paths, full, note)` for the importer-listing arm.

    FOUR THINGS HAVE TO HOLD before a listing is trusted at all: a listing has
    to be RECORDED (`meta.phaseGate.derived.listing`), the version command
    that was supposed to answer this machine's version has to have RUN AT ALL
    (a version command that cannot be run or exits non-zero is its own skip
    reason -- "the version command failed" -- never rendered as a machine
    answering `None`, which would read as an actual mismatched answer rather
    than as no answer at all), the machine asking has to answer the SAME
    version question the listing was verified against (a listing verified on
    one npm/node/etc answer is not evidence on another), and the
    listing itself has to have exited 0. Any of the four failing skips the arm
    with the reason named -- never an empty result read as "narrowed to
    nothing", and never a stale listing trusted in silence.

    EQUAL TO THE FULL LISTING MEANS THE WIDE GATE **IS** THE NARROW ANSWER:
    every suite the runner would collect imports something this phase
    touched, so there is nothing left to narrow away from and pretending
    otherwise would be a guess dressed as a derivation.

    A RELATED listing that named NONE while the ALL listing named SOME is its
    own printed reason too -- the arm contributes nothing, but silently (a
    `None` fallthrough) is indistinguishable from "nothing here to report",
    which is not what happened: the full listing found suites, the related one
    just did not name any of them.
    """
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived = gate.get("derived")
    derived = derived if isinstance(derived, dict) else None
    if not derived or not isinstance(derived.get("listing"), dict):
        return [], False, None
    distrust = version_distrust(derived, facts)
    if distrust and distrust[0] == "failed":
        return [], False, "importers: skipped - the version command failed"
    if distrust:
        return [], False, ("importers: skipped - listing verified on %s, this "
                           "machine answers %s" % (distrust[1], distrust[2]))
    listing = facts.get("listing")
    listing = listing if isinstance(listing, dict) else {}
    exit_code = listing.get("exit")
    if exit_code != 0:
        return [], False, "importers: skipped - listing exited %r" % (exit_code,)
    listed = [p for p in (listing.get("paths") or []) if isinstance(p, str)]
    full = facts.get("fullListing")
    full = full if isinstance(full, dict) else {}
    full_paths = [p for p in (full.get("paths") or []) if isinstance(p, str)]
    listed_set, full_set = set(listed), set(full_paths)
    if full_set and listed_set == full_set:
        return [], True, "DERIVED = FULL"
    if listed_set and full_set and listed_set < full_set:
        return listed, False, None
    if not listed_set and full_set:
        return [], False, ("importers: skipped - the related listing named no "
                           "suite while the full listing named %d"
                           % (len(full_set),))
    return [], False, None


def derive(manifest, phase, facts):
    """`{entries, basis, derived, narrowed, lines, shapeSource, attribution}`
    -- this phase's sign-off gate, computed the way `meta.phaseGate.mode`
    asks: only the part of the wide default that is NOT `meta.phaseGate
    .always` is ever replaced, and `meta.phaseGate.exclude` is read through
    `_phases.phase_gate_default` exactly once, so a fallback can never run
    fewer suites than `/audit:phase add` would already have written.

    `attribution` IS THE ONLY BREAKDOWN THIS PLUGIN COMPUTES, and it is
    `None` whenever `narrowed` is False -- EVERY wide basis, with no
    exception, including a full-suite resolution (`test_paths` at that point
    is real, but it is not what the wide gate runs, so reporting it as a
    breakdown would print a narrowed-looking count for a gate that is not
    narrowed). A second, independent computation of these same arms does not
    know every widening trigger this function knows -- a new trigger added
    here and not there reports a narrowed-looking breakdown for a gate that
    is actually wide, which is why `derive-phase-gate.py` no longer computes
    one: `attribution` is part of THIS function's own return, `{testsAdd,
    coupling, importers, changed, lastFailed, union}` only when `narrowed`
    is True, and a caller renders ONLY off this dict -- `narrowed` and
    `basis` decide what a WIDE result means (`derived-empty`'s two triggers,
    a full-suite resolution, `phase-no-spelling`), never `attribution`'s
    presence, which is now the same fact stated a second way.

    `facts` is the ONLY place an observation may arrive from: `listing` /
    `fullListing` (each `{exit, paths}`), `versionAnswer` (this machine's
    answer to the same question `meta.phaseGate.derived.verifiedOn` recorded),
    `changedSince` (paths changed since `phase.baseRef`), `lastFailedSuites`
    (the newest red phase-scope row's NAMED failures, already filtered to a
    `failingSuitesBasis` that says the runner named them), and `exempt` (the
    plan gate's exempt verdict, keyed by path). No argument here ever shells
    out or reads git -- that is the caller's job, once, before this runs.

    `_manifest_vocab.PHASE_GATE_BASIS[1]` ("derived-empty") IS reachable, from
    TWO triggers, both widening the WHOLE derivation before entries are built
    and both rendered from the SAME `basis` word by a caller, so an operator
    reading the human line never has to know which trigger fired to trust
    what it says: `meta.phaseGate.derived.listing.all` is an ADDITIONAL shape
    source beside `resolve_shape`'s, and it CAN legitimately come back with
    nothing to narrow to (an all-suites listing is free to name no suite at
    all) -- caught by `_full_listing_empty` right after the shape is resolved,
    before coupling/importers/changed/last-failed ever run. The SECOND
    trigger is `resolve_shape`'s own SPELLING source: unlike the SIBLING
    source (the same task that supplies it necessarily contributes at least
    one path to `_tests_add_arm` through the identical read
    `path_scoped_sibling` used to find it, so a sibling-sourced shape and
    `test_paths == []` cannot both hold), a spelling-sourced shape carries no
    such guarantee -- no task's own gate backs it. So AFTER every arm
    (tests.add, coupling, importers, changed, last-failed) has had its turn,
    an empty `test_paths` on the spelling source widens too, with its own
    reason ("spelling: nothing to substitute...") rather than substituting
    `{paths}` with nothing: depending on the runner, an empty `pytest ` or
    `vitest run ` means either the WHOLE suite or NOTHING, and either reading
    would make the gate mean something other than what it prints. Both
    triggers return `attribution: None` -- there is nothing to attribute a
    path to when the whole point of the trigger is that no arm found one.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    phase = phase if isinstance(phase, dict) else {}
    facts = facts if isinstance(facts, dict) else {}

    default = _phases.phase_gate_default(meta)
    always = list(default["always"])

    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    mode = gate.get("mode")
    if mode not in _phases.PHASE_GATE_MODES:
        # ABSENT MEANS NO DERIVATION. The wide default is the whole answer, and
        # `derived: False` says so as data rather than leaving a reader to infer
        # it from `basis` alone.
        return {"entries": list(default["entries"]),
                "basis": "meta.phaseGate.mode is not set - no derivation",
                "derived": False, "narrowed": False, "lines": [],
                "shapeSource": None, "attribution": None}

    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    derived_cfg = gate.get("derived")
    shape, shape_source, lines = resolve_shape(phase, build, derived_cfg)
    if shape is None:
        return {"entries": always + list(default["rest"]),
                "basis": "phase-no-spelling", "derived": True,
                "narrowed": False, "lines": lines, "shapeSource": None,
                "attribution": None}

    if _full_listing_empty(facts):
        # BEFORE ANYTHING ELSE RUNS: an ALL listing that ran, exited 0 and
        # named no suite is not evidence of anything narrower -- widen with
        # the reason printed rather than let coupling/importers/changed/
        # last-failed run against a listing that already said "nothing".
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[1], "derived": True,
                "narrowed": False,
                "lines": lines + ["derived-empty: the ALL listing ran, "
                                  "exited 0 and named no suite - nothing to "
                                  "narrow to, widening"],
                "shapeSource": None, "attribution": None}

    touched = _touched_files(phase)
    tests_add = _tests_add_arm(phase, build)
    test_paths = list(tests_add)
    coupling_new = []
    for path in _coupling_arm(meta, touched):
        if path not in test_paths:
            coupling_new.append(path)
            test_paths.append(path)

    importer_paths, full_suite, importer_note = _importers_arm(meta, facts)
    if importer_note:
        lines.append(importer_note)
    if full_suite:
        # SAME RULE AS EVERY OTHER WIDE BASIS: `narrowed` is False here, so
        # `attribution` is `None` here too -- `test_paths` at this point (the
        # union of `tests.add` and coupling, BEFORE the importer/changed/
        # last-failed loops even run) is not what the wide gate runs, and a
        # caller reporting it as a per-arm breakdown would be printing a
        # narrowed-looking count for a gate that is not narrowed. What IS
        # measured for this basis -- the related listing's count and the full
        # listing's count -- lives in `facts`, which the caller already has;
        # this function is not the one to duplicate it into `attribution`.
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[2],
                "derived": True, "narrowed": False, "lines": lines,
                "shapeSource": None, "attribution": None}
    importer_new = []
    for path in importer_paths:
        if path not in test_paths:
            importer_new.append(path)
            test_paths.append(path)

    changed_new = []
    for path in (facts.get("changedSince") or []):
        if (isinstance(path, str) and _phases.is_suite_path(path)
                and path not in test_paths):
            changed_new.append(path)
            test_paths.append(path)
    last_failed_new = []
    for path in (facts.get("lastFailedSuites") or []):
        if isinstance(path, str) and path not in test_paths:
            last_failed_new.append(path)
            test_paths.append(path)

    # NO "test_paths == []" GUARD HERE for the SIBLING-sourced shape, on
    # purpose: a sibling's own gate already contributed at least one path to
    # `test_paths` through `_tests_add_arm` (the identical read
    # `path_scoped_sibling` used to find the shape in the first place), so
    # this point in the function can never be reached with an empty set on
    # THAT source -- a branch written for it would be dead code no case here
    # could ever prove red. The SPELLING-sourced shape carries no such
    # guarantee (no task's own gate backs it), so IT gets the guard: an empty
    # `test_paths` there would substitute `{paths}` with nothing, and
    # depending on the runner an empty `pytest ` or `vitest run ` means either
    # the WHOLE suite or NOTHING -- either way a gate that silently means
    # something other than what it prints, which the phase's own rule forbids
    # (nothing narrows unless it is declared and printed; anything unbounded
    # turns wide with the reason printed).
    if shape_source == SPELLING_SOURCE and not test_paths:
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[1], "derived": True,
                "narrowed": False,
                "lines": lines + ["spelling: nothing to substitute - no arm "
                                  "named a test path, so the wide gate runs"],
                "shapeSource": None, "attribution": None}

    entries = list(always)
    for entry in point_shape(shape, shape_source, build, test_paths):
        if entry not in entries:
            entries.append(entry)

    smoke = gate.get("smoke")
    if isinstance(smoke, str) and smoke.strip():
        exempt = facts.get("exempt")
        exempt = exempt if isinstance(exempt, dict) else {}
        # NEVER DECIDED BY `meta.runtimeBoot.appRootPath`: the ONLY
        # questions asked of a touched file are whether the plan gate's own
        # exempt verdict already cleared it and whether it is a test file
        # itself -- a source file outside an app's own root is still a source
        # file, and reading the prefix here would be a second, silently
        # different rule about what "this phase's own work" means.
        if touched and all(_phases.is_suite_path(f) or exempt.get(f)
                           for f in touched):
            lines.append("smoke: skipped - every file this phase touched is "
                         "docs or tests")
        elif smoke not in entries:
            entries.append(smoke)

    return {"entries": entries, "basis": BASIS_NARROWED, "derived": True,
            "narrowed": True, "lines": lines, "shapeSource": shape_source,
            "attribution": {"testsAdd": tests_add, "coupling": coupling_new,
                           "importers": importer_new, "changed": changed_new,
                           "lastFailed": last_failed_new,
                           "union": list(test_paths)}}


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
