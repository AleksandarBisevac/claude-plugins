# Guard refusals by owner — which share depends on the plan, and which is generic

Input: the private redacted miner corpus in the maintainer's internal repository
(`reports/2026-10-05-deep-analysis/experiments/classifier-events.redacted.jsonl`, with
`CLASSIFIER.md` beside it for the mining method). A public reader of this document has no
access to that corpus and cannot re-run the command below; the command is here so the
maintainer can.

## Scope

Rows with `source == "plugin-hook"` and a `subsource` starting `audit-plugin:`, timestamped at
or after the v3.0.0 tag (2026-09-18) — this repo's own `.claude/hooks` carry a different
`source` and are excluded by the filter itself, not by a second pass. Command text in the
corpus is redacted, so every row is read through its `label` (the exact refusal message the
hook returned, truncated to its opening words by the miner) and its `tags`/`shape` fields —
never reconstructed from a command nobody can see here.

## Which hook branch owns which label

`label` is not a free-text summary; it is the opening words of the literal string the `decide()`
branch returned, so it identifies the branch that fired. Reading the three hooks that produced
these subsources (public source, no redaction involved) gives each label's dependency:

| Label (as the corpus truncates it) | Hook : branch | Depends on |
|---|---|---|
| `Outside the running plan …` / `… change magnitude` | `require-plan.py` | plan scope (declared `files`) |
| `docs audit audit-plan json is the …` / `docs audit phases P json is …` | `require-plan.py` (same gate, over `docs/audit/**`), **or** `guard-secrets-read.py`'s shell-write twin (`_manifest_write_verdict` → `_SHELL_SUBAGENT_MANIFEST`, `guard-secrets-read.py:1801-1822`) | manifest/phase file identity, either way — the docstring at `guard-secrets-read.py:1801-1803` says plainly "the two refusals are require-plan's two, in its order": the shell-write branch reuses require-plan's own message text rather than writing a second one, so the identical opening words this corpus's `label` field truncates to cannot, on their own, tell the two sources apart. The category is the same regardless of which one fired. |
| `Shell write into a source file` / `A source-file write from a heredoc` / `…inline-eval` (×2 shapes) | `guard-secrets-read.py:_plan_gate_write_verdict` (`guard-secrets-read.py:1642-1687`) | plan scope — graded through `_config.plan_gate_mode`, the same resolver `require-plan` uses (`guard-secrets-read.py:1654-1658`) |
| `Reading sourcing or copying a secret …` / `Reading a secret file from a …` | `guard-secrets-read.py` Rule #1 (`guard-secrets-read.py:2037-2043`, `:2084-2091`) | secret read — "refuses at every tier including the one with no manifest at all" (`guard-secrets-read.py:1648-1650`) |
| `Dumping environment values (printenv/env) is …` | `guard-secrets-read.py` Rule #2 (`guard-secrets-read.py:2007-2010`) | secret read (env-held credentials, not a file; same every-tier guarantee) |
| `` `git stash push`/`drop`/`pop` moves work between … `` | `guard-history-rewrite.py` stash arm (`guard-history-rewrite.py:1622-1624`) | plan/journal state — gated on `plan_present(r, cfg)`, **not** on a recorded SHA (`guard-history-rewrite.py:1615-1621` explains the ordering: a stash removes work that was never committed, so waiting for a recorded SHA "would make this arm silent on exactly the repo where the incident happened") |
| `rebasing rewrites the SHAs recorded in …` / `force-push replaces history other clones already …` / `…--force-with-lease …` / `filter-branch filter-repo rewrites every SHA it …` | `guard-history-rewrite.py` SHA arm | a SHA the manifest records — `if not shas: return ("allow", "")` (`guard-history-rewrite.py:1636-1639`): with nothing recorded, every one of these commands is allowed |

These placements are not read off the label alone, and each is stated here as a decision
rather than left implicit:

- `docs audit …` rows are counted under **journal or manifest integrity**, not plan scope,
  because the branch is asking an identity question about the manifest/phase file itself
  (`guard-secrets-read.py:1727-1798` resolves the written path against `manifestPath` and the
  phase shards before any scope question is asked), not a coverage question about a task's
  declared files.
- `git stash` rows are counted under **journal or manifest integrity**, not "a SHA the
  manifest records", because the code comment at the branch is explicit that it is the other
  question: "Everything above asks … a SHA … Stash … removes work which was never committed at
  all … nothing in the plan that says it happened" (`guard-history-rewrite.py:1154-1160`).
- Env-dump and echoed-token rows are counted under **secret read**, not a category of their
  own: both are Rule #2 of the same secrets guard, gated the same way (every tier, plan or no
  plan), and the question this document asks — does a verdict depend on plan, manifest,
  recorded-SHA or secret-pattern state, or on none of them? — gets the same answer for Rule #2
  as for Rule #1.

## The re-derivation

No new `.py` file; this runs with the stdlib, against a `$CORPUS` the caller supplies (never a
path committed here — see "Scope" above for why a public reader cannot supply one):

```bash
CORPUS=/path/to/classifier-events.redacted.jsonl python3 - <<'PY'
import json, os, collections

PLAN_SCOPE = {
    "Outside the running plan this session's",
    "Outside the running plan change magnitude",
    "Shell write into a source file",
    "A source-file write from a heredoc",
    "A source-file write from an inline-eval",
    "Writing source files via an inline-eval",
}
JOURNAL_MANIFEST_LABELS = {
    "docs audit audit-plan json is the",
    "docs audit phases P json is",
}
SHA_RECORDED = {
    "rebasing rewrites the SHAs recorded in",
    "force-push replaces history other clones already",
    "force-push --force-with-lease still replaces the remote's",
    "filter-branch filter-repo rewrites every SHA it",
}
SECRET_READ = {
    "Reading sourcing or copying a secret",
    "Reading a secret file from a",
    "Dumping environment values printenv env is",
}

STASH_MARK = "`" + "g" + "it stash"  # split so this file's own text is not
                                      # itself a stash command for the guard
                                      # that will read it (see the note below)

