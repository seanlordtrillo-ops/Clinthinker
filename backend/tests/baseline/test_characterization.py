import json
import random
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database, main, ml, questions


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def load_snapshot(name):
    with (SNAPSHOT_DIR / name).open("r", encoding="utf-8") as snapshot:
        return json.load(snapshot)


def save_snapshot(name, value):
    with (SNAPSHOT_DIR / name).open("w", encoding="utf-8") as snapshot:
        json.dump(value, snapshot, indent=2, sort_keys=True)
        snapshot.write("\n")


def json_shape(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if not value:
            return ["empty-list"]
        return [json_shape(value[0])]
    if isinstance(value, dict):
        return {key: json_shape(child) for key, child in sorted(value.items())}
    return type(value).__name__


class CharacterizationSnapshots(unittest.TestCase):
    def test_ml_predict_snapshot(self):
        ml._fit_models.cache_clear()
        self.addCleanup(ml._fit_models.cache_clear)
        random.seed(4242)
        examples = [
            ("normalization functional dependency primary key third normal form", "Databases"),
            ("database table relation schema normalization foreign key", "Databases"),
            ("select join group by aggregate query sql tables", "Databases"),
            ("router packet network routing protocol subnet gateway", "Networking"),
            ("tcp udp ip routing switch network packet", "Networking"),
            ("dns dhcp subnet firewall network interface", "Networking"),
        ]
        snapshot = ml.predict(
            "database join query primary key normalization",
            training_examples=examples,
        )
        self.assertEqual(snapshot, load_snapshot("ml_predict.json"))

    def test_evaluate_classifier_snapshot(self):
        random.seed(4242)
        examples = [
            ("database relation primary key foreign key normalization", "Databases"),
            ("sql select join group by database query", "Databases"),
            ("table schema index transaction database", "Databases"),
            ("normalization third normal form dependency relation", "Databases"),
            ("router packet routing subnet network", "Networking"),
            ("tcp udp ip switch gateway protocol", "Networking"),
            ("dns dhcp firewall network interface", "Networking"),
            ("packet forwarding routing table network layer", "Networking"),
        ]
        snapshot = ml.evaluate_classifier(examples)
        self.assertEqual(snapshot, load_snapshot("evaluate_classifier.json"))

    def test_generate_questions_snapshot(self):
        random.seed(4242)
        training = [
            ("router routing packets network protocol connection", "Networking"),
            ("routing table forwards packets network layer router", "Networking"),
            ("network protocol communication packet switching", "Networking"),
            ("database tables schema keys database", "Databases"),
            ("database relation primary key query transactions", "Databases"),
            ("tables store records relational schema normalization", "Databases"),
        ]
        material = (
            "Router is a device that forwards data packets between networks using routing tables. "
            "Routing is the process of selecting a path for data packets across interconnected networks. "
            "Network protocol is a formal set of rules that govern communication between devices."
        )
        deterministic_uuids = [
            uuid.UUID(int=index) for index in range(1, 100)
        ]

        with patch(
            "app.questions.uuid.uuid4",
            side_effect=deterministic_uuids,
        ):
            snapshot = questions.generate_questions(
                requested_count=4,
                question_type="Multiple Choice",
                difficulty="Moderate",
                topic_filter="All Topics",
                per_topic=2,
                training_examples=training,
                dataset_id="dataset-1",
                dataset_name="Study set",
                sources=[
                    {
                        "id": "upload-1",
                        "name": "Networks lesson",
                        "text": material,
                        "kind": "course",
                    }
                ],
            )
        self.assertEqual(snapshot, load_snapshot("generate_questions.json"))

    def test_default_settings_snapshot(self):
        self.assertEqual(database.DEFAULT_SETTINGS, load_snapshot("default_settings.json"))

    def test_app_version_matches_manifests(self):
        with (PROJECT_ROOT / "version.json").open("r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        with (PROJECT_ROOT / "frontend" / "package.json").open("r", encoding="utf-8") as package_file:
            package = json.load(package_file)
        snapshot = {
            "app_version": main.APP_VERSION,
            "manifest_version": manifest["version"],
            "frontend_version": package["version"],
        }
        self.assertEqual(snapshot, load_snapshot("app_versions.json"))


class BaselineApiCharacterization(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = Path(self.tempdir.name)
        self.uploads = self.storage / "uploads"
        self.storage_patch = patch.object(database, "STORAGE", self.storage)
        self.uploads_patch = patch.object(database, "UPLOADS", self.uploads)
        self.db_path_patch = patch.object(database, "DB_PATH", self.storage / "assistant.sqlite3")
        self.main_uploads_patch = patch.object(main, "UPLOADS", self.uploads)
        self.storage_patch.start()
        self.uploads_patch.start()
        self.db_path_patch.start()
        self.main_uploads_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.addCleanup(self.uploads_patch.stop)
        self.addCleanup(self.db_path_patch.stop)
        self.addCleanup(self.main_uploads_patch.stop)
        main._question_batches.clear()
        database.initialize()
        self.client = TestClient(main.app)

    def tearDown(self):
        main._question_batches.clear()
        self.tempdir.cleanup()

    def test_openapi_route_list_snapshot(self):
        routes = sorted(
            {
                (method, path)
                for path, operations in main.app.openapi()["paths"].items()
                for method in operations
                if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}
            },
            key=lambda item: (item[1], item[0]),
        )
        snapshot = [{"method": method, "path": path} for method, path in routes]
        self.assertEqual(snapshot, load_snapshot("api_routes.json"))

    def test_database_schema_snapshot(self):
        database.initialize()
        with database.connect() as db:
            tables = {}
            rows = db.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
            for row in rows:
                columns = [
                    dict(column)
                    for column in db.execute(
                        f'PRAGMA table_info("{row["name"]}")'
                    ).fetchall()
                ]
                foreign_keys = [
                    dict(key)
                    for key in db.execute(
                        f'PRAGMA foreign_key_list("{row["name"]}")'
                    ).fetchall()
                ]
                tables[row["name"]] = {
                    "sql": row["sql"],
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                }
        self.assertEqual(tables, load_snapshot("database_schema.json"))

    def test_api_response_shapes(self):
        older_manifest = {
            "version": "0.0.1",
            "installer_url": None,
            "sha256": None,
        }
        with patch.object(main, "_fetch_update_manifest", return_value=older_manifest):
            responses = [
                ("GET", "/api/health", self.client.get("/api/health")),
                ("GET", "/api/diagnostics", self.client.get("/api/diagnostics")),
                ("GET", "/api/updates/check", self.client.get("/api/updates/check")),
                ("POST", "/api/updates/install", self.client.post("/api/updates/install", headers={"X-Clinthinker-Request": "1"})),
                ("POST", "/api/upload", self.client.post("/api/upload")),
                ("POST", "/api/lessons/upload", self.client.post("/api/lessons/upload")),
                ("GET", "/api/uploads", self.client.get("/api/uploads")),
                (
                    "PUT",
                    "/api/uploads/missing/exam",
                    self.client.put("/api/uploads/missing/exam", json={"is_exam": True}),
                ),
                ("GET", "/api/training-datasets", self.client.get("/api/training-datasets")),
                (
                    "POST",
                    "/api/training-datasets/evaluate",
                    self.client.post(
                        "/api/training-datasets/evaluate",
                        json={"training_dataset_id": "builtin"},
                    ),
                ),
                (
                    "GET",
                    "/api/training-datasets/builtin/topics",
                    self.client.get("/api/training-datasets/builtin/topics"),
                ),
                (
                    "POST",
                    "/api/training-datasets/csv",
                    self.client.post("/api/training-datasets/csv"),
                ),
                (
                    "POST",
                    "/api/training-datasets/documents",
                    self.client.post("/api/training-datasets/documents"),
                ),
                (
                    "DELETE",
                    "/api/training-datasets/missing",
                    self.client.delete("/api/training-datasets/missing"),
                ),
                (
                    "GET",
                    "/api/uploads/missing/text",
                    self.client.get("/api/uploads/missing/text"),
                ),
                (
                    "DELETE",
                    "/api/uploads/missing",
                    self.client.delete("/api/uploads/missing"),
                ),
                (
                    "POST",
                    "/api/predict/stream",
                    self.client.post("/api/predict/stream"),
                ),
                ("GET", "/api/analysis/latest", self.client.get("/api/analysis/latest")),
                ("GET", "/api/settings", self.client.get("/api/settings")),
                ("PUT", "/api/settings", self.client.put("/api/settings")),
                (
                    "POST",
                    "/api/questions/generate",
                    self.client.post("/api/questions/generate"),
                ),
                (
                    "GET",
                    "/api/questions/preferences",
                    self.client.get("/api/questions/preferences"),
                ),
                (
                    "POST",
                    "/api/questions/feedback",
                    self.client.post("/api/questions/feedback"),
                ),
                (
                    "DELETE",
                    "/api/questions/feedback",
                    self.client.delete("/api/questions/feedback"),
                ),
                (
                    "POST",
                    "/api/questions/answers",
                    self.client.post("/api/questions/answers"),
                ),
                (
                    "POST",
                    "/api/questions/save",
                    self.client.post("/api/questions/save"),
                ),
                (
                    "GET",
                    "/api/questions/saved",
                    self.client.get("/api/questions/saved"),
                ),
                (
                    "PUT",
                    "/api/questions/sessions/missing",
                    self.client.put(
                        "/api/questions/sessions/missing",
                        json={},
                    ),
                ),
                (
                    "DELETE",
                    "/api/questions/sessions/missing",
                    self.client.delete("/api/questions/sessions/missing"),
                ),
            ]

        snapshot = {
            f"{method} {path}": {
                "status": response.status_code,
                "shape": json_shape(response.json()),
            }
            for method, path, response in responses
        }
        self.assertEqual(snapshot, load_snapshot("api_response_shapes.json"))
