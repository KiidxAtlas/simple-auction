"""Every test gets a throwaway home folder, so nothing a test does can touch
the real settings or data under ~/Documents and ~/.config."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_application_lifetime():
    """Destroy test widgets while Qt and its platform plugin are still alive."""
    app = QApplication.instance() or QApplication([])
    yield app
    # processEvents() alone does not deliver deferred deletion outside exec().
    # Tests may leave hidden windows or deferred children behind. Dispose of
    # those before PySide's atexit cleanup, not during interpreter finalization.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.shutdown()


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    return home
