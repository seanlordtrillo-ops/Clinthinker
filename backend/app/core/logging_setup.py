from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "clinthinker"
LOG_FILENAME = "clinthinker.log"


def get_data_directory() -> Path:
    configured = os.environ.get("TOPIC_ASSISTANT_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        data_root = Path(local_app_data) if local_app_data else Path.home()
        return data_root / "Clinthinker©" / "storage"
    return Path(__file__).resolve().parents[2] / "storage"


def setup_logging(
    data_directory: str | os.PathLike[str] | None = None,
) -> logging.Logger:
    directory = (
        Path(data_directory).expanduser()
        if data_directory is not None
        else get_data_directory()
    )
    directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    expected_log_path = os.path.normcase(
        os.path.abspath(str(directory / LOG_FILENAME))
    )
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler)
    ]
    console_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, RotatingFileHandler)
    ]
    if (
        len(file_handlers) == 1
        and os.path.normcase(os.path.abspath(file_handlers[0].baseFilename))
        == expected_log_path
        and len(console_handlers) == 1
    ):
        return logger

    for handler in list(logger.handlers):
        if isinstance(handler, (RotatingFileHandler, logging.StreamHandler)):
            logger.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(
        directory / LOG_FILENAME,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    logger.addHandler(console_handler)

    return logger


configure_logging = setup_logging
get_logger = setup_logging
