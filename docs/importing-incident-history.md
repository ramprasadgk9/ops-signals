# Importing Incident History

A new install starts with empty operational memory, so "have we seen this before?" has nothing to
search. Importing your past postmortems and incidents fixes that on day one: each one becomes a
resolved case that similar-case search, alert enrichment and the assistant can match against.

## At a glance

- **What it reads:** CSV and Markdown files, or a `.zip` of them. Jira and PagerDuty CSV exports are
  recognised automatically; any other CSV works through column names or a small mapping.
- **What it creates:** one resolved case per incident, marked as imported, indexed into memory.
- **Safe to repeat:** uploading the same export again changes nothing; an edited record updates its
  existing case. Nothing is ever duplicated.
- **Reversible:** every import is a batch you can undo from the Integrations page.

## Where to find it

- **Operational Memory page:** the **Import past incidents** button. When memory is empty, the
  inventory offers the same button.
- **Integrations page:** the **Incident history** card lists past imports, with **Import again** and
  **Undo**.
- **Command line**, for bulk imports or a mounted folder:

```
ops-signals import-cases ./exports --dry-run
ops-signals import-cases ./exports
```

- **API:** `POST /api/case-imports/preview` and `POST /api/case-imports` take multipart `files` and
  an optional `settings` JSON field. `GET /api/case-imports` lists batches,
  `DELETE /api/case-imports/{batch_id}` undoes one.

## The import wizard

1. **Source** - pick the tool the export came from, or let Ops Signals detect it. The step shows a
   short checklist for that source and links to the templates.
2. **Upload** - drop CSV, Markdown or `.zip` files, plus an optional `ops-signals-import.yaml`.
3. **Preview and mapping** - see what each record will do (new, updated, unchanged, skipped,
   duplicate) and why a record is skipped. Add service aliases or column overrides and re-check.
4. **Import** - write the cases, index them into memory, and undo if it went wrong.

Nothing is written until step 4.

## Which incidents to include

Ten good postmortems are worth more than five hundred alert tickets. A match is only useful if the
past case says what went wrong and what fixed it.

- Export **resolved** incidents that have a **written root cause**. Records without one are skipped
  and listed in the preview.
- Prefer the **last one to two years**. Older incidents describe systems that may no longer exist
  and produce misleading matches.
- Leave out pure alert noise (auto-resolved pages, test incidents).

## Fields

Each record maps onto these case fields. The four required ones must be present or the record is
skipped.

| Field | Required | What it holds |
|---|---|---|
| `source_id` | recommended | The tool's own ID (`OPS-412`, `Q1ABC23`). Used to match re-imports. |
| `title` | yes | One-line description of the incident. |
| `service` | yes | Affected service. Several are allowed; the first is the main one. |
| `started_at` | yes | When it began. |
| `root_cause` | yes | Why it happened. |
| `resolved_at` | no | When it ended. |
| `severity` | no | Severity or priority as your tool writes it. |
| `symptom` | no | What people saw: impact, error rates, latency. |
| `corrective_action` | no | What fixed it. |
| `outcome` | no | Result and follow-ups. |
| `notes` | no | Timeline and anything else worth keeping. |
| `source_url` | no | Link back to the original record. |
| `tags` | no | Labels, comma or semicolon separated. |

## Dates and time zones

ISO 8601 is preferred: `2025-03-14T18:20:00Z`. Jira's `14/Mar/25 6:20 PM`, `2025-03-14 18:20` and
US `03/14/2025` dates are also read. A date without a time zone is taken as **UTC**, so export in UTC
or add the offset.

## Markdown postmortems

One postmortem per `.md` file. Put the fields in frontmatter and the story under headings:

```
---
id: PM-2025-007
title: Search results empty after index rebuild
service: search-api
started_at: 2025-07-21T13:05:00Z
severity: SEV2
url: https://example.com/postmortems/PM-2025-007
---

## Summary
## Root cause
## Resolution
## Outcome
## Timeline
```

Headings are matched by meaning: *Root cause*, *Why it happened* and *Contributing factors* fill
`root_cause`; *Resolution*, *Fix*, *Remediation* and *Mitigation* fill `corrective_action`; *Summary*,
*Impact* and *What happened* fill `symptom`; *Outcome*, *Lessons* and *Follow-up* fill `outcome`. Any
other section is kept as a note. Frontmatter wins when both say something.

