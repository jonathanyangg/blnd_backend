from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.comments import schemas, services
from app.core.rate_limit import LIMIT_COMMENT, LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db

router = APIRouter()


@router.post(
    "/", response_model=schemas.CommentResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(LIMIT_COMMENT)
async def create_comment(
    request: Request,
    body: schemas.CreateCommentRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.create_comment(user_id, body.tmdb_id, body.body, db)


@router.get("/", response_model=schemas.CommentsListResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_comments(
    request: Request,
    tmdb_id: int = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_comments(user_id, tmdb_id, limit, offset, db)


@router.post(
    "/{comment_id}/reply",
    response_model=schemas.CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(LIMIT_COMMENT)
async def create_reply(
    request: Request,
    comment_id: int,
    body: schemas.CreateReplyRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.create_reply(user_id, comment_id, body.body, db)


@router.patch("/{comment_id}", response_model=schemas.CommentResponse)
@limiter.limit(LIMIT_DEFAULT)
async def edit_comment(
    request: Request,
    comment_id: int,
    body: schemas.EditCommentRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.edit_comment(user_id, comment_id, body.body, db)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def delete_comment(
    request: Request,
    comment_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_comment(user_id, comment_id, db)


@router.post("/{comment_id}/like", response_model=schemas.LikeResponse)
@limiter.limit(LIMIT_DEFAULT)
async def like_comment(
    request: Request,
    comment_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.like_comment(user_id, comment_id, db)


@router.delete("/{comment_id}/like", response_model=schemas.LikeResponse)
@limiter.limit(LIMIT_DEFAULT)
async def unlike_comment(
    request: Request,
    comment_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.unlike_comment(user_id, comment_id, db)
