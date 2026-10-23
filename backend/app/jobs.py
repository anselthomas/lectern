"""Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import Job


def enqueue(db: Session, type_: str, **payload) -> Job:
    job = Job(type=type_, payload={k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                                   for k, v in payload.items()})
    db.add(job)
    return job


def claim(db: Session) -> Job | None:
    row = db.execute(text(
        """
        UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs WHERE status = 'pending' AND run_after <= now()
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
        ) RETURNING id
        """
    )).first()
    db.commit()
    return db.get(Job, row[0]) if row else None


def finish(db: Session, job: Job, error: str | None = None, max_attempts: int = 3) -> None:
    if error is None:
        job.status = "done"
        job.error = None
    elif job.attempts < max_attempts:
        job.status = "pending"
        job.error = error[:4000]
        job.run_after = datetime.now(timezone.utc) + timedelta(seconds=30 * job.attempts)
    else:
        job.status = "failed"
        job.error = error[:4000]
    db.commit()


def release_stale(db: Session, minutes: int = 45) -> None:
    db.execute(text("UPDATE jobs SET status = 'pending' WHERE status = 'running' "
                    "AND locked_at < now() - make_interval(mins => :m)"), {"m": minutes})
    db.commit()
