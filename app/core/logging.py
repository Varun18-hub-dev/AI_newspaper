"""Centralized logging configuration."""

import logging
import sys


def setup_logger(name: str = "ai_newspaper", level: str = "INFO") -> logging.Logger:
    """Configures and returns a standardized logger.

    Args:
        name: Name of the logger.
        level: Logging level (e.g. DEBUG, INFO, WARNING, ERROR).

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
