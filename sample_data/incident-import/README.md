# Sample incident exports

Made-up incidents for trying the importer (docs/importing-incident-history.md). Services match the
local mock metrics (`checkout`, `payments`, both reporting `cpu_usage`), so imported cases can be
recalled against them.

| File | What it is |
|---|---|
| `jira-postmortems.csv` | Jira-style export: repeated Component/s and Labels columns, Jira dates, one row with no root cause, an email and a token to mask |
| `ops-signals-import.yaml` | Service aliases: `Checkout Service` → `checkout`, `Payments` → `payments` |
| `jira-postmortems-edited.csv` | The same export later: OPS-131's fix was edited and OPS-160 is new |
| `pagerduty-incidents.csv` | PagerDuty-style export, one row with no root cause |
| `postmortems/` and `postmortems.zip` | Three Markdown postmortems; `search-cache-stampede.md` has no `id` |

## Steps and what you should see

Open **Operational Memory → Import past incidents**, or **Integrations → Incident history**.

1. **Jira without aliases.** Upload `jira-postmortems.csv` and click Preview.
   Expect **5 new, 1 skipped** (OPS-150, missing root_cause), **2 values masked**, and services
   `Checkout Service`, `Payments` and `Search`. Click Cancel.
2. **Jira with aliases.** Upload `jira-postmortems.csv` and `ops-signals-import.yaml` together.
   Services in the preview are now `checkout` and `payments` (`Search` has no alias). Import:
   **5 new**. Alternatively, type `Checkout Service = checkout` in Service aliases on step 3.
3. **Same file again.** Repeat step 2: **0 new, 5 unchanged**. The Cases count doesn't change.
4. **Edited export.** Upload `jira-postmortems-edited.csv` with the yaml: **1 new** (OPS-160),
   **1 updated** (OPS-131), **4 unchanged**.
5. **PagerDuty.** Upload `pagerduty-incidents.csv`: detected as `pagerduty-csv`, **3 new,
   1 skipped**.
6. **Markdown in a zip.** Upload `postmortems.zip`: **3 new**. Then upload
   `postmortems/search-cache-stampede.md` alone: **1 unchanged**, matched by fingerprint since the
   file has no id.

After all six: **12 imported cases**.

## Where to look afterwards

- **Cases:** each imported case has an `Imported · jira OPS-101` style badge; filter with
  *Imported only*. Open OPS-131: the token in its root cause shows as `[secret]`.
- **Case Details:** the badge links to the original record; Resolution doesn't ask for a learning
  outcome.
- **Integrations → Incident history:** one row per import with its counts and an **Undo** button.
- **Recall** (needs memory enabled): on Operational Memory, **Alert Context Preview** with metric
  `cpu_usage`, service `checkout` and message `checkout CPU above 90% after a release` should list
  imported checkout incidents under similar cases. Payments incidents should not appear.
