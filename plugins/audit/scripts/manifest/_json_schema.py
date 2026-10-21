#!/usr/bin/env python3
"""
JSON Schema, read the way `ajv` reads `schema/audit-plan.schema.json`, with the
stdlib alone.

WHY THIS EXISTS. The published schema was applied by exactly one thing - CI's
`ajv` step over three committed plans - while every verb a user runs revalidates
through `validate-manifest`'s rules, which typed bug values and nothing else. So
a verb could write a plan the schema refuses and nothing local said so. The
answer is not a dependency (a guard that needs `pip install` is off on most
machines) but a reader for the keywords this schema is written in, and an honest
word for every keyword it is not.

WHAT IT READS. `SUPPORTED` is the set of constraint keywords `check()`
interprets; `ANNOTATIONS` is the set it may ignore because they constrain
nothing. Any OTHER keyword met on the way is returned in `unread`, never taken
as a pass - the caller says the value was not verified against it. The build
holds the shipped schema to `SUPPORTED` (`tests/test__json_schema.py`), so a
keyword the schema gains is a red build here before it is a warning at a user's
site.

THE DIALECT, where Python and ECMAScript differ and the schema can tell:
  * `integer` admits an integral float (`7.0`), as draft 2020-12 says;
  * a boolean is never a number, although Python's `bool` is an `int`;
  * `enum`/`const` compare numbers by value (`1.0` equals `1`);
  * a `pattern` is ECMAScript with the `u` flag: `\\d` and `\\w` are ASCII, and a
    trailing `$` is the end of the string, not of a last line. A pattern this
    reader cannot compile is returned as an unread `pattern`, never raised.

Pure: parsed JSON in, `(findings, unread)` out (`check_findings`), each finding
coded `schema.<kind>`; `check` gives the same answer as `(kind, text)` pairs. A
caller re-codes a reason under its own rule, because one reader serves two
callers whose findings must stay apart (`_manifest_crossrefs`' bug values and
`_manifest_rules`' whole plan).

This module carries no `--selftest` of its own; its cases live in
`tests/test__json_schema.py` - see `tests/_harness.py`.
"""
import json
import os
import re
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

SUPPORTED = frozenset(["$ref", "type", "enum", "const", "items", "oneOf",
                       "anyOf", "allOf", "pattern", "properties", "required",
                       "additionalProperties", "minLength", "maxLength",
                       "minimum", "maximum", "exclusiveMinimum",
                       "exclusiveMaximum"])
ANNOTATIONS = frozenset(["description", "title", "default", "examples",
                         "$comment", "deprecated", "readOnly", "writeOnly",
                         "$id", "$schema", "$defs", "definitions"])
# A `$ref` chain longer than this is a loop, not a schema.
MAX_DEPTH = 32
_JSON_TYPE_NAMES = ((bool, "boolean"), (int, "integer"), (float, "number"),
                    (str, "string"), (list, "array"), (dict, "object"))
# The exact-type lookup `json_type` tries first: a large plan meets the type
# question once per schema node, so a dict hit beats a walk of isinstance calls.
_EXACT_TYPE = dict([(type(None), "null")] + list(_JSON_TYPE_NAMES))


# --- loading ----------------------------------------------------------------------
def resolve(ref, doc):
    """The schema object a local `$ref` names, or None when it names nothing."""
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    target = doc
    for part in [p for p in ref[1:].split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        target = target.get(part) if isinstance(target, dict) else None
    return target if isinstance(target, (dict, bool)) else None


def unresolved_refs(doc):
    """Every `$ref` in `doc` that names nothing, sorted - a schema holding one
    would read the value under it as checked when nothing was."""
    out = set()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref is not None and resolve(ref, doc) is None:
                out.add(str(ref))
            for key, val in node.items():
                if key not in ("enum", "const", "default", "examples"):
                    walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)
    walk(doc)
    return sorted(out)


