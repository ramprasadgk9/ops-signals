# Investigate a finding

**Investigate** on a finding card asks an AI model to check what it can and suggest where to look
next. It runs read-only checks against the finding's Prometheus, the deploys recorded for the
service and past cases, then lists steps: what it checked and found, what you need to check
yourself, and what a past case suggests. It never claims a root cause: you confirm one.

It needs an AI provider (see [Where AI is used](ai-features.md)). Everything else on a finding works
without one.

## What Investigate does, and what it doesn't

Investigate **helps you investigate**: it narrows down where to look. In the time it takes you to
open a dashboard it compares the finding with related metrics, checks recorded deploys and past
cases, rules out what it can with evidence, and hands you the steps it can't do itself, with the
exact query or command.

It does **not** find the root cause or the fix. Every claim points at a check you can open, steps
nothing backs are marked **Not checked**, and the summary says where to look, never "the root cause
is". When nothing it can reach explains the problem, it says **Nothing found in metrics**. You
confirm the cause on the case's Root Cause tab and the fix on Resolution.

How much it can rule out depends on what it can see: today that is metrics, recorded deploys and
past cases (see [What does it check?](#what-does-it-check)), and on the model (see
[Which AI model to use for Investigate](#which-ai-model-to-use-for-investigate)).

## How do I investigate a finding?

To investigate a finding, open **Findings** and click **Investigate** on a card under Needs
attention (or in the finding's details). In the dialog:

1. Check **What your team knows** about the service: what it depends on and behaviour that is normal
   for it. Change anything that is wrong; it is saved for everyone when you start.
2. Untick any source you don't want it to use.
3. Optionally, say what you already know about today ("we moved checkout-db to a new node pool this
   evening").
4. Click **Start investigating**.

The checks show up as they run. When it stops, you get a short summary of where to look and the
steps. Mark a step **Found something** or **Ruled out**, add a note, or type a question or a fact
in the box and **Send**: it takes that into account and checks further.

## Which findings can be investigated?

Investigate shows on cards under **Needs attention** whose finding came from Prometheus and has a
service. A finding from an uploaded CSV file or from OTLP data has no query to run again, so it
can't be investigated; the dialog says so if you open it from the details. Findings under Context
only don't get the button.

## What does it check?

It can use these read-only checks, each limited in code:

| Check | What it does |
| --- | --- |
| List series | Metrics that carry the service's label, with their label names, to find metrics about its database, cache, queue or other services |
| Label values | The values of one label, such as pod, route, code or version |
| Range query | A PromQL range query on the finding's own Prometheus connection, summarised per series: level before and after the change, min, max and when it moved most |
| Changes | Deploys, rollbacks and config changes recorded for a service ([deploy discovery](deploy-discovery.md) and CI events) |
| Past cases | Closed cases on the service with their recorded cause and fix |
| Other findings | Findings on other services in the same time range, such as its dependencies |

Before the model's first turn, every investigation runs three starting checks: the query that found
the finding, whether the service's scrape targets were up (`up`), and how many samples Prometheus got
from them (`scrape_samples_scraped`). They don't count toward its checks. A range query's result says
where data is missing, the gap when the problem started first ("no data 14:19–14:26 (when the
problem started)"). When `up` has no data then either, the model is told Prometheus wasn't scraping
those targets, so the gap isn't the service's alone. A finding from an older run that didn't keep its
query starts from its metric and service label instead (`request_latency_p95{service="mixed-lab"}`),
when Prometheus has that metric.

It reads metrics only: not logs, traces or the databases and services themselves. When the next
step needs one of those, it gives you the step to do, with the exact query or command.

## What your team knows about a service

**What your team knows** holds, per service, what it depends on (services, databases, queues,
caches, outside services), behaviour that is normal for it ("traffic halves on Sundays"), its owner,
channel and runbook. Investigate reads it before its first check, so with checkout-db listed it
looks at database wait early instead of guessing.

The first time anyone investigates a service, the dialog asks what it depends on. It suggests
dependencies from labels on the service's own metrics (`db_name`, `peer_service`, `queue`,
`topic`...), each showing the label it came from; click **Add** or **Not a dependency**. Nothing is
added without a person. **Skip, just start** is always there.

Each line keeps who wrote it. To add a line from an investigation, tick **This is always true** under
your note about today. Editors can change the notes; everyone can read them.

## When does it stop?

The model stops on its own when it has a lead it can't check further, when everything it can reach
is ruled out, or when it needs your answer. Ops Signals stops it when:

- it has used its checks: 15 in the first round, 8 in each later one (**Paused**: click **Continue**
  for more);
- it has asked the model 8 times or run for 2 minutes in one round (**Paused**); set
  `OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS` for a longer round (a local model can need several
  minutes for a few checks);
- three checks in a row found nothing new (**It stopped finding anything new**);
- Prometheus couldn't be reached twice in a row (**Couldn't reach Prometheus**);
- the AI provider failed or answered unreadably twice (**The AI model didn't answer**);
- you click **Stop**.

Every ending keeps the steps so far. After a stop forced by the limits, it is asked once, with no
more checks allowed, to write up what it found. If it doesn't, each distinct check becomes a step
and the dialog says the model didn't write up its steps.

## What the steps mean

- **Worth a look**: it checked and found something that changed at or before the problem started.
- **Ruled out**: it checked, and this isn't it.
- **Your step**: something it can't reach, with what to run.
- **From a past case**: a closed case with the same symptom and how it was fixed.

Every step it checked links to the check behind it (**Show query**). A step that claims a check or
past case the investigation doesn't have is marked **Not checked**, and one backed only by queries
that failed stays to check: a failed query rules nothing out. The summary says where to look, never
"the root cause is", and is left out when it cites a check or past case the investigation doesn't
have. A query that names a metric Prometheus doesn't have counts as failed, not as "no data", and
the model gets the service's real metric names back. A step for you whose query names such a metric
says so under the query. Only metric names are checked; a wrong label value still comes back as no
data. **Found where to look** needs a step worth a look that a check backs, or a step for you;
otherwise it says **Nothing found in metrics**.

## Save an investigation to a case

To keep an investigation, click **Save to a case**. It opens a case for the finding (or uses the
existing one), shows the investigation on the case's Investigation tab, and adds one line to the
case's notes ("Saved guided investigation #10 to this case"). Nothing else goes into your notes by
itself, and that line doesn't count as an investigation note: until someone saves one, the case's
**Next action** says to go through the investigation, lists the steps worth a look and the steps it
left for you, and opens the Investigation tab.

To use what it found in your notes, click **Use as note** under the investigation. It puts a draft
in the **Investigation note** box: where to look, the evidence, what was ruled out, what is still
to do (your steps, with their queries), what people marked, and a "What I found" line for you. The
draft is built from the investigation's own steps and checks, not by another AI call, and leaves
out steps nothing backs. Edit it, then click **Save Investigation**; text already in the box is
kept and the draft goes below it. **Draft from case** on the Root Cause tab then uses your saved
note; the root cause is still yours to write and save.

## Who can investigate?

Editors and Admins start, continue and stop investigations, mark steps and save them to a case.
Viewers can open saved investigations but not start one, since each round runs queries and calls the
AI provider.

## What is sent to the AI provider?

The finding's plain wording, the query that found it, changes recorded near its start, the team's
notes on the service, your note about today, and the results of each check (summarised, not the raw
points). Where it goes depends on the AI provider you configured: your own machine or a hosted
service.

## Which AI model to use for Investigate

Investigate asks the model to plan several checks, write valid PromQL, keep track of what it found
and finish with steps in a fixed format. That needs a model that **can call tools**, and it goes much
better with one that **thinks before it answers**. Size matters more than for the other AI features.

What we saw on 8 Nov 2026, with the same findings, code and limits for each model (lab services on a
laptop, synthetic metrics, no recorded deploys):

| Model | Where | What happened |
| --- | --- | --- |
| A small hosted model (the cheapest tier of a major provider) | API | 5 of 5 finished, about 13 s each, 5 to 6 checks of its own per finding, no failed checks. It compared related metrics at the onset, ruled things out with evidence and said "Nothing found in metrics" when that was true |
| `qwen3:14b` (thinks, calls tools) | Local, Ollama, 32 GB laptop | Runs checks of its own: 8 in a 5-minute round (settings below), at about 30 to 40 s per reply. Pauses more often (click **Continue**) and is weaker at choosing what to check than the hosted model |
| `qwen2.5:7b` | Local, Ollama | Ran almost no checks of its own; 2 of 5 rounds failed with replies that couldn't be read |
| `llama3.1:8b` | Local, Ollama | Put its answer inside a tool call and repeated the same check |
| `gemma3:4b` (no tool calling) | Local, Ollama | Runs with the checks asked for as JSON in its replies, but unreliably |

So:

- **Best results:** a hosted model that calls tools. Even a small, cheap one did well.
- **Local only:** a model of about 14B or more that calls tools and thinks, such as `qwen3:14b`,
  with the settings below. Expect a few minutes per round on a laptop.
- **Avoid for Investigate:** models of 8B or less, and models without tool calling. They are fine
  for the short AI texts elsewhere in Ops Signals, not for multi-step checks.

When a model goes wrong, the guards show it instead of hiding it: steps nothing backs are marked
**Not checked**, made-up metric names are flagged, a model that answers without checking is sent
back once, and a round that fails ends with **The AI model didn't answer** and the provider's error.

### Settings for a local model

| Setting | What it does | For a local model on a laptop |
| --- | --- | --- |
| `OPS_SIGNALS_AI_ENABLED`, `OPS_SIGNALS_AI_PROVIDER` | Turn AI on and pick the provider | `true`, `ollama` |
| `OPS_SIGNALS_OLLAMA_MODEL` | The model | `qwen3:14b` or larger |
| `OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS` | How long to wait for one reply | `120` to `300` |
| `OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS` | How long one round may run before it pauses (default 120) | `300` |

Restart the backend after changing them. A thinking model is asked not to think for the short AI
texts (root cause drafts, finding wording), so those stay quick; Investigate lets it think.

## Adding more sources

Today Investigate sees Prometheus metrics, recorded deploys and changes, past cases and other
findings. Logs, traces, Kubernetes events, database statistics or a service catalog are **not
connected yet**; when a step needs one, it becomes a step for you. Each source it could reach would
let it rule out more on its own.

Each check is a tool in `backend/app/investigation/tools.py` (`ToolBox`): a `ToolSpec` (name,
description for the model, JSON schema of its arguments) and a handler that returns a short text
result. The loop, the limits, the evidence references (c1, c2...), the repeat detection and the steps
work the same for any tool, so a new source is one new tool. A new tool should:

- be **read-only**, and limited in time range and result size, like the Prometheus checks;
- **summarise** what it found in a few lines instead of returning raw data;
- take its connection and credentials from Ops Signals' settings, never from the model;
- take the `purpose` argument every tool has, so the engineer sees why it ran.

## Current limitations

- Web UI only: the Grafana plugin has no Findings page yet.
- Only findings from Prometheus with a service can be investigated (not CSV or OTLP).
- Metrics, recorded deploys and past cases only: no logs, traces or database access (see
  [Adding more sources](#adding-more-sources)).
- The checks query the finding's Prometheus connection, with the backend's own access to it.
