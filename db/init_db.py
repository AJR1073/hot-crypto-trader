"""
Database initialization utilities.

Provides functions for:
- Getting database URL from environment
- Creating database engine and tables
- Getting database sessions
"""

import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .base import Base
from .models import OHLCV, BacktestRun, BacktestTrade  # noqa: F401 - ensure models are registered

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "sqlite:///data/hot_crypto.db"


def get_db_url(db_url: Optional[str] = None) -> str:
    """
    Get the database URL.

    Priority:
    1. Explicit db_url argument
    2. HOT_CRYPTO_DB_URL environment variable
    3. Default SQLite path

    Args:
        db_url: Optional explicit database URL

    Returns:
        Database URL string
    """
    if db_url:
        return db_url
    return os.getenv("HOT_CRYPTO_DB_URL", DEFAULT_DB_URL)


def init_db(db_url: Optional[str] = None):
    """
    Initialize the database, creating tables if they don't exist.

    For SQLite databases, also ensures the directory exists.

    Args:
        db_url: Optional database URL override
        
    Returns:
        SQLAlchemy Engine instance
    """
    url = get_db_url(db_url)
    logger.info(f"Initializing database: {url}")
    
    # For SQLite, ensure directory exists
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "")
        if not db_path.startswith(":"):  # Not an in-memory DB
            db_dir = Path(db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured directory exists: {db_dir}")
    
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(engine)
    
    logger.info("Database tables created successfully")
    return engine


def get_session(db_url: Optional[str] = None) -> Session:
    """
    Create a new database session.

    Args:
        db_url: Optional database URL override

    Returns:
        SQLAlchemy Session instance
    """
    url = get_db_url(db_url)
    engine = create_engine(url, echo=False)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def get_engine(db_url: Optional[str] = None):
    """
    Get a database engine.

    Args:
        db_url: Optional database URL override

    Returns:
        SQLAlchemy Engine instance
    """
    url = get_db_url(db_url)
    return create_engine(url, echo=False)


if __name__ == "__main__":
    # Allow running as script: python -m db.init_db
    logging.basicConfig(level=logging.INFO)
    engine = init_db()
    print(f"Database initialized: {get_db_url()}")
