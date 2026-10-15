"""Guided full backups and isolated restores; activation always requires restart."""

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from simple_auction.services import backup
from simple_auction.services.config import Config
from simple_auction.ui.background import run_io


class BackupDialog(QDialog):
    def __init__(self, config: Config, database=None, remote_client=False, parent=None):
        super().__init__(parent)
        self.config = config
        self.database = database
        self.remote_client = remote_client or config.sharing.mode == "join"
        self.restored = None
        self.activation_requested = False
        self.setWindowTitle("Backup and restore")
        self.resize(580, 340)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "A full backup includes the catalogue, photos, shipping records and settings. "
            "API keys and pairing codes are not included. Keep backups somewhere separate "
            "from your working data. Restore always creates a separate copy."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self._refresh_status()
        layout.addWidget(self.status)
        self.backup_button = QPushButton("Create full backup…")
        self.backup_button.setEnabled(not self.remote_client)
        self.backup_button.clicked.connect(self._backup)
        layout.addWidget(self.backup_button)
        self.restore_button = QPushButton("Restore into a new folder…")
        self.restore_button.clicked.connect(self._restore)
        layout.addWidget(self.restore_button)
        if self.remote_client:
            note = QLabel(
                "This computer is a remote client. Create full backups on the host; its cache is not a full catalogue."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        self.activate_button = QPushButton("Use restored settings after restart…")
        self.activate_button.setEnabled(False)
        self.activate_button.clicked.connect(self._activate)
        layout.addWidget(self.activate_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_status(self):
        value = backup.last_backup_status()
        self.status.setText(
            f"Last full backup: {value.get('created_at', 'unknown time')}\n{value.get('path', '')}"
            if value
            else "No successful full backup recorded on this computer."
        )

    def _backup(self):
        name, _ = QFileDialog.getSaveFileName(
            self, "New full backup", "auction-backup.zip", "ZIP archive (*.zip)"
        )
        if not name:
            return
        try:
            result = run_io(
                self,
                "Creating consistent full backup…",
                lambda: backup.create_backup(
                    self.config,
                    Path(name),
                    database=self.database,
                    remote_client=self.remote_client,
                ),
            )
        except (OSError, ValueError, sqlite3.Error) as e:
            QMessageBox.warning(self, "Backup not created", str(e))
            return
        self._refresh_status()
        self.result_label.setText(
            f"Backup created: {result.path}\n{result.file_count} files.\n{result.status_warning}"
        )

    def _restore(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Open full backup", "", "ZIP archive (*.zip)"
        )
        if not name:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a NEW or EMPTY restore folder"
        )
        if not folder:
            return
        answer = QMessageBox.question(
            self,
            "Restore a separate copy?",
            f"Restore into {folder}?\nCurrent files and settings will not change. "
            "Sharing will be off in the restored copy.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = run_io(
                self,
                "Validating and restoring a separate copy…",
                lambda: backup.restore_backup(Path(name), Path(folder)),
            )
        except (OSError, ValueError, sqlite3.Error) as e:
            QMessageBox.warning(self, "Restore not completed", str(e))
            return
        self.restored = result
        safe_to_activate = (
            self.database is None
            and not self.remote_client
            and self.config.sharing.mode == "off"
        )
        self.activate_button.setEnabled(safe_to_activate)
        self.result_label.setText(
            f"Restored copy: {result.destination}\nRestored settings: {result.config_path}\n"
            "Current settings have NOT changed. Activation requires an explicit choice and restart."
            + (
                "\nStop sharing and reopen this dialog before activating a restored copy."
                if not safe_to_activate
                else ""
            )
        )

    def _activate(self):
        if (
            self.restored is None
            or self.database is not None
            or self.remote_client
            or self.config.sharing.mode != "off"
        ):
            return
        if (
            QMessageBox.question(
                self,
                "Activate restored settings?",
                "Use the restored copy the NEXT time the app starts? Existing settings will be "
                "saved as config.json.bak. Restart immediately after closing this dialog; "
                "do not continue editing the current catalogue.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.restored.config.save()
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Settings not activated", str(e))
            return
        self.activation_requested = True
        self.activate_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.result_label.setText(
            f"Restored settings activated. Restart now.\nCopy: {self.restored.config_path}"
        )
        self.accept()
