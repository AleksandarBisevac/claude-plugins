#!/usr/bin/env python3
"""The newest published tag must have a GitHub Release, and Latest must name it.

WHY THIS EXISTS (F222). The Releases page had drifted until it presented an old
version as Latest while the README told readers to `curl` from a much newer tag.
Nothing was wrong with the tags: every release this project has cut carries an
annotated `v<version>` tag, pushed, never moved. What was missing was the OTHER
published surface. A tag is a git object; a Release is a page GitHub shows to
anybody who opens the repository, and until this check existed nothing in the
release procedure created one, so the page drifted a little further with every
release and no gate could see it.

THE SYMPTOM WAS CLOSED BY HAND AND THE MECHANISM WAS NOT, which is the reason a
check rather than a note. Backfilling the missing Releases fixes the page once;
only something that runs at release time keeps it fixed. The decision recorded
in `CONTRIBUTING.md`'s Release rule is that a Release is part of cutting one --
this is the half that notices when it was skipped.

IT ASKS A REMOTE, WHICH NO OTHER GATE HERE DOES, and that single fact decides
its shape:

  IT IS A RELEASE-SET GATE, NOT A PER-COMMIT ONE. `tools/verify.sh --release`
  runs it; a plain run does not, and `.github/workflows/ci.yml` does not. A
  gate that needs the network on every push is a gate that goes red for reasons
  that have nothing to do with the change under it, and a repository's CI has no
  business calling GitHub's API once per commit to learn something that changes
  once per release.

  "COULD NOT ASK" IS NOT "CLEAN". This is `check-committed-pii.py`'s rule, and
  the reason is the same one: a run that cleared nothing must not print what a
  run that found nothing prints. No `gh`, no authentication, no network, a rate
  limit, an origin that is not a GitHub remote -- each is a NAMED refusal with a
  non-zero exit, and an unrecognised failure is a refusal too (`gh-unclassified`)
  rather than a fall-through to the clean line.

  IT IS RUNNABLE OFFLINE AND HONEST ABOUT IT. Run it on a plane and it says
  which question it could not put and why, which is the whole of what it can
  truthfully say there.

WHAT COUNTS AS THE NEWEST TAG, and why the answer comes off the REMOTE. The
domain is tags that have been PUBLISHED, because only a published tag can have a
Release. This project's own rule says a local tag on a commit CI then failed is
"a release that never happened" and is deleted unpushed -- so a local tag list
would report such a tag as missing a Release, which is a finding about nothing.
`git ls-remote --tags origin` is the question that matches the claim.

AND HIGHEST VERSION, NOT MOST RECENTLY CREATED. `ls-remote` carries no dates, so
creation order is not available from the source the domain comes from; version
order is, it is total over the tags this project cuts, and it is the order the
README's `curl` pins and the changelog already read in.

WHAT IT DOES NOT CHECK, said rather than implied. It does not read the Release's
BODY. The backfilled notes were derived from `CHANGELOG.md`, and comparing them
would be a second generator with a second set of failure modes; the claim here is
that the page exists and points at the right version, which is the claim that was
false. A draft Release IS a finding, because a draft is not a published page and
the drift this exists for is a page a reader sees.

Exit codes: 0 clean - 1 a finding or a refusal - 2 usage error.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)

GH_BIN = "gh"
ORIGIN = "origin"

USAGE = "usage: check-release-published.py [--repo <path>] [--selftest]\n"


# --- the vocabulary -----------------------------------------------------------
# EVERY NAME A RUN CAN PRINT, with the sentence a reader gets for it. Split in two
# because the halves mean different things and a reader must not have to guess
# which they are holding: a FINDING is an answer GitHub gave that is wrong, a
# REFUSAL is a question that could not be put at all. Collapsing them would let
# "the API was unreachable" read as "the Release is missing", which sends somebody
# to publish a Release that is already there.
FINDINGS = {
    "no-release-for-tag": ("the newest published tag has no GitHub Release, so "
                           "the Releases page does not know this version exists"),
    "release-is-draft": ("the newest published tag's Release is a DRAFT, which is "
                         "not a page anybody but a maintainer can see"),
    "no-latest-release": ("this repository publishes tags and has no Release at "
                          "all marked Latest"),
    "latest-is-not-newest": ("Latest names an older version than the newest "
                             "published tag - which is what a reader lands on, "
                             "and what the README's fetch pins then contradict"),
}

REFUSALS = {
    "gh-unavailable": ("`gh` is not on PATH, so GitHub was never asked. Install "
                       "the GitHub CLI or run this where it is available"),
    "gh-unauthenticated": ("`gh` is installed and not authenticated, so GitHub "
                           "answered nothing. `gh auth login`, or set GH_TOKEN"),
    "github-unreachable": ("GitHub could not be reached, so the run cleared "
                           "nothing. This is the offline answer and it is the "
                           "honest one"),
    "github-rate-limited": ("GitHub refused the request for rate limiting, so "
                            "the questions went unanswered. Wait and re-run"),
    "github-refused": ("GitHub refused the request, so the questions went "
                       "unanswered. A token without permission to read this "
                       "repository's releases answers this way"),
    "gh-unclassified": ("`gh` failed in a way this check does not recognise. It "
                        "is reported as a refusal rather than passed over, "
                        "because a failure nobody classified cleared nothing"),
    "unreadable-payload": ("GitHub answered and the answer would not parse as "
                           "JSON, so nothing could be read out of it"),
    "remote-unknown": ("`%s` is not a GitHub remote this check can address, so "
                       "there is no Releases page to ask about" % (ORIGIN,)),
    "remote-tags-unavailable": ("the remote could not be asked what tags it "
                                "carries, so the domain is unknown and nothing "
                                "was checked"),
    "no-published-tags": ("the remote carries no `v<semver>` tag, so this run "
                          "cleared NOTHING - check the remote before reading "
                          "anything into it"),
}


def is_refusal(status):
    """True when `status` names a question that could not be put.

    A PREDICATE AND NOT A COMPARISON AT EACH SITE. `status != "ok"` is the shape
    that swallows `absent`, which is an ANSWER, and every caller would have to
    remember that on its own.
    """
    return status in REFUSALS


# --- asking git ---------------------------------------------------------------
def git_reader(root=None):
    """A callable `(args) -> (stdout, returncode)` bound to one working tree.

    INJECTED RATHER THAN CALLED DIRECTLY so the cases below drive `repo_slug()`
    and `published_tags()` over recorded git output. Every refusal branch is then
    exercised without a network and without a fixture repository per case -- and
    the impure reader still gets its own case, pointed at a directory that is not
    a repository at all.
    """
    cwd = root or REPO

    def read(args):
        try:
            proc = subprocess.Popen(["git"] + list(args), cwd=cwd,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            out, _err = proc.communicate()
        except OSError:
            return "", 127
        return out.decode("utf-8", "replace"), proc.returncode

    return read


_SLUG_RE = re.compile(
    r"github\.com[:/]+([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/*\s*$")


def slug_from_url(url):
    """`owner/name` for a GitHub remote URL, or None. Pure.

    Both spellings, because both are in use here and a check that read only one
    would refuse on a machine cloned the other way: `https://github.com/o/n.git`
    and `git@github.com:o/n`.
    """
    match = _SLUG_RE.search(url or "")
    if match is None:
        return None
    return "%s/%s" % (match.group(1), match.group(2))


def repo_slug(git):
    """`(slug, status)` for the tree `git` reads."""
    out, code = git(["remote", "get-url", ORIGIN])
    if code != 0:
        return None, "remote-unknown"
    slug = slug_from_url(out.strip())
    if slug is None:
        return None, "remote-unknown"
    return slug, "ok"


_TAG_REF = re.compile(r"refs/tags/(v\d+\.\d+\.\d+)(?:\^\{\})?\s*$")


def tags_from_ls_remote(text):
    """Every `v<semver>` tag named in `ls-remote --tags` output. Pure.

    DEDUPED, because an annotated tag arrives twice: once as the tag object and
    once as the `^{}` line that dereferences it to a commit. A count taken off the
    raw lines would be about git's wire format rather than about releases.
    """
    found = set()
    for line in (text or "").split("\n"):
        match = _TAG_REF.search(line)
        if match is not None:
            found.add(match.group(1))
    return sorted(found)


def version_key(tag):
    """`(major, minor, patch)` for a `v<semver>` tag. Pure.

    Numeric, not lexical: `v0.9.0` sorts above `v0.28.0` as text, and reading the
    Releases page against a tag chosen that way would have reproduced F222's
    symptom inside the check written to catch it.
    """
    parts = tag[1:].split(".")
    return tuple(int(p) for p in parts)


def newest_tag(tags):
    """The highest version among `tags`, or None for an empty list. Pure."""
    if not tags:
        return None
    return max(tags, key=version_key)


def published_tags(git):
    """`(tags, status)` -- the version tags the REMOTE carries."""
    out, code = git(["ls-remote", "--tags", ORIGIN])
    if code != 0:
        return [], "remote-tags-unavailable"
    tags = tags_from_ls_remote(out)
    if not tags:
        return [], "no-published-tags"
    return tags, "ok"


# --- asking GitHub ------------------------------------------------------------
_HTTP_RE = re.compile(r"\(HTTP (\d{3})\)")


def gh_failure_status(code, err):
    """The status name for a failed `gh api` run. Never None.

    THE ONE NON-REFUSAL IT CAN RETURN IS `absent`: HTTP 404 is GitHub ANSWERING
    that the thing asked about is not there, which is exactly what this check
    wants to know about a tag with no Release. Everything else is a refusal, and
    the last line is `gh-unclassified` rather than a fall-through -- a failure
    shape nobody has met yet must not be the one that returns the clean answer.

    PURE, over the pair a process exit hands back, so each branch below is driven
    from the strings `gh` really prints. Those were read off the tool rather than
    remembered: an unauthenticated `gh` exits 4 and names `gh auth login`, an
    unreachable host exits 1 saying `error connecting to`, and an HTTP status is
    rendered `(HTTP nnn)` on stderr with the body still on stdout.
    """
    text = err or ""
    low = text.lower()
    match = _HTTP_RE.search(text)
    if match is not None:
        status = int(match.group(1))
        if status == 404:
            return "absent"
        if status == 401:
            return "gh-unauthenticated"
        if status == 429:
            return "github-rate-limited"
        if status == 403:
            # 403 IS THE AMBIGUOUS ONE AND 429 IS NOT. GitHub spends 403 on a
            # rate limit AND on a token without permission, so only the sentence
            # tells them apart and only one of them is worth waiting out; 429
            # means rate limiting by definition and needs no sentence.
            return ("github-rate-limited" if "rate limit" in low
                    else "github-refused")
        return "gh-unclassified"
    if code == 4 or "gh auth login" in low or "gh_token" in low:
        return "gh-unauthenticated"
    if "error connecting to" in low or "internet connection" in low:
        return "github-unreachable"
    return "gh-unclassified"


def gh_api(path, root=None):
    """`(payload, status)` for one READ-ONLY `gh api` call.

    Read-only by construction: no method is passed, and `gh api` defaults to GET.
    This check never creates, edits or deletes anything on the remote -- it is the
    thing that notices a Release was not created, not the thing that creates one.
    """
    if shutil.which(GH_BIN) is None:
        return None, "gh-unavailable"
    try:
        proc = subprocess.Popen(
            [GH_BIN, "api", "-H", "Accept: application/vnd.github+json", path],
            cwd=root or REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
    except OSError:
        # A `gh` that `which` found and the OS then refused to start is the same
        # answer as no `gh` at all: the question was not put.
        return None, "gh-unavailable"
    if proc.returncode != 0:
        return None, gh_failure_status(proc.returncode,
                                       err.decode("utf-8", "replace"))
    try:
        return json.loads(out.decode("utf-8", "replace")), "ok"
    except ValueError:
        return None, "unreadable-payload"


def api_reader(root=None):
    """A callable `(path) -> (payload, status)` bound to one working tree."""
    def read(path):
        return gh_api(path, root)
    return read


# --- the verdict --------------------------------------------------------------
def check(root=None, git=None, api=None):
    """What this run could establish about the newest published tag.

    Returns `{"slug", "tag", "latest", "asked", "rows"}`. `rows` is
    `[(name, detail)]` and an empty one is the only clean answer; `asked` is
    every API path the run actually put, which is the basis the clean line
    carries -- "no findings" from a run that asked nothing is the silent pass
    this whole file is shaped around.

    A REFUSAL STOPS THE RUN. When `gh` is missing the second question fails
    exactly as the first did, and printing both would send a reader looking for a
    second cause for one condition. `check-committed-pii.py` withholds its
    `domain-empty` row behind `domain-unavailable` for the same reason.
    """
    git = git_reader(root) if git is None else git
    api = api_reader(root) if api is None else api
    run = {"slug": None, "tag": None, "latest": None, "asked": [], "rows": []}

    slug, status = repo_slug(git)
    if is_refusal(status):
        run["rows"].append((status, ORIGIN))
        return run
    run["slug"] = slug

    tags, status = published_tags(git)
    if is_refusal(status):
        run["rows"].append((status, slug))
        return run
    tag = newest_tag(tags)
    run["tag"] = tag

    path = "repos/%s/releases/tags/%s" % (slug, tag)
    run["asked"].append(path)
    payload, status = api(path)
    if is_refusal(status):
        run["rows"].append((status, path))
        return run
    if status == "absent":
        run["rows"].append(("no-release-for-tag", tag))
    elif (payload or {}).get("draft"):
        run["rows"].append(("release-is-draft", tag))

    path = "repos/%s/releases/latest" % (slug,)
    run["asked"].append(path)
    payload, status = api(path)
    if is_refusal(status):
        run["rows"].append((status, path))
        return run
    if status == "absent":
        run["rows"].append(("no-latest-release", slug))
        return run
    latest = (payload or {}).get("tag_name")
    run["latest"] = latest
    if latest != tag:
        run["rows"].append(("latest-is-not-newest",
                            "Latest is %s, newest published tag is %s"
                            % (latest, tag)))
    return run


def report(run):
    """`(exit code, [lines])` for one `check()` result. PURE.

    Pure so the cases read exactly what an operator reads, rather than a
    paraphrase of it, and so every wording below is driven without a network.
    """
    lines = []
    for name, detail in run["rows"]:
        label = "REFUSED" if is_refusal(name) else "FOUND"
        lines.append("%s %s: %s (%s)"
                     % (label, name, FINDINGS.get(name) or REFUSALS[name],
                        detail))
    refused = [n for n, _d in run["rows"] if is_refusal(n)]
    if refused:
        lines.append("")
        lines.append("NOTHING WAS CHECKED. This run did not clear the Releases "
                     "page; it failed to ask. Re-run where the question can be "
                     "put before reading anything into a green release.")
        return 1, lines
    if run["rows"]:
        lines.append("")
        lines.append("The newest published tag is not the version a reader lands "
                     "on. CONTRIBUTING.md's Release rule has the step that "
                     "creates a Release for a tag that has been pushed.")
        return 1, lines
    return 0, ["OK: %s is the newest published tag, it has a Release, and Latest "
               "names it (%s, asked: %s)"
               % (run["tag"], run["slug"], ", ".join(run["asked"]))]


# --- command line -------------------------------------------------------------
def parse_argv(argv):
    """`(root, problem)` -- exactly one of the two is None."""
    rest = list(argv)
    root = None
    if "--repo" in rest:
        index = rest.index("--repo")
        if index + 1 >= len(rest):
            return None, "--repo needs a path"
        root = rest[index + 1]
        del rest[index:index + 2]
        if not os.path.isdir(root):
            return None, "--repo %r is not a directory" % (root,)
    if rest:
        return None, "unknown argument(s): %s" % (" ".join(rest),)
    return root, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    root, problem = parse_argv(argv)
    if problem is not None:
        sys.stderr.write("check-release-published.py: %s\n" % (problem,))
        sys.stderr.write(USAGE)
        return 2
    code, lines = report(check(root))
    for line in lines:
        sys.stdout.write(line + "\n")
    return code


# --- selftest -----------------------------------------------------------------
def _fake_git(url_out=None, url_code=0, tags_out="", tags_code=0):
    """A `git` reader that answers from recorded output instead of a process."""
    def read(args):
        if args[:1] == ["remote"]:
            return (url_out or ""), url_code
        return tags_out, tags_code
    return read


def _quietly(argv):
    """`main(argv)`'s exit code with its usage text kept off the suite's output.

    The refusal itself is the thing under test; a suite that prints the usage
    block into its own transcript makes a passing run look like a failing one.
    """
    held, sys.stderr = sys.stderr, io.StringIO()
    try:
        return main(argv)
    finally:
        sys.stderr = held


def _fake_api(table):
    """An `api` reader answering from `{path suffix: (payload, status)}`.

    Matched on a SUFFIX so a case names `releases/latest` rather than restating
    the owner and the repository, which are the parts a case is not about.
    """
    def read(path):
        for suffix, answer in table.items():
            if path.endswith(suffix):
                return answer
        return None, "absent"
    return read


_LS_REMOTE = ("aaaa\trefs/tags/v0.9.0\n"
              "bbbb\trefs/tags/v0.9.0^{}\n"
              "cccc\trefs/tags/v0.28.0\n"
              "dddd\trefs/tags/v0.28.0^{}\n"
              "eeee\trefs/tags/v1.8.0\n"
              "ffff\trefs/tags/v1.8.0^{}\n"
              "9999\trefs/tags/not-a-version\n")


def _cases(check_case):
    _git_ok = _fake_git(url_out="https://github.com/an-owner/a-repo.git\n",
                        tags_out=_LS_REMOTE)

    # --- the pure readers, which decide what the whole run is ABOUT
    check_case("r1 both remote spellings resolve to one slug, and a URL that is "
               "not GitHub resolves to nothing rather than to a guess: %r"
               % ([slug_from_url("https://github.com/an-owner/a-repo.git"),
                   slug_from_url("git@github.com:an-owner/a-repo"),
                   slug_from_url("https://gitlab.com/an-owner/a-repo.git")],),
               slug_from_url("https://github.com/an-owner/a-repo.git")
               == "an-owner/a-repo"
               and slug_from_url("git@github.com:an-owner/a-repo")
               == "an-owner/a-repo"
               and slug_from_url("https://gitlab.com/an-owner/a-repo.git") is None)

    _tags = tags_from_ls_remote(_LS_REMOTE)
    check_case("r2 an annotated tag arrives twice on the wire and is ONE tag "
               "here, and a tag that is not a version is not one at all - a "
               "domain read off the raw lines would be about git's wire format: "
               "%r" % (_tags,),
               _tags == ["v0.28.0", "v0.9.0", "v1.8.0"])

    check_case("r3 the newest tag is chosen NUMERICALLY. This is the case that "
               "fails on a lexical sort, which would pick v0.9.0 and reproduce "
               "F222's own symptom inside the check written to catch it: %r"
               % (newest_tag(_tags),),
               newest_tag(_tags) == "v1.8.0"
               and newest_tag(["v2.0.0", "v10.0.0"]) == "v10.0.0"
               and newest_tag([]) is None)

    # --- every way `gh` can fail, from the strings it really prints
    check_case("g1 an unauthenticated `gh` is a REFUSAL, by its exit code and by "
               "either sentence it prints - the exit alone would miss a wrapper "
               "that normalises it: %r"
               % (gh_failure_status(4, "To get started with GitHub CLI, please "
                                      "run:  gh auth login"),),
               gh_failure_status(4, "") == "gh-unauthenticated"
               and gh_failure_status(1, "please run:  gh auth login")
               == "gh-unauthenticated"
               and gh_failure_status(1, "populate the GH_TOKEN environment "
                                        "variable") == "gh-unauthenticated")

    check_case("g2 an unreachable host is a refusal and NOT a missing Release - "
               "offline is the state this check is most often run in, and the "
               "two answers have opposite repairs: %r"
               % (gh_failure_status(1, "error connecting to nonexistent.invalid\n"
                                       "check your internet connection or "
                                       "https://githubstatus.com"),),
               gh_failure_status(1, "error connecting to a.invalid")
               == "github-unreachable")

    check_case("g3 HTTP 404 is the one ANSWER a failed call carries: GitHub "
               "saying the Release is not there is the finding this check "
               "exists for, so it must not be classified as a refusal: %r"
               % (gh_failure_status(1, "gh: Not Found (HTTP 404)"),),
               gh_failure_status(1, "gh: Not Found (HTTP 404)") == "absent"
               and is_refusal("absent") is False)

    check_case("g4 a rate limit and a plain refusal are told apart by the "
               "sentence, not by the status alone - both arrive as 403 and only "
               "one is worth waiting out: %r"
               % ([gh_failure_status(1, "gh: API rate limit exceeded (HTTP 403)"),
                   gh_failure_status(1, "gh: Forbidden (HTTP 403)"),
                   gh_failure_status(1, "gh: Too Many Requests (HTTP 429)")],),
               gh_failure_status(1, "gh: API rate limit exceeded (HTTP 403)")
               == "github-rate-limited"
               and gh_failure_status(1, "gh: Forbidden (HTTP 403)")
               == "github-refused"
               and gh_failure_status(1, "gh: Too Many Requests (HTTP 429)")
               == "github-rate-limited")

    check_case("g5 a failure nobody has classified is a REFUSAL, never a pass. "
               "This is the branch that decides what an unknown `gh` version "
               "does to this gate, and the quiet answer would be the one that "
               "lets a release ship unpublished: %r"
               % (gh_failure_status(1, "gh: something new (HTTP 500)"),),
               gh_failure_status(1, "gh: something new (HTTP 500)")
               == "gh-unclassified"
               and gh_failure_status(1, "") == "gh-unclassified"
               and is_refusal("gh-unclassified") is True)

    check_case("g6 every name a run can print has a sentence, and no name is in "
               "both halves - a status that were both a finding and a refusal "
               "would render under whichever `report()` asked about first: %r"
               % (sorted(set(FINDINGS) & set(REFUSALS)),),
               not (set(FINDINGS) & set(REFUSALS))
               and all(len(v) > 40 for v in FINDINGS.values())
               and all(len(v) > 40 for v in REFUSALS.values()))

    # --- the verdict, over answers that are wrong in each way
    _clean = check(git=_git_ok, api=_fake_api({
        "releases/tags/v1.8.0": ({"draft": False}, "ok"),
        "releases/latest": ({"tag_name": "v1.8.0"}, "ok")}))
    _code, _lines = report(_clean)
    check_case("v1 a repository whose newest published tag has a Release that "
               "is Latest is clean, and the clean line carries the tag, the "
               "repository AND the paths it asked - a green with no basis is "
               "indistinguishable from a green that asked nothing: %r"
               % (_lines,),
               _code == 0 and _clean["rows"] == []
               and _clean["asked"] == ["repos/an-owner/a-repo/releases/tags/v1.8.0",
                                       "repos/an-owner/a-repo/releases/latest"]
               and "v1.8.0" in _lines[0] and "an-owner/a-repo" in _lines[0]
               and "releases/latest" in _lines[0])

    _f222 = check(git=_git_ok, api=_fake_api({
        "releases/tags/v1.8.0": (None, "absent"),
        "releases/latest": ({"tag_name": "v0.28.0"}, "ok")}))
    _code, _lines = report(_f222)
    check_case("v2 F222 ITSELF, as the page actually stood: the newest tag has "
               "no Release and Latest names a far older version. BOTH are "
               "reported, because publishing the missing Release and Latest "
               "moving are one repair only when nothing else drifted: %r"
               % (_f222["rows"],),
               _code == 1
               and _f222["rows"] == [("no-release-for-tag", "v1.8.0"),
                                     ("latest-is-not-newest",
                                      "Latest is v0.28.0, newest published tag "
                                      "is v1.8.0")]
               and "FOUND no-release-for-tag" in _lines[0]
               and "REFUSED" not in "\n".join(_lines))

    _draft = check(git=_git_ok, api=_fake_api({
        "releases/tags/v1.8.0": ({"draft": True}, "ok"),
        "releases/latest": ({"tag_name": "v0.28.0"}, "ok")}))
    check_case("v3 a DRAFT Release is a finding. It exists, so the tag lookup "
               "answers, and a check reading only presence would call the page "
               "published when no reader can see it: %r" % (_draft["rows"],),
               _draft["rows"][0] == ("release-is-draft", "v1.8.0"))

    _norel = check(git=_git_ok, api=_fake_api({
        "releases/tags/v1.8.0": ({"draft": False}, "ok"),
        "releases/latest": (None, "absent")}))
    check_case("v4 a repository with a Release for the tag and NOTHING marked "
               "Latest is named as that, rather than as the tag finding it is "
               "not: %r" % (_norel["rows"],),
               _norel["rows"] == [("no-latest-release", "an-owner/a-repo")])

    # --- and every way the run can fail to ask at all
    _blind = check(git=_git_ok, api=_fake_api({
        "releases/tags/v1.8.0": (None, "gh-unavailable"),
        "releases/latest": ({"tag_name": "v1.8.0"}, "ok")}))
    _code, _lines = report(_blind)
    check_case("v5 A REFUSAL IS NOT A CLEAN RUN and does not read as a missing "
               "Release: exit %d, the row is the refusal alone, and the closing "
               "line says nothing was checked rather than that the page is "
               "green: %r" % (_code, _blind["rows"]),
               _code == 1 and len(_blind["rows"]) == 1
               and _blind["rows"][0][0] == "gh-unavailable"
               and _lines[0].startswith("REFUSED gh-unavailable")
               and "NOTHING WAS CHECKED" in "\n".join(_lines)
               and not _lines[0].startswith("OK:"))

    check_case("v6 ...and it STOPS. With `gh` missing the second question fails "
               "exactly as the first did, and two rows for one condition sends a "
               "reader looking for a second cause: asked %r"
               % (_blind["asked"],),
               len(_blind["asked"]) == 1 and _blind["latest"] is None)

    _noremote = check(git=_fake_git(url_out="", url_code=128))
    _notags = check(git=_fake_git(url_out="https://github.com/an-owner/a-repo\n",
                                  tags_out="", tags_code=0))
    _dead = check(git=_fake_git(url_out="https://github.com/an-owner/a-repo\n",
                                tags_code=128))
    check_case("v7 the git half refuses in its own words, and a remote that "
               "carries NO version tag is a refusal rather than a vacuous pass - "
               "a domain that narrowed to nothing cleared nothing, which is "
               "check-committed-pii.py's `domain-empty` rule: %r"
               % ([_noremote["rows"], _notags["rows"], _dead["rows"]],),
               _noremote["rows"] == [("remote-unknown", ORIGIN)]
               and _notags["rows"] == [("no-published-tags", "an-owner/a-repo")]
               and _dead["rows"] == [("remote-tags-unavailable", "an-owner/a-repo")]
               and report(_notags)[0] == 1
               and _noremote["asked"] == [])

    # --- the impure readers, driven for real and offline
    _scratch = tempfile.mkdtemp(prefix="release-check-")
    try:
        _slug, _status = repo_slug(git_reader(_scratch))
        check_case("i1 the REAL git reader, pointed at a directory that is not a "
                   "repository: it refuses by name instead of raising, which is "
                   "what makes this runnable anywhere: %r" % (_status,),
                   _slug is None and _status == "remote-unknown")
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(_scratch)

    _path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = os.path.join(_scratch, "no-such-directory")
        _payload, _status = gh_api("repos/an-owner/a-repo/releases/latest")
    finally:
        os.environ["PATH"] = _path
    check_case("i2 the REAL GitHub reader with no `gh` reachable refuses without "
               "starting a process at all - the branch an operator on a machine "
               "without the CLI actually takes, and the one that must not raise "
               "its way out of the gate: %r" % (_status,),
               _payload is None and _status == "gh-unavailable"
               and is_refusal(_status) is True)

    check_case("i3 a wrong command line is a usage error and not a verdict about "
               "a repository: %r"
               % ([parse_argv(["--repo"])[1], parse_argv(["--wat"])[1]],),
               parse_argv([]) == (None, None)
               and parse_argv(["--repo", REPO])[0] == REPO
               and parse_argv(["--repo"])[1] is not None
               and parse_argv(["--wat"])[1] is not None
               and _quietly(["--wat"]) == 2)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main())
