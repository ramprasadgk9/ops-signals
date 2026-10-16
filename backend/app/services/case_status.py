"""A case's status, worked out from what has been recorded on it, and kept in its stored column.

The Cases API used to derive the status only when building its response and never save it, so the
stored case_status stayed "open" for good. Everything that reads the column - Overview's open
cases, recurring problems, similar-case results, the MCP tools, "this fix worked before" (which
only learns from resolved cases) and memory's search payload - saw a resolved case as open.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import OperationalCaseEntity

logger = logging.getLogger(__name__)

# An outcome that ends the case. Recording one is the user saying the case is done, so it closes
# the case even when the root cause isn't verified; the UI then marks it "Root cause unconfirmed".
# The resolution endpoint already requires a learning outcome for exactly these.
CLOSING_OUTCOMES = {"resolved", "mitigated", "won_t_fix"}


def _filled(value: str | None) -> bool:
    return value is not None and len(value.strip()) > 0


def derive_case_status(case: OperationalCaseEntity) -> tuple[str, str]:
    """(case_status, investigation_status) from the case's fields:

    1. Investigation notes exist → investigation_status "in_progress".
    2. RCA and a corrective action exist → case_status "in_progress".
    3. A closing outcome (resolved, mitigated, won't fix) is recorded, or the RCA is verified and
       a corrective action and an outcome summary exist → "resolved" / "completed". The second
       half is the original rule, kept so no case resolved under it reopens.

    The case status always starts from "open", never from the stored value: a case whose RCA is
    later un-verified goes back, instead of staying resolved. The investigation status starts
    from the stored one, which is what the user picked. Imported cases arrive resolved from their
    postmortem and keep their stored statuses.
    """
    if case.is_imported:
        return case.case_status, case.investigation_status

    case_status = "open"
    investigation_status = case.investigation_status
    if case.investigation_notes:
        investigation_status = "in_progress"

    has_rca = _filled(case.root_cause_summary)
    has_resolution = _filled(case.corrective_action)
    closing_outcome = (case.outcome_status or "").lower() in CLOSING_OUTCOMES
    if closing_outcome or (case.root_cause_verified and has_resolution and _filled(case.outcome_summary)):
        case_status = "resolved"
        investigation_status = "completed"
    elif has_rca and has_resolution:
        case_status = "in_progress"
    return case_status, investigation_status


def sync_case_status(case: OperationalCaseEntity) -> bool:
    """Writes the derived case status to the case's column; True if it changed. The caller commits.
    resolved_at is left alone: the learning service sets it when an outcome is recorded."""
    case_status, _ = derive_case_status(case)
    if case.case_status == case_status:
        return False
    case.case_status = case_status
    return True


def backfill_case_statuses(db: Session) -> int:
    """Corrects cases saved while the status was never stored. A changed case already in memory is
    marked stale, so re-indexing gives its search entry the new status. Returns how many changed."""
    changed = 0
    for case in db.execute(select(OperationalCaseEntity)).scalars():
        if sync_case_status(case):
            changed += 1
            if case.memory_status == "indexed":
                case.memory_status = "stale"
    if changed:
        db.commit()
        logger.info("Corrected the stored status of %d case(s)", changed)
    return changed
