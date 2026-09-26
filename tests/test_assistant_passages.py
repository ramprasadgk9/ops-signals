from __future__ import annotations

from backend.app.assistant.passages import quote_is_in, select_passage, split_units
from backend.app.assistant.schemas import AssistantEvidenceGroup, AssistantSource
from backend.app.assistant.service import OperationalIntelligenceAssistant

SECTION = """Set one shared token:

```bash
export OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"
```

After that, every request needs `Authorization: Bearer <token>`, except:

- `GET /api/health`, so load balancers and container health checks still work.
- The receivers: `POST /api/integrations/alertmanager` and `POST /api/events`.
  Each one checks its own token if you set one.

| Switch | Default |
| --- | --- |
| `OPS_SIGNALS_ALLOW_FILE_WRITES` | `false` |
"""


def test_units_keep_code_blocks_whole_and_join_wrapped_list_items() -> None:
    units = split_units(SECTION)

    assert units[1] == '```bash\nexport OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"\n```'
    assert units[4] == "- The receivers: `POST /api/integrations/alertmanager` and `POST /api/events`. Each one checks its own token if you set one."
    assert "| --- | --- |" not in units
    assert units[-1] == "| `OPS_SIGNALS_ALLOW_FILE_WRITES` | `false` |"


def test_a_named_identifier_picks_its_unit() -> None:
    assert select_passage("What does OPS_SIGNALS_ALLOW_FILE_WRITES default to?", SECTION) == "| `OPS_SIGNALS_ALLOW_FILE_WRITES` | `false` |"


def test_a_lead_in_is_quoted_with_the_code_block_it_introduces() -> None:
    quote = select_passage("How do I set one shared token?", SECTION)

    assert quote.startswith("Set one shared token:\n```bash\nexport OPS_SIGNALS_API_TOKEN")


def test_a_list_item_is_quoted_with_the_rest_of_its_list() -> None:
    quote = select_passage("Which endpoint do load balancers use?", SECTION)

    assert "GET /api/health" in quote and "POST /api/events" in quote


def test_quote_matching_ignores_case_whitespace_and_markdown() -> None:
    assert quote_is_in("every request needs Authorization: Bearer <token>", SECTION)
    assert quote_is_in("Set one   shared TOKEN ... every request needs", SECTION)
    assert not quote_is_in("every request needs a client certificate", SECTION)
    assert not quote_is_in("every request needs ... Set one shared token", SECTION)


def _doc(summary: str, quote: str | None = None) -> AssistantSource:
    return AssistantSource(
        source_type="app_documentation",
        title="Security model",
        section="Turning on authentication",
        score=0.6,
        reference="docs/security-model.md#turning-on-authentication",
        summary=summary,
        quote=quote,
    )


def test_an_llm_quote_that_is_in_its_source_is_kept_with_the_sources_citation() -> None:
    answer = 'Set OPS_SIGNALS_API_TOKEN.\n[1] "every request needs `Authorization: Bearer <token>`"'

    verified = OperationalIntelligenceAssistant._verify_llm_quotes(answer, [_doc(SECTION)])

    assert verified == (
        "Set OPS_SIGNALS_API_TOKEN.\n\n"
        "From Security model > Turning on authentication (docs/security-model.md#turning-on-authentication):\n"
        "> every request needs `Authorization: Bearer <token>`"
    )


def test_an_invented_llm_quote_is_replaced_by_the_sources_own_passage() -> None:
    answer = 'Use mutual TLS.\n[1] "Every client must present a certificate."'

    verified = OperationalIntelligenceAssistant._verify_llm_quotes(answer, [_doc(SECTION, quote="Set one shared token:")])

    assert "certificate" not in verified.split("\n\n", 1)[1]
    assert verified.endswith("> Set one shared token:")


def test_a_quote_attributed_to_the_wrong_source_is_dropped() -> None:
    other = AssistantSource(source_type="finding", title="cpu shifted", score=0.5, reference="/findings", summary="cpu went up")
    answer = 'Tokens.\n[1] "Set one shared token"'

    verified = OperationalIntelligenceAssistant._verify_llm_quotes(answer, [other, _doc(SECTION)])

    assert verified == "Tokens."


def test_the_template_answer_leads_with_the_quoted_passage_and_its_citation() -> None:
    group = AssistantEvidenceGroup(source_type="app_documentation", label="Documentation", count=1, sources=[_doc(SECTION, quote="Set one shared token:")])

    answer = OperationalIntelligenceAssistant._template_answer("How do I turn on auth?", [group])

    assert "From Security model > Turning on authentication (docs/security-model.md#turning-on-authentication):\n> Set one shared token:" in answer


def test_an_echoed_evidence_label_is_not_part_of_the_quote() -> None:
    answer = 'Tokens.\n[1] "Security model > Turning on authentication" (relevance 0.52): “Set one shared token”'

    verified = OperationalIntelligenceAssistant._verify_llm_quotes(answer, [_doc(SECTION)])

    assert verified.endswith("> Set one shared token")
