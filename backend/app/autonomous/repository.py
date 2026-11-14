from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.models.entities import AutonomousMetricJobEntity, AutonomousPolicyEntity, AutonomousPolicyRunEntity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutonomousPolicyNotFoundError(Exception):
    pass


class AutonomousPolicyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        name: str,
        datasource: str,
        backend: str,
        scope: dict,
        monitoring_categories: dict,
        execution_policy: dict,
        schedule_minutes: int | None,
        connection_id: str = "default",
        created_by: str | None = None,
    ) -> AutonomousPolicyEntity:
        now = utc_now()
        enabled = schedule_minutes is not None
        policy = AutonomousPolicyEntity(
            id=uuid4().hex,
            name=name,
            datasource=datasource,
            backend=backend,
            connection_id=connection_id,
            scope_json=scope,
            monitoring_categories_json=monitoring_categories,
            execution_policy_json=execution_policy,
            enabled=enabled,
            schedule_minutes=schedule_minutes,
            next_run_at=(now + _minutes(schedule_minutes)) if enabled and schedule_minutes else None,
            consecutive_failures=0,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            edited_by=created_by,
            edited_at=now,
        )
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def get(self, policy_id: str) -> AutonomousPolicyEntity:
        policy = self.db.execute(select(AutonomousPolicyEntity).where(AutonomousPolicyEntity.id == policy_id)).scalar_one_or_none()
        if policy is None:
            raise AutonomousPolicyNotFoundError(policy_id)
        return policy

    def list(self, *, limit: int = 50) -> list[AutonomousPolicyEntity]:
        query = select(AutonomousPolicyEntity).order_by(AutonomousPolicyEntity.updated_at.desc()).limit(limit)
        return list(self.db.execute(query).scalars().all())

    def list_due(self, *, now: datetime) -> list[AutonomousPolicyEntity]:
        query = select(AutonomousPolicyEntity).where(
            AutonomousPolicyEntity.enabled.is_(True),
            AutonomousPolicyEntity.schedule_minutes.is_not(None),
            AutonomousPolicyEntity.next_run_at.is_not(None),
            AutonomousPolicyEntity.next_run_at <= now,
        )
        return list(self.db.execute(query).scalars().all())

    def claim_due(self, policy: AutonomousPolicyEntity, *, now: datetime) -> bool:
        """Claims a due policy for this backend by moving next_run_at one interval ahead, but only if
        it is still due. When several backends share the database, exactly one of them gets True for
        each due run; the others see next_run_at already in the future and skip it. A row lock would
        not do here: the run commits several times, which would release it before the run ends."""
        claimed = self.db.execute(
            update(AutonomousPolicyEntity)
            .where(
                AutonomousPolicyEntity.id == policy.id,
                AutonomousPolicyEntity.enabled.is_(True),
                AutonomousPolicyEntity.next_run_at <= now,
            )
            .values(next_run_at=now + _minutes(policy.schedule_minutes))
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        return claimed.rowcount == 1

    def update_config(
        self,
        policy_id: str,
        *,
        scope: dict,
        monitoring_categories: dict,
        execution_policy: dict,
        schedule_minutes: int | None,
        connection_id: str = "default",
        edited_by: str | None = None,
    ) -> AutonomousPolicyEntity:
        """Full edit - always sent together, mirrors what the "Save & Schedule" form submits."""
        policy = self.get(policy_id)
        policy.connection_id = connection_id
        policy.scope_json = scope
        policy.monitoring_categories_json = monitoring_categories
        policy.execution_policy_json = execution_policy
        policy.schedule_minutes = schedule_minutes
        policy.enabled = schedule_minutes is not None
        policy.next_run_at = utc_now() + _minutes(schedule_minutes) if schedule_minutes else None
        policy.updated_at = utc_now()
        policy.edited_by = edited_by
        policy.edited_at = policy.updated_at
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def set_enabled(self, policy_id: str, *, enabled: bool, edited_by: str | None = None) -> AutonomousPolicyEntity:
        """Pause ("Remove") or resume a schedule without discarding its configuration."""
        policy = self.get(policy_id)
        policy.enabled = enabled
        if enabled and policy.schedule_minutes:
            policy.next_run_at = utc_now() + _minutes(policy.schedule_minutes)
        else:
            policy.next_run_at = None
        policy.updated_at = utc_now()
        policy.edited_by = edited_by
        policy.edited_at = policy.updated_at
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def record_run_result(
        self,
        policy_id: str,
        *,
        status: str,
        ran_at: datetime,
    ) -> AutonomousPolicyEntity:
        """Advances next_run_at and the failure streak after a scheduled run completes."""
        policy = self.get(policy_id)
        policy.last_run_status = status
        policy.consecutive_failures = 0 if status != "failed" else policy.consecutive_failures + 1
        if policy.enabled and policy.schedule_minutes:
            policy.next_run_at = ran_at + _minutes(policy.schedule_minutes)
        policy.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def delete(self, policy_id: str) -> None:
        policy = self.get(policy_id)
        self.db.delete(policy)
        self.db.commit()


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


class AutonomousPolicyRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_run(
        self,
        *,
        policy_id: str | None,
        trigger: str,
        policy_snapshot: dict,
        metrics_discovered: int,
        metrics_selected: int,
        jobs_planned: int,
    ) -> AutonomousPolicyRunEntity:
        now = utc_now()
        run = AutonomousPolicyRunEntity(
            id=uuid4().hex,
            policy_id=policy_id,
            trigger=trigger,
            status="planned",
            policy_snapshot_json=policy_snapshot,
            metrics_discovered=metrics_discovered,
            metrics_selected=metrics_selected,
            jobs_planned=jobs_planned,
            created_at=now,
            updated_at=now,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_running(self, run_id: str) -> AutonomousPolicyRunEntity:
        run = self.get_run(run_id)
        run.status = "running"
        run.started_at = run.started_at or utc_now()
        run.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_completed(
        self,
        run_id: str,
        *,
        status: str,
        jobs_completed: int,
        jobs_skipped: int,
        jobs_failed: int,
        findings_created: int,
        error_summary: str | None = None,
        jobs_not_checked: int | None = None,
    ) -> AutonomousPolicyRunEntity:
        run = self.get_run(run_id)
        run.status = status
        if jobs_not_checked is not None:
            # Kept in the snapshot JSON rather than a new column; a new dict so the change is saved.
            run.policy_snapshot_json = {**(run.policy_snapshot_json or {}), "jobs_not_checked": jobs_not_checked}
        run.completed_at = utc_now()
        run.jobs_completed = jobs_completed
        run.jobs_skipped = jobs_skipped
        run.jobs_failed = jobs_failed
        run.findings_created = findings_created
        run.error_summary = error_summary
        run.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, run_id: str) -> AutonomousPolicyRunEntity:
        run = self.db.execute(select(AutonomousPolicyRunEntity).where(AutonomousPolicyRunEntity.id == run_id)).scalar_one()
        return run

    def list_runs(
        self,
        *,
        status: str | None = None,
        policy_id: str | None = None,
        limit: int = 50,
    ) -> list[AutonomousPolicyRunEntity]:
        query = select(AutonomousPolicyRunEntity)
        if status:
            query = query.where(AutonomousPolicyRunEntity.status == status)
        if policy_id:
            query = query.where(AutonomousPolicyRunEntity.policy_id == policy_id)
        return list(self.db.execute(query.order_by(AutonomousPolicyRunEntity.created_at.desc()).limit(limit)).scalars().all())


class AutonomousJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_jobs(self, jobs: list[AutonomousMetricJobEntity]) -> list[AutonomousMetricJobEntity]:
        self.db.add_all(jobs)
        self.db.commit()
        for job in jobs:
            self.db.refresh(job)
        return jobs

    def mark_running(self, job_id: str) -> AutonomousMetricJobEntity:
        job = self.get_job(job_id)
        job.status = "running"
        job.started_at = job.started_at or utc_now()
        job.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_completed(
        self,
        job_id: str,
        *,
        analysis_run_id: str,
        duration_ms: int,
    ) -> AutonomousMetricJobEntity:
        job = self.get_job(job_id)
        job.status = "completed"
        job.analysis_run_id = analysis_run_id
        job.completed_at = utc_now()
        job.duration_ms = duration_ms
        job.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_skipped(self, job_id: str, *, reason_code: str, reason_detail: str | None = None) -> AutonomousMetricJobEntity:
        job = self.get_job(job_id)
        job.status = "screened_out"
        job.skip_reason_code = reason_code
        job.skip_reason_detail = reason_detail
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_failed(
        self,
        job_id: str,
        *,
        error_type: str,
        error_message: str,
        duration_ms: int | None = None,
        error_code: str | None = None,
    ) -> AutonomousMetricJobEntity:
        job = self.get_job(job_id)
        job.status = "failed"
        job.error_type = error_type
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = utc_now()
        job.duration_ms = duration_ms
        job.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def increment_retry(self, job_id: str) -> AutonomousMetricJobEntity:
        job = self.get_job(job_id)
        job.retry_count += 1
        job.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> AutonomousMetricJobEntity:
        job = self.db.execute(select(AutonomousMetricJobEntity).where(AutonomousMetricJobEntity.id == job_id)).scalar_one()
        return job

    def get_jobs_for_run(self, policy_run_id: str) -> list[AutonomousMetricJobEntity]:
        query = select(AutonomousMetricJobEntity).where(AutonomousMetricJobEntity.policy_run_id == policy_run_id)
        return list(self.db.execute(query.order_by(AutonomousMetricJobEntity.created_at.asc())).scalars().all())

