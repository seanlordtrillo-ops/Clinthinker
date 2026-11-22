import ast
import builtins
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database, main
from app.core.errors import build_error_record
from app.core.logging_setup import setup_logging


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SNAPSHOT_DIR = BACKEND_ROOT / "tests" / "baseline" / "snapshots"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def contract_assert(test, condition, file, function, expected, actual, probable_cause):
    if not condition:
        record = build_error_record(
            file=file,
            function=function,
            expected_input_output=expected,
            actual_result=actual,
            probable_cause=probable_cause,
        )
        test.fail(json.dumps(record, sort_keys=True, default=str))


class MissingCodeContracts(unittest.TestCase):
    def test_manifest_modules_and_public_functions_exist(self):
        with MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)

        for module_name in manifest["modules"]:
            with self.subTest(module=module_name):
                try:
                    module = importlib.import_module(module_name)
                except Exception as error:
                    contract_assert(
                        self,
                        False,
                        module_name,
                        "<module>",
                        "Importable module",
                        f"{type(error).__name__}: {error}",
                        "Missing module or broken module dependency",
                    )
                    continue

                contract_assert(
                    self,
                    True,
                    module_name,
                    "<module>",
                    "Importable module",
                    "Importable module",
                    "",
                )

                for function_name in manifest["functions"].get(module_name, []):
                    with self.subTest(function=function_name):
                        contract_assert(
                            self,
                            hasattr(module, function_name),
                            module_name,
                            function_name,
                            "Exported and importable",
                            "Missing attribute",
                            "Missing code or changed public API",
                        )


class UnexpectedChangeContracts(unittest.TestCase):
    def test_route_table_matches_step1_snapshot(self):
        actual = sorted(
            {
                (method, path)
                for path, operations in main.app.openapi()["paths"].items()
                for method in operations
                if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}
            },
            key=lambda item: (item[1], item[0]),
        )
        with (SNAPSHOT_DIR / "api_routes.json").open("r", encoding="utf-8") as snapshot_file:
            expected = [
                (item["method"], item["path"])
                for item in json.load(snapshot_file)
            ]

        contract_assert(
            self,
            actual == expected,
            "backend/app/main.py",
            "app.openapi",
            expected,
            actual,
            "Route table changed or API snapshot is stale",
        )

    def test_settings_keys_match_step1_snapshot(self):
        with (SNAPSHOT_DIR / "default_settings.json").open("r", encoding="utf-8") as snapshot_file:
            expected = json.load(snapshot_file)
        actual = database.DEFAULT_SETTINGS

        contract_assert(
            self,
            actual.keys() == expected.keys(),
            "backend/app/database.py",
            "DEFAULT_SETTINGS",
            sorted(expected.keys()),
            sorted(actual.keys()),
            "Top-level settings keys changed",
        )
        contract_assert(
            self,
            actual["question_generation"].keys()
            == expected["question_generation"].keys(),
            "backend/app/database.py",
            "DEFAULT_SETTINGS.question_generation",
            sorted(expected["question_generation"].keys()),
            sorted(actual["question_generation"].keys()),
            "Question-generation settings keys changed",
        )


