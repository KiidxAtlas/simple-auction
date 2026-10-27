import csv
import logging
import subprocess
from collections import defaultdict
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import (
    QFile,
    QFileSystemWatcher,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
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
    dossier,
    excel,
    importer,
    kpi,
    lookup,
    lot_details,
    network,
    numbering,
    output,
    research,
    source_update,
    storage,
)
from simple_auction.services.config import Config
from simple_auction.services.excel import ExcelLockedError
from simple_auction.services.image import archive_removed, lot_photo_files
from simple_auction.services.updates import is_frozen
from simple_auction.ui import strings, theme
from simple_auction.ui.background import PhotoFixThread, run_io
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.components.lot_sidebar import LotSidebar, Selection
from simple_auction.ui.components.research_panel import ResearchPanel
from simple_auction.ui.import_dialog import ImportDialog
from simple_auction.ui.network_poll import NetworkPoll
from simple_auction.ui.output_page import OutputPage
from simple_auction.ui.settings import SettingsDialog
from simple_auction.ui.shipping_page import ShippingPage
from simple_auction.ui.source_update_dialog import SourceCheckThread, SourceUpdateDialog
from simple_auction.ui.toast import UNDO_MS, Toast
from simple_auction.ui.update_dialog import (
    UpdateCheckThread,
    UpdateDialog,
    keep_until_finished,
)

