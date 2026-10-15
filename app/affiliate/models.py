import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WatchProviderCache(Base):
    __tablename__ = "watch_provider_cache"

    media_type: Mapped[str] = mapped_column(Text, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
