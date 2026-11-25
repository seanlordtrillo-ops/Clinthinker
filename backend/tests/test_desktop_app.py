import importlib.util
import logging
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_desktop_app():
    import pytest

    pytest.importorskip("webview")
    pytest.importorskip("tkinter")
    spec = importlib.util.spec_from_file_location(
        "desktop_app_for_storage_tests",
        PROJECT_ROOT / "desktop_app.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("Could not load desktop_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configured_environment_directory_skips_legacy_selection(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    configured_directory = tmp_path / "configured-storage"
    monkeypatch.setenv("TOPIC_ASSISTANT_DATA_DIR", str(configured_directory))

    storage_dir, migrate_storage = desktop_app.choose_storage_directory(
        os.environ.get("TOPIC_ASSISTANT_DATA_DIR"),
        legacy_storage_exists=True,
        renamed_storage_exists=False,
    )

    assert storage_dir == configured_directory
    assert not migrate_storage


def test_fresh_install_uses_current_app_folder(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    monkeypatch.delenv("TOPIC_ASSISTANT_DATA_DIR", raising=False)

    storage_dir, migrate_storage = desktop_app.choose_storage_directory(
        os.environ.get("TOPIC_ASSISTANT_DATA_DIR"),
        tmp_path,
    )

    assert storage_dir == tmp_path / desktop_app.APP_NAME / "storage"
    assert not migrate_storage


def test_unset_environment_selects_legacy_migration_destination(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    monkeypatch.delenv("TOPIC_ASSISTANT_DATA_DIR", raising=False)
    legacy_storage = tmp_path / "Topic Prediction Assistant" / "storage"
    legacy_storage.mkdir(parents=True)

    storage_dir, migrate_storage = desktop_app.choose_storage_directory(
        os.environ.get("TOPIC_ASSISTANT_DATA_DIR"),
        tmp_path,
        legacy_storage_exists=True,
        renamed_storage_exists=False,
    )

    assert storage_dir == tmp_path / desktop_app.APP_NAME / "storage"
    assert migrate_storage


def test_legacy_storage_moves_before_logging_is_configured(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    from app.core.logging_setup import setup_logging

    local_app_data = tmp_path / "local-app-data"
    legacy_storage = local_app_data / "Topic Prediction Assistant" / "storage"
    legacy_storage.mkdir(parents=True)
    (legacy_storage / "saved.txt").write_text("preserved", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.delenv("TOPIC_ASSISTANT_DATA_DIR", raising=False)

    storage_dir = desktop_app._resolve_storage_directory()
    saved_file = storage_dir / "saved.txt"
    assert storage_dir == local_app_data / desktop_app.APP_NAME / "storage"
    assert saved_file.read_text(encoding="utf-8") == "preserved"
    assert not (storage_dir / "clinthinker.log").exists()
    assert not legacy_storage.exists()

    logger = setup_logging(storage_dir)
    try:
        assert (storage_dir / "clinthinker.log").is_file()
        assert saved_file.read_text(encoding="utf-8") == "preserved"
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_fresh_install_creates_storage_before_logging(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    from app.core.logging_setup import setup_logging

    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.delenv("TOPIC_ASSISTANT_DATA_DIR", raising=False)

    storage_dir = desktop_app._resolve_storage_directory()
    assert storage_dir == local_app_data / desktop_app.APP_NAME / "storage"
    assert storage_dir.is_dir()
    assert not (storage_dir / "clinthinker.log").exists()

    logger = setup_logging(storage_dir)
    try:
        assert (storage_dir / "clinthinker.log").is_file()
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_startup_error_is_logged_with_traceback_and_shown(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    storage_dir = tmp_path / "final-storage"
    root = tmp_path / "application"
    monkeypatch.setenv("TOPIC_ASSISTANT_DATA_DIR", str(storage_dir))
    monkeypatch.setattr(desktop_app, "project_path", lambda: root)

    def fail_runtime(_root):
        raise RuntimeError("simulated desktop startup failure")

    monkeypatch.setattr(desktop_app, "install_webview2_runtime", fail_runtime)
    shown_messages = []
    monkeypatch.setattr(desktop_app, "show_error", shown_messages.append)

    try:
        desktop_app.main()
    except RuntimeError as error:
        desktop_app._handle_startup_error(error)
    finally:
        logger = logging.getLogger("clinthinker")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    log_contents = (storage_dir / "clinthinker.log").read_text(encoding="utf-8")
    assert "Desktop application startup failed." in log_contents
    assert "Traceback (most recent call last):" in log_contents
    assert "RuntimeError: simulated desktop startup failure" in log_contents
    assert desktop_app._startup_logging_ready
    assert shown_messages == [
        "The app could not start:\n\nsimulated desktop startup failure"
    ]


def test_migration_failure_is_logged_in_temp_file(tmp_path, monkeypatch):
    desktop_app = _load_desktop_app()
    root = tmp_path / "application"
    (root / "frontend" / "dist").mkdir(parents=True)
    local_app_data = tmp_path / "local-app-data"
    legacy_storage = local_app_data / "Topic Prediction Assistant" / "storage"
    legacy_storage.mkdir(parents=True)
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.delenv("TOPIC_ASSISTANT_DATA_DIR", raising=False)
    monkeypatch.setattr(desktop_app, "project_path", lambda: root)
    monkeypatch.setattr(desktop_app, "install_webview2_runtime", lambda _root: True)

    def fail_migration(_source, _destination):
        raise OSError("simulated migration failure")

    monkeypatch.setattr(desktop_app.shutil, "move", fail_migration)
    monkeypatch.setattr(desktop_app.tempfile, "gettempdir", lambda: str(system_temp))
    shown_messages = []
    monkeypatch.setattr(desktop_app, "show_error", shown_messages.append)

    try:
        desktop_app.main()
    except OSError as error:
        desktop_app._handle_startup_error(error)
    else:
        raise AssertionError("Expected migration to fail")

    log_contents = (system_temp / "startup-error.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last):" in log_contents
    assert "OSError: simulated migration failure" in log_contents
    assert not (legacy_storage / "clinthinker.log").exists()
    assert shown_messages == [
        "The app could not start:\n\nsimulated migration failure"
    ]
