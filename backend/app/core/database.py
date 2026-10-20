"""Synchronous SQLAlchemy engine and session factory."""

from sqlalchemy import Engine, create_engine
from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models and Alembic metadata."""


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None

if settings.database_url:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    """Yield a short-lived database session for a request."""
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with SessionLocal() as session:
        yield session
