"""Bounded smoke tests for startup, shutdown, and release metadata."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_startup_and_shutdown_complete(tmp_path: Path) -> None:
    """The real window opens and closes cleanly (bounded so CI can't hang)."""
    source = f"""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from simple_auction.services.config import Config
from simple_auction.ui import theme
from simple_auction.ui.main_page import MainPage

app = QApplication([])
theme.apply(app)
base = Path({str(tmp_path)!r})
window = MainPage(Config(base_dir=base, photos_dir=base / "photos"))
window.show()
QTimer.singleShot(25, window.close)
QTimer.singleShot(75, app.quit)
raise SystemExit(app.exec())
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            # Keep the real window layout settings untouched.
            "HOME": str(tmp_path),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_version_matches_pyproject() -> None:
    from simple_auction import __version__

    with (ROOT / "pyproject.toml").open("rb") as handle:
        assert __version__ == tomllib.load(handle)["project"]["version"]


def test_release_metadata_check_is_non_mutating() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    tag = f"v{version}"
    result = subprocess.run(
        ["bash", "scripts/release.sh", "--check", tag],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert f"Release metadata is consistent for {tag}." in result.stdout


def test_release_check_rejects_wrong_tag() -> None:
    result = subprocess.run(
        ["bash", "scripts/release.sh", "--check", "v999.0.0"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "does not match" in (result.stderr + result.stdout)
