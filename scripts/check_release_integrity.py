#!/usr/bin/env python3
"""Validate release metadata consistency across backend/web/changelog/workflows."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(1)


def read_backend_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        fail("Missing [project].version in pyproject.toml")
    return version


def read_web_version() -> str:
    package_json = ROOT / "web" / "package.json"
    data = json.loads(package_json.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str) or not version:
        fail("Missing version in web/package.json")
    return version


def assert_changelog_has_released_entry(version: str) -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(rf"^## \[{re.escape(version)}\] — (.+)$", re.MULTILINE)
    match = pattern.search(changelog)
    if not match:
        fail(f"CHANGELOG.md missing release heading for version {version}")
    if match.group(1).strip().lower() == "unreleased":
        fail(f"CHANGELOG.md version {version} is still marked Unreleased")


def assert_publish_environment() -> None:
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8",
    )
    if "environment: pypi" not in publish:
        fail("publish.yml must include environment: pypi")


def main() -> int:
    backend_version = read_backend_version()
    web_version = read_web_version()

    if backend_version != web_version:
        fail(
            "Version mismatch: "
            f"pyproject.toml={backend_version}, web/package.json={web_version}",
        )

    assert_changelog_has_released_entry(backend_version)
    assert_publish_environment()

    print("OK: release integrity checks passed")
    print(f"Version: {backend_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
