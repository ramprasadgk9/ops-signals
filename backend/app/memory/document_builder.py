"""Document builder for operational case memory."""

from backend.app.models.entities import OperationalCaseEntity


class CaseDocumentBuilder:
    """Build deterministic text documents from operational cases for embedding."""

    CONTENT_VERSION = 1

    @staticmethod
    def build(case: OperationalCaseEntity) -> str:
        """Build a deterministic case document for embedding.

        Only includes meaningful operational information.
        Excludes raw time-series, raw JSON dumps, database IDs, and frontend labels.

        Args:
            case: The operational case entity

        Returns:
            Formatted text document for embedding
        """
        finding = case.finding_snapshot or {}
        if finding.get('source_type') == 'imported':
            return CaseDocumentBuilder._build_imported(case, finding)
        is_behavior = finding.get('source_type') == 'behavior'
        metric_label = ", ".join(finding.get('metric_names', [])) or finding.get('metric_name', 'unknown')

        parts = [
            "Operational Case",
            "",
            f"Service: {finding.get('service', 'unknown')}",
            f"Metric: {metric_label}",
            f"Category: {finding.get('category', 'unknown')}",
            f"Severity: {finding.get('health_status', 'unknown')}",
            f"Importance: {finding.get('importance_score', 0):.2f}",
            "",
            "Finding:" if not is_behavior else "Correlated Behavior:",
            finding.get('summary', ''),
            "",
        ]

        # Evidence section
        if is_behavior:
            evidence_facts = finding.get('evidence_facts', [])
            if evidence_facts:
                parts.append("Evidence:")
                parts.append(f"{len(evidence_facts)} correlated conditions matched across {metric_label}.")
                parts.append("")
        else:
            signal_ids = finding.get('signal_ids', [])
            if signal_ids:
                parts.append("Evidence:")
                parts.append(f"{len(signal_ids)} anomaly windows detected.")

                comparison_json = finding.get('comparison_json', {})
                if comparison_json:
                    if comparison_json.get('is_higher_than_previous'):
                        parts.append("Behavior differed from the previous comparison window.")
                    if comparison_json.get('has_stronger_trend'):
                        parts.append("The current trend was stronger than the previous trend.")

                parts.append("")

        return "\n".join(parts + CaseDocumentBuilder._resolution_sections(case))

    @staticmethod
    def _build_imported(case: OperationalCaseEntity, finding: dict) -> str:
        """An incident imported from a postmortem or incident tool has no metric, analyzer
        evidence or importance score - only what the postmortem said happened and why."""
        services = finding.get('services') or [finding.get('service', 'unknown')]
        origin = " ".join(part for part in (finding.get('source'), finding.get('source_id')) if part)
        parts = [
            f"Imported Incident ({origin or 'unknown source'})",
            "",
            f"Service: {', '.join(services)}",
        ]
        if finding.get('health_status'):
            parts.append(f"Severity: {finding['health_status']}")
        if finding.get('tags'):
            parts.append(f"Tags: {', '.join(finding['tags'])}")
        parts += ["", "Incident:", case.case_title]
        if finding.get('summary'):
            parts.append(finding['summary'])
        parts.append("")
        return "\n".join(parts + CaseDocumentBuilder._resolution_sections(case))

    @staticmethod
    def _resolution_sections(case: OperationalCaseEntity) -> list[str]:
        parts: list[str] = []

        # Investigation section (optional)
        if case.investigation_notes and len(case.investigation_notes) > 0:
            parts.append("Investigation:")
            investigation_summary = " ".join([
                note.get('note', '') 
                for note in case.investigation_notes 
                if note.get('note')
            ])
            if investigation_summary:
                parts.append(investigation_summary)
            parts.append("")

        # Root Cause Analysis section (optional, only when present)
        if case.root_cause_summary:
            parts.append("Root Cause Analysis:")
            parts.append(f"Status: {case.root_cause_status}")
            parts.append(case.root_cause_summary)
            if case.root_cause_verified:
                parts.append("(Verified)")
            if case.root_cause_confidence is not None:
                parts.append(f"Confidence: {case.root_cause_confidence:.2f}")
            parts.append("")

        # Corrective Action section (optional)
        if case.corrective_action:
            parts.append("Corrective Action:")
            parts.append(case.corrective_action)
            parts.append("")

        # Outcome section (optional)
        if case.outcome_summary:
            parts.append("Outcome:")
            parts.append(f"Status: {case.outcome_status}")
            parts.append(case.outcome_summary)
            parts.append("")

        # Write-up from Publish Knowledge (optional). A case without one builds the same text as
        # before, so CONTENT_VERSION stays and nothing is re-indexed.
        if case.writeup and case.writeup.strip():
            parts.append("Write-up:")
            parts.append(case.writeup.strip())
            parts.append("")

        return parts

    @staticmethod
    def build_symptom(case: OperationalCaseEntity) -> str:
        """What was seen, and nothing about why: the case's `symptom` vector. Same shape as the text
        a new finding searches with (seen_before.finding_query_text), so a finding is compared like
        for like - and a postmortem's symptom against a detected case's, without the template and
        resolution text that kept those two apart."""
        finding = case.finding_snapshot or {}
        if finding.get('source_type') == 'imported':
            services = ", ".join(finding.get('services') or [finding.get('service') or ''])
            return f"{services}: {case.case_title}. {finding.get('summary') or ''}".strip()
        metric = ", ".join(finding.get('metric_names', [])) or finding.get('metric_name') or ''
        title = finding.get('title') or case.case_title
        return f"{finding.get('service') or ''} {metric}: {title}. {finding.get('summary') or ''}".strip()

    @staticmethod
    def build_resolution(case: OperationalCaseEntity) -> str | None:
        """Why it happened and what fixed it: the case's `resolution` vector. None until the case
        has a root cause or a corrective action, so unresolved cases never match on fixes."""
        parts = []
        if case.root_cause_summary:
            parts.append(f"Cause: {case.root_cause_summary.strip()}")
        if case.corrective_action:
            parts.append(f"Fix: {case.corrective_action.strip()}")
        return " ".join(parts) or None

    @staticmethod
    def get_content_version() -> int:
        """Get current content version.

        Returns:
            Content version number
        """
        return CaseDocumentBuilder.CONTENT_VERSION
