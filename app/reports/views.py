from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db
from app.reports import schemas, services

router = APIRouter()


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def report_user(
    request: Request,
    body: schemas.ReportUserRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flag a user for objectionable content / abusive behavior.

    Per App Store Review Guideline 1.2, all reports are reviewed and
    actioned within 24 hours.
    """
    services.create_report(
        reporter_id=user_id,
        reported_user_id=body.reported_user_id,
        reason=body.reason,
        db=db,
    )
    return None
