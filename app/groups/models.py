import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    watchlist_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class BlendPick(Base):
    __tablename__ = "blend_picks"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pick_date: Mapped[date] = mapped_column(Date, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class BlendVeto(Base):
    __tablename__ = "blend_vetoes"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    veto_date: Mapped[date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
