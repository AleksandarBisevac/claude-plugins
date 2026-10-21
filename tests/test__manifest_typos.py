#!/usr/bin/env python3
"""
The cases for `_manifest_typos.py` — the did-you-mean detectors.

Every line either detector emits is a WARNING and `findings` is always empty,
so the whole risk here is the FALSE POSITIVE: a detector that fires on two
models a project deliberately uses is noise a reader learns to skip, and a
detector that has learned to skip is a detector that is off.

The two rules that keep it honest, and the cases exist for both directions of
each:

  * a spelling used TWICE is an established choice and is never flagged - so
    the suite pins both that a once-used near miss fires and that a twice-used
    one does not;
  * the near-miss window is one slip for a model id, and two only for skill
    names of six characters or more - because on short names two edits turn one
    real word into another and every hit would be noise.

`_check_skills` is gated on `_skills_in_use`, and that gate is the whole
back-compat contract: a manifest that never touches the feature must get zero
new lines from it. `[]` alone is not evidence of use, because generators
initialize an empty list on every task.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_typos as M                        # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _manifest_rules as _rules                   # noqa: E402


def _plan(tasks, areas=None):
    """A manifest with one phase and the given task dicts."""
    meta = {"version": 2}
    if areas is not None:
        meta["areas"] = areas
    return {"meta": meta,
            "phases": [{"id": "P0", "title": "P", "status": "pending",
                        "area": "app", "tasks": tasks}]}


def _task(tid, **kw):
    t = {"id": tid, "title": tid, "status": "pending"}
    t.update(kw)
    return t


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the near-miss predicates ---
    check("mt1 a case-only difference is one slip",
          M._model_near_miss("Opus", "opus"))
    check("mt2 ...and so are substitution, insertion, deletion and an "
          "ADJACENT TRANSPOSITION - the four classic typo shapes",
          M._model_near_miss("opus", "opux")
          and M._model_near_miss("opus", "opuss")
          and M._model_near_miss("opus", "opu")
          and M._model_near_miss("opus", "opsu"))
    check("mt3 ...and two slips are NOT: the model detector caps at one, "
          "which is what keeps it off two models a project chose on purpose",
          not M._model_near_miss("opus", "opxy"))
    check("mt4 a value is never a near miss of itself, so an id used once "
          "cannot flag against its own spelling",
          not M._model_near_miss("opus", "opus"))

    check("mt5 `_skill_near_miss` allows TWO slips, but only when both names "
          "are 6+ characters", M._skill_near_miss("writing-python",
                                                  "writng-pythn"))
    # `css` -> `sass` is two edits between two real, different things, and it
    # is the fixture that separates the two versions: with the floor at 6 this
    # is False, with the floor lowered it is True. The module's own docstring
    # cites `web` -> `wasm` for this, which is actually distance 3 and so
    # cannot tell the two apart - a fixture that names the bug beats one that
    # merely quotes the comment.
    check("mt6 ...and refuses two slips on SHORT names, because on those a "
          "two-edit window turns one real name into another ('css' -> 'sass') "
          "and every hit would be noise",
          not M._skill_near_miss("css", "sass"))

    # --- the model detector ---
    f, w = M._check_model_typos(_plan([_task("P0.1", model="opus"),
                                       _task("P0.2", model="opus"),
                                       _task("P0.3", model="opuss")]))
    check("mt7 an id used ONCE beside one used often is flagged, and the "
          "warning names the established spelling",
          f == [] and len(w) == 1 and "'opuss'" in w[0] and "'opus'" in w[0],
          "f=%r w=%r" % (f, w))
    f, w = M._check_model_typos(_plan([_task("P0.1", model="opus"),
                                       _task("P0.2", model="opus"),
                                       _task("P0.3", model="opuss"),
                                       _task("P0.4", model="opuss")]))
    check("mt8 ...and a spelling used TWICE is an established choice: with "
          "both used twice nothing is flagged at all - the case that fails if "
          "the once-only gate is dropped and every near pair fires",
          f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_model_typos(_plan([_task("P0.1", model="opus")]))
    check("mt9 a clean single-model manifest has no neighbour to near-miss "
          "and stays silent", f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_model_typos(
        {"meta": {"version": 2,
                  "usage": {"pricing": {"sonnet": {}, "_note": {}}}},
         "phases": [{"id": "P0", "title": "P", "status": "pending",
                     "tasks": [_task("P0.1", model="sonnett")]}]})
    check("mt10 ...and a meta.usage.pricing key is the second source a "
          "once-used id is compared against, so a typo shows up on a "
          "single-task plan too",
          f == [] and len(w) == 1 and "a meta.usage.pricing key" in w[0],
          "f=%r w=%r" % (f, w))
    check("mt11 `_check_model_typos` returns an ALWAYS-empty findings list "
          "beside its warnings - the pair is the shape every direct child of "
          "validate() answers with, so a detector that grows a hard rule "
          "needs no new signature",
          M._check_model_typos(_plan([]))[0] == [])

    # --- the skills advisory, and its gate ---
    f, w = M._check_skills(_plan([_task("P0.1"), _task("P0.2")]))
    check("mt12 a manifest that never mentions skills gets ZERO lines - the "
          "back-compat contract, and the case that fails if the gate is "
          "removed", f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_skills(_plan([_task("P0.1", skills=[]),
                                  _task("P0.2", skills=[])]))
    check("mt13 ...and `skills: []` alone is NOT evidence of use: generators "
          "initialize an empty list on every task, so this must stay silent",
          f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_skills(_plan([_task("P0.1", skills=["writing-python"]),
                                  _task("P0.2")]))
    check("mt14 ...but once one task uses the feature, a sibling that "
          "resolves NOTHING is named, with the three exits spelled out",
          f == [] and len(w) == 1 and "P0.2" in w[0]
          and "\"skills\": null" in w[0], "f=%r w=%r" % (f, w))
    f, w = M._check_skills(_plan([_task("P0.1", skills=["writing-python"]),
                                  _task("P0.2", skills=None)]))
    check("mt15 ...and an explicit null is the opt-out that stops both the "
          "area fallback and this warning: 'none applies' is an answer",
          f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_skills(
        _plan([_task("P0.1", skills=["writing-python"]), _task("P0.2")],
              areas={"app": {"skills": ["writing-css"]}}))
    check("mt16 ...and an area's default skills resolve for a task that "
          "declares none, so registering defaults is the second exit and it "
          "actually works", f == [] and w == [], "f=%r w=%r" % (f, w))

    # --- the skill-name detector ---
    f, w = M._check_skill_typos(_plan([
        _task("P0.1", skills=["writing-python"]),
        _task("P0.2", skills=["writing-python"]),
        _task("P0.3", skills=["writng-python"])]))
    check("mt17 a skill name used once beside one used often is flagged, and "
          "the warning says a one-slip name names a skill that never loads",
          f == [] and len(w) == 1 and "'writng-python'" in w[0],
          "f=%r w=%r" % (f, w))
    f, w = M._check_skill_typos(_plan(
        [_task("P0.1", skills=["writng-python"])],
        areas={"app": {"skills": ["writing-python", "writing-python"]}}))
    check("mt18 ...and meta.areas defaults are the OTHER place a name is "
          "counted from, so the established spelling can live in the registry",
          f == [] and len(w) == 1 and "'writng-python'" in w[0],
          "f=%r w=%r" % (f, w))

    # --- the aliases ---
    _names = ("_model_near_miss", "_check_model_typos", "_skills_in_use",
              "_check_skills", "_skill_near_miss", "_check_skill_typos")
    _forked = [n for n in _names if getattr(_rules, n) is not getattr(M, n)]
    check("mt19 every detector `_manifest_rules` re-exports IS this module's "
          "function: %r" % (_forked,), _forked == [])
    check("mt20 ...and `_safe_list` here is `_manifest_vocab`'s object, not a "
          "second copy of the coercion that keeps a bare string from being "
          "walked per-character", M._safe_list is _vocab._safe_list)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_typos.py --selftest\n")
    raise SystemExit(2)
