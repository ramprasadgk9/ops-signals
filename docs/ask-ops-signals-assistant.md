# Ask Ops Signals: Assistant Architecture

The "Ask Ops Signals" chat is a retrieval-and-explanation layer over the application's own
operational data and documentation - not a general-purpose chatbot. It works with zero AI
configuration (deterministic retrieval + template answers) and gets better, not different, when
pointed at a local model.

## Why It's Built This Way

Every layer here follows the same rule: an optional, smarter path can only *add* to the
deterministic baseline, never replace or weaken it. A weak or unavailable model degrades
gracefully back to the same explainable behavior the app has without AI at all - it never leaves
the user with less evidence than the deterministic path alone would have found.

## Routing

`OperationalIntelligenceAssistant._route()` decides which evidence sources a question needs
(cases, findings, behaviors, memory, documentation, analyzers) using keyword matching. If an LLM
is configured, its classification is *added* to the keyword result - it can broaden which sources
get searched, but it can never narrow the keyword router's own baseline coverage. This is
deliberate: an under-confident small local model dropping a category (e.g. classifying "how does
X work" as behavior-only, missing that it's also a documentation question) must not cause the
system to silently lose evidence a plain keyword match would have found.

What leads the answer follows the first route. Quoted text is ignored when routing - in
`Tell me about the finding "... baseline shift ..."` the title names a finding, it doesn't ask for
analyzer docs - and data-health phrasing ("did any metric stop reporting?") or "the finding" puts
the findings search first. Each source appears once: documentation is searched once even when both
the analyzer and docs routes fire, Operational Memory never repeats a case the case search already
returned, and duplicate findings collapse. When a question names a service the recent findings
have ("What changed recently on trend-lab?"), the findings search is limited to that service.

Documentation is searched for every question, not only the ones the router sends there: "What
outcome categories can a resolved case have?" routes to cases, but its answer is in the docs.
Documentation found this way is placed after the routed evidence, and only a real match counts -
the generic "architecture overview" fallback query is used only when the router chose
documentation. The keyword router ignores the product's own name, so "How do I deploy Ops Signals?"
is not read as a question about signals.

## Retrieval

- **Cases**: semantic search against the same Qdrant collection (`operational_cases`) case memory
  already populates, with keyword-overlap search as a fallback if semantic search is unavailable.
- **Findings and behaviors**: semantic search via a lazy indexer (`EvidenceMemoryIndexer`) that
  embeds a row into its own Qdrant collection the first time it's searched, not on write - the
  core analysis pipeline is untouched by this. Repeat queries hit the vector store directly.
- **Documentation**: semantic search over `operational_intelligence_docs` - generated concept
  docs plus every Markdown file under `docs/` (recursively, excluding `docs/archive/`) and
  `README.md`. Each Markdown section is its own chunk of at most 900 characters, embedded with its
  heading path ("Security model > Turning on authentication"); a longer section is split on
  paragraph boundaries into windows that keep the heading. The size matters: the embedding model
  (`all-MiniLM-L6-v2`) reads 256 tokens, about 1,000 characters, and silently ignores the rest.
  Documentation search uses one score floor (0.3) for every client, whatever `minimum_score` the
  client sends - that field is the case-memory threshold.

Every documentation source carries `source_path`, `section`, and a `reference` that links to the
section (`docs/security-model.md#turning-on-authentication`, GitHub's anchor for the heading).

Documentation results are reranked before the answer uses them: a section whose heading shares the
question's words gets a small bonus (0.05 at most), and design and proposal docs under
`docs/design/` count 0.9 of their score, so a plan's "non-goals" section no longer outranks the
README's setup section for "Where do I point my OTel Collector?". Both values were chosen by
sweeping the golden set; larger heading bonuses put more right docs first but made quoted answers
worse. A heading-only search entry per section was also tried and made both worse, so it isn't
used.

"Which analyzers are there?" asks for a list no single quoted sentence holds, so it is answered
from the analyzer registry: the "What Are Analyzers?" document leads and quotes its catalog - every
registered analyzer with what it finds - word for word. Analyzer pages carry only what is specific
to each analyzer; lines that read the same on every page are left out.

## Adding Documentation

Put the file under `docs/` (anywhere except `docs/archive/`) or edit `README.md`, then either
restart the backend or click **Reindex docs** on the Ask Ops Signals page. The page shows when that
is needed: `GET /api/assistant/knowledge/status` compares the docs on disk with the index by content
hash (about 20 ms, nothing embedded) and returns `pending_changes`; when there are any, the button
carries their count and a banner names the docs. The **?** next to the button explains it to people
who haven't met the word "reindex". The button calls:

```bash
curl -X POST http://localhost:8001/api/assistant/knowledge/bootstrap
```

(add `-H "Authorization: Bearer $OPS_SIGNALS_API_TOKEN"` when a token is set). Only documents that
were added, edited or removed are re-embedded; the rest are skipped by content hash, so a reindex
with nothing changed takes milliseconds. The response lists what happened:

```json
{"added": ["docs/new-feature.md"], "changed": ["docs/security-model.md"], "removed": [],
 "unchanged_documents": 63, "chunks_embedded": 21, "duration_ms": 410}
```

`GET /api/assistant/knowledge/status` returns the same record for the most recent run as
`last_bootstrap`. `?force=true` re-embeds everything. A change to chunking (`INDEX_VERSION` in
`knowledge_bootstrap.py`) or to the embedding model does that automatically on the next run.

A new doc is searchable at once, but nothing checks that it is answered well until it has golden
questions. **Docs check** is for that.

## Docs Check

`/assistant/docs-check` in the web UI, linked from the reindex result as **Test the new docs →**:

1. **Docs** lists every doc under `README.md` and `docs/` with how many golden questions cite it and
   which sections none do; docs the last reindex added or changed come first.
2. **Draft questions** writes questions for a doc's untested sections. With AI, the model writes one
   informal question per section plus a phrase copied from it; a phrase that isn't really in the
   section is dropped. Without AI, a plain question per heading. Everything stays editable.
3. **Ask** runs the question through the assistant and shows whether it cited the section you
   expect, or which one it cited instead, with the quote.
4. Mark it **Good** or **Wrong** and **Save**. The page previews the YAML it will append to
   `benchmark/assistant/golden_questions.yml` - checked by the server the same way
   `tests/test_assistant_golden.py` will check it - and appends it. A question the assistant gets
   wrong today is saved as `category: known_gap`: recorded and reported, not scored, so a known
   failure never breaks the build; the benchmark report says when one starts passing.

Saving writes a file, so it needs `OPS_SIGNALS_ALLOW_FILE_WRITES=true` (the dev scripts set it) and a
checkout that has `benchmark/` - packaged images don't. Without it the page still drafts and asks.
Commit the updated golden file with your doc.

API: `GET /api/assistant/docs-check/coverage`, `POST .../draft`, `POST .../evaluate`, and
`POST .../tests` (`dry_run: true` returns the YAML without writing and needs no file writes).

## Answer Feedback

Every answer asks "Did this answer your question?". A thumbs-down asks why (wrong section, missing a
step, outdated, not in the docs). Both are stored in `ops_assistant_feedback` with the question and
what was cited (`POST /api/assistant/feedback`, `PATCH /api/assistant/feedback/{id}`). The person who
answered is never sent anywhere else.

Open thumbs-down questions, grouped by question, are listed on the Docs check page under **Flagged
by users** (`GET /api/assistant/feedback/flagged`) - the most direct evidence of a question the
assistant gets wrong. **Add as test** turns one into a golden question for the doc and section that
should answer it and marks its feedback `added_as_test`; **Dismiss** marks it `dismissed`. Where file
writes are on, the Ask Ops Signals page links to them ("3 questions flagged as not answered").

## Answer Synthesis

Answers about documentation quote the passage they rest on, with its citation:

~~~text
From Security model > Turning on authentication (docs/security-model.md#turning-on-authentication):
> Set one shared token:
> ```bash
> export OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"
> ```
~~~

- **Without AI**, `select_passage()` (`backend/app/assistant/passages.py`) picks the sentence,
  list item, table row or code block of the matched section closest to the question - by
  embedding similarity plus word overlap, weighted towards exact identifiers such as env var
  names - and widens it where it needs context: a lead-in ending in ":" brings its code block, a
  list item brings the rest of a short list. The quote is the section's own text, word for word.
  Each source's `quote` field carries it too, and the web UI shows it on the source card.
- **With AI**, the model gets the evidence numbered and is told to answer in 1-3 sentences, then
  quote its supporting passages as `[n] "exact text"`. Each quote is checked against evidence item
  n (`quote_is_in()`, ignoring case, whitespace and Markdown). A quote that isn't there is dropped
  and logged; one that is gets its citation from source n's own metadata, never from the model.
  When no quote survives, the top source's deterministic quote is added instead, so an AI answer
  about documentation always shows its passage.

If the LLM is disabled, fails, or there's no evidence at all, the response uses the deterministic
answer. Every response carries `ai_synthesis_used` so it's never ambiguous which path produced it -
the UI shows this as an "AI-generated" vs. "Evidence summary (no AI)" label.

`synthesize_from_evidence()` is shared with the separate autonomous-run Q&A endpoint
(`/api/autonomous/questions/answer`); that endpoint does not use the quoting described above.

## Enabling Local AI

No API key, no cloud calls. Bundle a local model via Ollama:

```bash
docker compose --profile ai up -d   # opt-in - not started by a plain `docker compose up`
```

Then point the backend at it (env vars, or `ai:` in `config.yaml`):

```bash
OPS_SIGNALS_AI_ENABLED=1 OPS_SIGNALS_AI_PROVIDER=ollama OPS_SIGNALS_OLLAMA_MODEL=<model-you-have-pulled>
```

Any Ollama chat-capable model works - there's no dependency on a specific one, and the routing
safety net above means a smaller/weaker model degrades in quality of prose, not correctness of
what evidence gets found.

## First-Screen Examples

"What can I ask?" splits its example questions in two. **About Ops Signals** is a fixed list answered
from the docs, which are always there. **About your systems** comes from
`GET /api/assistant/starter-questions`, built from what this install has analysed: the service with
the most recent findings ("What changed recently on payments-api?"), the newest finding and case by
title, and "Did any metric stop reporting?". A question whose source is missing is left out, and
the placeholder service `unknown` is never named. With nothing analysed yet, the card offers
**Load demo data** and **Connect a source** instead of questions that could only come back empty.
Examples avoid dates ("yesterday"), which the assistant can't filter by yet, and "what caused",
which it can't claim.

## Follow-Up Suggestions

Suggested follow-up questions are generated from the top retrieved source's actual title,
service, and metric name (e.g. "What analyzer detected the request_latency_p95 change?"), not
generic instruction phrases. A generic phrase like "Show related cases" carries no real search
terms, so the next query built from it has nothing meaningful to match against - it isn't a real
question, it's an instruction with nowhere to go.

## Quality Benchmarking

`benchmark/assistant/golden_questions.yml` holds known-answer questions about the documentation:
for each, the file and section that answers it and phrases the answer must contain.
`python -m benchmark.assistant_benchmark` indexes the real corpus with the real embedding model
into an in-memory Qdrant, asks each question once per client surface (web, Grafana, API/MCP, with
the `top_k`/`minimum_score` each sends), and reports:

| Metric | Passes when |
| --- | --- |
| `doc_hit@1`, `doc_hit@3` | an expected file is the first / in the first three documentation sources |
| `section_hit@3` | an expected file *and section* is in the first three |
| `evidence_has_answer` | every expected phrase is in the evidence the LLM is given |
| `answer_has_answer` | every expected phrase is in the answer returned with AI off |

`--ai` runs the same questions through the configured LLM and also counts quotes the model made up.
Questions with `category: out_of_scope` (nothing in the docs answers them) or `known_gap` (saved
from Docs check while the assistant still gets them wrong) are reported but not scored.
`tests/test_assistant_golden.py` fails the build when the golden set no longer matches the docs (a
section was renamed or its answer removed) or when a metric drops below its recorded floor.

The golden set covers documentation answers only. Answers built from findings, cases and behaviors
- which need an analysed dataset - are not benchmarked yet.
