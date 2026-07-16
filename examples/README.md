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

**▶ Live demo:** https://aleksandarbisevac.github.io/claude-plugins/ — the same
report, hosted. Try the search, the phase-status chips, expand a phase, and
**Save as PDF**.

## What this example is designed to show

| Look at | Where in the example |
|---|---|
| All four **phase/task statuses** | `P1` done · `P2` in_progress · `P3` pending · tasks incl. a **blocked** one (`P2.3`) |
| A **hard gate** between phases | `P3.blockedBy: ["P2"]` — P3 can't start until P2 is done |
| **Task ordering** inside a phase | `P2.4.dependsOn: ["P2.1"]` |
| The full **bug lifecycle** | `BUG-1` open · `BUG-2` triaged · `BUG-3` in_progress · `BUG-4` fixed · `BUG-5` wontfix |
| A **bug ↔ fix task** link (reciprocal) | `BUG-4` ↔ `BF1.2` (`fixedIn` = the fix commit) |
| An **Azure DevOps** link | `BUG-3.ado` / `P1.1.ado` (`meta.ado` configures the sync) |
| A **narrative summary** in the report | `meta.reportSummary` → the blue Summary box |
| **Custom report filenames** | `meta.reportBasename: "acme-store-audit"` → `acme-store-audit.html/.md` |

## Regenerate the report

From the repo root (Python 3.8+, no dependencies):

```bash
python3 plugins/audit/scripts/render-report.py examples/acme-store/audit-plan.json
```

It reads `meta.reportBasename`, so it writes `acme-store-audit.html` + `.md` next
to the manifest. Validate the manifest the same way the commands do:

```bash
python3 plugins/audit/scripts/validate-manifest.py examples/acme-store/audit-plan.json
```

> This manifest is checked in CI on every push, so the example never drifts out of validity.
