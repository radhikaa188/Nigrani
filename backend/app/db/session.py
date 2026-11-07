"""
Database engine and session management for Nigrani platform database.
"""

from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import settings


def get_normalized_database_url(url: str | None = None) -> str:
    """Returns database URL formatted for psycopg3 driver."""
    db_url = url or settings.DATABASE_URL
    if not db_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5433")
        user = os.getenv("POSTGRES_USER", "nigrani_app")
        password = os.getenv("POSTGRES_PASSWORD", "nigrani_dev_password")
        db_name = os.getenv("POSTGRES_DB", "nigrani")
        db_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"  # pragma: allowlist secret

    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return db_url


DATABASE_URL = get_normalized_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
