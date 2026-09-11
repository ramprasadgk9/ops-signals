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

## Retrieval

- **Cases**: semantic search against the same Qdrant collection (`operational_cases`) case memory
  already populates, with keyword-overlap search as a fallback if semantic search is unavailable.
- **Findings and behaviors**: semantic search via a lazy indexer (`EvidenceMemoryIndexer`) that
  embeds a row into its own Qdrant collection the first time it's searched, not on write - the
  core analysis pipeline is untouched by this. Repeat queries hit the vector store directly.
- **Documentation**: semantic search over `operational_intelligence_docs` - generated concept
  docs plus every Markdown file under `docs/` (recursively) and `README.md`. Long documents are
  chunked rather than truncated, so a 30,000-character doc is fully searchable, not just its first
  few paragraphs.

## Answer Synthesis

When evidence is found and an LLM is configured, `synthesize_from_evidence()` asks the model to
answer strictly from the retrieved evidence - explicitly instructed not to invent facts, and to
say so plainly if the evidence only partially answers the question. If the LLM is disabled, fails,
or there's no evidence at all, the response falls back to a fixed, deterministic template built
directly from the evidence fields. Every response carries `ai_synthesis_used` so it's never
ambiguous which path produced it - the UI shows this as an "AI-generated" vs. "Evidence summary
(no AI)" label.

This same `synthesize_from_evidence()` method is shared with the separate autonomous-run Q&A
endpoint (`/api/autonomous/questions/answer`) - one reasoning layer, not two independently
maintained ones with diverging answer quality.

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

## Follow-Up Suggestions

Suggested follow-up questions are generated from the top retrieved source's actual title,
service, and metric name (e.g. "What analyzer detected the request_latency_p95 change?"), not
generic instruction phrases. A generic phrase like "Show related cases" carries no real search
terms, so the next query built from it has nothing meaningful to match against - it isn't a real
question, it's an instruction with nowhere to go.

## Quality Benchmarking

See `benchmark/README.md`. As of this writing there is no dedicated benchmark for answer
groundedness or hallucination rate specifically - routing, retrieval, and detection accuracy are
covered; assistant answer quality is the one piece of this architecture without automated,
known-answer validation.
