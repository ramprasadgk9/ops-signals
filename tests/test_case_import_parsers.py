from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backend.app.case_import.parsers import ImportSettings, parse_files
from backend.app.case_import.redaction import redact

FIXTURES = Path(__file__).parent / "fixtures" / "case_import"
TEMPLATES = Path(__file__).resolve().parents[1] / "backend" / "app" / "case_import" / "templates"


def _read(path: Path) -> tuple[str, bytes]:
    return path.name, path.read_bytes()


def test_generic_csv_template_maps_every_field() -> None:
    parsed = parse_files([_read(TEMPLATES / "incident-template.csv")], ImportSettings())

    assert parsed.file_profiles == {"incident-template.csv": "generic-csv"}
    assert len(parsed.records) == 2
    first = parsed.records[0]
    assert first.problems == []
    assert first.source == "csv"
    assert first.source_id == "INC-1001"
    assert first.title == "Checkout latency spike during evening peak"
    assert first.service == "checkout-api"
    assert first.started_at == datetime(2025, 3, 14, 18, 20, tzinfo=timezone.utc)
    assert first.resolved_at == datetime(2025, 3, 14, 19, 5, tzinfo=timezone.utc)
    assert first.severity == "SEV2"
    assert "connection pool exhausted" in first.root_cause
    assert first.corrective_action.startswith("Restored max connections")
    assert first.outcome.startswith("Latency back to baseline")
    assert first.notes and "config rolled back" in first.notes[0]
    assert first.source_url == "https://example.com/incidents/INC-1001"


def test_markdown_postmortem_uses_frontmatter_and_sections() -> None:
    parsed = parse_files([_read(TEMPLATES / "example-postmortem.md")], ImportSettings())

    assert parsed.file_profiles == {"example-postmortem.md": "markdown"}
    record = parsed.records[0]
    assert record.problems == []
    assert record.source == "postmortems"
    assert record.source_id == "PM-2025-007"
    assert record.service == "search-api"
    assert record.tags == ["search", "elasticsearch"]
    assert record.symptom.startswith("About 30% of search requests")
    assert record.root_cause.startswith("The nightly index rebuild")
    assert record.corrective_action.startswith("Pointed the alias back")
    assert record.outcome.startswith("Results recovered")
    assert any("14:10 alias reverted" in note for note in record.notes)


def test_markdown_without_frontmatter_falls_back_to_h1_and_needs_service() -> None:
    text = "# Cache stampede\n\n## Root cause\n\nTTL expiry aligned across all keys.\n"
    parsed = parse_files([("cache.md", text.encode())], ImportSettings())

    record = parsed.records[0]
    assert record.title == "Cache stampede"
    assert record.root_cause == "TTL expiry aligned across all keys."
    assert "missing service" in record.problems
    assert "missing started_at" in record.problems


def test_jira_export_is_detected_and_merges_repeated_columns() -> None:
    parsed = parse_files([_read(FIXTURES / "jira-export.csv")], ImportSettings())

    assert parsed.file_profiles == {"jira-export.csv": "jira-csv"}
    first = parsed.records[0]
    assert first.source == "jira"
    assert first.source_id == "OPS-412"
    assert first.service == "Checkout"
    assert first.services == ["Checkout", "Payments"]
    assert first.tags == ["incident", "sev2"]
    assert first.started_at == datetime(2025, 3, 14, 18, 20, tzinfo=timezone.utc)
    assert first.severity == "High"
    assert first.root_cause.startswith("New release read a feature flag")
    assert first.corrective_action.startswith("Added the flag")


def test_jira_row_without_root_cause_is_reported_not_dropped_silently() -> None:
    parsed = parse_files([_read(FIXTURES / "jira-export.csv")], ImportSettings())

    missing = [record for record in parsed.records if record.source_id == "OPS-420"][0]
    assert missing.problems == ["missing root_cause"]
    assert missing.ref == "jira-export.csv row 4"


