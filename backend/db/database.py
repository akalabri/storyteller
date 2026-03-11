"""
Database engine and session factory.

Usage
-----
    from backend.db.database import get_db, init_db

    # On startup:
    init_db()

    # In a request handler:
    db = next(get_db())
    try:
        ...
    finally:
        db.close()
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as DBSession

from backend.config import DATABASE_URL
from backend.db.models import Base

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables (safe to call multiple times)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a DB session, auto-close when done. Use as a FastAPI dependency or manually."""
    db: DBSession = SessionLocal()
    try:
        yield db
    finally:
        db.close()

