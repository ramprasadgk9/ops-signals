# Investigate a finding

**Investigate** on a finding card asks an AI model to check what it can and suggest where to look
next. It runs read-only checks against the finding's Prometheus, the deploys recorded for the
service and past cases, then lists steps: what it checked and found, what you need to check
yourself, and what a past case suggests. It never claims a root cause: you confirm one.

It needs an AI provider (see [Where AI is used](ai-features.md)). Everything else on a finding works
without one.

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
- it has asked the model 8 times or run for 2 minutes in one round (**Paused**);
- three checks in a row found nothing new (**It stopped finding anything new**);
- Prometheus couldn't be reached twice in a row (**Couldn't reach Prometheus**);
- the AI provider failed or answered unreadably twice (**The AI model didn't answer**);
- you click **Stop**.

Every ending keeps the steps so far. After a stop forced by the limits, it is asked once, with no
more checks allowed, to write up what it found.

## What the steps mean

- **Worth a look**: it checked and found something that changed at or before the problem started.
- **Ruled out**: it checked, and this isn't it.
- **Your step**: something it can't reach, with what to run.
- **From a past case**: a closed case with the same symptom and how it was fixed.

Every step it checked links to the check behind it (**Show query**). A step that claims a check or
past case the investigation doesn't have is marked **Not checked**. The summary says where to look,
never "the root cause is".

## Save an investigation to a case

To keep an investigation, click **Save to a case**. It opens a case for the finding (or uses the
existing one) and adds an investigation note with what people marked **Found something**, what was
ruled out and their notes. The case's Investigation tab shows the investigation. **Draft from case**
on the Root Cause tab can then use the note; the root cause is still yours to write and save.

## Who can investigate?

Editors and Admins start, continue and stop investigations, mark steps and save them to a case.
Viewers can open saved investigations but not start one, since each round runs queries and calls the
AI provider.

## What is sent to the AI provider?

The finding's plain wording, the query that found it, changes recorded near its start, the team's
notes on the service, your note about today, and the results of each check (summarised, not the raw
points). Where it goes depends on the AI provider you configured: your own machine or a hosted
service.

It works best with a strong model that can call tools. A local model without tool calling (Ollama's
`gemma3`, for example) still runs, with the checks asked for as JSON in its replies, but less
reliably. Small local models often lose track over several checks or answer in plain text instead of
the steps; then the round ends with **The AI model didn't answer**, with the provider's error.

## Current limitations

- Web UI only: the Grafana plugin has no Findings page yet.
- Only findings from Prometheus with a service can be investigated (not CSV or OTLP).
- Metrics only: no logs, traces or database access.
- The checks query the finding's Prometheus connection, with the backend's own access to it.
