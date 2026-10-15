from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_recycle=1800,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_DEEP_HEALTH_TIMEOUT_SECONDS = 2


def ping_database() -> None:
    """SELECT 1 on the app engine URL, with a 2s connect and statement timeout."""
    probe = create_engine(
        engine.url,
        poolclass=NullPool,
        connect_args={"connect_timeout": _DEEP_HEALTH_TIMEOUT_SECONDS},
    )
    try:
        with probe.connect() as conn:
            conn.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": str(_DEEP_HEALTH_TIMEOUT_SECONDS * 1000)},
            )
            conn.execute(text("SELECT 1"))
    finally:
        probe.dispose()


class Base(DeclarativeBase):
    pass
