import logging
import shutil
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QFile, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
)

from simple_auction.constants import APP_NAME, AUTOSAVE_MS, AUTOSAVE_RETRY_MS
from simple_auction.models import Lot
from simple_auction.services import (
    api_key,
    excel,
    listing,
    lookup,
    lot_details,
    numbering,
    research,
)
from simple_auction.services.config import Config
from simple_auction.services.excel import ExcelLockedError
from simple_auction.services.image import lot_photo_files, process_photos
from simple_auction.services.updates import is_frozen
from simple_auction.ui import strings, theme
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.components.lot_sidebar import LotSidebar, Selection
from simple_auction.ui.components.research_panel import ResearchPanel
from simple_auction.ui.settings import SettingsDialog
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
        self.auction_no: int | None = None
        self.lot_no: int | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(*theme.WINDOW_SIZE)

        self.sidebar = LotSidebar()
        self.form = LotForm()
        self.form.set_serial_links(config.serial_links)
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
        self.setCentralWidget(self.splitter)
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
        self.form.changed.connect(lambda: self._autosave.start(AUTOSAVE_MS))
        self.form.save_now.connect(self.flush)
        self.form.export_requested.connect(self.export_current)
        self.form.new_auction_requested.connect(self.create_auction)
        self.form.serial_lookup_requested.connect(self.lookup_serial)
        self.form.research_toggled.connect(self.research.setVisible)
        self.research.closed.connect(self._close_research)

        help_menu = self.menuBar().addMenu(strings.MENU_HELP)
        check = help_menu.addAction(strings.MENU_CHECK_UPDATES, self.check_for_updates)
        # On macOS this puts it in the app menu, next to About and Settings.
        check.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)

        self._startup_update_thread: UpdateCheckThread | None = None
        if is_frozen():  # built app only: running from source isn't "installed"
            QTimer.singleShot(STARTUP_UPDATE_DELAY_MS, self._startup_update_check)

        self.refresh()

    # -- data ---------------------------------------------------------------

    def _path(self, auction_no: int) -> Path:
        return excel.auction_path(self.config.auctions_dir, auction_no)

    def _images_dir(self, auction_no: int) -> Path:
        return self.config.auction_photos_dir(auction_no)

    def _details(self, auction_no: int) -> Path:
        return lot_details.details_path(self.config.data_dir, auction_no)

    def _lots(self, auction_no: int) -> list[Lot]:
        lots = excel.load_auction(self._path(auction_no))
        lot_details.fill(self._details(auction_no), lots)
        return lots

    def refresh(self) -> None:
        folder = self.config.auctions_dir
        self.sidebar.populate(
            {no: self._lots(no) for no in excel.list_auctions(folder)}
        )

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
        self.auction_no, self.lot_no = auction_no, lot.lot_number
        self.form.load(lot, auction_no)

    def _clear(self) -> None:
        self._autosave.stop()
        self.auction_no = self.lot_no = None
        self.form.clear()
        self.research.reset(None)

    def _close_research(self) -> None:
        self.research.hide()
        self.form.set_research_checked(False)

    # -- autosave -----------------------------------------------------------

    def flush(self) -> bool:
        """Save the open lot if it has edits. Returns False if saving failed."""
        self._autosave.stop()
        if self.auction_no is None or not self.form.is_dirty():
            return True
        auction_no = self.auction_no
        lot = listing.apply_condition(self.form.collect())
        path = self._path(auction_no)
        new_photos = any(p.parent != self._images_dir(auction_no) for p in lot.photos)
        if new_photos:  # compressing can take a moment
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            photos = process_photos(
                lot.lot_number, lot.photos, self._images_dir(auction_no), self._trash
            )
            excel.save_lot(path, lot)
            lot_details.save(self._details(auction_no), lot)
        except ExcelLockedError:
            self.form.set_save_state(
                "error", strings.SAVE_LOCKED_INLINE.format(file=path.name)
            )
            self._autosave.start(AUTOSAVE_RETRY_MS)
            return False
        except Exception:
            log.exception("Saving lot %s failed", lot.lot_number)
            self.form.set_save_state("error", strings.SAVE_FAILED_INLINE)
            return False
        finally:
            if new_photos:
                QApplication.restoreOverrideCursor()
        if photos != lot.photos:
            self.form.set_photos(photos)
        self.form.mark_saved()
        self.sidebar.update_title(auction_no, lot.lot_number, lot.title)
        return True

    def _leave_lot(self) -> bool:
        """Save before moving away from the open lot; warn and stay if it fails."""
        if self.flush():
            return True
        self._locked_warning()
        if self.auction_no is not None and self.lot_no is not None:
            self.sidebar.select(self.auction_no, self.lot_no)
        return False

    # -- updates ------------------------------------------------------------

    def check_for_updates(self) -> None:
        UpdateDialog(self).exec()

    def _startup_update_check(self) -> None:
        """Check quietly; only speak up if a newer version exists."""
        # Not parented to the window: deleting a running QThread is fatal.
        thread = UpdateCheckThread()
        thread.checkComplete.connect(self._on_startup_update_checked)
        self._startup_update_thread = thread
        thread.start()

    def _on_startup_update_checked(self, info) -> None:
        if info is not None and info.is_newer:
            UpdateDialog(self, info).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._ui_state.setValue("splitter", self.splitter.saveState())
        thread = self._startup_update_thread
        if thread is not None and thread.isRunning():
            thread.checkComplete.disconnect()
            keep_until_finished(thread)
        self._startup_update_thread = None
        if self.flush():
            event.accept()
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(strings.UNSAVED_TITLE)
        box.setText(
            strings.UNSAVED_BODY.format(
                n=self.lot_no, file=self._path(self.auction_no).name
            )
        )
        quit_btn = box.addButton(
            strings.QUIT_ANYWAY, QMessageBox.ButtonRole.DestructiveRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is quit_btn:
            event.accept()
        else:
            event.ignore()

    # -- create / open ------------------------------------------------------

    def create_auction(self) -> None:
        if not self._leave_lot():
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
        try:
            lot_no = numbering.next_lot(
                self._lots(auction_no), auction_no, self.config.step
            )
        except ValueError as e:
            QMessageBox.warning(self, strings.AUCTION_FULL_TITLE, str(e))
            return
        lot = Lot(lot_number=lot_no)
        try:
            excel.save_lot(self._path(auction_no), lot)
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
        lot = next(
            (x for x in self._lots(auction_no) if x.lot_number == lot_number), None
        )
        if lot is None:
            return
        lot.photos = lot_photo_files(lot_number, self._images_dir(auction_no))
        self._show(auction_no, lot)

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

        for auction_no, numbers in lots.items():
            try:
                excel.delete_lots(self._path(auction_no), numbers)
            except ExcelLockedError:
                self._locked_warning()
                continue
            lot_details.delete(self._details(auction_no), numbers)
            for n in numbers:
                for photo in lot_photo_files(n, self._images_dir(auction_no)):
                    self._trash(photo)
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
            shutil.copy2(self._path(auction_no), dest)
        except OSError:
            log.exception("Exporting auction %s failed", auction_no)
            QMessageBox.critical(self, strings.EXPORT, strings.EXPORT_FAILED)
            return
        self._status(strings.EXPORTED.format(path=dest))

    def open_settings(self) -> None:
        if not self._leave_lot():
            return
        existing = excel.list_auctions(self.config.auctions_dir)
        dialog = SettingsDialog(self.config, existing, self)
        if dialog.exec():
            self.config.base_dir = dialog.base_dir()
            self.config.move_old_files()
            self.config.photos_dir = dialog.photos_dir()
            # Only remember the number if it differs from what the files give.
            from_files = numbering.next_auction(
                excel.list_auctions(self.config.auctions_dir), self.config.step
            )
            chosen = dialog.next_auction()
            self.config.start_at = None if chosen == from_files else chosen
            self.config.serial_links = dialog.serial_links()
            self.config.save()
            self.form.set_serial_links(self.config.serial_links)
            if key := dialog.new_api_key():
                api_key.save(key)
                research.forget_search_check()
                self.research.reset(self.lot_no)  # next question uses the new key
            self._clear()
            self.refresh()