Without frontmatter, the first `# Heading` becomes the title, but service and start time are still
required, so add at least those two keys. A `source:` key labels the records (default `markdown`).

## Generic CSV

One incident per row, a header row, UTF-8. Common column names are recognised without mapping:
`id`, `title`, `service`, `started_at` (or `date`, `created`), `resolved_at`, `severity` (or
`priority`), `symptom` (or `summary`, `impact`, `description`), `root_cause` (or `cause`, `rca`),
`fix` (or `resolution`, `remediation`), `outcome`, `notes` (or `timeline`), `url`, `tags`.

Start from the CSV template in the wizard if your columns are named differently, or map them with
column overrides.

## Jira

Detected from the `Issue key` and `Summary` columns.

- Filter with JQL first, for example `issuetype = Postmortem AND resolution IS NOT EMPTY`.
- Root cause and fix usually live in custom fields. Add them as columns before exporting, or use
  **Export CSV (all fields)**. Fields named *Root Cause* and *Corrective Action* / *Fix* /
  *Resolution details* are picked up automatically; map anything else with a column override.
- **Component/s** becomes the service, **Priority** the severity, **Description** the symptom and
  **Labels** the tags. Jira writes one column per value for multi-value fields; all are kept.
- Jira's native CSV export stops at 1000 issues. Export in date ranges and upload them together.

## PagerDuty

Detected from `incident_number`, or from `service_name` with `urgency`. `service_name` becomes the
service and `urgency` the severity.

The console's CSV export may not include incident notes, which is where root causes usually are.
Check your export: if there is no root cause column, add one (`root_cause`) before uploading,
otherwise every row is skipped. This profile has not yet been checked against a real PagerDuty
export, so report any column it misses.

## incident.io, Confluence and Google Docs

- **incident.io:** `inc post-mortems content` prints a postmortem as Markdown. Save each to a file
  and add frontmatter with id, service and start time.
- **Confluence or Google Docs:** export pages to Markdown. Consistent *Root cause* and *Resolution*
  headings are what make these import cleanly, so a shared postmortem template pays off.

## Service aliases and column overrides

Service names in incident tools rarely match metric labels (`Checkout` vs `checkout-api`). Without
a match, same-service filtering in similar-case search won't connect them.

- **Service aliases** rename services: `Checkout = checkout-api`, one per line.
- **Column overrides** point a field at a column the profile doesn't know:
  `root_cause = Custom field (Why it happened)`.

Both are in step 3 of the wizard. For folder imports, put them in an `ops-signals-import.yaml` next
to the files; settings typed in the wizard win over the file. The wizard's templates include a
commented example.

## Re-importing and duplicates

Every record is keyed by its source and ID, under a unique database index:

| On re-upload | Result |
|---|---|
| ID not seen before | New case, indexed. |
| Same ID, same content | Nothing happens (**unchanged**). |
| Same ID, changed content | The existing case is updated in place and re-indexed. |
| Same record twice in one upload | Imported once, counted as a **duplicate row**. |

A record with no ID gets a fingerprint from its title, start time and service, so re-uploading the
same file still matches. Editing the title of an ID-less record makes it a new case; give records
IDs where you can.

Fields that come from the export (title, root cause, fix and so on) are overwritten on update: the
source tool is the authority. **Notes you added in Ops Signals are kept.**

The same incident exported from two tools (a PagerDuty incident and its Jira postmortem) has two
different keys and becomes two cases.

## Privacy and masking

Imported text is stored in Postgres, embedded into Qdrant and quoted by the assistant. Before
anything is stored, emails, IP addresses, bearer tokens, `password=` / `token=` style values, and AWS,
GitHub, Slack and `sk-` keys are masked. The preview shows how many values were masked.

Masking catches obvious patterns only. Remove customer names, internal hostnames and anything else
sensitive before exporting.

The uploaded files themselves are not kept; only the mapped fields are stored.

## What gets stored where

- **Postgres, `ops_operational_cases`:** one row per incident, with `source` (the tool),
  `source_id`, `source_url`, the batch that created it, and a content hash used to detect changes.
  Detected cases have `source = detected`.
- **Qdrant, collection `operational_cases`:** one point per case, in the same collection as detected
  cases, so one search covers both. The payload carries `origin` (`imported` or `detected`) and
  `source`.
- **Postgres, `ops_case_imports`:** one row per import: files, profiles, counts and status.

## How imported cases behave

