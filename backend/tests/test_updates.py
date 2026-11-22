import io
import hashlib
import json
import os
import sqlite3
import tempfile
import urllib.error
import unittest
from contextlib import ExitStack
from pathlib import Path
from urllib.request import Request
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from app import database, main


class UpdateTests(unittest.TestCase):
    installer_url = (
        "https://github.com/seanlordtrillo-ops/Clinthinker/"
        "releases/download/v2.0.6/Clinthinker-Setup-2.0.6.exe"
    )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        storage = Path(self.temporary.name)
        patches = (
            patch.object(database, "STORAGE", storage),
            patch.object(database, "UPLOADS", storage / "uploads"),
            patch.object(database, "DB_PATH", storage / "assistant.sqlite3"),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        database.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_release_versions_are_synchronized(self):
        project_root = Path(__file__).resolve().parents[2]
        manifest = json.loads((project_root / "version.json").read_text(encoding="utf-8"))
        frontend_package = json.loads(
            (project_root / "frontend" / "package.json").read_text(encoding="utf-8")
        )
        frontend_lock = json.loads(
            (project_root / "frontend" / "package-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual(main.APP_VERSION, "2.0.5")
        self.assertEqual(manifest["version"], main.APP_VERSION)
        self.assertEqual(frontend_package["version"], main.APP_VERSION)
        self.assertEqual(frontend_lock["version"], main.APP_VERSION)

    def test_check_reports_only_newer_numeric_versions(self):
        manifest = {
            "version": "2.10.0",
            "installer_url": self.installer_url,
            "sha256": "a" * 64,
            "changelog": "What's new",
        }
        with patch(
            "app.main.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
        ) as open_url:
            response = self.client.get("/api/updates/check")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"available": True, "version": "2.10.0", "changelog": "What's new"},
        )
        open_url.assert_called_once_with(main.UPDATE_MANIFEST_URL, timeout=5)

    def test_check_reports_no_update_when_checksum_is_missing_or_invalid(self):
        manifests = (
            {
                "version": "2.10.0",
                "installer_url": self.installer_url,
            },
            {
                "version": "2.10.0",
                "installer_url": self.installer_url,
                "sha256": "not-a-checksum",
            },
        )
        for manifest in manifests:
            with self.subTest(manifest=manifest), patch.object(
                main, "_fetch_update_manifest", return_value=manifest
            ):
                response = self.client.get("/api/updates/check")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"available": False})

    def test_check_shows_no_banner_when_manifest_version_matches(self):
        manifest = {"version": main.APP_VERSION}
        with patch(
            "app.main.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
        ):
            response = self.client.get("/api/updates/check")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})

    def test_check_silently_ignores_equal_invalid_or_unreachable_manifests(self):
        manifests = (
            {"version": "2.0", "installer_url": "https://example.test/setup.exe"},
            {"version": "2.0.1", "installer_url": "https://github.com.attacker.test/setup.exe"},
        )
        for manifest in manifests:
            with self.subTest(manifest=manifest), patch(
                "app.main.urllib.request.urlopen",
                return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
            ):
                response = self.client.get("/api/updates/check")
                self.assertEqual(response.json(), {"available": False})

        with patch(
            "app.main.urllib.request.urlopen",
            side_effect=TimeoutError("offline"),
        ):
            response = self.client.get("/api/updates/check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})

    def test_install_uses_manifest_url_checks_sha_backs_up_and_launches(self):
        with database.connect() as db:
            db.execute("CREATE TABLE update_backup_probe (value TEXT NOT NULL)")
            db.execute(
                "INSERT INTO update_backup_probe(value) VALUES('preserved row')"
            )
        installer_bytes = b"installer package"
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.6.exe"}]
        }
        with (
            patch(
                "app.main.urllib.request.urlopen",
                side_effect=[
                    io.BytesIO(json.dumps(manifest).encode("utf-8")),
                    io.BytesIO(json.dumps(release).encode("utf-8")),
                    io.BytesIO(installer_bytes),
                ],
            ) as open_url,
            patch("app.main.time.sleep"),
            patch("app.main.subprocess.Popen") as launch,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"started": True})
        self.assertEqual(open_url.call_args_list[0], call(main.UPDATE_MANIFEST_URL, timeout=5))
        release_request = open_url.call_args_list[1].args[0]
        self.assertIsInstance(release_request, Request)
        self.assertEqual(
            release_request.full_url,
            "https://api.github.com/repos/seanlordtrillo-ops/Clinthinker/"
            "releases/tags/v2.0.6",
        )
        asset_request = open_url.call_args_list[2].args[0]
        self.assertIsInstance(asset_request, Request)
        self.assertEqual(
            asset_request.full_url,
            "https://api.github.com/repos/seanlordtrillo-ops/Clinthinker/"
            "releases/assets/12345",
        )
        self.assertEqual(asset_request.get_header("Accept"), "application/octet-stream")
        backups = list(database.STORAGE.glob("assistant-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        backup_db = sqlite3.connect(backups[0])
        try:
            integrity = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
            backup_row = backup_db.execute(
                "SELECT value FROM update_backup_probe"
            ).fetchone()
        finally:
            backup_db.close()
        self.assertEqual(integrity, "ok")
        self.assertEqual(backup_row, ("preserved row",))
        launch.assert_called_once()
        self.assertTrue(Path(launch.call_args.args[0][0]).is_file())

    def test_installer_uses_silent_detached_flags_and_schedules_shutdown(self):
        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)
        shutdown_calls = []
        timers = []

        class CapturedTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.started = False
                self.daemon = False

            def start(self):
                self.started = True

        def capture_timer(interval, function):
            timer = CapturedTimer(interval, function)
            timers.append(timer)
            return timer

        with (
            patch.object(
                main.app.state,
                "shutdown_callback",
                lambda: shutdown_calls.append(True),
                create=True,
            ),
            patch.object(main.threading, "Timer", side_effect=capture_timer),
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(main, "_github_asset_api_url", return_value="asset-url"),
            patch.object(
                main,
                "_download_update_asset",
                side_effect=self._write_installer(installer_bytes),
            ),
            patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
            patch("app.main.subprocess.Popen") as launch,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            launch.call_args.args[0],
            [
                str(Path(self.temporary.name) / "clinthinker-updates" / "Clinthinker-Setup-2.0.6.exe"),
                "/SILENT",
                "/NORESTART",
            ],
        )
        self.assertEqual(
            launch.call_args.kwargs["cwd"],
            str(Path(self.temporary.name) / "clinthinker-updates"),
        )
        self.assertEqual(launch.call_args.kwargs["stdin"], main.subprocess.DEVNULL)
        self.assertEqual(launch.call_args.kwargs["stdout"], main.subprocess.DEVNULL)
        self.assertEqual(launch.call_args.kwargs["stderr"], main.subprocess.DEVNULL)
        if os.name == "nt":
            self.assertEqual(
                launch.call_args.kwargs["creationflags"],
                main.subprocess.DETACHED_PROCESS
                | main.subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].interval, 1.5)
        self.assertTrue(timers[0].daemon)
        self.assertTrue(timers[0].started)
        self.assertEqual(shutdown_calls, [])
        timers[0].function()
        self.assertEqual(shutdown_calls, [True])

    def test_install_without_shutdown_callback_does_not_schedule_shutdown(self):
        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)
        with (
            patch.dict(main.app.state._state, {}, clear=False),
            patch.object(main.threading, "Timer") as timer,
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(main, "_github_asset_api_url", return_value="asset-url"),
            patch.object(
                main,
                "_download_update_asset",
                side_effect=self._write_installer(installer_bytes),
            ),
            patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
            patch("app.main.subprocess.Popen"),
        ):
            main.app.state._state.pop("shutdown_callback", None)
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        timer.assert_not_called()

    def test_failed_installer_launch_does_not_schedule_shutdown(self):
        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)
        shutdown_calls = []
        with (
            self.assertLogs("clinthinker", level="INFO"),
            patch.object(
                main.app.state,
                "shutdown_callback",
                lambda: shutdown_calls.append(True),
                create=True,
            ),
            patch.object(main.threading, "Timer") as timer,
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(main, "_github_asset_api_url", return_value="asset-url"),
            patch.object(
                main,
                "_download_update_asset",
                side_effect=self._write_installer(installer_bytes),
            ),
            patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
            patch("app.main.subprocess.Popen", side_effect=PermissionError("blocked")),
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertIn("launch installer step", response.json()["detail"])
        self.assertEqual(shutdown_calls, [])
        timer.assert_not_called()

    def test_install_prunes_to_five_newest_backups_and_preserves_other_files(self):
        with database.connect() as db:
            db.execute("CREATE TABLE update_backup_probe (value TEXT NOT NULL)")
            db.execute(
                "INSERT INTO update_backup_probe(value) VALUES('live row')"
            )
        live_database_bytes = database.DB_PATH.read_bytes()
        unrelated_path = database.STORAGE / "unrelated.txt"
        unrelated_path.write_bytes(b"unrelated data")
        old_backups = []
        for index in range(6):
            backup = database.STORAGE / f"assistant-old-{index}.sqlite3"
            backup.write_bytes(f"old backup {index}".encode("utf-8"))
            timestamp = 1_000 + index
            os.utime(backup, (timestamp, timestamp))
            old_backups.append(backup)

        installer_bytes = b"installer package"
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.6.exe"}]
        }
        with (
            patch(
                "app.main.urllib.request.urlopen",
                side_effect=[
                    io.BytesIO(json.dumps(manifest).encode("utf-8")),
                    io.BytesIO(json.dumps(release).encode("utf-8")),
                    io.BytesIO(installer_bytes),
                ],
            ),
            patch("app.main.time.sleep"),
            patch("app.main.subprocess.Popen") as launch,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        remaining_backups = list(database.STORAGE.glob("assistant-*.sqlite3"))
        self.assertEqual(len(remaining_backups), 5)
        new_backups = [path for path in remaining_backups if path not in old_backups]
        self.assertEqual(len(new_backups), 1)
        self.assertEqual(set(remaining_backups), set(old_backups[-4:]) | set(new_backups))
        self.assertTrue(database.DB_PATH.is_file())
        self.assertEqual(database.DB_PATH.read_bytes(), live_database_bytes)
        self.assertEqual(unrelated_path.read_bytes(), b"unrelated data")
        launch.assert_called_once()

    def test_pruning_error_does_not_stop_update(self):
        installer_bytes = b"installer package"
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.6.exe"}]
        }
        for index in range(6):
            (database.STORAGE / f"assistant-old-{index}.sqlite3").write_bytes(
                f"old backup {index}".encode("utf-8")
            )

        with (
            patch(
                "app.main.urllib.request.urlopen",
                side_effect=[
                    io.BytesIO(json.dumps(manifest).encode("utf-8")),
                    io.BytesIO(json.dumps(release).encode("utf-8")),
                    io.BytesIO(installer_bytes),
                ],
            ),
            patch("app.main.time.sleep"),
            patch("app.main.subprocess.Popen") as launch,
            patch.object(Path, "unlink", side_effect=OSError("prune denied")),
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"started": True})
        launch.assert_called_once()

    def test_install_rejects_missing_checksum_before_download(self):
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
        }
        with (
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(main, "_github_asset_api_url") as get_asset_url,
            patch.object(main, "_download_update_asset") as download,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "The installer checksum is invalid."})
        get_asset_url.assert_not_called()
        download.assert_not_called()

    def test_install_rejects_invalid_checksum_before_download(self):
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": "not-a-checksum",
        }
        with (
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(main, "_github_asset_api_url") as get_asset_url,
            patch.object(main, "_download_update_asset") as download,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "The installer checksum is invalid."})
        get_asset_url.assert_not_called()
        download.assert_not_called()

    def test_install_rejects_non_github_manifest_url(self):
        manifest = {
            "version": "2.0.6",
            "installer_url": "https://github.com.attacker.test/setup.exe",
        }
        with patch(
            "app.main.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
        ) as open_url, patch("app.main.subprocess.Popen") as launch:
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(open_url.call_count, 1)
        launch.assert_not_called()

    def test_install_rejects_missing_request_header_before_network_call(self):
        with (
            patch.object(main, "_fetch_update_manifest") as fetch_manifest,
            patch("app.main.urllib.request.urlopen") as open_url,
        ):
            response = self.client.post("/api/updates/install")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"detail": "Missing required request header."},
        )
        fetch_manifest.assert_not_called()
        open_url.assert_not_called()

    def test_install_rejects_incorrect_request_header_before_network_call(self):
        with (
            patch.object(main, "_fetch_update_manifest") as fetch_manifest,
            patch("app.main.urllib.request.urlopen") as open_url,
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "0"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"detail": "Missing required request header."},
        )
        fetch_manifest.assert_not_called()
        open_url.assert_not_called()

    def test_install_accepts_correct_request_header_and_preserves_existing_behavior(self):
        manifest = {"version": main.APP_VERSION}
        with patch.object(
            main, "_fetch_update_manifest", return_value=manifest
        ) as fetch_manifest:
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "No newer update is available."},
        )
        fetch_manifest.assert_called_once_with()

    def test_install_route_has_no_request_body(self):
        operation = self.client.get("/openapi.json").json()["paths"][
            "/api/updates/install"
        ]["post"]
        self.assertNotIn("requestBody", operation)

    def test_install_refuses_checksum_mismatch_before_backup_or_launch(self):
        database.DB_PATH.write_bytes(b"local database")
        manifest = {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": "0" * 64,
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.6.exe"}]
        }
        with patch(
            "app.main.urllib.request.urlopen",
            side_effect=[
                io.BytesIO(json.dumps(manifest).encode("utf-8")),
                io.BytesIO(json.dumps(release).encode("utf-8")),
                io.BytesIO(b"installer bytes do not match"),
            ],
        ), patch("app.main.time.sleep"), patch("app.main.subprocess.Popen") as launch:
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(database.STORAGE.glob("assistant-*.sqlite3")), [])
        launch.assert_not_called()

    def test_download_resumes_partial_asset_after_connection_error(self):
        class FakeResponse(io.BytesIO):
            def __init__(self, content, status, headers):
                super().__init__(content)
                self.status = status
                self.headers = headers
                self.failed_after_read = False

            def read(self, size=-1):
                if self.status == 200 and not self.failed_after_read:
                    self.failed_after_read = True
                    return super().read(4)
                if self.status == 200:
                    raise ConnectionResetError("connection interrupted")
                return super().read(size)

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "app.main.urllib.request.urlopen",
                side_effect=[
                    FakeResponse(b"partial", 200, {"Content-Length": "8"}),
                    FakeResponse(
                        b"tail",
                        206,
                        {"Content-Length": "4", "Content-Range": "bytes 4-7/8"},
                    ),
                ],
            ) as open_url,
            patch("app.main.time.sleep"),
        ):
            target = Path(temporary) / "installer.exe"
            main._download_update_asset("https://api.github.com/assets/12345", target)
            self.assertEqual(target.read_bytes(), b"parttail")
            self.assertEqual(open_url.call_count, 2)
            retry_request = open_url.call_args_list[1].args[0]
            self.assertEqual(retry_request.get_header("Range"), "bytes=4-")

    def test_installer_url_must_be_a_release_download_asset(self):
        self.assertFalse(main._valid_installer_url(
            "https://github.com/seanlordtrillo-ops/Clinthinker/other/file.exe"
        ))
        self.assertFalse(main._valid_installer_url(
            "https://github.com/seanlordtrillo-ops/Clinthinker/releases/download/"
            "v2.0.6/nested/installer.exe"
        ))

    def _update_stage_events(self, captured):
        return [
            json.loads(record.getMessage().split("update_stage=", 1)[1])
            for record in captured.records
            if "update_stage=" in record.getMessage()
        ]

    def _valid_install_manifest(self, installer_bytes=b"installer package", checksum=None):
        return {
            "version": "2.0.6",
            "installer_url": self.installer_url,
            "sha256": checksum or hashlib.sha256(installer_bytes).hexdigest(),
        }

    def _write_installer(self, installer_bytes):
        def write_installer(_asset_url, installer_path):
            installer_path.parent.mkdir(parents=True, exist_ok=True)
            installer_path.write_bytes(installer_bytes)

        return write_installer

    def test_unexpected_install_failures_report_their_stage_and_log_once(self):
        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)

        class BrokenHash:
            def sha256(self):
                raise RuntimeError("private hash failure")

        rate_limit = urllib.error.HTTPError(
            "https://api.github.com/releases",
            403,
            "rate limited",
            {"X-RateLimit-Remaining": "0"},
            None,
        )
        cases = [
            (
                "check for update",
                [
                    patch.object(
                        main,
                        "_fetch_update_manifest",
                        side_effect=TimeoutError("private fetch failure"),
                    )
                ],
                "the update information request timed out",
                "Update failed at the check for update step: the update information request timed out. Check your internet connection and try again.",
                ["check for update"],
            ),
            (
                "validate update info",
                [patch.object(main, "_fetch_update_manifest", return_value=[])],
                "the update details could not be validated",
                "Update failed at the validate update info step: the update details could not be validated. Check the version, installer link, and SHA-256 information.",
                ["check for update", "validate update info"],
            ),
            (
                "find release on GitHub",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(main, "_github_asset_api_url", side_effect=rate_limit),
                ],
                "GitHub rate-limited the release lookup",
                "Update failed at the find release on GitHub step: GitHub rate-limited the release lookup. Check the GitHub release and try again.",
                ["check for update", "validate update info", "find release on GitHub"],
            ),
            (
                "find release on GitHub",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(
                        main,
                        "_github_asset_api_url",
                        side_effect=ValueError(
                            "The installer was not found in the GitHub release."
                        ),
                    ),
                ],
                "the installer file was not found in the GitHub release",
                "Update failed at the find release on GitHub step: the installer file was not found in the GitHub release. Check the GitHub release and try again.",
                ["check for update", "validate update info", "find release on GitHub"],
            ),
            (
                "download",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(main, "_github_asset_api_url", return_value="asset-url"),
                    patch.object(
                        main,
                        "_download_update_asset",
                        side_effect=urllib.error.URLError("private download failure"),
                    ),
                ],
                "the installer could not be reached",
                "Update failed at the download step: the installer could not be reached. Check your connection and try again.",
                [
                    "check for update",
                    "validate update info",
                    "find release on GitHub",
                    "download",
                ],
            ),
            (
                "verify checksum",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(main, "_github_asset_api_url", return_value="asset-url"),
                    patch.object(
                        main,
                        "_download_update_asset",
                        side_effect=self._write_installer(installer_bytes),
                    ),
                    patch.object(main, "hashlib", BrokenHash()),
                    patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
                ],
                "the downloaded installer could not be read for verification",
                "Update failed at the verify checksum step: the downloaded installer could not be read for verification. Download the update again.",
                [
                    "check for update",
                    "validate update info",
                    "find release on GitHub",
                    "download",
                    "verify checksum",
                ],
            ),
            (
                "back up database",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(main, "_github_asset_api_url", return_value="asset-url"),
                    patch.object(
                        main,
                        "_download_update_asset",
                        side_effect=self._write_installer(installer_bytes),
                    ),
                    patch.object(
                        database,
                        "DB_PATH",
                        Path(self.temporary.name) / "missing-assistant.sqlite3",
                    ),
                    patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
                ],
                "the local database file is missing",
                "Update failed at the back up database step: the local database file is missing. Check database availability and permissions, then try again.",
                [
                    "check for update",
                    "validate update info",
                    "find release on GitHub",
                    "download",
                    "verify checksum",
                    "back up database",
                ],
            ),
            (
                "launch installer",
                [
                    patch.object(main, "_fetch_update_manifest", return_value=manifest),
                    patch.object(main, "_github_asset_api_url", return_value="asset-url"),
                    patch.object(
                        main,
                        "_download_update_asset",
                        side_effect=self._write_installer(installer_bytes),
                    ),
                    patch("app.main.subprocess.Popen", side_effect=PermissionError("private path")),
                    patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
                ],
                "the installer could not be started",
                "Update failed at the launch installer step: the installer could not be started. Check permissions or antivirus settings, then try again.",
                [
                    "check for update",
                    "validate update info",
                    "find release on GitHub",
                    "download",
                    "verify checksum",
                    "back up database",
                    "launch installer",
                ],
            ),
        ]

        for stage, patchers, cause, detail, expected_stages in cases:
            with self.subTest(stage=stage, cause=cause):
                with self.assertLogs("clinthinker", level="INFO") as captured:
                    with ExitStack() as stack:
                        for patcher in patchers:
                            stack.enter_context(patcher)
                        response = self.client.post(
                            "/api/updates/install",
                            headers={"X-Clinthinker-Request": "1"},
                        )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"detail": detail})
                self.assertNotIn("private", response.text)
                events = self._update_stage_events(captured)
                self.assertEqual([event["stage"] for event in events], expected_stages)
                self.assertEqual(events[-1], {
                    "cause": cause,
                    "stage": stage,
                    "status": "failure",
                })

    def test_explicit_install_http_errors_keep_details_and_log_the_stage(self):
        cases = [
            (
                "check for update",
                [],
                None,
                403,
                {"detail": "Missing required request header."},
            ),
            (
                "validate update info",
                [patch.object(main, "_fetch_update_manifest", return_value={"version": main.APP_VERSION})],
                {"X-Clinthinker-Request": "1"},
                409,
                {"detail": "No newer update is available."},
            ),
            (
                "validate update info",
                [patch.object(main, "_fetch_update_manifest", return_value={
                    "version": "2.0.6",
                    "installer_url": self.installer_url,
                })],
                {"X-Clinthinker-Request": "1"},
                422,
                {"detail": "The installer checksum is invalid."},
            ),
            (
                "verify checksum",
                [
                    patch.object(
                        main,
                        "_fetch_update_manifest",
                        return_value=self._valid_install_manifest(
                            checksum="0" * 64
                        ),
                    ),
                    patch.object(main, "_github_asset_api_url", return_value="asset-url"),
                    patch.object(
                        main,
                        "_download_update_asset",
                        side_effect=self._write_installer(b"installer package"),
                    ),
                    patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
                ],
                {"X-Clinthinker-Request": "1"},
                422,
                {"detail": "The installer checksum does not match."},
            ),
        ]

        for stage, patchers, headers, status, expected_body in cases:
            with self.subTest(stage=stage, expected_body=expected_body):
                with self.assertLogs("clinthinker", level="INFO") as captured:
                    with ExitStack() as stack:
                        for patcher in patchers:
                            stack.enter_context(patcher)
                        response = self.client.post(
                            "/api/updates/install",
                            headers=headers,
                        )

                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), expected_body)
                events = self._update_stage_events(captured)
                self.assertEqual(events[-1]["stage"], stage)
                self.assertEqual(events[-1]["status"], "failure")
                self.assertEqual(
                    sum(event["stage"] == stage for event in events),
                    1,
                )

    def test_decorated_update_helpers_log_one_stage_record_per_failure(self):
        with (
            self.assertLogs("clinthinker", level="INFO") as manifest_logs,
            patch(
                "app.services.updates.urllib.request.urlopen",
                return_value=io.BytesIO(b"{"),
            ),
        ):
            manifest_response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(manifest_response.status_code, 500)
        self.assertIn("check for update step", manifest_response.json()["detail"])
        self.assertEqual(
            [event["stage"] for event in self._update_stage_events(manifest_logs)],
            ["check for update"],
        )
        self.assertFalse(
            any("structured_error=" in record.getMessage() for record in manifest_logs.records)
        )

        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)

        with (
            self.assertLogs("clinthinker", level="INFO") as download_logs,
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(
                main,
                "_github_asset_api_url",
                return_value="https://api.github.com/releases/assets/1",
            ),
            patch(
                "app.services.updates.urllib.request.urlopen",
                side_effect=TimeoutError("private download exception"),
            ) as open_url,
            patch("app.services.updates.time.sleep"),
            patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
        ):
            download_response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(download_response.status_code, 500)
        self.assertIn("download step: the download timed out.", download_response.json()["detail"])
        self.assertNotIn("private download exception", download_response.text)
        self.assertEqual(open_url.call_count, 4)
        self.assertEqual(
            [event["stage"] for event in self._update_stage_events(download_logs)],
            [
                "check for update",
                "validate update info",
                "find release on GitHub",
                "download",
            ],
        )
        self.assertFalse(
            any("structured_error=" in record.getMessage() for record in download_logs.records)
        )

    def test_incomplete_download_after_retries_has_a_plain_stage_message(self):
        installer_bytes = b"installer package"
        manifest = self._valid_install_manifest(installer_bytes)

        class IncompleteResponse(io.BytesIO):
            status = 200
            headers = {"Content-Length": "20"}

        with (
            self.assertLogs("clinthinker", level="INFO") as captured,
            patch.object(main, "_fetch_update_manifest", return_value=manifest),
            patch.object(
                main,
                "_github_asset_api_url",
                return_value="https://api.github.com/releases/assets/1",
            ),
            patch(
                "app.services.updates.urllib.request.urlopen",
                side_effect=lambda *_args, **_kwargs: IncompleteResponse(b"partial"),
            ) as open_url,
            patch("app.services.updates.time.sleep"),
            patch("app.main.tempfile.gettempdir", return_value=self.temporary.name),
        ):
            response = self.client.post(
                "/api/updates/install",
                headers={"X-Clinthinker-Request": "1"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {
                "detail": (
                    "Update failed at the download step: the download remained "
                    "incomplete after retries. Check your connection and try again."
                )
            },
        )
        self.assertEqual(open_url.call_count, 4)
        events = self._update_stage_events(captured)
        self.assertEqual(events[-1]["stage"], "download")
        self.assertEqual(events[-1]["status"], "failure")
        self.assertFalse(
            any("structured_error=" in record.getMessage() for record in captured.records)
        )


if __name__ == "__main__":
    unittest.main()
