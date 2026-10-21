#!/usr/bin/env python3
"""
Where this project's files are, and the three modules the panel reads them
through -- the floor the rest of the panel's read side stands on.

Split out of `_panel_state.py` (U3.1), and the layer is the whole reason it
is a file. `_panel_state` has `_panel_write` and `panel-server`/`audit-task`
above it, so anything cut out of it has to fit in a layer below it, and
anything THOSE import in a layer below that. This module is that lower layer:
`_config_rules` and `_status_facts`, one layer down, are its deepest reach.

WHAT `_cores()` USED TO BE, AND WHY IT IS NOT HERE. It returned a positional
4-tuple of `(_manifest_rules, _config_rules, _status_facts, hooks/_config)`,
and `_manifest_rules` is itself this module's layer-mate -- so a base module
holding that tuple could only sit one layer up, which leaves no layer at all
for the five modules that read it. Measured across the tree: of the 19 reads of
that tuple, 8 want the hooks config, 4 want `_manifest_rules`, and all four of
THOSE sit at `_panel_state`'s layer or above, where a plain
`import _manifest_rules` is an ordinary downward edge. So the grab-bag is unbundled here into three named accessors, and
`_panel_state._cores()` still assembles the same 4-tuple in the same order for
`_panel_write` and `audit-task`, which read it positionally.

ONE MEMO, STILL. `hooks_config()` is the only accessor that loads anything;
`config_rules()` and `status_facts()` hand back a module a plain `import`
already bound, which is why memoizing them was always vestigial. Keeping the
single memo below everything that reads it is what the old docstring's
warning was about -- two memos would be two answers to "have the cores been
loaded yet".

Stdlib only, Python 3.8 compatible.
"""
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

CONFIG_REL = ".claude/audit.config.json"

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _status_facts          # noqa: E402  (rollup/readiness/gate facts)
import _config_rules          # noqa: E402  (the audit.config.json rules)
import _loader                # noqa: E402  (the one path-importlib loader for scripts/)


# --- lazy import of the plugin's own pure cores (hyphenated filenames) ----------
def _load(modname, filename, directory=None):
    """Thin per-call wrapper: callers here pass an explicit modname (the file is
    hyphenated and not otherwise importable). Delegates to `_loader`, the one
    shared path-importlib loader — see its docstring for the caching policy.

    With no `directory` this goes through `_loader.load_script`, which resolves a
    scripts/ file by BASENAME wherever it sits — the same shape `audit-doctor._load`
    and `audit-usage._load` already take. The one `hooks/` caller passes
    `_output.HOOKS_DIR` and keeps the explicit join, because `hooks/` is not on that
    walk (and must not be: hooks may not be reached by an import at all)."""
    if directory is None:
        return _loader.load_script(filename, modname=modname)
    return _loader.load(os.path.join(directory, filename), modname=modname)


_CFG = None


def hooks_config():
    """`hooks/_config` -- DEFAULTS, `usage_cfg`, `state_dir`, `ledger_dir`,
    `plan_gate_mode` and the rest of the knobs both sides read.

    The one accessor here that does work, and therefore the one that memoizes.
    `_loader` caches underneath as well, so this memo is a second line of
    defence rather than the only one -- but it is the memo `_panel_write`'s
    cases patch, so it stays a single object in a single module."""
    global _CFG
    if _CFG is None:
        _CFG = _loader.load_hooks_config(modname="audit__config")
    return _CFG


def config_rules():
    """`_config_rules` -- `validate-config.py` without its `main()`."""
    return _config_rules


def status_facts():
    """`_status_facts` -- `audit-status.py`'s machine-readable half."""
    return _status_facts


def _defaults():
    return hooks_config().DEFAULTS


# --- path safety ----------------------------------------------------------------
def _within(project, path):
    """True iff `path` resolves inside `project` (no ../ escape, no symlink out)."""
    proj = os.path.realpath(project)
    tgt = os.path.realpath(path)
    return tgt == proj or tgt.startswith(proj + os.sep)


def _config_path(project):
    return os.path.join(project, CONFIG_REL)


def _manifest_path(project, config):
    mp = (config or {}).get("manifestPath") or _defaults()["manifestPath"]
    return os.path.normpath(os.path.join(project, mp))


def _read_json(path):
    """Thin delegation to the plugin's ONE JSON reader (_manifest_io.read_json)."""
    return _mio.read_json(path)


def read_config(project):
    try:
        obj = _read_json(_config_path(project))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
