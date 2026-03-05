import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WatchedMovie(Base):
    __tablename__ = "watched_movies"
    __table_args__ = (UniqueConstraint("user_id", "tmdb_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)
    watched_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source: Mapped[str] = mapped_column(String, server_default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class WatchlistMovie(Base):
    __tablename__ = "watchlist_movies"
    __table_args__ = (UniqueConstraint("watchlist_id", "tmdb_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    added_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String, server_default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
