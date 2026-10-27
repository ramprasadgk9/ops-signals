# Where AI is used

Every place Ops Signals uses AI, in one table. Every feature also works without AI: detection,
findings, cases, alerts and the assistant run on rules, statistics and templates (ADR-007). With an
AI provider configured, the places below add written text on top. Each one falls back to its usual
behavior when there's no provider, the call fails or the reply doesn't pass its checks.

## The list

| Area | Where you see it | What AI adds | Without AI | When the model runs |
|---|---|---|---|---|
| **Finding wording** | Finding details (Findings → View details), Validate Data's Finding Summary, the plugin's evidence panel | **What to check**: one more thing to check, after the template's line. **Happened with**: one sentence after the first line. **Why it matters**: only for a metric the wording file doesn't describe, in place of "We don't know what this metric means". Lines carry an **AI** chip; **Show template wording** switches back. See [AI wording](finding-wording.md#ai-wording). | The template lines from `config/finding_templates.yaml`. Admins see once how to turn AI on. | First open of a finding's details; saved |
| **Finding summary** | Finding cards and details, for a finding with no plain wording | A plain rewrite of the stored summary, with an **AI** chip | The stored summary | First open of its details; saved |
| **Combined patterns** | Behavior Intelligence → Detected; combined patterns on Findings | A plain explanation of why the pattern matched | The pattern's summary | When the list loads, for each match not explained yet (the list waits for them); saved |
| **Suggested fixes** | Finding details → Seen before? → **Draft a runbook** | A runbook draft from the fixes that worked, citing the cases. Never saved. | "AI assistance is not configured." under the button | On click |
| **Recurring problems** | Recurring Problems list | A name for each group ("DB pool runs out after deploys") | The group's central case title | Each page load, one call for all groups |
| **Recurring problems lookup** | Recurring Problems → lookup → **Raw activity** | 1-2 sentences on repeated activity that never became a case, with an **AI** chip | The counts and recent titles | Each lookup |
| **Ticket comments** | Case → ticket card → **⚡ AI Triage**; also on ticket sync and ticket webhooks | Picks the comments that matter operationally and adds them to the case notes | Comments stay on the ticket | On click, sync and webhook |
| **Ask Ops Signals** | Web UI Assistant page | A 1-3 sentence answer from the evidence found, with word-for-word quotes; AI also routes the question (past incidents, the app, or both) | The template answer and keyword routing; the evidence found is the same | Each question |
| **Autonomous run questions** | Plugin **Ask Ops Signals** panel, and **Ask** on a finding there | An answer written from the run's findings | The template answer | Each question |
| **Analyzer recommendation** | Analyzer Recommendation | A second opinion next to the rule-based pick, saying where it disagrees | The rule-based pick only | Each recommendation |
| **Docs check** (admins) | Assistant → Docs check → **Draft questions** | Test questions written for doc sections that have none | Questions drafted from headings | On click |
| **Case root cause and resolution** | API and MCP only: `POST /api/cases/{id}/rca/suggest`, `/resolution/suggest` | A draft root cause from the case and similar past cases; a resolution summary from its notes. Never saved. | `available: false` | On request |

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
explains every match not explained yet before showing the list. The others run each time you ask. A small model on a laptop answers in about 2-3
seconds per call. With a hosted provider, each call is billed by that provider.

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
