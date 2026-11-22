import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.logging_setup import (
    LOGGER_NAME,
    LOG_FILENAME,
    get_data_directory,
    setup_logging,
)
from app import main


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(LOGGER_NAME)
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()

    def tearDown(self):
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()

    def test_configures_one_rotating_file_and_console_handler(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            logger = setup_logging(directory)
            try:
                from logging.handlers import RotatingFileHandler

                rotating_handlers = [
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

                self.assertEqual(len(rotating_handlers), 1)
                self.assertEqual(len(console_handlers), 1)
                self.assertEqual(
                    os.path.normcase(
                        os.path.abspath(rotating_handlers[0].baseFilename)
                    ),
                    os.path.normcase(
                        os.path.abspath(str(directory / LOG_FILENAME))
                    ),
                )
                self.assertEqual(rotating_handlers[0].maxBytes, 5 * 1024 * 1024)
                self.assertEqual(rotating_handlers[0].backupCount, 3)
            finally:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()

    def test_setup_logging_is_idempotent_for_the_same_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = setup_logging(temporary)
            try:
                setup_logging(temporary)
                setup_logging(temporary)
                self.assertEqual(len(logger.handlers), 2)
            finally:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()

    def test_setup_logging_preserves_handlers_for_the_same_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = setup_logging(temporary)
            handlers = tuple(logger.handlers)
            try:
                setup_logging(temporary)
                self.assertEqual(tuple(logger.handlers), handlers)
            finally:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()

    def test_data_directory_respects_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"TOPIC_ASSISTANT_DATA_DIR": temporary},
                clear=False,
            ):
                self.assertEqual(get_data_directory(), Path(temporary))

    def test_frozen_data_directory_uses_localappdata(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"LOCALAPPDATA": temporary},
                clear=True,
            ), patch("app.core.logging_setup.sys.frozen", True, create=True):
                self.assertEqual(
                    get_data_directory(),
                    Path(temporary) / "Clinthinker©" / "storage",
                )

    def test_application_startup_configures_logging_once(self):
        with patch.object(main, "_logging_setup_complete", False), patch.object(
            main, "initialize"
        ), patch.object(
            main._core_logging_setup,
            "setup_logging",
        ) as setup:
            main.startup()
            main.startup()

        setup.assert_called_once_with()
