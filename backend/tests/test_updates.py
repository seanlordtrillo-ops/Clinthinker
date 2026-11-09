import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from app import database, main


class UpdateTests(unittest.TestCase):
    installer_url = (
        "https://github.com/seanlordtrillo-ops/Clinthinker/"
        "releases/download/v2.0.5/Clinthinker-Setup-2.0.5.exe"
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

        self.assertEqual(main.APP_VERSION, "2.0.4")
        self.assertEqual(manifest["version"], main.APP_VERSION)
        self.assertEqual(frontend_package["version"], main.APP_VERSION)
        self.assertEqual(frontend_lock["version"], main.APP_VERSION)

    def test_check_reports_only_newer_numeric_versions(self):
        manifest = {
            "version": "2.10.0",
            "installer_url": self.installer_url,
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
        database.DB_PATH.write_bytes(b"local database")
        installer_bytes = b"installer package"
        manifest = {
            "version": "2.0.5",
            "installer_url": self.installer_url,
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.5.exe"}]
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
            response = self.client.post("/api/updates/install")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"started": True})
        self.assertEqual(open_url.call_args_list[0], call(main.UPDATE_MANIFEST_URL, timeout=5))
        release_request = open_url.call_args_list[1].args[0]
        self.assertIsInstance(release_request, Request)
        self.assertEqual(
            release_request.full_url,
            "https://api.github.com/repos/seanlordtrillo-ops/Clinthinker/"
            "releases/tags/v2.0.5",
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
        self.assertEqual(backups[0].read_bytes(), b"local database")
        launch.assert_called_once()
        self.assertTrue(Path(launch.call_args.args[0][0]).is_file())

    def test_install_rejects_non_github_manifest_url(self):
        manifest = {
            "version": "2.0.5",
            "installer_url": "https://github.com.attacker.test/setup.exe",
        }
        with patch(
            "app.main.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
        ) as open_url, patch("app.main.subprocess.Popen") as launch:
            response = self.client.post("/api/updates/install")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(open_url.call_count, 1)
        launch.assert_not_called()

    def test_install_route_has_no_request_body(self):
        operation = self.client.get("/openapi.json").json()["paths"][
            "/api/updates/install"
        ]["post"]
        self.assertNotIn("requestBody", operation)

    def test_install_refuses_checksum_mismatch_before_backup_or_launch(self):
        database.DB_PATH.write_bytes(b"local database")
        manifest = {
            "version": "2.0.5",
            "installer_url": self.installer_url,
            "sha256": "0" * 64,
        }
        release = {
            "assets": [{"id": 12345, "name": "Clinthinker-Setup-2.0.5.exe"}]
        }
        with patch(
            "app.main.urllib.request.urlopen",
            side_effect=[
                io.BytesIO(json.dumps(manifest).encode("utf-8")),
                io.BytesIO(json.dumps(release).encode("utf-8")),
                io.BytesIO(b"installer bytes do not match"),
            ],
        ), patch("app.main.time.sleep"), patch("app.main.subprocess.Popen") as launch:
            response = self.client.post("/api/updates/install")

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
            "v2.0.5/nested/installer.exe"
        ))


if __name__ == "__main__":
    unittest.main()
