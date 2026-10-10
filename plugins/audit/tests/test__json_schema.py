#!/usr/bin/env python3
"""
The cases for `_json_schema.py` - the stdlib reader of the plan's JSON Schema.

Two directions for every keyword, because a reader has two wrong versions: one
that never rejects (the fault this module exists to close - the schema was
applied by nothing a verb runs), and one that rejects what the schema admits
(every plan this repository and its users hold would go red). Each keyword gets
an admitted value and a refused one, and the fixtures are picked where Python's
reading and ECMAScript's disagree, so a reader written the Python way fails.

The last cases are about the shipped schema itself: every keyword it uses must
be one this reader checks or may ignore, and a keyword it does not know is
reported, never passed.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402
import _json_schema as M                           # noqa: E402

SCHEMA_PATH = os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json")


def _kinds(node, value, doc=None):
    """The reason kinds `check` gives `value` against `node`."""
    reasons, _unread = M.check(node, value, doc if doc is not None else {}, "x")
    return [k for k, _t in reasons]


# Each row: keyword, schema node, a value it admits, a value it refuses, and
# the reason kind the refusal must carry.
KEYWORD_ROWS = (
    ("type", {"type": "string"}, "a", None, "type"),
    ("type integer", {"type": "integer"}, 7.0, 7.5, "type"),
    ("type number", {"type": "number"}, 7, True, "type"),
    ("type union", {"type": ["string", "null"]}, None, 3, "type"),
    ("enum", {"enum": ["a", 1]}, 1.0, "b", "enum"),
    ("const", {"const": 1}, 1.0, True, "const"),
    ("pattern", {"pattern": "^BUG-\\d+$"}, "BUG-12", u"BUG-٣", "pattern"),
    ("pattern $", {"pattern": "^a$"}, "a", "a\n", "pattern"),
    ("pattern \\w", {"pattern": "^\\w+$"}, "ab_9", u"é", "pattern"),
    ("minLength", {"minLength": 1}, "a", "", "min-length"),
    ("maxLength", {"maxLength": 1}, "a", "ab", "max-length"),
    ("minimum", {"minimum": 1}, 1, 0, "minimum"),
    ("maximum", {"maximum": 1}, 1, 2, "maximum"),
    ("exclusiveMinimum", {"exclusiveMinimum": 0}, 0.5, 0, "exclusive-minimum"),
    ("exclusiveMaximum", {"exclusiveMaximum": 1}, 0.5, 1, "exclusive-maximum"),
    ("required", {"required": ["a"]}, {"a": 1}, {"b": 1}, "required"),
    ("properties", {"properties": {"a": {"type": "string"}}}, {"a": "s"},
     {"a": 1}, "type"),
    ("additionalProperties false", {"properties": {"a": {}},
                                    "additionalProperties": False},
     {"a": 1}, {"a": 1, "b": 2}, "additional"),
    ("additionalProperties schema", {"additionalProperties": {"type": "integer"}},
     {"k": 1}, {"k": "s"}, "type"),
    ("items", {"items": {"type": "string"}}, ["a"], ["a", 2], "type"),
    ("oneOf", {"oneOf": [{"type": "string"}, {"type": "integer"}]}, 3, None,
     "arms"),
    ("oneOf ambiguous", {"oneOf": [{"type": "number"}, {"type": "integer"}]},
     1.5, 1, "arms"),
    ("anyOf", {"anyOf": [{"type": "string"}, {"type": "null"}]}, None, 2, "arms"),
    ("allOf", {"allOf": [{"type": "string"}, {"minLength": 2}]}, "ab", "a",
     "min-length"),
    ("$ref", {"$ref": "#/$defs/s"}, "a", 1, "type"),
    ("false schema", {"properties": {"a": False}}, {}, {"a": 1}, "false"),
)


def _cases(check):
    doc_for_ref = {"$defs": {"s": {"type": "string"}}}
    faults = {}
    for name, node, ok, bad, kind in KEYWORD_ROWS:
        doc = doc_for_ref if "$ref" in node else node
        got_ok, got_bad = _kinds(node, ok, doc), _kinds(node, bad, doc)
        if got_ok or got_bad != [kind]:
            faults[name] = (got_ok, got_bad)
    check("js1 RED-FIRST: every supported keyword admits its admitted value with "
          "no reason and refuses its refused one with exactly one reason of its "
          "own kind - fixtures picked where Python and ECMAScript disagree "
          "(7.0 is an integer, True is no number, a non-ASCII digit is no \\d, "
          "a trailing newline is not before `$`): %r" % (faults,),
          faults == {} and len(KEYWORD_ROWS) > 20, faults)
    covered = set()
    for _n, node, _o, _b, _k in KEYWORD_ROWS:
        covered |= set(node)
    check("js2 ...and the rows exercise EVERY keyword SUPPORTED names, so one "
          "added to the set without a row is named here: %r"
          % (sorted(M.SUPPORTED - covered),), M.SUPPORTED <= covered)

    # An unsupported keyword is reported, never passed.
    reasons, unread = M.check({"type": "array", "uniqueItems": True}, [1, 1],
                              {}, "x")
    check("js3 an unsupported keyword is returned as UNREAD, never taken as a "
          "pass: %r" % ((reasons, unread),),
          reasons == [] and unread == set(["uniqueItems"]))
    reasons, unread = M.check({"type": "string", "description": "d",
                               "title": "t", "$comment": "c"}, "s", {}, "x")
    check("js4 ALLOW: annotations are not constraints, and are not reported as "
          "unread: %r" % ((reasons, unread),), reasons == [] and unread == set())
    reasons, unread = M.check({"pattern": "("}, "s", {}, "x")
    check("js5 a pattern that will not compile is an unread `pattern`, never a "
          "raise and never a pass: %r" % ((reasons, unread),),
          reasons == [] and unread == set(["pattern"]))
    reasons, unread = M.check({"$ref": "#/$defs/nope"}, "s", {}, "x")
    check("js6 a $ref that names nothing is unread, never a pass: %r"
          % ((reasons, unread),), reasons == [] and len(unread) == 1)

    # ECMAScript's \s stays Unicode-wide: the earlier re.ASCII reading narrowed
    # it along with \d.
    check("js7 \\s keeps Unicode whitespace (a no-break space), as ECMAScript's "
          "`u` flag reads it, while \\d stays ASCII",
          M.ecma_pattern("^\\s$").search(u" ") is not None
          and M.ecma_pattern("^\\d$").search(u"٣") is None
          and M.ecma_pattern("^[\\d-]+$").search("1-2") is not None
          and M.ecma_pattern("^\\D$").search("a") is not None)

    # Paths: the document root is the empty path, children are dotted.
    reasons, _u = M.check({"properties": {"phases": {"items": {
        "required": ["id"]}}}}, {"phases": [{}]}, {}, "")
    check("js8 a reason names the path from the document root, dotted and "
          "indexed: %r" % (reasons,),
          reasons == [("required", "phases[0].id is required by the schema")])

    # The shipped schema.
    doc = M.load_document(SCHEMA_PATH)
    check("js9 BUILD-TIME: every keyword the shipped schema uses is one this "
          "reader checks or may ignore: %r" % (M.unsupported(doc),),
          M.unsupported(doc) == [] and "additionalProperties" in M.keywords(doc))
    doctored = copy.deepcopy(doc)
    doctored["$defs"]["task"]["properties"]["title"]["maxItems"] = 2
    check("js10 ...and a keyword the schema gains is named by that walk, on a "
          "property behind a $def: %r" % (M.unsupported(doctored),),
          M.unsupported(doctored) == ["maxItems"])

    root = tempfile.mkdtemp(prefix="json-schema-")
    try:
        loads = {}
        for name, body in (("list", "[1]"),
                           ("dangling", json.dumps({"$ref": "#/$defs/x"})),
                           ("unparsable", "{ nope"),
                           ("good", json.dumps({"type": "object"}))):
            path = os.path.join(root, name + ".json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            try:
                loads[name] = ("ok", M.load_document(path))
            except (OSError, ValueError) as exc:
                loads[name] = ("refused", str(exc))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    check("js11 a schema file that parses to a non-object, or holds a $ref "
          "naming nothing, is REFUSED at load like an unparsable one - never "
          "loaded as a schema that checks nothing; an object loads: %r" % (loads,),
          [loads[n][0] for n in ("list", "dangling", "unparsable", "good")]
          == ["refused", "refused", "refused", "ok"]
          and "not a schema object" in loads["list"][1]
          and "#/$defs/x" in loads["dangling"][1])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__json_schema.py --selftest\n")
    raise SystemExit(2)