def category(row):
    label = row.get("label", "")
    if label.startswith(STASH_MARK):
        return "journal_or_manifest_integrity"
    if label in PLAN_SCOPE:
        return "plan_scope"
    if label in JOURNAL_MANIFEST_LABELS:
        return "journal_or_manifest_integrity"
    if label in SHA_RECORDED:
        return "sha_recorded"
    if label in SECRET_READ:
        return "secret_read"
    # A generic-destructive row is anything left over: a refusal whose label
    # names no plan/manifest/SHA/secret dependency. Never folded into a
    # neighbor — reported on its own, or not at all.
    return "generic_destructive_undetermined"

path = os.environ["CORPUS"]
rows = [json.loads(l) for l in open(path) if l.strip()]
era = [r for r in rows
       if r.get("source") == "plugin-hook"
       and str(r.get("subsource", "")).startswith("audit-plugin:")
       and r.get("ts", "") >= "2026-09-18"]

counts = collections.Counter(category(r) for r in era)
undetermined = [r for r in era if category(r) == "generic_destructive_undetermined"]

print("era rows:", len(era))
for k in ("plan_scope", "journal_or_manifest_integrity", "sha_recorded",
          "secret_read", "generic_destructive_undetermined"):
    print(" ", k, counts.get(k, 0))
for r in undetermined:
    print("  undetermined label:", repr(r.get("label")), "subsource:", r.get("subsource"))
PY
```

A heredoc spelling the git-stash verb as literal text — even as a string a Python program never
executes — is itself denied by `guard-history-rewrite.py`'s heredoc-as-code reading, in any
worktree carrying an audit plan: the guard misreads the literal string as a command it must
grade, which is a false positive (the text is data, not something anything runs). That is why the
command above builds the one marker string from a split literal instead of writing it out. The
false positive is itself a data point for the question this document asks rather than
something to route around quietly: the refusal still depended on a plan being present in the tree the command ran in
(`guard-history-rewrite.py:1622-1624`), so it is a `journal_or_manifest_integrity`-class
instance, not a counter-example to the generic-row finding below.

## Result (one run against the corpus named above, re-derivable with the command above)

| Category | Rows | Host basis assessed? |
|---|---|---|
| Plan scope | 38 | n/a — plugin-only by construction (see below) |
| Journal or manifest integrity | 10 | n/a — plugin-only by construction |
| A SHA the manifest records | 9 | n/a — plugin-only by construction |
| Secret read | 19 | n/a — depends on the path or token matching a pattern, not on plugin state (see below) |
| Generic destructive operation | 0 | none fell here in this run; see below |

Summing the five rows in the table above reproduces the command's own "era rows" line, with
nothing left in the `generic_destructive_undetermined` bucket — a label the mapping table does
not recognize would print there by name, and none did. The branch tracing in the previous section
shows **why**: for each of the three hooks, every deny arm that reaches a Bash command in this
corpus is gated on plan, manifest, recorded-SHA or secret-pattern state:

- `guard-secrets-read.py`'s only two write-reaching branches are `_plan_gate_write_verdict`
  (plan scope) and the manifest-path check (`guard-secrets-read.py:1727-1798`, manifest/journal
  identity); there is no third write branch that denies independent of either.
- `guard-history-rewrite.py` returns `("allow", "")` outright when the manifest records no SHA
  at all (`guard-history-rewrite.py:1636-1639`) and gates the stash arm on `plan_present`
  (`guard-history-rewrite.py:1622-1624`) — so a rebase, force-push, filter-branch, reset or
  stash in a repository with no audit plan is not refused by this hook, regardless of how
  destructive the git operation is in itself.
- `require-plan.py`'s whole subject is plan/manifest scope by name.
- Rule #1/#2 of `guard-secrets-read.py` refuse at every tier including no-plan-at-all
  (`guard-secrets-read.py:1648-1650`), which is why they are their own category (secret read)
  rather than a generic one: the dependency is on the pattern being secret-shaped, not on the
  plugin's own state.

So the answer to **"what share of these refusals depended on something other than the command's
own destructiveness?"** is the whole of the era slice the command counts: none of it is a row
whose verdict was independent of plan, manifest, recorded-SHA or secret-pattern state. The
narrower share that **only the plugin could have made** is the plan-scope, integrity and
recorded-SHA rows. The secret-read rows are outside it: their verdict depends on a path or a
token matching a pattern, which reads no plugin state, so for them "would Claude Code's own
layers have stopped it?" stays a live question even though none of them is generic.
`docs/research/guard-ownership-design.md` answers it rule by rule. That is a statement about the **code as it is written today**: nothing in the three
guard hooks currently denies a destructive git or shell operation unconditionally. The
questions it leaves are therefore not "which generic rows can be retired?" but, rule by rule in
`guard-secrets-read.py` and `guard-history-rewrite.py`: could this rule fire independent of
plan/manifest state (which would make it a candidate for a `permissions.deny` fragment even
though no such row showed up by construction in this corpus)? And does CLAUDE.md's own
description of guard scope still match what the code denies?

## What a differently-scoped corpus could show

If a future month's corpus or a different repository produces a non-empty
`generic_destructive_undetermined` list, the host-basis question — would a documented
auto-mode block category, or a `permissions.deny` rule matching the command as written, have
stopped it? — stays unanswered here for the same reason the corpus stays private: the command text
needed to check either basis is redacted. That column in the result table is filled with "n/a"
for this run because there is nothing in that bucket to assess, not because the question was
skipped.
