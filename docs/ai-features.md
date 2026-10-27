# Where AI is used

Every place Ops Signals uses AI, in one table. Every feature also works without AI: detection,
findings, cases, alerts and the assistant run on rules, statistics and templates (ADR-007). With an
AI provider configured, the places below add written text on top. Each one falls back to its usual
behavior when there's no provider, the call fails or the reply doesn't pass its checks.

## The list

| Feature | Where you see it | AI runs |
|---|---|---|
| [Finding wording](#finding-wording) | Finding details, Validate Data, plugin evidence panel | First open, then saved |
| [Finding summary](#finding-summary) | Findings with no plain wording | First open, then saved |
| [Combined patterns](#combined-patterns) | Behavior Intelligence → Detected | List load, then saved |
| [Runbook draft](#runbook-draft) | Finding details → Seen before? | On click |
| [Recurring problem names](#recurring-problem-names) | Recurring Problems | Each page load |
| [Raw activity summary](#raw-activity-summary) | Recurring Problems → lookup | Each lookup |
| [Ticket comment triage](#ticket-comment-triage) | Case → ticket card | Click, sync, webhook |
| [Ask Ops Signals](#ask-ops-signals) | Web UI Assistant | Each question |
| [Autonomous run questions](#autonomous-run-questions) | Plugin Ask Ops Signals panel | Each question |
| [Analyzer recommendation](#analyzer-recommendation) | Analyzer Recommendation | Each recommendation |
| [Docs check questions](#docs-check-questions) | Assistant → Docs check (admins) | On click |
| [Root cause and resolution drafts](#root-cause-and-resolution-drafts) | Case → Root Cause, Resolution | On click |

Each feature below says what AI adds and what you see without it.

### Finding wording

- **AI adds:** one more thing under **What to check**; one sentence after the first **Happened
  with** line; for a metric the wording file doesn't describe, **Why it matters** in place of "We
  don't know what this metric means". Each AI line has an **AI** chip; **Show template wording**
  switches back. Details: [AI wording](finding-wording.md#ai-wording).
- **Without AI:** the template lines from `config/finding_templates.yaml`. Admins see once how to
  turn AI on, next to the lines.

### Finding summary

- **AI adds:** a plain rewrite of the stored summary, with an **AI** chip, for a finding that has
  no plain wording.
- **Without AI:** the stored summary.

### Combined patterns

- **AI adds:** a plain explanation of why the pattern matched, on Behavior Intelligence → Detected
  and on combined patterns in Findings.
- **Without AI:** the pattern's summary.

### Runbook draft

- **AI adds:** **Draft a runbook** turns the fixes that worked before into steps, citing the cases.
  Never saved.
- **Without AI:** "AI assistance is not configured." under the button.

### Recurring problem names

- **AI adds:** a name for each group of past problems ("DB pool runs out after deploys"), one call
  for all groups.
- **Without AI:** the title of the group's central case.

### Raw activity summary

- **AI adds:** 1-2 sentences on repeated activity that never became a case, with an **AI** chip.
- **Without AI:** the counts and recent titles.

### Ticket comment triage

- **AI adds:** **⚡ AI Triage** picks the ticket comments that matter operationally and adds them
  to the case notes. Also runs when comments sync or arrive by webhook.
- **Without AI:** comments stay on the ticket.

### Ask Ops Signals

- **AI adds:** a 1-3 sentence answer from the evidence found, with word-for-word quotes. AI also
  decides whether the question is about past incidents, the app, or both.
- **Without AI:** the template answer and keyword routing. The evidence found is the same.

### Autonomous run questions

- **AI adds:** an answer written from the run's findings, in the plugin's **Ask Ops Signals** panel
  and **Ask** on a finding there.
- **Without AI:** the template answer.

### Analyzer recommendation

- **AI adds:** a second opinion next to the rule-based pick, saying where it disagrees.
- **Without AI:** the rule-based pick only.

### Docs check questions

- **AI adds:** test questions for doc sections that have none (**Draft questions**, admins).
- **Without AI:** questions drafted from headings.

### Root cause and resolution drafts

- **AI adds:** **Draft from case** on a case's Root Cause tab fills the summary from the notes,
  ticket comments, matched deploy and similar past cases; on the Resolution tab it fills the outcome
  summary and corrective action. Shows what it was drafted from, never saves. Details:
  [AI drafts](operational-cases.md#ai-drafts-on-the-root-cause-and-resolution-tabs).
- **Without AI:** no button; the boxes work as before. Admins see once how to turn AI on.

## Never AI-written

- Detection: analyzers, the router, scores, priority, trust numbers, drill-down, deploy matching
- Finding cards' plain wording on the list, and Slack finding and alert messages
- What gets saved: an RCA, a resolution or a runbook is saved only when a person saves it

## Data each feature shares

Only the text needed for that one place: a finding's facts and wording, a case's notes and its
similar cases' resolutions, ticket comments, the assistant's retrieved evidence, or a metric's
profile. Where it goes depends on the provider you chose: on your own machine, or to a hosted
service, whose terms should fit your data (ticket comments and case notes can name people and
systems).

## Cost and speed

Most places run once and save the result (finding wording, summaries, pattern explanations), so
reopening is instant. The first load of Behavior Intelligence after turning AI on can be slow: it
explains every match not explained yet before showing the list. The others run each time you
ask. A small model on a laptop answers in about 2-3 seconds per call. With a hosted provider, each call is billed by that provider.

## Turn it on

A local model needs no API key and keeps everything on your machine:

```bash
docker compose --profile ai up -d
OPS_SIGNALS_AI_ENABLED=1 OPS_SIGNALS_AI_PROVIDER=ollama ./scripts/run_all.sh
```

The first command starts Ollama and pulls `qwen2.5:3b` (about 2 GB, once); set
`OPS_SIGNALS_OLLAMA_MODEL` to use another model you have. Check it under **Integrations → AI
provider → Test connection**. Other providers and every setting: [Enabling Local AI](ask-ops-signals-assistant.md#enabling-local-ai)
and [Other AI Providers](ask-ops-signals-assistant.md#other-ai-providers).
