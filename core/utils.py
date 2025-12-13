"""
Utility functions for HOT-Crypto.

Provides common utilities including:
- Logging setup
- Time helpers
- Configuration loading
"""

import logging
import os
from datetime import datetime
from typing import Optional

import yaml


def setup_logging(
    level: str = "INFO",
    log_format: Optional[str] = None,
) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_format: Custom log format string

    Returns:
        Configured root logger
    """
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    log_level = os.getenv("LOG_LEVEL", level)
    logging.basicConfig(level=log_level, format=log_format)
    return logging.getLogger("hot-crypto")


def load_yaml_config(filepath: str) -> dict:
    """
    Load a YAML configuration file.

    Args:
        filepath: Path to the YAML file

    Returns:
        Parsed configuration dict
    """
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.utcnow()


def ms_to_datetime(ms: int) -> datetime:
    """Convert millisecond timestamp to datetime."""
    return datetime.utcfromtimestamp(ms / 1000)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to millisecond timestamp."""
    return int(dt.timestamp() * 1000)
