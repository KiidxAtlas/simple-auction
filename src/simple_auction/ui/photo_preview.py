"""A large view of a lot's photos, to check focus and markings."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from simple_auction.ui import strings


def load_pixmap(path: Path) -> QPixmap:
    """The photo upright (camera rotation applied); null if it can't be read."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return QPixmap.fromImage(reader.read())


def file_size_text(path: Path) -> str:
    try:
        return f"{max(1, round(path.stat().st_size / 1000))} KB"
    except OSError:
        return ""


class PhotoPreview(QDialog):
    """Shows one photo at a time; arrow keys (or the buttons) move between them."""

    def __init__(
        self, photos: list[Path], index: int = 0, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.PHOTO_PREVIEW_TITLE)
        self.resize(900, 700)
        self._photos = list(photos)
        self._index = min(max(index, 0), len(self._photos) - 1)
        self._pixmap = QPixmap()

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(QSize(1, 1))
        # The picture adapts to the window, never the other way round.
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.caption = QLabel()
        self.caption.setObjectName("hint")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_btn = QPushButton(strings.PREVIOUS)
        self.next_btn = QPushButton(strings.NEXT)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        close = QPushButton(strings.CLOSE)
        close.clicked.connect(self.accept)

        bar = QHBoxLayout()
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.caption, 1)
        bar.addWidget(self.next_btn)
        bar.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.image, 1)
        layout.addLayout(bar)

        for key, step in (("Left", -1), ("Right", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda step=step: self.step(step))
        self._show()

    def step(self, delta: int) -> None:
        index = self._index + delta
        if 0 <= index < len(self._photos):
            self._index = index
            self._show()

    def _show(self) -> None:
        path = self._photos[self._index]
        self._pixmap = load_pixmap(path)
        if self._pixmap.isNull():
            self.caption.setText(strings.PHOTO_UNREADABLE.format(name=path.name))
        else:
            self.caption.setText(
                strings.PHOTO_CAPTION.format(
                    n=self._index + 1,
                    total=len(self._photos),
                    name=path.stem,
                    width=self._pixmap.width(),
                    height=self._pixmap.height(),
                    size=file_size_text(path),
                )
            )
        self.prev_btn.setEnabled(self._index > 0)
        self.next_btn.setEnabled(self._index < len(self._photos) - 1)
        self._fit()

    def _fit(self) -> None:
        if self._pixmap.isNull():
            self.image.clear()
            return
        self.image.setPixmap(
            self._pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