def test_pagerduty_export_is_detected() -> None:
    parsed = parse_files([_read(FIXTURES / "pagerduty-export.csv")], ImportSettings())

    assert parsed.file_profiles == {"pagerduty-export.csv": "pagerduty-csv"}
    first = parsed.records[0]
    assert first.source == "pagerduty"
    assert first.source_id == "Q1ABC23"
    assert first.service == "orders-api"
    assert first.severity == "high"
    assert first.source_url == "https://acme.pagerduty.com/incidents/Q1ABC23"
    assert first.root_cause.startswith("Expired TLS certificate")


def test_service_aliases_and_column_map_override_profile() -> None:
    csv_text = (
        "Issue key,Summary,Created,Component/s,Custom field (Why it happened)\n"
        "OPS-1,Queue backlog,2025-01-02 10:00,Checkout,Consumer crashed on a bad message\n"
    )
    settings = ImportSettings(
        column_map={"root_cause": "Custom field (Why it happened)"},
        service_aliases={"Checkout": "checkout-api"},
    )
    parsed = parse_files([("jira.csv", csv_text.encode())], settings)

    record = parsed.records[0]
    assert record.problems == []
    assert record.service == "checkout-api"
    assert record.root_cause == "Consumer crashed on a bad message"


def test_record_without_id_gets_a_stable_fingerprint() -> None:
    text = (
        "---\ntitle: Disk full\nservice: metrics-store\nstarted_at: 2025-02-01T10:00:00Z\n---\n\n"
        "## Root cause\n\nRetention job stopped.\n"
    )
    first = parse_files([("a.md", text.encode())], ImportSettings()).records[0]
    renamed = parse_files([("renamed.md", text.encode())], ImportSettings()).records[0]

    assert first.source_id is None
    assert first.identity_id.startswith("fp-")
    assert first.identity_id == renamed.identity_id


def test_content_hash_changes_only_when_content_changes() -> None:
    template = _read(TEMPLATES / "incident-template.csv")
    again = parse_files([template], ImportSettings()).records[0]
    first = parse_files([template], ImportSettings()).records[0]
    assert first.content_hash == again.content_hash

    edited_bytes = template[1].replace(b"lowered max connections", b"cut max connections")
    edited = parse_files([(template[0], edited_bytes)], ImportSettings()).records[0]
    assert edited.content_hash != first.content_hash


def test_zip_upload_is_expanded() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("postmortems/example.md", (TEMPLATES / "example-postmortem.md").read_text())
        archive.writestr("postmortems/notes.txt", "ignored")
        archive.writestr("__MACOSX/postmortems/._example.md", "junk")
    parsed = parse_files([("export.zip", buffer.getvalue())], ImportSettings())

    assert [record.source_id for record in parsed.records] == ["PM-2025-007"]
    assert any("notes.txt" in warning for warning in parsed.warnings)


def test_settings_file_inside_upload_is_applied() -> None:
    settings_yaml = b"service_aliases:\n  Checkout: checkout-api\n"
    parsed = parse_files(
        [("ops-signals-import.yaml", settings_yaml), _read(FIXTURES / "jira-export.csv")],
        ImportSettings(),
    )
    assert parsed.records[0].service == "checkout-api"


def test_imported_text_is_redacted() -> None:
    parsed = parse_files([_read(FIXTURES / "jira-export.csv")], ImportSettings())

    first, second = parsed.records[0], parsed.records[1]
    assert "alice@example.com" not in first.symptom
    assert "[email]" in first.symptom
    assert first.redactions == 1
    assert "10.2.3.4" not in second.root_cause
    assert "[ip]" in second.root_cause


def test_redact_masks_common_secrets() -> None:
    text = (
        "token=abc123def456 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig "
        "key AKIAABCDEFGHIJKLMNOP slack xoxb-1234-5678-abcdefgh github ghp_" + "a" * 36
    )
    cleaned, count = redact(text)

    assert "abc123def456" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "AKIAABCDEFGHIJKLMNOP" not in cleaned
    assert "xoxb-1234" not in cleaned
    assert "ghp_" not in cleaned
    assert count == 5