class InvalidConfigurationContracts(unittest.TestCase):
    def test_data_directory_environment(self):
        from app.core.logging_setup import get_data_directory

        missing_environment = dict(os.environ)
        missing_environment.pop("TOPIC_ASSISTANT_DATA_DIR", None)
        with patch.dict(os.environ, missing_environment, clear=True):
            missing_directory = get_data_directory()

        with tempfile.TemporaryDirectory() as temporary:
            not_a_directory = Path(temporary) / "file"
            not_a_directory.write_text("not a directory", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"TOPIC_ASSISTANT_DATA_DIR": str(not_a_directory)},
                clear=False,
            ):
                bad_directory = get_data_directory()
                try:
                    setup_logging(bad_directory)
                    bad_directory_rejected = False
                except (OSError, ValueError):
                    bad_directory_rejected = True

        contract_assert(
            self,
            missing_directory.is_absolute() and bad_directory_rejected,
            "backend/app/core/logging_setup.py",
            "get_data_directory/setup_logging",
            "Missing env has a valid fallback; file-as-directory env is rejected",
            f"fallback={missing_directory}; file_as_directory_rejected={bad_directory_rejected}",
            "Bad TOPIC_ASSISTANT_DATA_DIR must not initialize a file as a directory",
        )

    def test_unwritable_data_directory_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
                try:
                    setup_logging(directory)
                    unwritable = False
                except PermissionError:
                    unwritable = True
        contract_assert(
            self,
            unwritable,
            "backend/app/core/logging_setup.py",
            "setup_logging",
            "PermissionError for unwritable data directory",
            "PermissionError raised" if unwritable else "Directory creation unexpectedly succeeded",
            "Logging cannot write in the configured data directory",
        )

    def test_versions_match(self):
        with (PROJECT_ROOT / "version.json").open("r", encoding="utf-8") as manifest_file:
            manifest_version = json.load(manifest_file)["version"]
        with (PROJECT_ROOT / "frontend" / "package.json").open("r", encoding="utf-8") as package_file:
            package_version = json.load(package_file)["version"]

        contract_assert(
            self,
            main.APP_VERSION == manifest_version == package_version,
            "backend/app/main.py",
            "APP_VERSION",
            manifest_version,
            f"{main.APP_VERSION} / {manifest_version} / {package_version}",
            "Version metadata is inconsistent",
        )

    def test_frontend_dist_exists(self):
        dist = PROJECT_ROOT / "frontend" / "dist"
        contract_assert(
            self,
            dist.is_dir() and (dist / "index.html").is_file(),
            "frontend/dist",
            "frontend build",
            "frontend/dist/index.html",
            str(dist),
            "Frontend build output is missing",
        )


class BrokenDependencyContracts(unittest.TestCase):
    def test_every_app_module_imports_cleanly(self):
        app_directory = BACKEND_ROOT / "app"
        for path in sorted(app_directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(BACKEND_ROOT).with_suffix("")
            module_name = ".".join(relative.parts)
            with self.subTest(module=module_name):
                try:
                    importlib.import_module(module_name)
                    actual = "clean import"
                    valid = True
                except Exception as error:
                    actual = f"{type(error).__name__}: {error}"
                    valid = False
                contract_assert(
                    self,
                    valid,
                    str(path),
                    "<module>",
                    "Clean module import",
                    actual,
                    "Missing or broken dependency",
                )

    def test_no_circular_app_imports(self):
        app_directory = BACKEND_ROOT / "app"
        graph = {}
        for path in sorted(app_directory.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            relative = path.relative_to(BACKEND_ROOT).with_suffix("")
            module_name = ".".join(relative.parts)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            edges = set()
            package = ".".join(relative.parts[:-1])
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    edges.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.level:
                        edges.add(package + "." + node.module)
                    else:
                        edges.add(node.module)
            graph[module_name] = edges

        def visit(module, trail):
            if module in trail:
                cycle = trail[trail.index(module):] + [module]
                return cycle
            for edge in graph.get(module, set()):
                if edge.startswith("app.") and edge in graph:
                    found = visit(edge, trail + [module])
                    if found:
                        return found
            return None

        for module in graph:
            cycle = visit(module, [])
            contract_assert(
                self,
                cycle is None,
                "backend/app",
                module,
                "No circular imports",
                " -> ".join(cycle) if cycle else "No cycle",
                "Circular module dependency",
            )

    def test_local_function_callees_exist(self):
        app_directory = BACKEND_ROOT / "app"
        for path in sorted(app_directory.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            module_names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            imported_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported_names.update(alias.asname or alias.name for alias in node.names)
            known = module_names | imported_names | set(dir(builtins)) | {"self", "cls"}

            for function in [
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                missing = []
                local_names = (
                    module_names
                    | imported_names
                    | set(dir(builtins))
                    | {"self", "cls"}
                    | {"function", "error", "check"}
                    | {argument.arg for argument in function.args.args}
                    | {argument.arg for argument in function.args.kwonlyargs}
                    | ({function.args.vararg.arg} if function.args.vararg else set())
                    | ({function.args.kwarg.arg} if function.args.kwarg else set())
                )
                local_names.update(
                    node.name
                    for node in ast.walk(function)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                for node in ast.walk(function):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        if node.func.id not in local_names:
                            missing.append(node.func.id)
                missing = sorted(set(missing))
                contract_assert(
                    self,
                    not missing,
                    str(path),
                    function.name,
                    "Every local callees name exists",
                    ", ".join(missing),
                    "Function calls a missing or renamed callee",
                )
