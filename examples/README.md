# Examples

A small, self-contained audit you can read in a minute — a fictional web app
(`acme-store`) mid-audit. It exists so you can see a real manifest and the report
it renders **without installing anything**.

## `acme-store/` — a worked audit

| File | What it is |
|---|---|
| [`audit-plan.json`](acme-store/audit-plan.json) | The manifest — the single source of truth the plugin reads and writes. |
| [`acme-store-audit.html`](acme-store/acme-store-audit.html) | The rendered report (interactive; open it in a browser). |
| [`acme-store-audit.md`](acme-store/acme-store-audit.md) | The Markdown twin (renders inline on GitHub). |
| [`.claude/audit.config.json`](acme-store/.claude/audit.config.json) | The per-repo config — what `/audit:panel` edits, and what makes the example a *project* rather than a loose JSON file. |

**▶ Live demo:** https://aleksandarbisevac.github.io/claude-plugins/ — the same
report, hosted. Try the search, the phase-status chips, expand a phase, and
**Save as PDF**.

## What this example is designed to show

| Look at | Where in the example |
|---|---|
| All four **phase/task statuses** | `P1` done · `P2` in_progress · `P3` pending · tasks incl. a **blocked** one (`P2.3`) |
| A **hard gate** between phases | `P3.blockedBy: ["P2"]` — P3 can't start until P2 is done |
| **Monorepo areas** (tags + registry) | `P1: auth` · `P2: storefront, checkout` (a multi-tag phase) · `P3: storefront` · `BF1` untagged on purpose · described in `meta.areas` — the report's Area chips filter on them |
| **Task ordering** inside a phase | `P2.4.dependsOn: ["P2.1"]` |
| The full **bug lifecycle** | `BUG-1` open · `BUG-2` triaged · `BUG-3` in_progress · `BUG-4` fixed · `BUG-5` wontfix |
| A **bug ↔ fix task** link (reciprocal) | `BUG-4` ↔ `BF1.2` (`fixedIn` = the fix commit) |
| An **Azure DevOps** link | `BUG-3.ado` / `P1.1.ado` (`meta.ado` configures the sync) |
| A **narrative summary** in the report | `meta.reportSummary` → the blue Summary box |
| **Custom report filenames** | `meta.reportBasename: "acme-store-audit"` → `acme-store-audit.html/.md` |

## Run it — two scripts, no install, no Claude session

The two surfaces the plugin renders — the **control panel** and the **report** —
are plain Python scripts underneath, and the example is a project they accept.
So you can drive both without installing the plugin or opening a session
(Python 3.8+, no dependencies, run from any directory):

```bash
examples/panel.sh          # open the control panel on the example  (Ctrl-C stops it)
examples/report.sh --open  # re-render the report and open it in a browser
```

Both take `--help`, and both pass unrecognized flags straight through to the
script underneath.

### `panel.sh` — the control panel

| Command | What it does |
|---|---|
| `examples/panel.sh` | Foreground; opens your browser. `Ctrl-C` stops it. |
| `examples/panel.sh --detach` | Background; prints the URL. Survives the shell. |
| `examples/panel.sh status` | Is one running for this example, and where. |
| `examples/panel.sh stop` | Stop it. |

This is what [`/audit:panel`](../plugins/audit/commands/panel.md) runs, aimed at
`acme-store/`: edit guards and paths, and set `reviewSkill` / per-task models
from the autocomplete built by discovering the skills and agents on *your*
machine. Saving writes to the example's `.claude/audit.config.json` and manifest —
that's the point, and `git checkout examples/acme-store` undoes it.

It binds `127.0.0.1` only and requires a per-launch token. The pidfile holding
that token (`acme-store/.claude/audit-panel.json`) is gitignored, so running the
panel never dirties the tree. Since 0.35 the panel maintains that ignore rule
itself — and this example ships `acme-store/.claude/.gitignore` committed, so
the first launch finds the rule already in place and writes nothing.

### `report.sh` — the report

Validates the manifest, then renders `acme-store-audit.html` + `.md` next to it
(the filenames come from `meta.reportBasename`), under the same
`CLAUDE_PROJECT_DIR` CI uses so the **Usage** section reads the example's
committed ledger. (A committed ledger is also exactly what `/audit:doctor`'s
hygiene check warns about — per-machine usage data does not normally belong in
git. The example keeps it on purpose as demo data, so the warning here is the
check working, not the example broken.)

It also refreshes **`docs/index.html`**, which CI requires to be a byte copy of
the committed example report — re-rendering and forgetting that copy is how the
live demo once went a month stale. `--out-dir <dir>` renders to scratch instead
and touches nothing committed.

> Every render stamps a fresh `generated <UTC>` line, so an in-place run leaves a
> small git diff even when nothing else changed. Discard it with
> `git checkout examples/acme-store docs/index.html`.

### The commands underneath

The scripts are thin — this is all they call, and the plain form still works:

```bash
python3 plugins/audit/scripts/manifest/validate-manifest.py    examples/acme-store/audit-plan.json
python3 plugins/audit/scripts/report/render-report.py examples/acme-store/audit-plan.json
python3 plugins/audit/scripts/panel-server.py --project examples/acme-store
```

> This manifest is checked in CI on every push, so the example never drifts out of validity.
