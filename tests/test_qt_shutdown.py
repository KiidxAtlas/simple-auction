"""Qt teardown must complete before the test interpreter exits."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_pytest_destroys_remaining_widgets_before_interpreter_shutdown(tmp_path):
    conftest = tmp_path / "conftest.py"
    shutil.copyfile(Path(__file__).with_name("conftest.py"), conftest)
    with conftest.open("a") as stream:
        stream.write(
            "\n\ndef pytest_sessionfinish(session):\n"
            "    from shiboken6 import isValid\n"
            "    assert QApplication.instance() is None\n"
            "    assert all(not isValid(widget) for widget in session.items[0].module.widgets)\n"
        )
    (tmp_path / "test_widgets.py").write_text(
        "from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget\n"
        "app = QApplication.instance() or QApplication([])\n"
        "widgets = []\n\n"
        "def test_hidden_and_deferred_widgets():\n"
        "    parent = QWidget()\n"
        "    child = QLineEdit(parent)\n"
        "    dialog = QDialog()\n"
        "    dialog.deleteLater()\n"
        "    widgets.extend([parent, child, dialog])\n"
        "    assert QApplication.instance() is not None\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
