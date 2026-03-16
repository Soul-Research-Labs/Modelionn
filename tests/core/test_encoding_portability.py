from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TOKENS = ("btoa(", "atob(")
TARGET_DIRS = ("sdk", "registry", "subnet")


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for rel in TARGET_DIRS:
        files.extend((ROOT / rel).rglob("*.py"))
    return files


def test_shared_python_modules_do_not_use_browser_base64_apis() -> None:
    offenders: list[str] = []

    for file_path in _iter_python_files():
        text = file_path.read_text(encoding="utf-8")
        if any(token in text for token in FORBIDDEN_TOKENS):
            offenders.append(str(file_path.relative_to(ROOT)))

    assert not offenders, (
        "Browser-only base64 helpers found in shared Python modules: "
        + ", ".join(offenders)
    )
