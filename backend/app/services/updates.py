from __future__ import annotations

import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core.checks import checks


UPDATE_MANIFEST_URL = "https://seanlordtrillo-ops.github.io/Clinthinker/version.json"


def update_failure_cause(stage: str, error: Exception) -> str:
    causes = []
    pending = [error]
    seen = set()
    while pending:
        cause = pending.pop()
        if id(cause) in seen:
            continue
        seen.add(id(cause))
        causes.append(cause)
        if cause.__cause__ is not None:
            pending.append(cause.__cause__)
        if cause.__context__ is not None:
            pending.append(cause.__context__)
        if isinstance(cause, urllib.error.URLError) and isinstance(
            cause.reason, BaseException
        ):
            pending.append(cause.reason)

    if stage == "check for update":
        if any(isinstance(cause, (json.JSONDecodeError, UnicodeDecodeError)) for cause in causes):
            return "the update information is not valid"
        if any(isinstance(cause, (TimeoutError, socket.timeout)) for cause in causes):
            return "the update information request timed out"
        if any(isinstance(cause, urllib.error.URLError) for cause in causes):
            return "the update information could not be reached"
        return "the update information could not be fetched"

    if stage == "validate update info":
        return "the update details could not be validated"

    if stage == "find release on GitHub":
        for cause in causes:
            if isinstance(cause, urllib.error.HTTPError):
                if cause.code == 403 and cause.headers is not None and cause.headers.get(
                    "X-RateLimit-Remaining"
                ) == "0":
                    return "GitHub rate-limited the release lookup"
                if cause.code == 404:
                    return "the GitHub release or installer file was not found"
                if cause.code == 403:
                    return "GitHub denied the release lookup"
            if isinstance(cause, ValueError):
                if str(cause) == "The installer was not found in the GitHub release.":
                    return "the installer file was not found in the GitHub release"
                if str(cause) == "The GitHub release does not contain assets.":
                    return "the GitHub release does not contain installer assets"
                if str(cause) == "Invalid GitHub release response.":
                    return "GitHub returned invalid release information"
        return "GitHub release information could not be retrieved"

    if stage == "download":
        for cause in causes:
            if isinstance(cause, (TimeoutError, socket.timeout)):
                return "the download timed out"
            if isinstance(cause, urllib.error.HTTPError):
                if cause.code == 404:
                    return "the installer file was not found on GitHub"
                if cause.code == 403 and cause.headers is not None and cause.headers.get(
                    "X-RateLimit-Remaining"
                ) == "0":
                    return "GitHub rate-limited the installer download"
            if isinstance(cause, urllib.error.URLError):
                return "the installer could not be reached"
            if isinstance(cause, (ConnectionError, http.client.HTTPException)):
                return "the download was interrupted"
            if isinstance(cause, OSError) and str(cause) == (
                "The installer download ended before completion."
            ):
                return "the download remained incomplete after retries"
        return "the installer download could not be completed after retries"

    if stage == "verify checksum":
        return "the downloaded installer could not be read for verification"

    if stage == "back up database":
        if any(isinstance(cause, FileNotFoundError) for cause in causes):
            return "the local database file is missing"
        return "the database backup could not be created or verified"

    if stage == "launch installer":
        return "the installer could not be started"

    return "an unexpected problem occurred"


def _version_parts(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        return None
    return tuple(int(part) for part in value.split("."))


@checks(
    expected="Update manifest dictionary",
    probable_cause="Update manifest fetch failed",
)
def _fetch_update_manifest() -> dict:
    with urllib.request.urlopen(UPDATE_MANIFEST_URL, timeout=5) as response:
        manifest = json.loads(response.read().decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid update manifest.")
    return manifest


def _valid_installer_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    path_parts = parsed.path.split("/")
    return (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and len(path_parts) == 7
        and path_parts[:5]
        == ["", "seanlordtrillo-ops", "Clinthinker", "releases", "download"]
        and bool(path_parts[5])
        and bool(path_parts[6])
        and not parsed.query
        and not parsed.fragment
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{64}", value) is not None


def _github_asset_api_url(installer_url: str) -> str:
    parsed = urllib.parse.urlsplit(installer_url)
    path_parts = parsed.path.split("/")
    if (
        len(path_parts) != 7
        or path_parts[:5]
        != ["", "seanlordtrillo-ops", "Clinthinker", "releases", "download"]
        or not path_parts[5]
        or not path_parts[6]
    ):
        raise ValueError("The installer URL is not a GitHub release asset URL.")

    tag = urllib.parse.unquote(path_parts[5])
    asset_name = urllib.parse.unquote(path_parts[6])
    release_url = (
        "https://api.github.com/repos/seanlordtrillo-ops/Clinthinker/releases/tags/"
        + urllib.parse.quote(tag, safe="")
    )
    request = urllib.request.Request(
        release_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Clinthinker",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        release = json.loads(response.read().decode("utf-8"))
    if not isinstance(release, dict):
        raise ValueError("Invalid GitHub release response.")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("The GitHub release does not contain assets.")
    for asset in assets:
        if (
            isinstance(asset, dict)
            and asset.get("name") == asset_name
            and isinstance(asset.get("id"), int)
            and not isinstance(asset.get("id"), bool)
        ):
            return (
                "https://api.github.com/repos/seanlordtrillo-ops/Clinthinker/"
                f"releases/assets/{asset['id']}"
            )
    raise ValueError("The installer was not found in the GitHub release.")


@checks(
    expected="Downloaded update installer",
    probable_cause="Update installer download failed",
)
def _download_update_asset(asset_url: str, installer_path: Path) -> None:
    installer_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = installer_path.with_suffix(installer_path.suffix + ".part")
    last_error = None
    for attempt in range(4):
        offset = partial_path.stat().st_size if partial_path.exists() else 0
        headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "Clinthinker",
        }
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(asset_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_headers = getattr(response, "headers", {})
                content_range = response_headers.get("Content-Range", "")
                resume = (
                    offset > 0
                    and getattr(response, "status", None) == 206
                    and content_range.startswith(f"bytes {offset}-")
                )
                mode = "ab" if resume else "wb"
                if not resume:
                    offset = 0
                expected_length = response_headers.get("Content-Length")
                expected_length = (
                    int(expected_length) if expected_length is not None else None
                )
                received = 0
                with partial_path.open(mode) as installer_file:
                    while chunk := response.read(1024 * 1024):
                        installer_file.write(chunk)
                        received += len(chunk)
                if expected_length is not None and received != expected_length:
                    raise OSError("The installer download ended before completion.")
            partial_path.replace(installer_path)
            return
        except (
            http.client.HTTPException,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            last_error = error
            if attempt < 3:
                time.sleep(2**attempt)
    raise OSError("The installer download failed after retries.") from last_error
