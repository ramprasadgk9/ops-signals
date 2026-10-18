"""Turns uploaded incident exports into standard incident records.

Every source - a Jira or PagerDuty CSV export, a generic CSV, a folder of Markdown postmortems -
goes through a profile that maps its columns or sections onto the same fields. The import service
(service.py) only ever sees IncidentRecord, so adding a source means adding a profile, nothing else.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import PurePosixPath

import yaml

from backend.app.case_import.redaction import redact

FIELDS = (
    "source_id",
    "title",
    "service",
    "started_at",
    "resolved_at",
    "severity",
    "symptom",
    "root_cause",
    "corrective_action",
    "outcome",
    "notes",
    "source_url",
    "tags",
)
REQUIRED_FIELDS = ("title", "service", "started_at", "root_cause")
SETTINGS_FILE_NAMES = {"ops-signals-import.yaml", "ops-signals-import.yml"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}
MAX_TEXT_CHARS = 20_000
MAX_RECORDS = 20_000
MAX_ZIP_ENTRIES = 5_000
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


class ImportSettingsError(ValueError):
    """Raised for settings a user supplied that cannot be applied, such as an unknown profile."""


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    kind: str  # "csv" or "markdown"
    default_source: str
    # Field -> normalized header names, most specific first. Markdown profiles use these for
    # frontmatter keys.
    columns: dict[str, tuple[str, ...]]
    checklist: tuple[str, ...]


_GENERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "source_id": ("id", "incident_id", "key", "issue_key", "ticket", "reference"),
    "title": ("title", "name", "incident", "incident_title", "headline", "subject"),
    "service": ("service", "services", "component", "components", "application", "app", "system"),
    "started_at": ("started_at", "start", "start_time", "started", "date", "created", "created_at", "incident_start", "opened_at"),
    "resolved_at": ("resolved_at", "resolved", "end", "end_time", "ended_at", "closed_at", "incident_end"),
    "severity": ("severity", "sev", "priority", "urgency"),
    "symptom": ("symptom", "symptoms", "summary", "impact", "description", "what_happened"),
    "root_cause": ("root_cause", "rootcause", "cause", "rca", "root_cause_summary"),
    "corrective_action": ("fix", "corrective_action", "resolution", "remediation", "mitigation", "action_taken"),
    "outcome": ("outcome", "result", "follow_up", "lessons", "lessons_learned"),
    "notes": ("notes", "timeline", "comments", "details"),
    "source_url": ("url", "link", "source_url", "incident_url", "html_url"),
    "tags": ("tags", "labels"),
}

PROFILES: dict[str, Profile] = {
    "markdown": Profile(
        id="markdown",
        label="Markdown postmortems",
        kind="markdown",
        default_source="markdown",
        columns=_GENERIC_COLUMNS,
        checklist=(
            "One postmortem per .md file, upload several files or a .zip.",
            "Add frontmatter with id, title, service and started_at (see the example).",
            "Use headings named Summary, Root cause, Resolution, Outcome and Timeline.",
            "Remove customer names, emails and credentials before exporting.",
        ),
    ),
    "generic-csv": Profile(
        id="generic-csv",
        label="Other CSV",
        kind="csv",
        default_source="csv",
        columns=_GENERIC_COLUMNS,
        checklist=(
            "One incident per row with a header row, UTF-8 encoded.",
            "Include id, title, service, started_at and root_cause columns at minimum.",
            "Prefer ISO 8601 dates such as 2025-03-14T18:20:00Z; dates without a zone are read as UTC.",
            "Start from the CSV template if your columns have different names.",
        ),
    ),
    "jira-csv": Profile(
        id="jira-csv",
        label="Jira CSV export",
        kind="csv",
        default_source="jira",
        columns={
            "source_id": ("issue_key",),
            "title": ("summary",),
            "service": ("component_s", "custom_field_service", "custom_field_affected_service", "custom_field_services"),
            "started_at": ("custom_field_incident_start", "custom_field_start_time", "created"),
            "resolved_at": ("custom_field_incident_end", "custom_field_end_time", "resolved"),
            "severity": ("custom_field_severity", "priority"),
            "symptom": ("custom_field_impact", "description"),
            "root_cause": ("custom_field_root_cause", "custom_field_rootcause", "custom_field_cause", "root_cause"),
            "corrective_action": (
                "custom_field_corrective_action",
                "custom_field_fix",
                "custom_field_resolution_details",
                "custom_field_remediation",
                "custom_field_mitigation",
            ),
            "outcome": ("custom_field_outcome", "custom_field_follow_up", "custom_field_lessons_learned"),
            "notes": ("custom_field_timeline",),
            "source_url": ("custom_field_url",),
            "tags": ("labels",),
        },
        checklist=(
            "Filter with JQL, for example issuetype = Postmortem AND resolution IS NOT EMPTY.",
            "Add your root cause and fix fields as columns before exporting, or choose Export CSV (all fields).",
            "Components become the service; map names like Checkout to checkout-api with service aliases.",
            "Jira dates carry no time zone and are read as UTC.",
        ),
    ),
    "pagerduty-csv": Profile(
        id="pagerduty-csv",
        label="PagerDuty CSV export",
        kind="csv",
        default_source="pagerduty",
        columns={
            "source_id": ("id", "incident_id", "incident_number"),
            "title": ("title", "description"),
            "service": ("service_name", "service"),
            "started_at": ("created_on", "created_at", "created"),
            "resolved_at": ("resolved_on", "resolved_at", "resolved"),
            "severity": ("urgency", "priority"),
            "symptom": ("summary",),
            "root_cause": ("root_cause", "custom_field_root_cause"),
            "corrective_action": ("resolution", "fix", "corrective_action"),
            "outcome": ("outcome",),
            "notes": ("notes",),
            "source_url": ("html_url", "url", "incident_url"),
            "tags": (),
        },
        checklist=(
            "Export resolved incidents only.",
            "The console export may not include notes, so add a root_cause column before uploading.",
            "service_name becomes the service; it should match the service label in your metrics.",
        ),
    ),
}


@dataclass
class ImportSettings:
    profile: str | None = None
    source: str | None = None
    column_map: dict[str, str] = field(default_factory=dict)
    service_aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ImportSettings":
        data = data or {}
        if not isinstance(data, dict):
            raise ImportSettingsError("settings must be an object")
        unknown = set(data) - {"profile", "source", "column_map", "service_aliases"}
        if unknown:
            raise ImportSettingsError(f"unknown settings: {', '.join(sorted(unknown))}")
        settings = cls(
            profile=data.get("profile") or None,
            source=data.get("source") or None,
            column_map=dict(data.get("column_map") or {}),
            service_aliases={str(k): str(v) for k, v in (data.get("service_aliases") or {}).items()},
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.profile and self.profile not in PROFILES:
            raise ImportSettingsError(f"unknown profile '{self.profile}', expected one of {', '.join(PROFILES)}")
        bad_fields = set(self.column_map) - set(FIELDS)
        if bad_fields:
            raise ImportSettingsError(f"column_map has unknown fields: {', '.join(sorted(bad_fields))}")

    def merged_over(self, base: "ImportSettings") -> "ImportSettings":
        """These settings, falling back to `base` for anything not set here."""
        return ImportSettings(
            profile=self.profile or base.profile,
            source=self.source or base.source,
            column_map={**base.column_map, **self.column_map},
            service_aliases={**base.service_aliases, **self.service_aliases},
        )


@dataclass
class IncidentRecord:
    ref: str
    source: str
    source_id: str | None = None
    title: str = ""
    service: str = ""
    services: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    severity: str = ""
    symptom: str = ""
    root_cause: str = ""
    corrective_action: str = ""
    outcome: str = ""
    notes: list[str] = field(default_factory=list)
    source_url: str = ""
    tags: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    redactions: int = 0

    @property
    def identity_id(self) -> str | None:
        """The source's own ID, or a fingerprint of title, start time and service when the record
        has none - so re-uploading the same ID-less file still matches the case it created."""
        if self.source_id:
            return self.source_id
        if not (self.title and self.started_at and self.service):
            return None
        basis = f"{self.title.strip().lower()}|{self.started_at.strftime('%Y-%m-%dT%H:%M')}|{self.service.strip().lower()}"
        return "fp-" + hashlib.sha256(basis.encode()).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        content = {
            "title": self.title,
            "service": self.service,
            "services": self.services,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "severity": self.severity,
            "symptom": self.symptom,
            "root_cause": self.root_cause,
            "corrective_action": self.corrective_action,
            "outcome": self.outcome,
            "notes": self.notes,
            "source_url": self.source_url,
            "tags": self.tags,
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


@dataclass
class ParsedUpload:
    records: list[IncidentRecord] = field(default_factory=list)
    file_profiles: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    settings: ImportSettings = field(default_factory=ImportSettings)


def parse_files(files: list[tuple[str, bytes]], settings: ImportSettings) -> ParsedUpload:
    """Parses uploaded files (CSV, Markdown, or .zip archives of them) into incident records.

    An ops-signals-import.yaml among the files supplies default settings; `settings` passed in
    explicitly (from the wizard or API) take precedence over it.
    """
    settings.validate()
    upload = ParsedUpload()
    expanded = _expand_archives(files, upload.warnings)

    file_settings = ImportSettings()
    data_files: list[tuple[str, bytes]] = []
    for name, data in expanded:
        if PurePosixPath(name).name.lower() in SETTINGS_FILE_NAMES:
            try:
                file_settings = ImportSettings.from_dict(yaml.safe_load(data.decode("utf-8-sig")) or {})
            except (yaml.YAMLError, UnicodeDecodeError, ImportSettingsError) as exc:
                raise ImportSettingsError(f"{name}: {exc}") from exc
        else:
            data_files.append((name, data))
    upload.settings = settings.merged_over(file_settings)

    for name, data in data_files:
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in MARKDOWN_SUFFIXES | {".csv"} and _looks_binary(data):
            # Latin-1 decodes any bytes, so an image or a spreadsheet saved as .csv used to import as
            # 0 records with no warning (QA-42).
            upload.warnings.append(f"Skipped {name}: it isn't a text file. Export it as CSV (UTF-8) or Markdown.")
            continue
        if suffix in MARKDOWN_SUFFIXES:
            upload.file_profiles[name] = "markdown"
            upload.records.append(_parse_markdown(name, _decode(data), upload.settings))
        elif suffix == ".csv":
            text = _decode(data)
            rows = list(csv.reader(io.StringIO(text)))
            if not rows:
                upload.warnings.append(f"Skipped {name}: the file is empty.")
                continue
            profile = PROFILES[upload.settings.profile] if upload.settings.profile else detect_csv_profile(rows[0])
            if profile.kind != "csv":
                raise ImportSettingsError(f"profile '{profile.id}' cannot read CSV file {name}")
            records = _parse_csv(name, rows, profile, upload.settings)
            if not records:
                upload.warnings.append(f"Skipped {name}: it has a header row but no incidents.")
                continue
            upload.file_profiles[name] = profile.id
            upload.records.extend(records)
        else:
            upload.warnings.append(
                f"Skipped {name}: only .md, .markdown, .csv, .zip and ops-signals-import.yaml files are read."
            )
        if len(upload.records) > MAX_RECORDS:
            raise ImportSettingsError(f"upload has more than {MAX_RECORDS} records; split it into smaller imports")
    return upload


def detect_csv_profile(header: list[str]) -> Profile:
    headers = {_normalize(column) for column in header}
    if {"issue_key", "summary"} <= headers:
        return PROFILES["jira-csv"]
    if "incident_number" in headers or ({"service_name", "urgency"} <= headers):
        return PROFILES["pagerduty-csv"]
    return PROFILES["generic-csv"]


def _expand_archives(files: list[tuple[str, bytes]], warnings: list[str]) -> list[tuple[str, bytes]]:
    expanded: list[tuple[str, bytes]] = []
    for name, data in files:
        if PurePosixPath(name).suffix.lower() != ".zip":
            expanded.append((name, data))
            continue
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ImportSettingsError(f"{name} is not a readable zip file") from exc
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ImportSettingsError(f"{name} has more than {MAX_ZIP_ENTRIES} files")
        if sum(info.file_size for info in entries) > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ImportSettingsError(f"{name} expands to more than {MAX_ZIP_UNCOMPRESSED_BYTES} bytes")
        for info in entries:
            parts = PurePosixPath(info.filename).parts
            if parts[0] == "__MACOSX" or any(part.startswith(".") for part in parts):
                continue
            expanded.append((info.filename, archive.read(info)))
    return expanded


def _looks_binary(data: bytes) -> bool:
    """NUL bytes or many control characters near the start: not text in any encoding a CSV or
    Markdown export uses (UTF-8, or Latin-1 from older Windows tools)."""
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    control = sum(1 for byte in sample if byte < 32 and byte not in (9, 10, 12, 13))
    return control > len(sample) // 20


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header).strip().lower()).strip("_")


def _parse_csv(name: str, rows: list[list[str]], profile: Profile, settings: ImportSettings) -> list[IncidentRecord]:
    header = [_normalize(column) for column in rows[0]]
    columns = _columns_for(profile, settings)
    records: list[IncidentRecord] = []
    for line_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        # Jira repeats a header once per value for multi-value fields (Component/s, Labels), so
        # collect every non-empty cell under its header instead of keeping only the last.
        values: dict[str, list[str]] = {}
        for column, cell in zip(header, row):
            if cell.strip():
                values.setdefault(column, []).append(cell.strip())
        raw = {field_name: _first_present(values, aliases) for field_name, aliases in columns.items()}
        record = IncidentRecord(ref=f"{name} row {line_number}", source=settings.source or profile.default_source)
        _fill_record(record, raw, settings)
        records.append(record)
    return records


def _columns_for(profile: Profile, settings: ImportSettings) -> dict[str, tuple[str, ...]]:
    columns = dict(profile.columns)
    for field_name, header in settings.column_map.items():
        columns[field_name] = (_normalize(header),)
    return columns


def _first_present(values: dict[str, list[str]], aliases: tuple[str, ...]) -> list[str]:
    for alias in aliases:
        if alias in values:
            return values[alias]
    return []


_SECTION_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("root_cause", ("root cause", "why it happened", "contributing factor", "cause")),
    ("corrective_action", ("corrective", "resolution", "remediation", "mitigation", "fix")),
    ("outcome", ("outcome", "lessons", "follow-up", "follow up")),
    ("symptom", ("summary", "impact", "symptom", "what happened", "overview", "description")),
)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _parse_markdown(name: str, text: str, settings: ImportSettings) -> IncidentRecord:
    record = IncidentRecord(ref=name, source=settings.source or PROFILES["markdown"].default_source)
    frontmatter, body = _split_frontmatter(text)
    if frontmatter is None:
        frontmatter = {}
    elif not isinstance(frontmatter, dict):
        record.problems.append("frontmatter is not a key: value block")
        frontmatter = {}

    raw: dict[str, list[str]] = {}
    keys = {_normalize(key): value for key, value in frontmatter.items()}
    columns = _columns_for(PROFILES["markdown"], settings)
    for field_name, aliases in columns.items():
        for alias in aliases:
            if alias in keys and keys[alias] not in (None, ""):
                raw[field_name] = _as_list(keys[alias])
                break
    if not settings.source and keys.get("source"):
        record.source = str(keys["source"]).strip()

    title, sections, preamble = _split_sections(body)
    if "title" not in raw and title:
        raw["title"] = [title]
    # Frontmatter values win over body sections; several sections with the same meaning (two
    # "Root cause" headings) are joined.
    from_body: set[str] = set()
    for heading, section_text in sections:
        if not section_text:
            continue
        target = _section_field(heading)
        if target is None:
            raw.setdefault("notes", []).append(f"{heading}: {section_text}")
        elif target not in raw or target in from_body:
            raw.setdefault(target, []).append(section_text)
            from_body.add(target)
    if "symptom" not in raw and preamble:
        raw["symptom"] = [preamble]

    _fill_record(record, raw, settings)
    return record


def _split_frontmatter(text: str) -> tuple[object | None, str]:
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            try:
                return yaml.safe_load("\n".join(lines[1:index])), "\n".join(lines[index + 1 :])
            except yaml.YAMLError:
                return "invalid", "\n".join(lines[index + 1 :])
    return None, text


def _split_sections(body: str) -> tuple[str, list[tuple[str, str]], str]:
    """Returns the first H1 (if any), each (heading, text) for H2+ sections, and any text that sits
    between the H1 and the first H2."""
    title = ""
    sections: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match and len(match.group(1)) == 1 and not title and not sections:
            title = match.group(2).strip()
        elif match and len(match.group(1)) <= 3:
            sections.append((match.group(2).strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return title, [(heading, "\n".join(lines).strip()) for heading, lines in sections], "\n".join(preamble).strip()


def _section_field(heading: str) -> str | None:
    lowered = heading.lower()
    for field_name, keywords in _SECTION_FIELDS:
        if any(keyword in lowered for keyword in keywords):
            return field_name
    return None


def _as_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in value if item not in (None, "")]
    return [_scalar(value)]


def _scalar(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _fill_record(record: IncidentRecord, raw: dict[str, list[str]], settings: ImportSettings) -> None:
    def text(field_name: str) -> str:
        joined = "\n\n".join(value for value in raw.get(field_name, []) if value)
        cleaned, count = redact(joined[:MAX_TEXT_CHARS])
        record.redactions += count
        return cleaned.strip()

    id_values = raw.get("source_id") or []
    record.source_id = id_values[0] if id_values else None
    record.title = text("title")
    record.severity = text("severity")
    record.symptom = text("symptom")
    record.root_cause = text("root_cause")
    record.corrective_action = text("corrective_action")
    record.outcome = text("outcome")
    record.source_url = (raw.get("source_url") or [""])[0]
    for note in raw.get("notes", []):
        cleaned, count = redact(note[:MAX_TEXT_CHARS])
        record.redactions += count
        if cleaned.strip():
            record.notes.append(cleaned.strip())

    record.services = _dedupe(_alias(service, settings.service_aliases) for service in _split_list(raw.get("service", [])))
    record.service = record.services[0] if record.services else ""
    record.tags = _dedupe(_split_list(raw.get("tags", [])))

    for field_name in ("started_at", "resolved_at"):
        values = raw.get(field_name) or []
        if not values:
            continue
        parsed = parse_datetime(values[0])
        if parsed is None:
            record.problems.append(f"unreadable {field_name}: '{values[0]}'")
        setattr(record, field_name, parsed)

    for field_name in REQUIRED_FIELDS:
        if not getattr(record, field_name) and not any(p.startswith(f"unreadable {field_name}") for p in record.problems):
            record.problems.append(f"missing {field_name}")


def _split_list(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        items.extend(part.strip().strip("[]").strip() for part in re.split(r"[;,]", value))
    return [item for item in items if item]


def _alias(service: str, aliases: dict[str, str]) -> str:
    if service in aliases:
        return aliases[service]
    lowered = {key.lower(): value for key, value in aliases.items()}
    return lowered.get(service.lower(), service)


def _dedupe(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


_DATE_FORMATS = (
    "%d/%b/%y %I:%M %p",
    "%d/%b/%Y %I:%M %p",
    "%d/%b/%y %H:%M",
    "%d/%b/%y",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
    "%d %b %Y %H:%M",
    "%d %b %Y",
    "%b %d, %Y",
)


def parse_datetime(value: str) -> datetime | None:
    """Reads ISO 8601 and the common export formats (Jira's 14/Mar/25 6:20 PM among them). Values
    without a time zone are taken as UTC."""
    value = value.strip()
    if not value:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for date_format in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(value, date_format)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
