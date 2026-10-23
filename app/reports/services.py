import uuid
from datetime import datetime, timedelta, timezone
from hashlib import blake2b

from fastapi import HTTPException, status
from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from app.reports.models import UserReport

# Minimum time between duplicate reports (same reporter + same reported user).
# Prevents flooding the table without blocking repeat reports indefinitely.
DUPLICATE_WINDOW = timedelta(hours=24)


def create_report(
    reporter_id: str, reported_user_id: str, reason: str, db: Session
) -> dict:
    """Persist a user report.

    - Rejects self-reports (400).
    - Silently no-ops (returns existing row) if the same reporter already
      reported the same user within the last 24 hours. This keeps the table
      lean without letting abusers game it.
    - Otherwise inserts a new `user_reports` row with `status='open'`.
    """
    try:
        reporter_uuid = uuid.UUID(reporter_id)
        reported_uuid = uuid.UUID(reported_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user id.",
        ) from exc

    if reporter_uuid == reported_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't report yourself.",
        )

    # Serialize the duplicate check and insert for this reporting pair. The
    # transaction-scoped advisory lock also makes concurrent callers safe on
    # deployments with multiple app instances.
    lock_bytes = reporter_uuid.bytes + reported_uuid.bytes
    lock_id = int.from_bytes(blake2b(lock_bytes, digest_size=8).digest(), "big") & (
        2**63 - 1
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    cutoff = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    existing = db.scalar(
        select(UserReport).where(
            and_(
                UserReport.reporter_id == reporter_uuid,
                UserReport.reported_id == reported_uuid,
                UserReport.created_at >= cutoff,
            )
        )
    )
    if existing is not None:
        return {"id": existing.id, "deduped": True}

    report = UserReport(
        reporter_id=reporter_uuid,
        reported_id=reported_uuid,
        reason=reason,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "deduped": False}