- They are **resolved**, with the root cause marked confirmed, and their dates are the incident's
  own, not the import time.
- They show an **Imported** badge on Cases, Case Details and Operational Memory, linking back to the
  original when a URL was imported. The Cases page can filter to imported or detected only.
- They have no metric signals, linked alerts or analysis run.
- **Recall:** similar-case search and alert enrichment normally only consider past cases on the
  same metric. A postmortem has no metric, so imported cases are matched on service and on what the
  text says instead. This is why service aliases matter: an imported case on `Checkout` will not be
  recalled for an alert on `checkout-api`.

## Where to see matches

- **Findings:** open any finding. Its **Seen before?** section lists past cases that look like it,
  imported ones included, without opening a case first.
- **Case Details → Similar Cases:** the same for a case.
- **Operational Memory → Alert Context Preview**, and the Slack message for incoming alerts: when
  there are no resolved outcomes for the service and metric but past incidents match, the verdict
  reads **Seen before** and quotes the closest incident's cause and fix.
- **Ask Ops Signals:** questions like "have we seen high CPU on checkout before?"
- **Operational Memory → Monitoring coverage:** each imported incident checked against what Ops
  Signals analysed and flagged while it happened: **Detected**, **Flagged something else**,
  **Missed** (the service was analysed, nothing was flagged) or **Not watched** (nothing analysed
  that service then). This needs the postmortem's service and start time, and the service named as
  it is in your metrics - use aliases when importing. Analyzer findings are worded generically, so a
  different problem on the same service can score close; anything under the 60% bar is listed as
  flagged something else, by title, for you to judge.
- **Operational Memory → Recurring problems:** imported and detected cases grouped into problems
  that happened three or more times in the chosen window, by symptom or by cause. Postmortems group
  with the detected cases of the same problem, because both are compared on what was seen.
- **Case Details → Similar Cases → Same fix elsewhere:** other incidents, imported or detected, that
  the same cause and fix resolved, and whether the fix held.

Seen before? and Similar Cases also say how familiar the problem is: **New pattern**, **First time
on <service>**, **Seen before**, or **Recurring** when three or more past cases on the same service
match.

Matches on the same service are listed first; matches on other services are folded away and
labelled. Within each group, matches are ordered by similarity plus small bonuses for sharing exact
words with the alert or finding (an error code, a service name), a verified root cause, and being
recent; together the bonuses are worth at most 25 points, so a much more similar case is never
pushed down. Each match is marked **strong** (70% or more) or **possible** (40-70%), always on plain
similarity. A finding is compared with each past case's symptom - what was seen, not why - so a
detected finding and a postmortem about the same problem usually score as a strong match even though
one is written by Ops Signals and the other by a person. Repeats of the same incident (same service,
symptom, cause and fix) fold under one match as **+N more like this**.
- Resolving one never asks for a learning outcome: learning outcomes score the analyzers behind a
  detection, and an imported case has none. Analyzer scores and Overview counts are unaffected.

## Undoing an import

On the Integrations page, **Undo** on a batch deletes the cases that batch **created** and removes
them from memory. Cases it only updated stay, with their updated content. Undo can't be reversed;
re-import the files to bring the cases back.

## Troubleshooting

- **Every row is skipped with "missing root_cause"** - the export has no root cause column the
  profile recognises. Add one, or map it with a column override.
- **"unreadable started_at"** - the date format isn't recognised. Re-export with ISO 8601 dates.
- **Cases imported but similar-case search finds nothing** - memory is disabled or indexing failed.
  The import result says how many were indexed; use **Add to Memory** on a case to retry.
- **Imports fail on an old local SQLite database** - SQLite can't relax the original case
  constraint in place. Start from a new SQLite file, or use Postgres.

## Limits

- Total upload size follows `OPS_SIGNALS_MAX_UPLOAD_BYTES` (50 MB by default).
- Up to 20,000 records per import; a `.zip` may hold up to 5,000 files and 200 MB uncompressed.
- Long text fields are cut at 20,000 characters.
- Files other than `.md`, `.markdown`, `.csv`, `.zip` and `ops-signals-import.yaml` are skipped
  with a warning.
- A `.csv` or `.md` file that isn't text (a spreadsheet or image renamed, for example), and a CSV
  with a header row but no incidents, are skipped with a warning. UTF-8 is expected; a Latin-1
  export from older Windows tools is still read.