log = logging.getLogger(__name__)

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
        self._catalogue_lots: dict[int, list[Lot]] = {}
        self._phone_imports = []  # retain temporary images until a successful save

        self.setWindowTitle(APP_NAME)
        self.resize(*theme.WINDOW_SIZE)
        self.setMinimumSize(*theme.WINDOW_MIN_SIZE)

        self.sidebar = LotSidebar()
        self.form = LotForm()
        self.form.set_serial_links(config.serial_links)
        self.form.set_conditions(config.conditions)
        self.form.set_custom_fields(config.custom_fields)
        self.form.set_title_fields(config.title_fields)
        self.form.set_desc_fields(config.desc_fields)
        self.research = ResearchPanel(self.form.current_lot)
        self.research.set_custom_fields(config.custom_fields)
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
        self.output = output.OutputLog(config.data_dir / output.FILE_NAME)
        self.output_page = OutputPage()
        self.output_page.refresh_requested.connect(self.refresh_output)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.splitter)
        self.pages.addWidget(self.shipping)
        self.pages.addWidget(self.output_page)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_header())
        content_layout.addWidget(self.pages, 1)
        self.setCentralWidget(content)
        self.toast = Toast(content)

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self.flush)

        self.sidebar.new_auction.connect(self.create_auction)
        self.sidebar.new_lot.connect(self.create_lot)
        self.sidebar.lot_selected.connect(self.open_lot)
        self.sidebar.export_auction.connect(self.export_auction)
        self.sidebar.delete_requested.connect(self.delete_items)
        self.sidebar.import_requested.connect(self.import_auctions)
        self.form.changed.connect(lambda: self._autosave.start(AUTOSAVE_MS))
        self.form.save_now.connect(self.flush)
        self.form.export_requested.connect(self.export_current)
        self.form.new_auction_requested.connect(self.create_auction)
        self.form.new_lot_requested.connect(self._new_lot_in_current_auction)
        self.form.import_requested.connect(self.import_auctions)
        self.form.delete_requested.connect(self.delete_current)
        self.form.step_requested.connect(self.step_lot)
        self.form.serial_lookup_requested.connect(self.lookup_serial)
        self.form.research_toggled.connect(self.research.setVisible)
        self.research.closed.connect(self._close_research)
        self.research.apply_requested.connect(self.form.apply_autofill)
        self.research.packet_saved.connect(self._save_research_record)
        self.form.evidence_requested.connect(self.open_evidence)
        self.form.phone_requested.connect(self.phone_intake)
        self.form.duplicates_requested.connect(self.review_duplicates)
        self.form.duplicate_requested.connect(self.duplicate_current)
        go_to = QShortcut(QKeySequence("Ctrl+G"), self)
        go_to.activated.connect(self.sidebar.focus_search)
        self.form.changed.connect(self._review_current)

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
        self._photo_fix_thread: PhotoFixThread | None = None
        QTimer.singleShot(0, self._fix_saved_photos)
        self._apply_history_access()
        self._update_counts()
        # Roll the "today" count over at midnight without needing a save.
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._update_counts)
        self._day_timer.start()

    def _build_header(self) -> QWidget:
        """App name and Catalogue/Shipping switch; status and Settings at right."""
        header = QWidget()
        header.setObjectName("workspaceHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 12, 8)
        layout.setSpacing(10)
        brand = QLabel()
        brand.setObjectName("brandMark")
        brand.setFixedSize(28, 28)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_icon(brand, "gavel", "accent_text", QSize(16, 16))
        layout.addWidget(brand)
        app_name = QLabel(strings.APP_TITLE)
        app_name.setObjectName("appName")
        layout.addWidget(app_name)
        layout.addSpacing(18)
        segmented = QFrame()
        segmented.setObjectName("segmented")
        segments = QHBoxLayout(segmented)
        segments.setContentsMargins(3, 3, 3, 3)
        segments.setSpacing(2)
        self.nav = QButtonGroup(self)
        self.nav_catalogue = QPushButton(strings.CATALOGUE_NAV)
        self.nav_shipping = QPushButton(strings.SHIPPING_NAV)
        self.nav_output = QPushButton(strings.OUTPUT_NAV)
        for button, icon in (
            (self.nav_catalogue, "book"),
            (self.nav_shipping, "box"),
            (self.nav_output, "chart"),
        ):
            button.setCheckable(True)
            theme.set_icon(button, icon)
            self.nav.addButton(button)
            segments.addWidget(button)
        self.nav_catalogue.setChecked(True)
        self.nav_catalogue.clicked.connect(lambda: self.show_workspace(shipping=False))
        self.nav_shipping.clicked.connect(lambda: self.show_workspace(shipping=True))
        self.nav_output.clicked.connect(lambda: self.show_workspace(output=True))
        layout.addWidget(segmented)
        layout.addStretch()
        self.update_button = QPushButton()
        self.update_button.setObjectName("link")
        self.update_button.setToolTip(strings.SOURCE_UPDATES_WAITING_TIP)
        theme.set_icon(self.update_button, "update", "accent")
        self.update_button.clicked.connect(self.check_for_updates)
        self.update_button.hide()
        layout.addWidget(self.update_button)
        self.started_chip = QLabel()
        self.started_chip.setObjectName("chip")
        self.started_chip.setToolTip(
            "Lots with meaningful saved information today. Photos alone do not count."
        )
        layout.addWidget(self.started_chip)
        self.info_chip = QLabel()
        self.info_chip.setObjectName("chip")
        self.info_chip.setToolTip(
            "Lots with a title, a condition and identifying details (make, model or serial) today. Photos and research are not needed."
        )
        layout.addWidget(self.info_chip)
        self.network_status = QLabel()
        self.network_status.setObjectName("chip")
        layout.addWidget(self.network_status)
        self.reload_shared_button = QPushButton(strings.RELOAD_SHARED)
        theme.set_icon(self.reload_shared_button, "refresh")
        self.reload_shared_button.clicked.connect(self.reload_shared)
        layout.addWidget(self.reload_shared_button)
        self.spellcheck_button = QPushButton("Spell check auction…")
        self.spellcheck_button.clicked.connect(self.spellcheck_auction)
        layout.addWidget(self.spellcheck_button)
        tools = QPushButton("Tools")
        tools_menu = QMenu(tools)
        tools_menu.addAction("Ready to publish — work queue…", self.open_work_queue)
        tools_menu.addAction("Back up / restore…", self.backup_restore)
        tools_menu.addAction("Recover deleted items…", self.recover_deleted)
        tools_menu.addAction("Consignor review sheets…", self.review_sheets)
        tools.setMenu(tools_menu)
        layout.addWidget(tools)
        settings_button = QPushButton(strings.SETTINGS_BTN)
        theme.set_icon(settings_button, "settings")
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(settings_button)
        return header

    def show_workspace(self, *, shipping: bool = False, output: bool = False) -> None:
        """Switch between catalogue, shipping and output, saving what's open first."""
        if output and not self.config.history_access:
            output = False
        target = (
            self.output_page if output else self.shipping if shipping else self.splitter
        )
        current = self.pages.currentWidget()
        if target is not current:
            if current is self.splitter:
                left = self._leave_lot()
            elif current is self.shipping:
                left = self.shipping.flush()
            else:
                left = True
            if left and self._enter_workspace(target):
                self.pages.setCurrentWidget(target)
        # A refused switch leaves the highlighted tab on the current workspace.
        current = self.pages.currentWidget()
        buttons = {
            self.shipping: self.nav_shipping,
            self.output_page: self.nav_output,
        }
        buttons.get(current, self.nav_catalogue).setChecked(True)

    def _enter_workspace(self, target: QWidget) -> bool:
        if target is self.shipping:
            return self.shipping.activate()
        if target is self.output_page:
            self.refresh_output()
        return True

    # -- output ---------------------------------------------------------------

    def _apply_history_access(self) -> None:
        """Show the Output button only while history access is unlocked."""
        self.nav_output.setVisible(self.config.history_access)
        if not self.config.history_access and self.pages.currentWidget() is (
            self.output_page
        ):
            self.show_workspace()

    def _own_history(self) -> dict:
        """This computer's counted history, uploaded before the host's answer
        is adopted so that nothing counted here before connecting is lost."""
        return self.output.rows()

    def _update_counts(self) -> None:
        today = output.today()
        started = self.output.started_on(today)
        info = self.output.count_on(today)
        self.started_chip.setText(f"{started} started")
        theme.repolish(self.started_chip, state="ok" if started else "")
        self.info_chip.setText(f"{info} filled in")
        theme.repolish(self.info_chip, state="ok" if info else "")

    def refresh_output(self) -> None:
        """Rebuild the Output page from the history and the catalogue as saved."""
        today = output.today()
        try:
            pipeline = kpi.pipeline(self._workflow_catalogue())
        except OSError, ValueError, network.NetworkError, catalogue.CatalogueReadError:
            log.exception("Reading the catalogue for the Output page failed")
            pipeline = None
        self.output_page.show_report(
            kpi.report(self.output.completions, today),
            pipeline,
            today,
            kpi.report(self.output.started, today),
        )

    def _track_progress(self, auction_no: int, lot: Lot) -> None:
        """Count the lot's stages as they are saved now. Each lot counts once
        per day and stage; a lot that is cleared again stops counting."""
        self.output.track(lot, auction_no)
        self._update_counts()

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
                self._net_status("Disconnected")
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
        self._catalogue_lots = auctions
        self.sidebar.populate(auctions)
        self._update_navigation()
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
        self.toast.show_message(text)

    def _net_status(self, text: str, *, ok: bool = False) -> None:
        """The sharing chip in the top bar: accent when fine, amber otherwise."""
        self.network_status.setText(text)
        theme.repolish(self.network_status, state="ok" if ok else "warning")

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
        self._review_current()
        self._update_navigation()

    def _update_navigation(self) -> None:
        if self.auction_no is None or self.lot_no is None:
            return
        self.form.set_navigation(
            self.sidebar.neighbor(self.auction_no, self.lot_no, -1) is not None,
            self.sidebar.neighbor(self.auction_no, self.lot_no, 1) is not None,
        )

    def step_lot(self, step: int) -> None:
        """Open the previous (-1) or next (+1) lot in the same auction."""
        if self.auction_no is None or self.lot_no is None:
            return
        target = self.sidebar.neighbor(self.auction_no, self.lot_no, step)
        if target is not None:
            auction_no = self.auction_no
            self.open_lot(auction_no, target)
            if self.lot_no == target:
                self.sidebar.select(auction_no, target)

    def _clear(self) -> None:
        self._autosave.stop()
        self.auction_no = self.lot_no = None
        self._shared_base = None
        self.form.clear()
        self.research.reset(None)

    def _close_research(self) -> None:
        self.research.hide()
        self.form.set_research_checked(False)

    def _new_lot_in_current_auction(self) -> None:
        if self.auction_no is not None:
            self.create_lot(self.auction_no)

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
        shown = self.form.collect()
        lot = self.form.collect_for_save()
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
        # Something may have changed the form while the save ran (e.g. a serial
        # lookup result); those edits aren't on disk yet, so keep them dirty.
        unchanged = self.form.collect() == shown
        if photos != lot.photos and self.form.collect().photos == shown.photos:
            self.form.set_photos(photos)
        if unchanged:
            self.form.mark_saved()
        else:
            self._autosave.start(AUTOSAVE_MS)
        self.sidebar.update_lot(auction_no, lot)
        self._catalogue_lots.setdefault(auction_no, [])
        self._catalogue_lots[auction_no] = [
            lot if old.lot_number == lot.lot_number else old
            for old in self._catalogue_lots[auction_no]
        ]
        self._track_progress(auction_no, replace(lot, photos=photos))
        self._review_current()
        self._release_phone_imports()
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
            self.update_button.setText(
                strings.SOURCE_UPDATES_WAITING.format(
                    changes=strings.count(status.behind, "update")
                )
            )
            self.update_button.show()

    def _on_startup_update_checked(self, info, _error: str = "") -> None:
        if self._io_busy:
            QTimer.singleShot(
                300, lambda: self._on_startup_update_checked(info, _error)
            )
            return
        if info is not None and info.is_newer:
            UpdateDialog(self, info).exec()

    def _fix_saved_photos(self) -> None:
        """Bring photos saved earlier up to the ProxiBid standard, quietly."""
        if self._photo_fix_thread is not None and self._photo_fix_thread.isRunning():
            return
        # Not parented to the window: deleting a running QThread is fatal.
        thread = PhotoFixThread(self.config.photos_dir)
        thread.fixed.connect(self._on_photos_fixed)
        self._photo_fix_thread = thread
        thread.start()

    def _on_photos_fixed(self, count: int) -> None:
        if count:
            self._status(
                strings.PHOTOS_FIXED.format(photos=strings.count(count, "photo"))
            )

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
        fixer = self._photo_fix_thread
        if fixer is not None and fixer.isRunning():
            fixer.fixed.disconnect()
            keep_until_finished(fixer)
        self._photo_fix_thread = None
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
                for auction_no in auctions:
                    self.output.forget(auction_no)
                for auction_no, numbers in lots.items():
                    self.output.forget(auction_no, numbers)
                self.refresh()
            except network.NetworkError as e:
                QMessageBox.warning(self, "Sharing", str(e))
            return

        backups: list[tuple[int, list[Lot], dict[Path, bytes]]] = []
        for auction_no, numbers in lots.items():
            try:
                path, details, images = (
                    self._path(auction_no),
                    self._details(auction_no),
                    self._images_dir(auction_no),
                )
                saved = self._lots_to_restore(auction_no, numbers)
                removed = self._io(
                    strings.IO_DELETING,
                    partial(catalogue.delete, path, details, images, numbers),
                )
            except ExcelLockedError:
                self._locked_warning()
                continue
            except (OSError, ValueError) as e:
                QMessageBox.warning(self, "Deletion stopped", str(e))
                continue
            self.output.forget(auction_no, numbers)
            if saved:
                backups.append((auction_no, saved, removed))
            self._recycle(removed, images)
            if self.auction_no == auction_no and self.lot_no in numbers:
                self._clear()

        for auction_no in auctions:
            try:
                self._io(
                    strings.IO_DELETING,
                    partial(
                        catalogue.delete_auction,
                        self._path(auction_no),
                        self._details(auction_no),
                        self._images_dir(auction_no),
                    ),
                )
            except (OSError, ValueError, ExcelLockedError) as e:
                QMessageBox.warning(self, "Deletion stopped", str(e))
                continue
            self.output.forget(auction_no)
            if self.auction_no == auction_no:
                self._clear()

        self.refresh()
        self._update_counts()
        if self.auction_no is not None and self.lot_no is not None:
            self.sidebar.select(self.auction_no, self.lot_no)
        if backups and not auctions:
            self.toast.show_message(
                strings.DELETED.format(what=what),
                UNDO_MS,
                (strings.UNDO, partial(self._undo_delete, backups)),
            )
        else:
            self._status(strings.DELETED.format(what=what))

    # -- export / settings --------------------------------------------------

    def export_current(self) -> None:
        if self.auction_no is not None:
            self.export_auction(self.auction_no)

    def delete_current(self) -> None:
        if self.auction_no is not None and self.lot_no is not None:
            self.delete_items([(self.auction_no, self.lot_no)])

    def duplicate_current(self) -> None:
        """Add a lot after the last one, starting from this lot's details."""
        if self.auction_no is None or self.lot_no is None:
            return
        auction_no, source = self.auction_no, self.form.collect()
        self.create_lot(auction_no)
        if (self.auction_no, self.lot_no) != (auction_no, source.lot_number):
            self.form.copy_details(source)

    def _lots_to_restore(self, auction_no: int, numbers: set[int]) -> list[Lot]:
        """The lots about to be deleted, kept so that Undo can bring them back."""
        try:
            lots = self._lots(auction_no)
        except catalogue.CatalogueReadError, OSError:
            return []
        kept = [lot for lot in lots if lot.lot_number in numbers]
        for lot in kept:
            lot.photos = []
        return kept

    def _undo_delete(
        self, backups: list[tuple[int, list[Lot], dict[Path, bytes]]]
    ) -> None:
        if not self._leave_lot():
            return
        for auction_no, lots, photos in backups:
            restore = partial(
                catalogue.restore,
                self._path(auction_no),
                self._details(auction_no),
                lots,
                photos,
            )
            try:
                self._io(strings.IO_SAVING, restore)
            except ExcelLockedError:
                self._locked_warning()
                return
            except (OSError, ValueError) as e:
                log.exception("Restoring deleted lots failed")
                QMessageBox.warning(self, strings.UNDO, str(e))
                return
            for lot in lots:
                self.output.track(lot, auction_no)
        self.refresh()
        self._update_counts()
        auction_no, lots, _ = backups[0]
        self.open_lot(auction_no, lots[0].lot_number)
        self.sidebar.select(auction_no, lots[0].lot_number)
        count = sum(len(lots) for _, lots, _ in backups)
        self._status(strings.UNDO_RESTORED.format(what=strings.count(count, "lot")))

    def export_auction(self, auction_no: int) -> None:
        if not self._leave_lot():
            return
        dest, selected = QFileDialog.getSaveFileName(
            self,
            strings.EXPORT,
            str(Path.home() / "Documents" / str(auction_no)),
            f"{strings.EXPORT_CSV_FILTER};;{strings.EXPORT_XLSX_FILTER}",
            strings.EXPORT_CSV_FILTER,
        )
        if not dest:
            return
        destination = Path(dest)
        if not destination.suffix:
            ext = ".xlsx" if selected == strings.EXPORT_XLSX_FILTER else ".csv"
            destination = Path(dest + ext)
        if destination.suffix.lower() not in (".csv", ".xlsx"):
            QMessageBox.critical(self, strings.EXPORT, strings.EXPORT_FORMAT_REQUIRED)
            return
        try:
            if self.shared:

                def shared_export():
                    snapshot = self._client().snapshot()
                    if str(auction_no) not in snapshot["auctions"]:
                        raise network.NetworkError("This auction was deleted")
                    lots = [
                        Lot(**{k: v for k, v in data.items() if k != "photos"})
                        for data in snapshot["auctions"][str(auction_no)]
                    ]
                    excel.export_lots(lots, destination)

                self._io("Exporting shared auction…", shared_export)
            else:
                excel.export_auction(self._path(auction_no), destination)
        except OSError, network.NetworkError:
            log.exception("Exporting auction %s failed", auction_no)
            QMessageBox.critical(self, strings.EXPORT, strings.EXPORT_FAILED)
            return
        self._status(strings.EXPORTED.format(path=destination))

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

        if not self.shared:
            for lot in added:
                self.output.track(lot, auction_no)
            self._update_counts()
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
            if moved:
                self.output = output.OutputLog(self.config.data_dir / output.FILE_NAME)
                self._update_counts()
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
            self._fix_saved_photos()
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
            self.config.custom_fields = dialog.custom_fields()
            self.config.title_fields = dialog.title_fields()
            self.config.desc_fields = dialog.desc_fields()
            conditions = dialog.conditions()
            if conditions != dialog.original_conditions():
                # Only rewrite the file when the table changed, so comments
                # someone added to conditions.yaml aren't lost.
                self.config.conditions = conditions
                self.config.save_conditions()
            chosen_dark = dialog.dark_mode()
            chosen_dyslexic, chosen_size = dialog.dyslexic_font(), dialog.font_size()
            chosen_access = dialog.history_access()
            newly_unlocked = chosen_access and not self.config.history_access
            replace(
                self.config,
                dark_mode=chosen_dark,
                dyslexic_font=chosen_dyslexic,
                font_size=chosen_size,
                sharing=chosen_sharing,
                history_access=chosen_access,
            ).save()
            self.config.dark_mode = chosen_dark
            self.config.dyslexic_font = chosen_dyslexic
            self.config.font_size = chosen_size
            self.config.sharing = chosen_sharing
            self.config.history_access = chosen_access
            self._apply_history_access()
            if newly_unlocked:
                self._status(strings.HISTORY_UNLOCKED)
            self._configure_sharing()
            theme.apply(
                QApplication.instance(),
                dark_mode=chosen_dark,
                dyslexic_font=chosen_dyslexic,
                font_size=chosen_size,
            )
            self._watch_conditions()
            self.form.set_serial_links(self.config.serial_links)
            self.form.set_conditions(self.config.conditions)
            self.form.set_custom_fields(self.config.custom_fields)
            self.research.set_custom_fields(self.config.custom_fields)
            self.form.set_title_fields(self.config.title_fields)
            self.form.set_desc_fields(self.config.desc_fields)
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
                        strings.IO_OPENING_SHARED,
                        lambda: network.Database(self.config),
                    )
                    self.client = network.LocalClient(
                        db, self.config.data_dir / "shared-cache"
                    )
                    self.client.history = self._own_history
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
                history=self._own_history,
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
            self._net_status("Disconnected · check Settings")
            self.network_status.setToolTip(str(e))
            self.sidebar.populate({})
            if settings.mode == "join" and isinstance(e, network.Unavailable):
                self._net_status("Waiting for host · reconnecting automatically")
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

    def _apply_snapshot(self, snapshot, adopt_output=True):
        if self.client is not None and not self.client.identity:
            self.client.identity = snapshot["identity"]
        self._remember_connection()
        # Adopt only after this computer's history was uploaded (see _own_history).
        if "output" in snapshot and adopt_output:
            self.output.adopt(snapshot["output"])
            self._update_counts()
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
            self._catalogue_lots = auctions
            self._update_navigation()
            if self.auction_no is not None and self.lot_no is not None:
                self.sidebar.select(self.auction_no, self.lot_no)
            if self.pages.currentWidget() is self.output_page:
                self.refresh_output()
        state = (
            "Local"
            if isinstance(self.client, network.LocalClient)
            else ("Hosting" if self.host else "Connected")
        )
        self._net_status(
            state
            + (
                " · unsaved changes"
                if self.form.is_dirty() or self.shipping.dirty
                else " · synced"
            ),
            ok=True,
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
                self._net_status("Reconnecting automatically · edits kept")
                self.network_status.setToolTip(str(worker.error))
                return
            snapshot, batch, record, lot = worker.result
            # The poll uploads history only from a client that carries it.
            self._apply_snapshot(
                snapshot,
                adopt_output=worker.connection is not None
                and worker.connection.history is not None,
            )
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
                self._net_status("Lot changed on host · your edits kept")
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
                "Your unsaved edits will be kept in a recovery draft before loading the host's latest data. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            drafts = self._connection_drafts() if dirty else None
            snapshot = self._io("Reloading from host…", self._client().snapshot)
            record = self._record(snapshot, self.auction_no, self.lot_no)
            if record:
                lot = self._io(
                    "Downloading photos…", lambda: self._client().materialize(record)
                )
            path = self.shipping.path
            batch = (
                self._io(
                    "Reloading shipping…",
                    lambda: self._client().request("get_shipping", key=path),
                )
                if path
                else None
            )
            if record:
                self._shared_base = record
                self.form.load(lot, self.auction_no)
            else:
                self._clear()
            self.shipping.dirty = False
            self.shipping._save_timer.stop()
            self.shipping.sync_snapshot(snapshot["shipping"], batch)
            self._apply_snapshot(snapshot)
            if drafts:
                self._status(f"Previous edits preserved in {drafts['backup']}")
        except (OSError, ValueError, network.NetworkError) as e:
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

        def preserve():
            # Snapshot the actual photos too, not only temporary source paths.
            if lot:
                photos = []
                for index, source in enumerate(lot.photos):
                    target = path.with_suffix(".photos") / f"{index}{source.suffix}"
                    storage.atomic_write(target, source.read_bytes())
                    photos.append(str(target))
                serializable["lot"]["photos"] = photos
            storage.atomic_write(path, json.dumps(serializable, default=str).encode())

        self._io("Preserving unsaved edits…", preserve)
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

    # -- evidence, publication and intake -----------------------------------

    def _save_research_record(self, record: dict) -> None:
        try:
            self.form.add_research(record)
        except ValueError as error:
            QMessageBox.warning(self, "Research packet", str(error))
            return
        if self.flush():
            self._status("Research answer saved to this lot's packet")
        else:
            self._save_warning()

    def _review_current(self) -> None:
        lot = self.form.current_lot()
        matches = (
            dossier.duplicates(lot, self.auction_no, self._catalogue_lots)
            if lot is not None
            else []
        )
        self.form.set_duplicates(len(matches))

    def open_evidence(self) -> None:
        from simple_auction.ui.dossier_dialog import DossierDialog

        lot = self.form.current_lot()
        if lot is None:
            return
        dialog = DossierDialog(lot, self)
        if dialog.exec():
            self.form.set_dossier(dialog.packet)
            if not self.flush():
                self._save_warning()

    def _workflow_catalogue(self) -> dict[int, list[Lot]]:
        """Read the source of truth, including photos, for review/export."""

        def load():
            if self.shared:
                snapshot = self._client().snapshot()
                return {
                    int(auction): [
                        self._client().materialize(record) for record in records
                    ]
                    for auction, records in snapshot["auctions"].items()
                }
            auctions = {}
            for auction in excel.list_auctions(self.config.auctions_dir):
                lots = self._catalogue_cache.load(
                    self._path(auction), self._details(auction)
                )
                for lot in lots:
                    lot.photos = lot_photo_files(
                        lot.lot_number, self._images_dir(auction)
                    )
                auctions[auction] = lots
            return auctions

        return self._io("Preparing catalogue review…", load)

    def spellcheck_auction(self) -> None:
        from simple_auction.services import auction_spelling
        from simple_auction.ui.auction_spellcheck_dialog import AuctionSpellcheckDialog
        from simple_auction.ui.spellcheck import install_spellcheck

        auction = self.auction_no
        if auction is None:
            QMessageBox.information(
                self, "Spell check", "Open a lot in the auction to review first."
            )
            return
        if not self._leave_lot():
            return
        try:
            client = self._client() if self.shared else None
        except network.NetworkError as error:
            QMessageBox.warning(self, "Spell check", str(error))
            return
        records = {}

        checker = install_spellcheck(QApplication.instance()).checker

        def load():
            if client is not None:
                snapshot = client.snapshot()
                records.update(
                    {
                        record["lot_number"]: record
                        for record in snapshot["auctions"].get(str(auction), [])
                    }
                )
                lots = [client.materialize(record) for record in records.values()]
            else:
                lots = auction_spelling.load_local(
                    self._path(auction),
                    self._details(auction),
                    self._images_dir(auction),
                )
            return lots, auction_spelling.Review(lots, checker)

        try:
            lots, review = self._io("Preparing auction spell check…", load)
        except (OSError, ValueError, network.NetworkError) as error:
            QMessageBox.warning(self, "Spell check", str(error))
            return

        def save(expected, updated):
            if (self.auction_no, self.lot_no) == (
                auction,
                updated.lot_number,
            ) and self.form.is_dirty():
                raise ValueError(
                    "The open lot has new edits. Close spell check and save them first."
                )

            def commit():
                if client is not None:
                    record = client.save_lot(
                        auction, updated, records[updated.lot_number]
                    )
                    committed = client.materialize(record)
                    records[updated.lot_number] = record
                    return committed, {}
                return auction_spelling.save_local(
                    self._path(auction),
                    self._details(auction),
                    self._images_dir(auction),
                    expected,
                    updated,
                )

            committed, removed = self._io("Saving spelling replacement…", commit)
            self._recycle(removed, self._images_dir(auction))
            self.sidebar.update_lot(auction, committed)
            self._catalogue_lots[auction] = [
                committed if lot.lot_number == committed.lot_number else lot
                for lot in self._catalogue_lots.get(auction, lots)
            ]
            if (self.auction_no, self.lot_no) == (
                auction,
                committed.lot_number,
            ) and not self.form.is_dirty():
                self.form.load(committed, auction)
                if client is not None:
                    self._shared_base = records[committed.lot_number]
            self._track_progress(auction, committed)
            return committed

        AuctionSpellcheckDialog(auction, review, save, self).exec()

    def open_work_queue(self) -> None:
        from simple_auction.ui.workflow_dialogs import WorkQueueDialog

        if not self._leave_lot():
            return
        try:
            auctions = self._workflow_catalogue()
        except (OSError, ValueError, network.NetworkError) as error:
            QMessageBox.warning(self, "Work queue", str(error))
            return
        self._catalogue_lots = auctions
        dialog = WorkQueueDialog(auctions, self)
        if dialog.exec() and dialog.target:
            auction, number, target = dialog.target
            self.show_workspace(shipping=False)
            if self.pages.currentWidget() is not self.splitter:
                return
            self.open_lot(auction, number)
            if (self.auction_no, self.lot_no) == (auction, number):
                self.sidebar.select(auction, number)
                self.form.focus_issue(target)

    def review_duplicates(self) -> None:
        from simple_auction.ui.workflow_dialogs import DuplicateDialog

        lot = self.form.current_lot()
        if lot is None or not self._leave_lot():
            return
        matches = dossier.duplicates(lot, self.auction_no, self._catalogue_lots)
        dialog = DuplicateDialog(matches, self)
        if not dialog.exec() or not dialog.target:
            return
        auction, earlier = dialog.target
        if dialog.choice == "open":
            self.open_lot(auction, earlier.lot_number)
            self.sidebar.select(auction, earlier.lot_number)
            return
        packet = dossier.validate(lot.dossier)
        if dialog.choice == "reuse":
            old = dossier.validate(earlier.dossier)
            for key in ("findings", "research", "comparables"):
                for record in old[key]:
                    if record not in packet[key]:
                        packet[key].append(record)
            packet["relisted_from"] = f"Auction {auction} / Lot {earlier.lot_number}"
            packet["status"] = "Unverified"
            packet["review_approved"] = False
            packet["research_complete"] = False
        packet["duplicate_notes"] = dialog.explanation
        try:
            self.form.set_dossier(packet)
        except ValueError as error:
            QMessageBox.warning(self, "Duplicate review", str(error))
            return
        if not self.flush():
            self._save_warning()

    def phone_intake(self) -> None:
        from simple_auction.ui.phone_capture_dialog import PhoneCaptureDialog

        if self.lot_no is None or not self._leave_lot():
            return
        dialog = PhoneCaptureDialog(self.lot_no, self)
        if dialog.exec():
            self._phone_imports.append(dialog)
            self.form.add_photos(dialog.photos)
            if not self.flush():
                self._save_warning()
        else:
            dialog.deleteLater()

    def _release_phone_imports(self) -> None:
        current = self.form.current_lot()
        paths = set(current.photos) if current else set()
        pending = []
        for dialog in self._phone_imports:
            if paths.intersection(dialog.photos):
                pending.append(dialog)
            else:
                dialog.cleanup_photos()
                dialog.deleteLater()
        self._phone_imports = pending

    def backup_restore(self) -> None:
        from simple_auction.ui.backup_dialog import BackupDialog

        if not self._leave_lot() or not self.shipping.flush():
            return
        database = (
            self.host.db
            if self.host
            else self.client.db
            if isinstance(self.client, network.LocalClient)
            else None
        )
        remote = self.config.sharing.mode == "join"
        dialog = BackupDialog(
            self.config, database=database, remote_client=remote, parent=self
        )
        dialog.exec()
        if dialog.activation_requested:
            # Settings now point at the isolated restored copy. Do not allow
            # further edits to the old catalogue in this process.
            self.close()

    def review_sheets(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from simple_auction.ui.review_sheet_dialog import ReviewSheetDialog

        if not self._leave_lot() or not self.shipping.flush():
            return
        try:
            auctions = self._workflow_catalogue()
        except (OSError, ValueError, network.NetworkError) as error:
            QMessageBox.warning(self, "Consignor review", str(error))
            return
        if not auctions:
            self._status("No auctions to export")
            return
        numbers = sorted(auctions)
        selected = numbers.index(self.auction_no) if self.auction_no in numbers else 0
        text, accepted = QInputDialog.getItem(
            self,
            "Consignor review sheets",
            "Auction",
            [str(number) for number in numbers],
            selected,
            False,
        )
        if accepted:
            auction = int(text)
            ReviewSheetDialog(auction, auctions[auction], self).exec()

    def recover_deleted(self) -> None:
        from simple_auction.ui.recovery_dialog import RecoveryDialog

        if not self._leave_lot():
            return
        dialog = RecoveryDialog(
            self.config, self._client() if self.shared else None, self
        )
        dialog.exec()
        self.refresh()
        self._update_counts()