def load_document(path):
    """The schema at `path`, parsed. Raises OSError or ValueError, and ValueError
    too for a document that parses but cannot be a schema to check against: a
    non-object, or one holding a `$ref` that names nothing."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError("%s holds %s, not a schema object"
                         % (path, json_type(doc)))
    dangling = unresolved_refs(doc)
    if dangling:
        raise ValueError("%s holds a $ref that names nothing: %s"
                         % (path, ", ".join(dangling)))
    return doc


# --- the type system -----------------------------------------------------------------
def json_type(value):
    """The JSON type name of a parsed value (`null` for None)."""
    name = _EXACT_TYPE.get(type(value))
    if name is not None:
        return name
    for pytype, name in _JSON_TYPE_NAMES:
        if isinstance(value, pytype):
            return name
    return type(value).__name__


def type_admits(name, value, got=None):
    """Whether the JSON Schema type `name` admits `value`; `got` is the value's
    JSON type when the caller has already named it."""
    got = json_type(value) if got is None else got
    if name == "number":
        return got in ("integer", "number")
    if name == "integer" and got == "number":
        return float(value).is_integer()
    return got == name


def _is_number(value):
    return json_type(value) in ("integer", "number")


def _value_class(value):
    """JSON Schema compares numbers by value (1.0 equals 1); a boolean is never
    a number, although Python's bool is an int."""
    got = json_type(value)
    return "number" if got == "integer" else got


