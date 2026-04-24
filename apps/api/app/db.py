from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.models import Base

_ENGINE = None
_SESSION_LOCAL = None


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def init_db(settings: Settings | None = None) -> None:
    global _ENGINE, _SESSION_LOCAL
    settings = settings or get_settings()
    _ENGINE = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))
    _SESSION_LOCAL = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(_ENGINE)


def get_session_local():
    global _SESSION_LOCAL
    if _SESSION_LOCAL is None:
        init_db()
    return _SESSION_LOCAL


def get_db() -> Generator[Session, None, None]:
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()
