import csv
import logging
import shutil
import subprocess
from collections import defaultdict
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import (
    QFile,
    QFileSystemWatcher,
    QSettings,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simple_auction.constants import APP_NAME, AUTOSAVE_MS, AUTOSAVE_RETRY_MS
from simple_auction.models import Lot
from simple_auction.services import (
    api_key,
    catalogue,
    excel,
    importer,
    listing,
    lookup,
    lot_details,
    network,
    numbering,
    research,
    source_update,
    storage,
)
from simple_auction.services.config import Config
from simple_auction.services.excel import ExcelLockedError
from simple_auction.services.image import archive_removed, lot_photo_files
from simple_auction.services.updates import is_frozen
from simple_auction.ui import strings, theme
from simple_auction.ui.background import run_io
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.components.lot_sidebar import LotSidebar, Selection
from simple_auction.ui.components.research_panel import ResearchPanel
from simple_auction.ui.import_dialog import ImportDialog
from simple_auction.ui.network_poll import NetworkPoll
from simple_auction.ui.settings import SettingsDialog
from simple_auction.ui.shipping_page import ShippingPage
from simple_auction.ui.source_update_dialog import SourceCheckThread, SourceUpdateDialog
from simple_auction.ui.update_dialog import (
    UpdateCheckThread,
    UpdateDialog,
    keep_until_finished,
)

log = logging.getLogger(__name__)

STATUS_MS = 4000
STARTUP_UPDATE_DELAY_MS = 1500


class MainPage(QMainWindow):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.client = None
        self.host = None
        self._shared_base = None
        self._shared_snapshot = None
        self._poll_worker = None
        self._sharing_signature = None
        self._closing = False
        self.auction_no: int | None = None
        self.lot_no: int | None = None
        self._io_busy = False
        self._save_error: Exception | None = None
        self._catalogue_cache = catalogue.Cache()

        self.setWindowTitle(APP_NAME)
        self.resize(*theme.WINDOW_SIZE)

        self.sidebar = LotSidebar()
        self.form = LotForm()
        self.form.set_serial_links(config.serial_links)
        self.form.set_conditions(config.conditions)
        self.research = ResearchPanel(self.form.current_lot)
        self.research.hide()

        # Drag the edges between the panels to resize them; sizes are remembered.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("content")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        for widget in (self.sidebar, self.form, self.research):
            self.splitter.addWidget(widget)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes(
            [theme.SIDEBAR_WIDTH, theme.WINDOW_SIZE[0], theme.RESEARCH_WIDTH]
        )
        self._ui_state = QSettings(APP_NAME, "window")
        if state := self._ui_state.value("splitter"):
            self.splitter.restoreState(state)
        self.shipping = ShippingPage(config.data_dir / "shipping")
        self.pages = QStackedWidget()
        self.pages.addWidget(self.splitter)
        self.pages.addWidget(self.shipping)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header = QWidget()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        self.workspace_title = QLabel(strings.CATALOGUE_WORKSPACE)
        self.workspace_title.setObjectName("appName")
        header_layout.addWidget(self.workspace_title)
        header_layout.addStretch()
        settings_button = QPushButton(strings.SETTINGS_BTN)
        settings_button.clicked.connect(self.open_settings)
        header_layout.addWidget(settings_button)
        self.network_status = QLabel()
        self.network_status.setObjectName("hint")
        header_layout.addWidget(self.network_status)
        self.reload_shared_button = QPushButton("Reload from host")
        self.reload_shared_button.clicked.connect(self.reload_shared)
        header_layout.addWidget(self.reload_shared_button)
        self.shipping_button = QPushButton(strings.SHIPPING_NAV)
        self.shipping_button.setObjectName("primary")
        self.shipping_button.clicked.connect(self.toggle_workspace)
        header_layout.addWidget(self.shipping_button)
        content_layout.addWidget(header)
        content_layout.addWidget(self.pages, 1)
        self.setCentralWidget(content)
        self.statusBar().setSizeGripEnabled(False)

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self.flush)

        self.sidebar.new_auction.connect(self.create_auction)
        self.sidebar.new_lot.connect(self.create_lot)
        self.sidebar.lot_selected.connect(self.open_lot)
        self.sidebar.export_auction.connect(self.export_auction)
        self.sidebar.delete_requested.connect(self.delete_items)
        self.sidebar.settings_requested.connect(self.open_settings)
        self.sidebar.import_requested.connect(self.import_auctions)
        self.form.changed.connect(lambda: self._autosave.start(AUTOSAVE_MS))
        self.form.save_now.connect(self.flush)
        self.form.export_requested.connect(self.export_current)
        self.form.new_auction_requested.connect(self.create_auction)
        self.form.serial_lookup_requested.connect(self.lookup_serial)
        self.form.research_toggled.connect(self.research.setVisible)
        self.research.closed.connect(self._close_research)

        # The installed (Windows) app updates from release installers; a copy
        # run from a git checkout (e.g. on a Mac) updates by pulling commits.
        self._startup_update_thread: QThread | None = None
        self._source_root = source_update.repo_root()
        if is_frozen() or self._source_root is not None:
            help_menu = self.menuBar().addMenu(strings.MENU_HELP)
            help_menu.addAction(strings.MENU_CHECK_UPDATES, self.check_for_updates)
            QTimer.singleShot(STARTUP_UPDATE_DELAY_MS, self._startup_update_check)

        # conditions.yaml can be edited in any text editor while the app runs.
        self._conditions_watcher = QFileSystemWatcher(self)
        self._conditions_watcher.fileChanged.connect(
            # Editors often save in several steps; read once they're done.
            lambda _path: QTimer.singleShot(300, self._reload_conditions)
        )
        self._conditions_watcher.directoryChanged.connect(
            lambda _path: QTimer.singleShot(300, self._reload_conditions)
        )
        self._watch_conditions()
        if config.conditions_error:
            QTimer.singleShot(
                0, lambda: self._conditions_problem(config.conditions_error)
            )

        self._network_timer = QTimer(self)
        self._network_timer.setInterval(2000)
        self._network_timer.timeout.connect(self._poll_shared)
        QApplication.instance().aboutToQuit.connect(self._stop_sharing)
        self._configure_sharing()
        self.refresh()

    def toggle_workspace(self) -> None:
        if self.pages.currentWidget() is self.splitter:
            if not self._leave_lot() or not self.shipping.activate():
                return
            self.pages.setCurrentWidget(self.shipping)
            self.shipping_button.setText(strings.CATALOGUE_NAV)
            self.workspace_title.setText(strings.SHIPPING_WORKSPACE)
        elif self.shipping.flush():
            self.pages.setCurrentWidget(self.splitter)
            self.shipping_button.setText(strings.SHIPPING_NAV)
            self.workspace_title.setText(strings.CATALOGUE_WORKSPACE)

    # -- data ---------------------------------------------------------------

    def _path(self, auction_no: int) -> Path:
        return excel.auction_path(self.config.auctions_dir, auction_no)

    def _images_dir(self, auction_no: int) -> Path:
        return self.config.auction_photos_dir(auction_no)

    def _details(self, auction_no: int) -> Path:
        return lot_details.details_path(self.config.data_dir, auction_no)

    def _io(self, label: str, operation):
        if self._io_busy:
            raise RuntimeError("A catalogue operation is already in progress")
        self._io_busy = True
        try:
            return run_io(self, label, operation)
        finally:
            self._io_busy = False

    def _lots(self, auction_no: int) -> list[Lot]:
        if self.shared:
            snapshot = self._io("Loading shared auction…", self._client().snapshot)
            self._shared_snapshot = snapshot
            return [
                Lot(**{k: v for k, v in data.items() if k != "photos"})
                for data in snapshot["auctions"].get(str(auction_no), [])
            ]
        path, details = self._path(auction_no), self._details(auction_no)
        return self._io(
            strings.IO_LOADING, lambda: self._catalogue_cache.load(path, details)
        )

    def refresh(self) -> None:
        if self.shared:
            try:
                snapshot = self._io(
                    "Loading shared catalogue…", self._client().snapshot
                )
                self._apply_snapshot(snapshot)
            except network.NetworkError as e:
                self.network_status.setText("Disconnected")
                self.network_status.setToolTip(str(e))
            return
        folder = self.config.auctions_dir
        data_dir = self.config.data_dir

        def load_all():
            auctions, errors = {}, []
            for no in excel.list_auctions(folder):
                try:
                    auctions[no] = self._catalogue_cache.load(
                        excel.auction_path(folder, no),
                        lot_details.details_path(data_dir, no),
                    )
                except (catalogue.CatalogueReadError, OSError) as e:
                    auctions[no] = []
                    errors.append((no, e))
            return auctions, errors

        auctions, errors = self._io(strings.IO_LOADING, load_all)
        self.sidebar.populate(auctions)
        for no, error in errors:
            self._read_error(no, error)

    def _read_error(self, auction_no: int, error: Exception) -> None:
        log.error("Loading auction %s failed: %s", auction_no, error)
        QMessageBox.warning(
            self,
            strings.ERROR_TITLE,
            strings.CATALOGUE_READ_FAILED.format(n=auction_no, error=error),
        )

    def _recycle(self, removed: dict[Path, bytes], folder: Path) -> None:
        if not removed:
            return
        try:
            archive = self._io(
                strings.IO_DELETING, lambda: archive_removed(removed, folder)
            )
            self._trash(archive)
        except OSError as e:
            log.exception("Archiving removed photos failed")
            QMessageBox.warning(self, strings.DELETE, str(e))

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, STATUS_MS)

    def _locked_warning(self) -> None:
        QMessageBox.warning(self, strings.EXCEL_LOCKED_TITLE, strings.EXCEL_LOCKED_BODY)

    def _trash(self, path: Path) -> bool:
        if QFile.moveToTrash(str(path)):
            return True
        QMessageBox.warning(
            self, strings.DELETE, strings.TRASH_FAILED.format(name=path.name)
        )
        return False

    def _confirm_delete(self, what: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(strings.DELETE)
        box.setText(strings.CONFIRM_DELETE.format(what=what))
        delete = box.addButton(strings.DELETE, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is delete

    def _show(self, auction_no: int, lot: Lot) -> None:
        if (auction_no, lot.lot_number) != (self.auction_no, self.lot_no):
            self.research.reset(lot.lot_number)
        if self.shared:
            record = self._record(self._shared_snapshot, auction_no, lot.lot_number)
            if record is not None:
                lot = self._io(
                    "Loading shared photos…", lambda: self._client().materialize(record)
                )
                self._shared_base = record
        self.auction_no, self.lot_no = auction_no, lot.lot_number
        self.form.load(lot, auction_no)

    def _clear(self) -> None:
        self._autosave.stop()
        self.auction_no = self.lot_no = None
        self._shared_base = None
        self.form.clear()
        self.research.reset(None)

    def _close_research(self) -> None:
        self.research.hide()
        self.form.set_research_checked(False)

    # -- autosave -----------------------------------------------------------

    def flush(self) -> bool:
        """Save the open lot if it has edits. Returns False if saving failed."""
        if self._io_busy:
            self._autosave.start(AUTOSAVE_RETRY_MS)
            return False
        self._autosave.stop()
        if self.auction_no is None or not self.form.is_dirty():
            return True
        auction_no = self.auction_no
        lot = listing.apply_condition(self.form.collect(), self.config.conditions)
        path = self._path(auction_no)
        details, images = self._details(auction_no), self._images_dir(auction_no)
        try:
            photos, removed = self._io(
                strings.IO_SAVING,
                lambda: (
                    self._save_shared_lot(auction_no, lot)
                    if self.shared
                    else catalogue.save(path, details, images, lot)
                ),
            )
        except ExcelLockedError as e:
            self._save_error = e
            self.form.set_save_state(
                "error", strings.SAVE_LOCKED_INLINE.format(file=path.name)
            )
            self.form.save_state.setToolTip(str(e))
            self._autosave.start(AUTOSAVE_RETRY_MS)
            return False
        except Exception as e:
            self._save_error = e
            log.exception("Saving lot %s failed", lot.lot_number)
            summary = str(e).splitlines()[0] if str(e) else type(e).__name__
            if len(summary) > 48:
                summary = summary[:45] + "…"
            self.form.set_save_state(
                "error", strings.SAVE_ERROR_INLINE.format(error=summary)
            )
            self.form.save_state.setToolTip(str(e))
            return False
        self._save_error = None
        self.form.save_state.setToolTip("")
        if photos != lot.photos:
            self.form.set_photos(photos)
        self.form.mark_saved()
        self.sidebar.update_title(auction_no, lot.lot_number, lot.title)
        self._recycle(removed, images)
        return True

    def _save_warning(self) -> None:
        if isinstance(self._save_error, ExcelLockedError):
            self._locked_warning()
        else:
            QMessageBox.warning(
                self,
                strings.ERROR_TITLE,
                strings.SAVE_FAILED_DETAIL.format(
                    n=self.lot_no,
                    error=self._save_error or "A save is already in progress",
                ),
            )

    def _leave_lot(self) -> bool:
        """Save before moving away from the open lot; warn and stay if it fails."""
        if self.flush():
            return True
        self._save_warning()
        if self.auction_no is not None and self.lot_no is not None:
            self.sidebar.select(self.auction_no, self.lot_no)
        return False

    # -- updates ------------------------------------------------------------

    def check_for_updates(self) -> None:
        if self._source_root is not None:
            dialog = SourceUpdateDialog(self._source_root, self)
            dialog.restart_requested.connect(self._restart_after_update)
            dialog.exec()
        else:
            UpdateDialog(self).exec()

    def _restart_after_update(self) -> None:
        """Close (saving the open lot) and start the updated code."""
        if not self.close():
            return
        subprocess.Popen(
            source_update.restart_command(),
            cwd=self._source_root,
            start_new_session=True,
        )
        QApplication.quit()

    def _startup_update_check(self) -> None:
        """Check quietly; only speak up if there's something new."""
        # Not parented to the window: deleting a running QThread is fatal.
        if self._source_root is not None:
            thread = SourceCheckThread(self._source_root)
            thread.checked.connect(self._on_startup_source_checked)
        else:
            thread = UpdateCheckThread()
            thread.checkComplete.connect(self._on_startup_update_checked)
        self._startup_update_thread = thread
        thread.start()

    def _on_startup_source_checked(self, status, _error: str) -> None:
        if status is not None and status.behind:
            self.statusBar().showMessage(
                strings.SOURCE_UPDATES_WAITING.format(
                    changes=strings.count(status.behind, "update")
                )
            )

    def _on_startup_update_checked(self, info, _error: str = "") -> None:
        if self._io_busy:
            QTimer.singleShot(
                300, lambda: self._on_startup_update_checked(info, _error)
            )
            return
        if info is not None and info.is_newer:
            UpdateDialog(self, info).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._io_busy or self.shipping.busy:
            event.ignore()
            return
        if not self.shipping.flush():
            event.ignore()
            return
        self._ui_state.setValue("splitter", self.splitter.saveState())
        thread = self._startup_update_thread
        if thread is not None and thread.isRunning():
            for name in ("checkComplete", "checked"):
                if (signal := getattr(thread, name, None)) is not None:
                    signal.disconnect()
            keep_until_finished(thread)
        self._startup_update_thread = None
        if self.flush():
            self.research.reset(None)
            self._stop_sharing()
            event.accept()
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(strings.UNSAVED_TITLE)
        box.setText(
            strings.UNSAVED_BODY.format(
                n=self.lot_no,
                file=self._path(self.auction_no).name,
                error=self._save_error,
            )
        )
        quit_btn = box.addButton(
            strings.QUIT_ANYWAY, QMessageBox.ButtonRole.DestructiveRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is quit_btn:
            self.research.reset(None)
            self._stop_sharing()
            event.accept()
        else:
            event.ignore()

    # -- create / open ------------------------------------------------------

    def create_auction(self) -> None:
        if not self._leave_lot():
            return
        if self.shared:
            try:
                auction_no = self._io(
                    "Creating shared auction…",
                    lambda: self._client().request("new_auction"),
                )
                self.create_lot(auction_no)
            except (network.NetworkError, ValueError) as e:
                QMessageBox.warning(self, "Sharing", str(e))
            return
        existing = excel.list_auctions(self.config.auctions_dir)
        auction_no = numbering.next_auction(
            existing, self.config.step, self.config.start_at
        )
        excel.create_auction(self._path(auction_no))
        if self.config.start_at is not None:
            # The new file now carries the series forward on its own.
            self.config.start_at = None
            self.config.save()
        self.create_lot(auction_no)

    def create_lot(self, auction_no: int) -> None:
        """Add the next lot to the auction, then select and open it."""
        if not self._leave_lot():
            return
        if self.shared:
            try:
                data = self._io(
                    "Creating shared lot…",
                    lambda: self._client().request("new_lot", auction=auction_no),
                )
                lot = Lot(**{k: v for k, v in data.items() if k != "photos"})
                self.refresh()
                self.sidebar.select(auction_no, lot.lot_number)
                self._show(auction_no, lot)
                self.form.serial.setFocus()
            except (network.NetworkError, ValueError) as e:
                QMessageBox.warning(self, "Sharing", str(e))
            return
        try:
            lot_no = numbering.next_lot(
                self._lots(auction_no), auction_no, self.config.step
            )
        except (catalogue.CatalogueReadError, OSError) as e:
            self._read_error(auction_no, e)
            return
        except ValueError as e:
            QMessageBox.warning(self, strings.AUCTION_FULL_TITLE, str(e))
            return
        # No condition until someone picks one, so nothing is added to the
        # title or description before then (same as imported lots).
        lot = Lot(lot_number=lot_no)
        try:
            path, details = self._path(auction_no), self._details(auction_no)
            self._io(strings.IO_SAVING, lambda: catalogue.add(path, details, [lot]))
        except ExcelLockedError:
            self._locked_warning()
            return
        self.refresh()
        self.sidebar.select(auction_no, lot_no)
        self._show(auction_no, lot)
        self.form.serial.setFocus()

    def open_lot(self, auction_no: int, lot_number: int) -> None:
        if (auction_no, lot_number) == (self.auction_no, self.lot_no):
            return
        if not self._leave_lot():
            return
        try:
            lot = next(
                (x for x in self._lots(auction_no) if x.lot_number == lot_number), None
            )
        except (catalogue.CatalogueReadError, OSError) as e:
            self._read_error(auction_no, e)
            if self.auction_no is not None and self.lot_no is not None:
                self.sidebar.select(self.auction_no, self.lot_no)
            return
        if lot is None:
            return
        lot.photos = lot_photo_files(lot_number, self._images_dir(auction_no))
        try:
            self._show(auction_no, lot)
        except network.NetworkError as e:
            QMessageBox.warning(self, "Sharing", str(e))

    def lookup_serial(self, serial: str) -> None:
        path = lookup.table_path(self.config.data_dir)
        try:
            rules = lookup.load_rules(path)
        except (ValueError, KeyError, TypeError) as e:
            log.warning("Bad serial table %s: %s", path, e)
            self._status(strings.LOOKUP_TABLE_ERROR.format(error=e))
            self.form.show_lookup([])
            return
        if not rules:  # no table set up: just offer the lookup site
            self.form.show_lookup(None)
            return
        self.form.show_lookup(lookup.lookup_serial(serial, rules))

    # -- delete -------------------------------------------------------------

    def delete_items(self, items: list[Selection]) -> None:
        auctions = {a for a, lot in items if lot is None}
        lots: dict[int, set[int]] = defaultdict(set)
        for a, lot in items:
            if lot is not None and a not in auctions:  # covered by the auction
                lots[a].add(lot)
        n_lots = sum(len(v) for v in lots.values())
        what = " and ".join(
            part
            for part in (
                strings.count(len(auctions), "auction") if auctions else "",
                strings.count(n_lots, "lot") if n_lots else "",
            )
            if part
        )
        if not what or not self._confirm_delete(what):
            return
        # Save pending edits first, so they aren't written back after a delete.
        if not self._leave_lot():
            return

        if self.shared:
            try:
                snapshot = self._io(
                    "Checking shared auctions…", self._client().snapshot
                )
                for auction_no in sorted(auctions | lots.keys()):
                    self._io(
                        "Deleting shared records…",
                        lambda a=auction_no: self._client().request(
                            "delete",
                            auction=a,
                            numbers=None if a in auctions else sorted(lots[a]),
                            expected=snapshot["auctions"].get(str(a)),
                        ),
                    )
                self._clear()
                self.refresh()
            except network.NetworkError as e:
                QMessageBox.warning(self, "Sharing", str(e))
            return

        for auction_no, numbers in lots.items():
            try:
                path, details, images = (
                    self._path(auction_no),
                    self._details(auction_no),
                    self._images_dir(auction_no),
                )
                removed = self._io(
                    strings.IO_DELETING,
                    partial(catalogue.delete, path, details, images, numbers),
                )
            except ExcelLockedError:
                self._locked_warning()
                continue
            self._recycle(removed, images)
            if self.auction_no == auction_no and self.lot_no in numbers:
                self._clear()

        for auction_no in auctions:
            if not self._trash(self._path(auction_no)):
                continue
            if self._details(auction_no).exists():
                self._trash(self._details(auction_no))
            images = self._images_dir(auction_no)
            if images.exists():
                self._trash(images)
            if self.auction_no == auction_no:
                self._clear()

        self.refresh()
        if self.auction_no is not None and self.lot_no is not None:
            self.sidebar.select(self.auction_no, self.lot_no)
        self._status(strings.DELETED.format(what=what))

    # -- export / settings --------------------------------------------------

    def export_current(self) -> None:
        if self.auction_no is not None:
            self.export_auction(self.auction_no)

    def export_auction(self, auction_no: int) -> None:
        if not self._leave_lot():
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            strings.EXPORT,
            str(Path.home() / "Documents" / f"{auction_no}.xlsx"),
            "Excel (*.xlsx)",
        )
        if not dest:
            return
        try:
            if self.shared:

                def shared_export():
                    snapshot = self._client().snapshot()
                    from openpyxl import Workbook

                    wb = Workbook()
                    try:
                        wb.active.append(excel.HEADERS)
                        if str(auction_no) not in snapshot["auctions"]:
                            raise network.NetworkError("This auction was deleted")
                        for data in snapshot["auctions"][str(auction_no)]:
                            lot = Lot(
                                **{k: v for k, v in data.items() if k != "photos"}
                            )
                            wb.active.append(excel._lot_to_row(lot))
                        storage.atomic_write(Path(dest), excel._encode(wb))
                    finally:
                        wb.close()

                self._io("Exporting shared auction…", shared_export)
            else:
                shutil.copy2(self._path(auction_no), dest)
        except OSError, network.NetworkError:
            log.exception("Exporting auction %s failed", auction_no)
            QMessageBox.critical(self, strings.EXPORT, strings.EXPORT_FAILED)
            return
        self._status(strings.EXPORTED.format(path=dest))

    def import_auctions(self) -> None:
        """Import lots from old auction spreadsheets, one dialog per file."""
        if not self._leave_lot():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            strings.IMPORT_PICK,
            str(Path.home()),
            "Spreadsheets (*.xlsx *.xlsm *.csv)",
        )
        for name in files:
            self._import_file(Path(name))

    def _import_file(self, path: Path) -> None:
        try:
            sheet = importer.read_sheet(path)
        except (importer.SheetReadError, OSError, UnicodeDecodeError, csv.Error) as e:
            log.warning("Import of %s failed: %s", path, e)
            QMessageBox.warning(
                self,
                strings.IMPORT_READ_FAILED_TITLE,
                strings.IMPORT_READ_FAILED.format(name=path.name, error=e),
            )
            return
        if not sheet.rows:
            QMessageBox.information(
                self, strings.IMPORT_TITLE, strings.IMPORT_EMPTY.format(name=path.name)
            )
            return

        existing = self._existing_auctions()
        suggested = numbering.next_auction(
            existing, self.config.step, self.config.start_at
        )
        dialog = ImportDialog(
            path,
            sheet,
            existing,
            lambda n: {lot.lot_number for lot in self._lots(n)},
            suggested,
            self.config.step,
            [o.name for o in self.config.conditions],
            parent=self,
        )
        if not dialog.exec():
            return
        auction_no, lots = dialog.auction_no(), dialog.lots()
        try:
            workbook, details = self._path(auction_no), self._details(auction_no)
            added = self._io(
                strings.IO_IMPORTING,
                lambda: (
                    [
                        Lot(**v)
                        for v in self._client().request(
                            "import_lots",
                            auction=auction_no,
                            lots=[network.lot_data(lot) for lot in lots],
                        )
                    ]
                    if self.shared
                    else catalogue.add(workbook, details, lots)
                ),
            )
        except ExcelLockedError:
            self._locked_warning()
            return
        except network.NetworkError as e:
            QMessageBox.warning(self, "Sharing", str(e))
            return

        self.refresh()
        if added:
            self.sidebar.select(auction_no, added[0].lot_number)
            self.open_lot(auction_no, added[0].lot_number)
            self._status(
                strings.IMPORTED.format(
                    lots=strings.count(len(added), "lot"), n=auction_no
                )
            )
        else:
            self._status(strings.IMPORTED_NONE.format(n=auction_no))

    # -- conditions.yaml ----------------------------------------------------

    def _watch_conditions(self) -> None:
        watcher = self._conditions_watcher
        paths = watcher.files() + watcher.directories()
        if paths:
            watcher.removePaths(paths)
        path = self.config.conditions_path
        if path.parent.exists():
            watcher.addPath(str(path.parent))
        if path.exists():
            watcher.addPath(str(path))

    def _reload_conditions(self) -> None:
        if self._io_busy:
            QTimer.singleShot(300, self._reload_conditions)
            return
        if not self.config.conditions_path.exists():
            # Editors can remove the file before replacing it. Keep the last
            # good list and the directory watch instead of recreating the file.
            self._watch_conditions()
            return
        before = list(self.config.conditions)
        error = self.config.load_conditions()
        self._watch_conditions()  # editors that replace the file drop the watch
        if error:
            self._conditions_problem(error)
            return
        if self.config.conditions != before:
            self.form.set_conditions(self.config.conditions)
            self._status(strings.CONDITIONS_RELOADED)

    def _conditions_problem(self, error: str) -> None:
        if self._io_busy:
            QTimer.singleShot(300, lambda: self._conditions_problem(error))
            return
        QMessageBox.warning(
            self,
            strings.CONDITIONS_FILE_ERROR_TITLE,
            strings.CONDITIONS_FILE_ERROR.format(error=error),
        )

    def open_settings(self) -> None:
        # A disconnected client must still be able to repair its connection.
        # Drafts are preserved below, rather than blocking Settings behind save.
        if self.config.sharing.mode == "off":
            if not self.shipping.flush() or not self._leave_lot():
                return
        else:
            self.shipping.flush(warn=False)
            self.flush()
        existing = (
            list(map(int, self._shared_snapshot["auctions"]))
            if self.shared and self._shared_snapshot
            else excel.list_auctions(self.config.auctions_dir)
        )
        dialog = SettingsDialog(self.config, existing, self)
        if dialog.exec():
            chosen_sharing = dialog.sharing()
            drafts = self._connection_drafts()
            old_base = self.config.base_dir
            self.config.base_dir = dialog.base_dir()
            self.config.move_old_files()
            # A new main folder has (or gets) its own conditions.yaml.
            moved = self.config.base_dir != old_base
            if moved and not self.shared:
                self.shipping.reload(self.config.data_dir / "shipping")
            if moved and (error := self.config.load_conditions()):
                self._conditions_problem(error)
            new_photos = dialog.photos_dir()
            database = (
                self.host.db
                if self.host
                else (
                    self.client.db
                    if isinstance(self.client, network.LocalClient)
                    else None
                )
            )
            if database and new_photos != self.config.photos_dir:

                def copy_shared_assets():
                    for asset in database.assets.glob("*.jpg"):
                        target = new_photos / ".shared" / database.identity / asset.name
                        if not target.exists():
                            storage.atomic_write(target, asset.read_bytes())

                self._io("Copying shared photos to the new folder…", copy_shared_assets)
            self.config.photos_dir = new_photos
            # Only remember the number if it differs from what the files give.
            from_files = numbering.next_auction(
                existing
                if self.shared
                else excel.list_auctions(self.config.auctions_dir),
                self.config.step,
            )
            chosen = dialog.next_auction()
            self.config.start_at = None if chosen == from_files else chosen
            self.config.serial_links = dialog.serial_links()
            conditions = dialog.conditions()
            if conditions != dialog.original_conditions():
                # Only rewrite the file when the table changed, so comments
                # someone added to conditions.yaml aren't lost.
                self.config.conditions = conditions
                self.config.save_conditions()
            chosen_dark = dialog.dark_mode()
            replace(self.config, dark_mode=chosen_dark, sharing=chosen_sharing).save()
            self.config.dark_mode = chosen_dark
            self.config.sharing = chosen_sharing
            self._configure_sharing()
            theme.apply(QApplication.instance(), dark_mode=chosen_dark)
            self._watch_conditions()
            self.form.set_serial_links(self.config.serial_links)
            self.form.set_conditions(self.config.conditions)
            if key := dialog.new_api_key():
                api_key.save(key)
                research.forget_search_check()
                self.research.reset(self.lot_no)  # next question uses the new key
            self._clear()
            self.refresh()
            self._restore_connection_drafts(drafts)

    @property
    def shared(self):
        return (
            self.config.sharing.mode != "off"
            or (self.config.data_dir / "shared.sqlite3").exists()
        )

    def _client(self):
        if self.client is None:
            raise network.NetworkError(
                "The host is unavailable. Open Settings → Local network sharing to reconnect."
            )
        return self.client

    @staticmethod
    def _record(snapshot, auction, lot):
        if snapshot is None:
            return None
        return next(
            (
                v
                for v in snapshot["auctions"].get(str(auction), [])
                if v["lot_number"] == lot
            ),
            None,
        )

    def _existing_auctions(self):
        if self.shared:
            snapshot = self._io("Loading shared auctions…", self._client().snapshot)
            return sorted(map(int, snapshot["auctions"]))
        return excel.list_auctions(self.config.auctions_dir)

    def _save_shared_lot(self, auction, lot):
        if self._shared_base is None:
            raise network.NetworkError("Reload this lot from the host before editing")
        updated = self._client().save_lot(auction, lot, self._shared_base)
        # The save response becomes the next baseline only after all downloads
        # succeed. Retrying an interrupted save is idempotent on the server.
        photos = self._client().materialize(updated).photos
        self._shared_base = updated
        return photos, {}

    def _connection_signature(self):
        settings = self.config.sharing
        return (
            settings.mode,
            settings.address,
            settings.port,
            settings.code,
            settings.share_id,
            self.config.base_dir,
            self.config.photos_dir,
        )

    def _configure_sharing(self):
        settings = self.config.sharing
        signature = self._connection_signature()
        if self._sharing_signature == signature:
            return
        if (
            settings.mode == "off"
            and self._sharing_signature is None
            and self.client is None
            and self.host is None
            and not (self.config.data_dir / "shared.sqlite3").exists()
        ):
            self.reload_shared_button.hide()
            self.network_status.hide()
            if self.shipping.shared:
                self.shipping.set_connection(None, False)
                self.shipping.reload(self.config.data_dir / "shipping")
            return
        self._network_timer.stop()
        previous_host = self.host
        self.host = None
        if previous_host:
            self._io("Stopping local host…", previous_host.close)
        self.client = None
        self._shared_snapshot = None
        self._shared_base = None
        self.reload_shared_button.setVisible(self.shared)
        self.network_status.setVisible(self.shared)
        self._sharing_signature = None
        if settings.mode == "off":
            if (self.config.data_dir / "shared.sqlite3").exists():
                try:
                    db = self._io(
                        "Opening local catalogue database…",
                        lambda: network.Database(self.config),
                    )
                    self.client = network.LocalClient(
                        db, self.config.data_dir / "shared-cache"
                    )
                    self.shipping.set_connection(self.client, True)
                    self.shipping.folder = self.config.data_dir / "shipping"
                    self._apply_snapshot(
                        self._io("Loading local catalogue…", self.client.snapshot)
                    )
                except (OSError, network.NetworkError) as e:
                    self.shipping.set_connection(None, True)
                    self.sidebar.populate({})
                    QMessageBox.warning(self, "Local catalogue database", str(e))
            else:
                self.shipping.set_connection(None, False)
                self.shipping.reload(self.config.data_dir / "shipping")
            self.network_status.hide()
            self.reload_shared_button.hide()
            self._sharing_signature = signature
            return
        try:
            settings.validate()
            if settings.mode == "host":
                self.host = self._io(
                    "Starting local host and importing existing data…",
                    lambda: network.Host(self.config, settings.code, settings.port),
                )
                address = f"127.0.0.1:{self.host.port}"
                identity = self.host.db.identity
            else:
                address = network.endpoint(settings.address, settings.port)
                identity = settings.share_id
            self.client = network.Client(
                address,
                settings.code,
                identity=identity,
                cache=self.config.data_dir / "shared-cache",
            )
            self.shipping.folder = self.config.data_dir / "shipping"
            self.shipping.set_connection(self.client, True)
            snapshot = self._io("Connecting to local host…", self.client.snapshot)
            self._apply_snapshot(snapshot)
            self._sharing_signature = self._connection_signature()
        except (
            OSError,
            ValueError,
            network.NetworkError,
            catalogue.CatalogueReadError,
        ) as e:
            self.shipping.set_connection(self.client, True)
            self.network_status.setText("Disconnected · check Settings")
            self.network_status.setToolTip(str(e))
            self.sidebar.populate({})
            if settings.mode == "join" and isinstance(e, network.Unavailable):
                self.network_status.setText(
                    "Waiting for host · reconnecting automatically"
                )
                self._sharing_signature = signature
            else:
                QMessageBox.warning(self, "Local network sharing", str(e))
        self._network_timer.start()

    def _remember_connection(self):
        settings = self.config.sharing
        if settings.mode != "join" or self.client is None:
            return
        if (
            network.endpoint(settings.address, settings.port) == self.client.address
            and settings.share_id == self.client.identity
        ):
            return
        saved = replace(
            settings, address=self.client.address, share_id=self.client.identity
        )
        try:
            replace(self.config, sharing=saved).save()
        except OSError, ValueError:
            log.exception("Could not remember the reconnected host")
            self._status(
                "Connected, but could not remember the host address. Retrying automatically."
            )
            return
        self.config.sharing = saved
        self._sharing_signature = self._connection_signature()

    def _apply_snapshot(self, snapshot):
        if self.client is not None and not self.client.identity:
            self.client.identity = snapshot["identity"]
        self._remember_connection()
        changed = (
            not self._shared_snapshot
            or snapshot["revision"] != self._shared_snapshot["revision"]
        )
        self._shared_snapshot = snapshot
        if changed:
            auctions = {
                int(a): [
                    Lot(**{k: v for k, v in data.items() if k != "photos"})
                    for data in lots
                ]
                for a, lots in snapshot["auctions"].items()
            }
            self.sidebar.populate(auctions)
            if self.auction_no is not None and self.lot_no is not None:
                self.sidebar.select(self.auction_no, self.lot_no)
        state = (
            "Local"
            if isinstance(self.client, network.LocalClient)
            else ("Hosting" if self.host else "Connected")
        )
        self.network_status.setText(
            state
            + (
                " · unsaved changes"
                if self.form.is_dirty() or self.shipping.dirty
                else " · synced"
            )
        )
        self.network_status.setToolTip(
            "The host shares auctions, photos, and shipping. Keep it awake and allow Simple Auction through the private-network firewall."
        )

    def _poll_shared(self):
        if (
            self._closing
            or self.config.sharing.mode == "off"
            or not self.shared
            or self.client is None
            or self._poll_worker is not None
            or self._io_busy
            or self.shipping.busy
            or QApplication.activeModalWidget()
        ):
            return
        key = (self.auction_no, self.lot_no) if self.auction_no is not None else None
        worker = NetworkPoll(self.client, self.shipping.path, key, self._shared_base)
        self._poll_worker = worker
        worker.finished.connect(self._poll_finished)
        worker.start()

    def _poll_finished(self):
        worker = self._poll_worker
        self._poll_worker = None
        if worker is None:
            return
        try:
            if (
                self._closing
                or worker.client is not self.client
                or self._io_busy
                or self.shipping.busy
                or QApplication.activeModalWidget()
            ):
                return
            if worker.connection is not None and not isinstance(
                self.client, network.LocalClient
            ):
                self.client._next_discovery = worker.connection._next_discovery
                if worker.error is None:
                    self.client.address = worker.connection.address
                    self.client.identity = worker.connection.identity
            if worker.error:
                self.network_status.setText("Reconnecting automatically · edits kept")
                self.network_status.setToolTip(str(worker.error))
                return
            snapshot, batch, record, lot = worker.result
            self._apply_snapshot(snapshot)
            if (
                not self.form.is_dirty()
                and worker.current_key == (self.auction_no, self.lot_no)
                and worker.baseline == self._shared_base
            ):
                if record is None and self.auction_no is not None:
                    self._clear()
                elif lot is not None:
                    self._shared_base = record
                    self.form.load(lot, self.auction_no)
            elif (
                self.form.is_dirty()
                and worker.current_key == (self.auction_no, self.lot_no)
                and record != self._shared_base
            ):
                self.network_status.setText("Lot changed on host · your edits kept")
            if worker.shipping_key == self.shipping.path:
                self.shipping.sync_snapshot(snapshot["shipping"], batch)
        finally:
            worker.deleteLater()

    def reload_shared(self):
        if self._io_busy or self.shipping.busy:
            return
        dirty = self.form.is_dirty() or self.shipping.dirty
        if (
            dirty
            and QMessageBox.question(
                self,
                "Reload from host",
                "Reloading will discard your unsaved edits and load the host's latest data. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            snapshot = self._io("Reloading from host…", self._client().snapshot)
            record = self._record(snapshot, self.auction_no, self.lot_no)
            if record:
                lot = self._io(
                    "Downloading photos…", lambda: self._client().materialize(record)
                )
                self._shared_base = record
                self.form.load(lot, self.auction_no)
            else:
                self._clear()
            path = self.shipping.path
            batch = (
                self._io(
                    "Reloading shipping…",
                    lambda: self._client().request("get_shipping", key=path),
                )
                if path
                else None
            )
            self.shipping.dirty = False
            self.shipping._save_timer.stop()
            self.shipping.sync_snapshot(snapshot["shipping"], batch)
            self._apply_snapshot(snapshot)
        except network.NetworkError as e:
            QMessageBox.warning(self, "Sharing", str(e))

    def _stop_sharing(self):
        if self._closing:
            return
        self._closing = True
        self._network_timer.stop()
        if self._poll_worker is not None:
            self._poll_worker.finished.disconnect(self._poll_finished)
            keep_until_finished(self._poll_worker)
            self._poll_worker = None
        if self.host:
            self.host.close()
            self.host = None

    def _connection_drafts(self):
        if not self.form.is_dirty() and not self.shipping.dirty:
            return None
        import json
        from uuid import uuid4

        lot = self.form.collect() if self.form.is_dirty() else None
        drafts = {
            "identity": self.client.identity if self.client else "",
            "auction": self.auction_no,
            "lot": lot,
            "lot_base": self._shared_base,
            "shipping": self.shipping.batch if self.shipping.dirty else None,
            "shipping_key": self.shipping.path,
            "shipping_base": self.shipping._shared_base,
        }
        # A durable copy also survives switching to a different host or quitting.
        serializable = dict(drafts)
        serializable["lot"] = (
            {**network.lot_data(lot), "photos": [str(p) for p in lot.photos]}
            if lot
            else None
        )
        serializable["shipping"] = (
            network.batch_data(drafts["shipping"]) if drafts["shipping"] else None
        )
        path = self.config.data_dir / "shared-drafts" / (uuid4().hex + ".json")
        self._io(
            "Preserving unsaved edits…",
            lambda: storage.atomic_write(
                path, json.dumps(serializable, default=str).encode()
            ),
        )
        drafts["backup"] = path
        return drafts

    def _restore_connection_drafts(self, drafts):
        if drafts is None:
            return
        if not self.client or self.client.identity != drafts["identity"]:
            QMessageBox.information(
                self,
                "Unsaved edits preserved",
                f"Your previous edits were saved to {drafts['backup']} because the selected host changed.",
            )
            return
        if drafts["lot"] is not None:
            self.auction_no = drafts["auction"]
            self.lot_no = drafts["lot"].lot_number
            self._shared_base = drafts["lot_base"]
            self.form.load(drafts["lot"], self.auction_no)
            self.form._dirty = True
            self.form.set_save_state(
                "error", "Unsaved edits preserved. Save again after reconnecting."
            )
            self.sidebar.select(self.auction_no, self.lot_no)
        if drafts["shipping"] is not None:
            self.shipping.batch = drafts["shipping"]
            self.shipping.path = drafts["shipping_key"]
            self.shipping._shared_base = drafts["shipping_base"]
            self.shipping.dirty = True
            self.shipping._fill_buyers()
            self.shipping.notice.setText(
                "Unsaved edits preserved. Reconnect and save again."
            )
