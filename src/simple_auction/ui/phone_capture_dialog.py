"""Review phone photos for a frozen lot before handing paths to the editor."""

from pathlib import Path

import qrcode
from PySide6.QtCore import QSize, Qt, QTemporaryDir, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from simple_auction.services.network import local_addresses
from simple_auction.services.phone_capture import (
    SHOTS,
    PhoneCaptureSession,
)


class PhoneCaptureDialog(QDialog):
    """Accepted .photos remain valid until cleanup_photos() or dialog destruction.

    Keep this dialog alive until the parent has persisted the files. Closing or
    cancelling removes all unaccepted files and stops the listener. Identification
    is deliberately not automatic: the parent's existing photo-aware ResearchPanel
    supplies an explicit action followed by the existing AutofillDialog review.
    """

    def __init__(self, lot_number: int, parent=None) -> None:
        super().__init__(parent)
        if type(lot_number) is not int or lot_number <= 0:
            raise ValueError("A saved lot number is required.")
        self._lot_number = lot_number
        self.photos: list[Path] = []
        self._temporary = QTemporaryDir()
        if not self._temporary.isValid():
            raise OSError("Could not create a temporary phone-photo folder.")
        self._session: PhoneCaptureSession | None = None
        self._seen: set[Path] = set()
        self._finished = False
        self.setWindowTitle(f"Phone photos — lot {lot_number}")
        self.resize(720, 680)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Receive photos for lot {lot_number}")
        heading.setObjectName("emptyTitle")
        layout.addWidget(heading)
        intro = QLabel(
            "Connect your phone to the same trusted private Wi-Fi, then scan the QR code "
            "with its camera. The link is private and expires after 10 minutes. "
            "Local HTTP is not encrypted; do not use public Wi-Fi. Only this lot receives photos."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Computer's private address"))
        self.address = QComboBox()
        self.address.addItems(local_addresses())
        row.addWidget(self.address, 1)
        self.start_button = QPushButton("Start phone session")
        self.start_button.clicked.connect(self._start)
        self.start_button.setEnabled(self.address.count() > 0)
        row.addWidget(self.start_button)
        layout.addLayout(row)
        pairing = QHBoxLayout()
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pairing.addWidget(self.qr)
        instructions = QVBoxLayout()
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        self.link.setAccessibleName("Private phone capture link")
        instructions.addWidget(self.link)
        guide = QLabel(
            "1. Overall view\n2. Opposite side\n3. Maker and model markings\n"
            "4. Serial close-up\n5. Defects / wear\n\nUse sharp, well-lit JPEG, PNG or WebP photos "
            "(not HEIC). Maximum 12 MiB per photo, 30 megapixels and 24 photos. "
            "Nothing is sent for AI identification here."
        )
        guide.setWordWrap(True)
        instructions.addWidget(guide)
        pairing.addLayout(instructions, 1)
        layout.addLayout(pairing)
        self.status = QLabel(
            "Ready to pair."
            if self.address.count()
            else "No private LAN address found. Connect to private Wi-Fi and reopen this dialog."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(
            QLabel("Review received photos. Uncheck any you do not want to add:")
        )
        self.received = QListWidget()
        self.received.setIconSize(QSize(112, 84))
        self.received.itemChanged.connect(self._update_add_button)
        layout.addWidget(self.received, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.addButton(
            "Add photos", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.add_button.setObjectName("primary")
        self.add_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh)

    @property
    def lot_number(self) -> int:
        return self._lot_number

    def _start(self) -> None:
        if self._session is not None or self._finished:
            return
        session = PhoneCaptureSession(
            self.lot_number, Path(self._temporary.path()), self.address.currentText()
        )
        try:
            session.start()
        except OSError:
            session.stop()
            self.status.setText(
                "Could not listen on that address. Check your network or firewall, or choose another address."
            )
            return
        self._session = session
        # Do not capture the dialog in the destruction hook; it may already be gone.
        self.destroyed.connect(lambda _object=None, owned=session: owned.stop())
        self.link.setText(session.url)
        self.link.setCursorPosition(0)
        bitmap = qrcode.make(session.url, border=4).convert("RGB")
        image = QImage(
            bitmap.tobytes(),
            bitmap.width,
            bitmap.height,
            bitmap.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        self.qr.setPixmap(
            QPixmap.fromImage(image).scaled(
                240,
                240,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )
        self.address.setEnabled(False)
        self.start_button.setEnabled(False)
        self._timer.start()
        self._refresh()

    def _refresh(self) -> None:
        if self._session is None or self._finished:
            return
        for photo in self._session.photos:
            if photo.path in self._seen:
                continue
            self._seen.add(photo.path)
            item = QListWidgetItem(QIcon(str(photo.path)), SHOTS[photo.shot])
            item.setData(Qt.ItemDataRole.UserRole, photo.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.received.addItem(item)
        if self._session.active:
            seconds = self._session.remaining
            self.status.setText(
                f"{len(self._seen)} photo(s) received · link expires in {seconds // 60}:{seconds % 60:02d}"
            )
        else:
            self.status.setText(
                "Session ended. Review and add the photos received, or cancel and reopen to pair again."
            )
            self.link.clear()
            self.qr.clear()
            self._timer.stop()
        self._update_add_button()

    def _update_add_button(self, *_args) -> None:
        self.add_button.setEnabled(
            any(
                self.received.item(i).checkState() == Qt.CheckState.Checked
                for i in range(self.received.count())
            )
        )

    def done(self, result: int) -> None:
        if self._finished:
            return
        chosen = [
            self.received.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.received.count())
            if self.received.item(i).checkState() == Qt.CheckState.Checked
        ]
        if result == QDialog.DialogCode.Accepted and not chosen:
            return
        self._finished = True
        self._timer.stop()
        if self._session is not None:
            self._session.stop()
        if result == QDialog.DialogCode.Accepted:
            self.photos = chosen
            for path in Path(self._temporary.path()).iterdir():
                if path not in self.photos:
                    path.unlink(missing_ok=True)
        else:
            self.cleanup_photos()
        self.link.clear()
        self.qr.clear()
        super().done(result)

    def cleanup_photos(self) -> None:
        """Call only after accepted files are persisted (or deliberately discarded)."""
        if self._session is not None:
            self._session.stop()
        self.photos.clear()
        self._temporary.remove()
