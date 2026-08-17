from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import AutonomousMetricJobEntity, AutonomousPolicyRunEntity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    ) -> AutonomousPolicyRunEntity:
        run = self.get_run(run_id)
        run.status = status
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

