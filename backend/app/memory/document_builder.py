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

        return "\n".join(parts)

    @staticmethod
    def get_content_version() -> int:
        """Get current content version.

        Returns:
            Content version number
        """
        return CaseDocumentBuilder.CONTENT_VERSION
