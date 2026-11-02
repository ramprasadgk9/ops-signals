# Vision

**No team should debug the same incident twice.** We want a future where the person on call opens a
problem and already knows what changed, whether it has happened before, what fixed it last time and
what to try next, even at 3 a.m., even in their first week, even when everyone who fixed it before
has moved on.

This page is about where Ops Signals is going. For what it does today, see the
[README](../README.md) and the [UI tour](ui-tour.md).

## Why This Matters

Monitoring has become very good at telling teams **that** something changed. It is still poor at
telling them **what it means** and **what to do about it**. That knowledge lives in people's heads,
old Slack threads and closed tickets, and it leaves when people go off shift, change teams or leave.

So teams pay for the same incident again and again: the same hours of digging, the same wrong
guesses, the same fix found again by someone new. The cost isn't the outage alone. It's
everything the team has already learned and then forgotten. Keeping that knowledge is how
Ops Signals cuts the time to resolve an incident (MTTR): fewer pages for known noise, and a head
start on the real ones.

## Where We're Going

Each shift starts from something Ops Signals already does and says where we want to take it. The
**Next** parts are direction, not features: none of them is built yet.

### 1. From "what changed" to "what to do next"

**Today:** a finding explains the change in plain words and points to the past case that fixed
something similar.

**Next:** the steps that worked before become a suggested playbook for the new problem: check this,
then this, then try this fix. A person approves every step; Ops Signals never acts on its own.

### 2. Analyzers that get better from feedback

**Today:** several analyzers look at each metric, picked by the shape of its data. Teams can tune
them per service, and each finding can be marked right or wrong. The analyzers are tested against
data where the right answer is known.

**Next:** we keep adding and updating analyzers based on that feedback: the problems they missed,
the false alarms they raised, and the symptoms teams had to spot by hand. The aim is findings that
pick out the real symptom of a problem more often, with each release saying what got better.

### 3. From reacting to alerts to seeing problems coming

**Today:** scheduled analysis checks your metrics and posts important findings to Slack, often
before any alert fires. Ops Signals also groups problems that keep coming back and flags a problem
that returns after its fix.

**Next:** it recognises the early shape of a known problem ("this looks like the start of last
month's outage") and says so before anyone is paged.

### 4. Every incident leaves the team smarter

**Today:** cases record the root cause and the fix, and new findings show when the same thing was
seen before.

**Next:** someone new to the team starts with the team's whole history of problems and fixes, and
what one team learns can help another team that hits the same problem.

### 5. Trust that is earned, not assumed

**Today:** each finding shows how often findings for that metric turned out to be real, from your
team's answers, and an alerting tool can ask whether an alert looks real or like known noise before
it pages anyone.

**Next:** Ops Signals learns which findings matter to each team, gets quieter about the ones that
don't, and shows why it changed its mind.

### 6. Memory that works where people already are

**Today:** Ops Signals runs as its own web UI and inside Grafana, sends to Slack, and answers AI
tools through its MCP server.

**Next:** chat tools, ticket systems and AI agents use Ops Signals memory as their source of facts
about past incidents, so every answer they give is grounded in what really happened, with people
still in control.

### 7. Open at any size

**Today:** self-hosted, MIT-licensed and vendor-neutral, running as a single instance.

**Next:** several instances share the work for very large metric volumes, and the community adds
analyzers and integrations as easily as the core team does.

## What Won't Change

- **It works without AI.** Every core feature stays deterministic and explainable
  ([ADR-007](adr/ADR-007-deterministic-answer-composition.md)). AI can help with drafts and
  wording; it is never required.
- **People decide.** Ops Signals suggests and explains. People approve, act and close cases.
- **Your data is the record.** Decisions come from what is stored in PostgreSQL; search only helps
  find similar past cases.
- **Plain words first.** Say what happened in everyday words; keep the statistics in the details.
- **Open and neutral.** Self-hosted, open source, works with any Prometheus-compatible backend or
  OpenTelemetry, and favours no commercial vendor.

## What We Won't Become

- **An autopilot.** Ops Signals won't change your systems on its own.
- **Another monitoring stack.** It builds on Prometheus, Grafana and OpenTelemetry; it doesn't
  replace them.
- **A guessing machine.** It won't claim a root cause from similarity alone: a past case is a lead
  to check, not proof.
- **An oracle.** The assistant explains what is stored; it doesn't invent answers.

## Where We Are Now

Ops Signals already explains metric changes in plain words, links them to deploys, keeps cases and
shows when a problem was seen before, and runs as a web UI or a Grafana app plugin. The
[README](../README.md) has the full list; [roadmap.md](roadmap.md) has what's planned next.

## Help Shape It

The vision is set in the open. Share ideas in
[Discussions → Ideas](https://github.com/ramprasadgk9/ops-signals/discussions/categories/ideas);
how decisions are made is in [GOVERNANCE.md](../GOVERNANCE.md).