def json_equal(a, b):
    """Equality as JSON Schema defines it for `enum` and `const`."""
    if _value_class(a) != _value_class(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return (sorted(a) == sorted(b)
                and all(json_equal(a[k], b[k]) for k in a))
    return a == b


def parts(node, doc, depth=0):
    """`node` as the list of schema objects that must ALL hold: a `$ref` is
    followed and its siblings kept as a second part, since draft 2020-12 reads
    them as a conjunction. A ref that cannot be followed becomes a part carrying
    a keyword outside SUPPORTED, so it is reported, never passed."""
    if not isinstance(node, dict) or "$ref" not in node:
        return [node]
    ref = node["$ref"]
    siblings = dict((k, v) for k, v in node.items() if k != "$ref")
    target = resolve(ref, doc) if depth < MAX_DEPTH else None
    resolved = ([{"$ref (unresolved)": ref}] if target is None
                else parts(target, doc, depth + 1))
    return resolved + ([siblings] if siblings else [])


def admitted(node, doc, depth=0):
    """The words for what `node` admits, e.g. ['string', 'array of string']."""
    words = []
    if depth > MAX_DEPTH:
        return words
    for part in parts(node, doc):
        if not isinstance(part, dict):
            continue
        names = part.get("type")
        names = [names] if isinstance(names, str) else list(names or [])
        items = part.get("items")
        for name in names:
            if name == "array" and isinstance(items, dict):
                name = "array of %s" % "/".join(admitted(items, doc, depth + 1))
            words.append(name)
        if "enum" in part:
            words.append("one of %s" % json.dumps(part["enum"]))
        if "const" in part:
            words.append("exactly %s" % json.dumps(part["const"]))
        for combiner in ("oneOf", "anyOf"):
            for arm in part.get(combiner) or []:
                words.extend(admitted(arm, doc, depth + 1))
    return words


def _arm_types(node, doc):
    names = []
    for part in parts(node, doc):
        got = part.get("type") if isinstance(part, dict) else None
        names.extend([got] if isinstance(got, str) else list(got or []))
    return names


# --- patterns ------------------------------------------------------------------------
# What `\d` and `\w` mean under ECMAScript's `u` flag: ASCII only. Python's
# Unicode defaults read both wider, and `re.ASCII` - the earlier answer - would
# narrow `\s` with them, which ECMAScript keeps Unicode-wide.
_ECMA_CLASSES = {"d": "0-9", "w": "A-Za-z0-9_"}


def ecma_pattern(pattern):
    """`pattern` compiled to read as ajv reads it (`new RegExp(p, 'u')`) on the
    constructs that differ: `\\d`/`\\w` (and their negations) are ASCII, and a
    trailing unescaped `$` is the end of the string. Raises `re.error` for a
    pattern Python cannot compile, or a negated class escape inside a set,
    which has no faithful spelling here."""
    out, i, in_set = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            body = _ECMA_CLASSES.get(nxt.lower())
            if body is None:
                out.append(pattern[i:i + 2])
            elif in_set and nxt.isupper():
                raise re.error("negated class escape \\%s inside a set" % nxt)
            elif in_set:
                out.append(body)
            else:
                out.append(("[^%s]" if nxt.isupper() else "[%s]") % body)
            i += 2
            continue
        if ch == "[" and not in_set:
            in_set = True
        elif ch == "]" and in_set:
            in_set = False
        out.append(ch)
        i += 1
    text = "".join(out)
    if text.endswith("$"):
        head = text[:-1]
        escapes = len(head) - len(head.rstrip("\\"))
        if escapes % 2 == 0:
            text = head + r"\Z"
    return re.compile(text)


# --- the check -----------------------------------------------------------------------
def child(where, key):
    """The path of `key` under `where`; the document root is the empty path."""
    return "%s.%s" % (where, key) if where else str(key)


# The rule code every reason carries; `kind_of` reads the kind back off it.
CODE_PREFIX = "schema."


def kind_of(reason):
    """The kind of a reason `check_findings` returned - `type`, `enum`, ..."""
    return str(_output.finding_code(reason) or "")[len(CODE_PREFIX):]


def check(node, value, doc, where, depth=0):
    """(reasons, unread) for `value` against the schema `node`, each reason a
    `(kind, text)` pair - the shape `_manifest_crossrefs` codes bug values from.
    `check_findings` is the same answer as coded findings."""
    found, unread = check_findings(node, value, doc, where, depth)
    return _as_pairs(found), unread


def _as_pairs(found):
    return [(kind_of(x), str(x)) for x in found]


def check_findings(node, value, doc, where, depth=0):
    """(findings, unread) for `value` against the schema `node`.

    Each finding names the path it is about and is coded `schema.<kind>`;
    `unread` is the set of constraint keywords met on the way that this reader
    does not interpret, or could not apply (an uncompilable pattern)."""
    findings, unread = [], set()
    for part in parts(node, doc, depth):
        r, u = _check_part(part, value, doc, where, depth)
        findings.extend(r)
        unread |= u
    return findings, unread


def _check_part(part, value, doc, where, depth):
    if part is True or part == {}:
        return [], set()
    if not isinstance(part, dict):
        return [_output.finding("schema.false", "%s: the schema admits no value "
                                "here" % (where or "the document",))], set()
    unread = set(part) - SUPPORTED - ANNOTATIONS
    findings = []
    findings.extend(_scalar_reasons(part, value, doc, where, unread))
    if "items" in part and isinstance(value, list):
        for i, item in enumerate(value):
            r, u = check_findings(part["items"], item, doc,
                                  "%s[%d]" % (where, i), depth + 1)
            findings.extend(r)
            unread |= u
    if isinstance(value, dict):
        r, u = _check_object(part, value, doc, where, depth)
        findings.extend(r)
        unread |= u
    for arm in part.get("allOf") or []:
        r, u = check_findings(arm, value, doc, where, depth + 1)
        findings.extend(r)
        unread |= u
    for combiner in ("oneOf", "anyOf"):
        if combiner in part:
            r, u = _check_arms(part, combiner, value, doc, where, depth)
            findings.extend(r)
            unread |= u
    return findings, unread


# Each bound keyword, the reason kind it raises, and the comparison that
# breaks it - a table rather than four branches, read only for a value of the
# keyword's own type.
_LENGTH_BOUNDS = (("minLength", "min-length", lambda got, n: got < n),
                  ("maxLength", "max-length", lambda got, n: got > n))
_NUMBER_BOUNDS = (("minimum", "minimum", lambda got, n: got < n),
                  ("maximum", "maximum", lambda got, n: got > n),
                  ("exclusiveMinimum", "exclusive-minimum", lambda got, n: got <= n),
                  ("exclusiveMaximum", "exclusive-maximum", lambda got, n: got >= n))


def _scalar_reasons(part, value, doc, where, unread):
    """The keywords that judge `value` itself, not anything inside it.

    Asked once per schema node a plan value meets, which on a large plan is
    tens of thousands of times per validation - so the value's type is named
    once and each keyword family is entered only when the node carries it."""
    found = []
    got = json_type(value)
    names = part.get("type")
    if names is not None:
        names = [names] if isinstance(names, str) else list(names)
        if not any(type_admits(n, value, got) for n in names):
            found.append(_output.finding(
                "schema.type", "%s is %s, the schema admits %s"
                % (where, got, ", ".join(admitted(part, doc)))))
    if "enum" in part and not any(json_equal(value, v) for v in part["enum"]):
        found.append(_output.finding(
            "schema.enum", "%s %s is not one of %s"
            % (where, json.dumps(value), json.dumps(part["enum"]))))
    if "const" in part and not json_equal(value, part["const"]):
        found.append(_output.finding(
            "schema.const", "%s %s is not the schema's const %s"
            % (where, json.dumps(value), json.dumps(part["const"]))))
    if got == "string":
        if "pattern" in part:
            try:
                matched = ecma_pattern(part["pattern"]).search(value)
            except (re.error, TypeError):
                unread.add("pattern")
            else:
                if not matched:
                    found.append(_output.finding(
                        "schema.pattern",
                        "%s %r does not match the schema's pattern %s"
                        % (where, value, part["pattern"])))
        for key, kind, bad in _LENGTH_BOUNDS:
            if key in part and bad(len(value), part[key]):
                found.append(_output.finding(
                    CODE_PREFIX + kind, "%s is %d character(s) long, the "
                    "schema's %s is %s" % (where, len(value), key, part[key])))
    elif got in ("integer", "number"):
        for key, kind, bad in _NUMBER_BOUNDS:
            if key in part and _is_number(part[key]) and bad(value, part[key]):
                found.append(_output.finding(
                    CODE_PREFIX + kind, "%s %s is outside the schema's %s %s"
                    % (where, json.dumps(value), key, part[key])))
    return found


def _check_object(part, value, doc, where, depth):
    findings, unread = [], set()
    props = part.get("properties") or {}
    for key in part.get("required") or []:
        if key not in value:
            findings.append(_output.finding(
                "schema.required", "%s is required by the schema"
                % (child(where, key),)))
    for key in sorted(value, key=str):
        if key in props:
            sub = props[key]
        elif "additionalProperties" in part:
            sub = part["additionalProperties"]
        else:
            continue
        if sub is True:
            continue
        if sub is False and key not in props:
            findings.append(_output.finding(
                "schema.additional", "%s is not a property the schema allows"
                % (child(where, key),)))
            continue
        r, u = check_findings(sub, value[key], doc, child(where, key), depth + 1)
        findings.extend(r)
        unread |= u
    return findings, unread


def _check_arms(part, combiner, value, doc, where, depth):
    findings, unread = [], set()
    verdicts = [check_findings(arm, value, doc, where, depth + 1)
                for arm in part[combiner]]
    for _r, u in verdicts:
        unread |= u
    passing = [not r for r, _u in verdicts].count(True)
    # An arm of the value's own type that still failed says WHY (a list holding
    # a number); otherwise the sentence names what is admitted.
    same_type = [r for (r, _u), arm in zip(verdicts, part[combiner])
                 if any(type_admits(n, value) for n in _arm_types(arm, doc))]
    if passing == 0 and len(same_type) == 1:
        findings.extend(same_type[0])
    elif passing == 0 or (combiner == "oneOf" and passing > 1):
        findings.append(_output.finding(
            "schema.arms", "%s is %s, the schema admits %s%s"
            % (where, json_type(value),
               ", ".join(admitted(part, doc)) or "nothing",
               " - and it matches more than one of them"
               if passing > 1 else "")))
    return findings, unread


def keywords(doc):
    """Every keyword name the schema document uses in a schema position, sorted:
    data (`enum` values, `properties` names) is not walked as schema."""
    out = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            out.add(key)
            if key in ("properties", "$defs", "definitions", "patternProperties",
                       "dependentSchemas") and isinstance(val, dict):
                for sub in val.values():
                    walk(sub)
            elif key in ("oneOf", "anyOf", "allOf", "prefixItems") \
                    and isinstance(val, list):
                for sub in val:
                    walk(sub)
            elif isinstance(val, dict) and key not in ("const", "default"):
                walk(val)
    walk(doc)
    return sorted(out)


def unsupported(doc):
    """The keywords `doc` uses that this reader neither checks nor may ignore."""
    return [k for k in keywords(doc) if k not in SUPPORTED and k not in ANNOTATIONS]


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
