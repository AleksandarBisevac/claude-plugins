#!/usr/bin/env python3
"""
The cases for `_merge_install.py` - what a merge-driver install is, read back.

The end-to-end install (write, re-install, uninstall, a real `git merge`) is
`test_merge_manifest.py`'s; the doctor's reading of it is `test__doctor_setup.py`'s.
What is left here is the part both of those trust without looking: where the pieces
are located, and that the shim's recorded root reads back as the root that was
written - including a root the shell had to quote.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _merge_install as M                         # noqa: E402


def _cases(check):
    loc = {"toplevel": "/r", "common_dir": "/r/.git", "manifest_rel": "docs/audit/plan.json",
           "shard_glob_rel": "docs/audit/phases/*.json"}
    lines = M.attribute_lines(loc)
    check("mi1 install owns a header and one line each for the plan and its shard glob",
          lines == [M.ATTR_HEADER, "docs/audit/plan.json merge=audit-manifest",
                    "docs/audit/phases/*.json merge=audit-manifest"], lines)
    check("mi2 git config names the shim under the common dir, run through sh",
          M.driver_value(loc) == "sh '/r/.git/%s' %%O %%A %%B %%P" % (M.SHIM_REL,),
          M.driver_value(loc))

    shim = M.shim_text("/opt/plugin root")
    check("mi3 the shim records the root on one line the reader looks for",
          "\n%s'/opt/plugin root'\n" % (M.SHIM_ROOT_KEY,) in shim, shim)
    check("mi4 ...and every exit it takes is 0 or 1 - git aborts the WHOLE merge on an "
          "exit above 128",
          all(tok in ("0", "1") for tok in
              [ln.strip().split("exit ")[1].split(";")[0].split()[0]
               for ln in shim.splitlines() if "exit " in ln]), shim)
    check("mi5 ...and its fallback is git's line merge into %A with labels",
          'git merge-file -L ours -L base -L theirs "$2" "$1" "$3"' in shim)

    if not shutil.which("git"):
        _harness.skip(check, "mi6-mi9 locate and status_facts against real git",
                      "git", "git is not on PATH")
        return
    tmp = tempfile.mkdtemp(prefix="merge-install-selftest-")
    held = os.environ.copy()
    os.environ.update({"HOME": tmp, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull})
    try:
        loose = os.path.join(tmp, "loose", "plan.json")
        os.makedirs(os.path.dirname(loose))
        got, err = M.locate(loose)
        check("mi6 a manifest outside any work tree is an error naming it, not a location",
              got is None and "not inside a git work tree" in err, err)

        repo = os.path.join(tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        spaced = os.path.join(repo, "my plans", "plan.json")
        os.makedirs(os.path.dirname(spaced))
        got, err = M.locate(spaced)
        check("mi7 a path .gitattributes would have to quote is refused with the reason",
              got is None and "quote" in err, err)

        plan = os.path.join(repo, "docs", "audit", "plan.json")
        os.makedirs(os.path.dirname(plan))
        got, _e = M.locate(plan)
        check("mi8 a plan inside the tree locates relative to the top level, shards beside it",
              got is not None and got["manifest_rel"] == "docs/audit/plan.json"
              and got["shard_glob_rel"] == "docs/audit/phases/*.json", got)

        root = os.path.join(tmp, "it's here")
        os.makedirs(os.path.join(root, "scripts", "manifest"))
        open(os.path.join(root, "scripts", "manifest", "merge-manifest.py"), "w").close()
        os.makedirs(os.path.dirname(M.shim_path(got)))
        with open(M.shim_path(got), "w", encoding="utf-8") as fh:
            fh.write(M.shim_text(root))
        facts = M.status_facts(plan)
        check("mi9 a root the shell had to quote reads back as the root that was written",
              facts["shim_root"] == root and facts["shim_root_exists"] is True, facts)
    finally:
        os.environ.clear()
        os.environ.update(held)
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__merge_install.py --selftest\n")
    raise SystemExit(2)
