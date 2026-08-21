#!/usr/bin/env python3
"""
What branch this phase forks from, and what it is called.

`_branch` holds the rule; this is the door the orchestrator knocks on. It exists
as a real command rather than a prose instruction for one reason, and it is the
reason the module exists at all: `reference/orchestrator.md` could say "compose
`<prefix>/<phaseId>-<slug>`" while the shape was fixed, and a reader would get it
right every time. A TEMPLATE has cases — an absent `{initials}` must take the
separator behind it with it, or the name is `feature//p2-x` and git refuses it —
and a rule with cases belongs in something that can be tested.

It is also a real command rather than a `python3 -c` one-liner for the reason
`check-ado-item.py` gives: a one-liner naming a source path is the shape
`guard-secrets-read` refuses, so it would be blocked on the machines that most
need it.

ADVISORY, NOT A GATE — `SECURITY.md`'s split. Nothing here refuses a run: it
answers two questions and reports what would go wrong. The one exception is a
name git would reject, which is exit 1 because the very next command
(`git switch -c`) fails anyway, and failing here says why.

Initials come from `git config user.name` unless `meta.branch.initials` overrides
it. An identity that yields no initials is reported as such rather than guessed:
the placeholder collapses and the branch simply carries no mark, which is better
than carrying the wrong person's.

  parent   which branch to fork from and merge back into, and what decided it
  branch   the name to create, and which key's convention produced it

Usage:
  resolve-branch.py <manifest> --phase <phaseId>
  resolve-branch.py <manifest> --phase P2 --json
  resolve-branch.py <manifest> --globs          # the pre-approved branch globs

Exit codes: 0 resolved - 1 the name is not a legal git ref - 2 usage error.
"""
import json
import os
import subprocess
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

import _branch  # noqa: E402  (the rule this door opens onto)
import _manifest_io as _mio  # noqa: E402  (dual-format loader: single-file OR shards)


def git_user_name(git_root):
    """`git config user.name`, or "" when git cannot say.

    Fail-open: this is an advisory path, and a machine with no git identity
    should get a branch with no initials rather than no branch.
    """
    try:
        out = subprocess.run(["git", "-C", git_root or ".", "config", "user.name"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=10)
        if out.returncode == 0:
            return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return ""


def find_phase(manifest, phase_id):
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id):
            return ph
    return None


def resolve(manifest, phase_id, user_name):
    """The two answers plus their bases — the shape both output modes render."""
    meta = manifest.get("meta") or {}
    phase = find_phase(manifest, phase_id)
    if phase is None:
        return None
    from_bug = bool(phase.get("branchType") is None
                    and str(phase.get("id", "")).startswith("BUG"))
    parent = _branch.parent_branch(meta, phase)
    made = _branch.compose(meta, phase, initials=user_name, from_bug=from_bug)
    return {
        "phase": str(phase.get("id")),
        "parent": parent["branch"],
        "parentBasis": parent["basis"],
        "parentIsDevelopment": parent["is_development"],
        "branch": made["name"],
        "branchBasis": made["basis"],
        "type": made["type"],
        "typeBasis": made["typeBasis"],
        "violations": made["violations"],
        "unknownType": made["unknownType"],
        "initialsSource": ("meta.branch.initials"
                           if _branch.config(meta)["initials"] is not None
                           else ("git user.name" if user_name else "none available")),
    }


def render(ans):
    lines = ["parent   %s   (%s)" % (ans["parent"], ans["parentBasis"]),
             "branch   %s   (%s)" % (ans["branch"], ans["branchBasis"]),
             "type     %s   (%s)" % (ans["type"], ans["typeBasis"])]
    if not ans["parentIsDevelopment"]:
        # Said here so the sign-off report cannot forget it: a phase that merges
        # into a story branch has NOT reached the development branch, and silence
        # about that reads as "landed".
        lines.append("")
        lines.append("NOTE: this phase merges into %r, NOT into the development "
                     "branch. Sign-off must say so - the work has not reached the "
                     "development branch until %r is itself merged."
                     % (ans["parent"], ans["parent"]))
    if ans["unknownType"]:
        lines.append("")
        lines.append("WARNING: type %r is not in meta.branch.types, so it is "
                     "outside the pre-approved globs and every branch operation "
                     "on it will ask for confirmation." % (ans["type"],))
    if ans["violations"]:
        lines.append("")
        for v in ans["violations"]:
            lines.append("FINDING: the composed name is not a legal git ref: %s" % v)
    return "\n".join(lines)


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(__doc__.strip().split("Usage:")[-1].strip() + "\n")
        return 2
    manifest_path = argv[0]
    rest = argv[1:]
    as_json = "--json" in rest
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        sys.stderr.write("cannot read %s: %s\n" % (manifest_path, exc))
        return 2

    meta = manifest.get("meta") or {}
    if "--globs" in rest:
        globs = _branch.approved_globs(meta)
        if as_json:
            print(json.dumps({"globs": globs}, indent=1, sort_keys=True))
        else:
            print("\n".join(globs))
        return 0

    if "--phase" not in rest:
        sys.stderr.write("resolve-branch.py: --phase <phaseId> or --globs "
                         "is required\n")
        return 2
    phase_id = rest[rest.index("--phase") + 1] if len(rest) > rest.index("--phase") + 1 else ""
    if not phase_id:
        sys.stderr.write("resolve-branch.py: --phase needs a phase id\n")
        return 2

    ans = resolve(manifest, phase_id,
                  git_user_name(meta.get("gitRoot") or os.path.dirname(manifest_path)))
    if ans is None:
        sys.stderr.write("resolve-branch.py: no phase %r in %s\n"
                         % (phase_id, manifest_path))
        return 2
    print(json.dumps(ans, indent=1, sort_keys=True) if as_json else render(ans))
    return 1 if ans["violations"] else 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("resolve-branch.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_resolve_branch.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
