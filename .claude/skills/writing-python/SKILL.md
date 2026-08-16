---
name: writing-python
description: How Python is written in this repo — free functions over classes, structured returns instead of mutated arguments, comprehensions, no module state, and the stdlib-only, annotation-free, Python 3.8 dialect the AST lints enforce. Covers modular structure and the import-layer rule, DRY without copying a helper into a second file, what makes a function testable from a `--selftest`, readability rules (guard clauses, named predicates, why-not-what docstrings), and the anti-patterns that have actually bitten here. Use when planning, writing, reading, reviewing or refactoring any `.py` under plugins/audit/, when adding a helper or a new script, when deciding where a function belongs, or when the same logic is about to exist in two places.
---

# Writing Python here

Not a general Python style guide. This repo bans things most guides mandate, and the bans are
read out of the AST rather than trusted — `_output.house_style_violations()` fails the build, it
does not warn. Everything below is either enforced or measured from the tree as it stands.

## The dialect, in one paragraph

Stdlib only. Python 3.8 floor. **No `typing`, no `dataclasses`, no annotations, no walrus, no
`from __future__`** — banned by AST, because hooks start on every tool call and the import and
parse cost is real. `%`-style formatting; there is not one f-string in the tree. Reach for
`os.path`, `json`, `re`, `subprocess` — not for a dependency.

3.8 also rules out things that read as ordinary today: no `X | Y` unions, no `match`, no
`dict1 | dict2` merge, no `list[str]`. `vermin -t=3.8-` catches these; it will not catch the
banned imports, which is why the AST lint exists alongside it.

## Free functions, structured returns

The measured shape of this codebase: **734 top-level functions against 6 classes**, 227
comprehensions, and **6 `global` statements in ~42,000 lines**. That is the pattern to keep.

- **Write a function, not a class.** A class here needs a reason you can say out loud — the six
  that exist are all genuine (a lock, a launcher). Grouping related functions is what a module
  prefix is for.
- **Return a new value; do not mutate an argument.** 181 functions return a dict or tuple. A
  function that edits the caller's dict in place and also returns it is two contracts and the
  caller will rely on the wrong one.
- **No module state.** Constants at module level are fine (52 of them, uppercase, frozen tables).
  Mutable module state that a function writes to is how two callers start disagreeing about the
  same run. Where a cache is genuinely needed the existing pattern is an explicit
  `_cache`/`cache=True` argument, not a hidden global.
- **Comprehensions over accumulate loops** when the result is a list or dict and the body is one
  expression. Past that, a named function reads better than a nested comprehension.
- **Push I/O to the edges.** A function that takes values and returns values can be tested by a
  `--selftest` case with no temp directory and no `git init`; one that reads a file and prints
  cannot. Split the read from the decision — `decide()` taking parsed input is the shape every
  hook already uses, and it is why their logic has cases at all.

## Where code lives

- **Name by role.** `_underscore.py` is an importable helper; `hyphen-name.py` is an entry point
  something invokes. The name is the contract.
- **Flat, one directory deep.** The CI glob and `_output.py`'s guard are non-recursive *by
  design*; a file in a subdirectory silently stops being tested.
- **Imports go down, never sideways or up.** `_deps.LAYERS` assigns every module a layer and
  `layer_violations()` fails an unplaced or wrongly-layered file **by name**. `hooks/` may import
  nothing from `scripts/` at all. If a new helper does not fit a layer, that is information about
  the design, not an obstacle to route around.
- **Section markers every 400 lines.** Past that a flat scroll stops being a map;
  `navigability_violations()` enforces it, and `ui_navigability_violations()` does the same for
  the front end.

## DRY, and the way it fails here

The rule is not "never repeat a line". It is **one fact, one home**.

- If two modules need the same logic, it belongs in a **lower layer** both can import — not
  copied into the second file, and not re-derived.
- **The cautionary tale is real and still in the tree**: the token formatter exists in Python and
  is hand-written again in each of the two front-end surfaces. Two of the three now disagree —
  `uTok(2.6)` rounds to `"3"` while `fmtTokens(2.6, 1)` truncates to `"2"` — and both carry a
  comment claiming to mirror the Python. A copy with a comment saying it is a copy is still a
  copy.
- When a value must exist in two languages, **pin the agreement with a case** rather than a
  comment. A claim that two implementations agree is testable; test it.
- Do not extract for its own sake. Two similar-looking blocks that answer different questions
  should stay apart — the wrong abstraction costs more than the duplication.

## Readability

- **Guard clauses over nesting.** Return early; do not build an arrow of `if`/`else`.
- **Name the predicate.** `if _is_ready(task):` beats an inlined three-term `and` chain, and the
  name is where the reasoning goes.
- **Module docstring says *why the file exists*, not what it does.** That is a hard rule here and
  the reason the tree is navigable at 42k lines.
- **Comment the non-obvious constraint, never the mechanism.** The house comments that earn their
  place read like postmortems: what broke, and what would break again. A comment restating the
  next line is noise.
- **No `*Utils`, `*Helper`, `*Manager`, `*Impl`.** Name a module for the thing it owns.
- Keep functions short enough to hold. 39 functions in the tree exceed McCabe 15 — that is the
  known debt, not the target.

## Anti-patterns and pitfalls

- **Mutable default arguments** (`def f(items=[])`) — the default is created once and shared.
  Use `None` and build inside.
- **`x = x or default` when `0`, `False` or `""` are meaningful.** Use
  `x if x is not None else default`. This is the single most common silent-corruption bug in code
  that reduces data to a number.
- **Bare `except:` or a broad `except Exception:` that returns a normal-shaped value.** Either
  recover meaningfully or make the failure visible. See `no-silent-pass`.
- **Iterating a `set` into serialized output** — the order varies per process and the real diff
  drowns in noise. Impose a total order first.
- **Catching an exception to skip an item, with no count and no name.** Silent skips are how a
  job reports success over half the work.
- **Reaching around the layer rule** by importing inside a function to dodge the lint. The lint
  reads the AST; more importantly, the layering is the design.
- **Adding a file without its four obligations** — `--selftest`, `safe_stdio()` first in
  `__main__`, a `_deps.LAYERS` entry, a `PLUGIN-BUILD-GUIDE.md` tree line and section. Three of
  the four fail CI by name.

## Testability

A `--selftest` is not an afterthought here; it is the test suite, and CI fails a file without
one. Design for it:

- a function whose inputs are arguments and whose output is a return value needs no fixture;
- where a fixture is unavoidable, build it in a `tempfile.mkdtemp()` and delete it in `finally` —
  never commit one;
- **new behaviour means new cases**, and a case is only trusted once it has been seen red.

`no-silent-pass` owns that discipline — mutate the fix, mutate it the other way too, count rather
than assert presence, and choose fixture values that tell the two versions apart.
