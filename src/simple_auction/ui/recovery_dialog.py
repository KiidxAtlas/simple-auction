"""User-accessible, persistent recovery (never silently replaces current work)."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from simple_auction.services import network, recovery
from simple_auction.services.excel import ExcelLockedError
from simple_auction.ui.background import run_io


class RecoveryDialog(QDialog):
    def __init__(self, config, client=None, parent=None):
        super().__init__(parent)
        self.config, self.client = config, client
        self.setWindowTitle("Recover deleted items")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        label = QLabel(
            "Deleted lots and auctions can be restored with their photos. Existing numbers are never overwritten.\nPrevious saved revisions can be exported as snapshot.json and photos to a new folder; copy text or add photos back manually."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.source = QComboBox()
        if client:
            self.source.addItem("Shared host history", True)
        self.source.addItem("This computer's standalone history", False)
        self.source.currentIndexChanged.connect(self.reload)
        layout.addWidget(self.source)
        self.items = QListWidget()
        layout.addWidget(self.items)
        actions = QHBoxLayout()
        self.restore_button = QPushButton("Restore deleted items")
        self.restore_button.clicked.connect(self.restore_selected)
        actions.addWidget(self.restore_button)
        export = QPushButton("Export snapshot…")
        export.clicked.connect(self.export_selected)
        actions.addWidget(export)
        drafts = QPushButton("Open unsaved drafts folder")
        drafts.clicked.connect(self.open_drafts)
        actions.addWidget(drafts)
        layout.addLayout(actions)
        self.items.currentItemChanged.connect(self.selection_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reload()

    def io(self, callback):
        return run_io(self, "Recovering saved data…", callback)

    def selected(self):
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection_changed(self, *_):
        entry = self.selected()
        self.restore_button.setEnabled(
            bool(entry and entry["kind"] in {"lots", "auction"})
        )

    def reload(self, *_):
        self.items.clear()
        try:
            shared = bool(self.source.currentData())
            entries = self.io(
                lambda: (
                    self.client.request("recovery_list")
                    if shared
                    else recovery.list_local(self.config)
                )
            )
            for entry in entries:
                name = {
                    "revision": "Previous saved revision",
                    "lots": "Deleted lots",
                    "auction": "Deleted auction",
                }.get(entry["kind"], entry["kind"])
                item = QListWidgetItem(
                    f"{entry['created']} — Auction {entry['auction']} — {name}"
                )
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.items.addItem(item)
            if not entries:
                self.items.addItem(
                    "No recovery history yet. Only changes made after this feature was installed are recorded."
                )
        except (OSError, ValueError, TypeError, network.NetworkError) as e:
            QMessageBox.warning(self, "Recovery unavailable", str(e))
        self.selection_changed()

    def restore_selected(self):
        entry = self.selected()
        if not entry:
            return
        if (
            QMessageBox.question(
                self,
                "Restore deleted items",
                "Restore this deletion? If any number is already in use, nothing will be overwritten.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            shared = bool(self.source.currentData())
            self.io(
                lambda: (
                    self.client.request("recovery_restore", id=entry["id"])
                    if shared
                    else recovery.restore_local(self.config, entry["id"])
                )
            )
            QMessageBox.information(
                self,
                "Recovered",
                "Deleted items were restored. History is retained for reference.",
            )
        except (
            OSError,
            ValueError,
            TypeError,
            network.NetworkError,
            ExcelLockedError,
        ) as e:
            QMessageBox.warning(self, "Restore stopped", str(e))

    def export_selected(self):
        entry = self.selected()
        if not entry:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a parent folder for the recovered snapshot"
        )
        if not folder:
            return
        from uuid import UUID

        try:
            safe_id = UUID(entry["id"]).hex
        except ValueError, TypeError, AttributeError:
            QMessageBox.warning(self, "Export stopped", "Invalid recovery identity")
            return
        destination = Path(folder) / f"recovered-{safe_id}"
        try:
            shared = bool(self.source.currentData())

            def export():
                if shared:
                    payload = self.client.request("recovery_get", id=entry["id"])
                    recovery.export_snapshot(payload, destination)
                else:
                    recovery.export_local(self.config, entry["id"], destination)

            self.io(export)
            QMessageBox.information(
                self,
                "Snapshot exported",
                f"Text and photos saved to {destination}. Current work was not changed.",
            )
        except (OSError, ValueError, TypeError, network.NetworkError) as e:
            QMessageBox.warning(self, "Export stopped", str(e))

    def open_drafts(self):
        folder = self.config.data_dir / "shared-drafts"
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
