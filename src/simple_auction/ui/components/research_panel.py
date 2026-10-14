import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from google.genai import errors
from google.genai._gaos.lib import compat_errors as ce
from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from simple_auction.models import Lot
from simple_auction.services.research import (
    AUTOFILL_FIELDS,
    AUTOFILL_REQUEST,
    RESEARCH_REQUEST,
    MissingApiKeyError,
    ResearchChat,
    ResearchFailedError,
)
from simple_auction.services.title_layout import CustomField
from simple_auction.ui import strings, theme
from simple_auction.ui.autofill_dialog import AutofillDialog

log = logging.getLogger(__name__)

RENDER_MS = 60  # batch streamed text into one repaint


@dataclass
class _Turn:
    question: str
    answer: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)
    notice: str = ""  # why the answer is missing or cut short
    note: str = ""  # about how the answer was made (e.g. without web search)
    photos: int = 0  # photos sent along with this question


def _api_message(e: ce.APIStatusError) -> str:
    """The human-readable part of an API error, not the raw JSON."""
    body = e.body
    if isinstance(body, list) and body:  # Google sometimes wraps it in a list
        body = body[0]
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message") or e.message)
    return str(e.message)


class _Job(QObject):
    """Runs one question on a daemon thread; signals arrive on the UI thread."""

    text = Signal(str)
    status = Signal(str)
    done = Signal(list)
    filled = Signal(dict)  # auto-fill suggestions
    photos = Signal(str)  # how many photos went with the question
    refused = Signal()
    note = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self, chat: ResearchChat, question: str, lot: Lot, *, autofill: bool = False
    ) -> None:
        super().__init__()
        self._chat, self._question, self._lot = chat, question, lot
        self._autofill = autofill
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        with self._state_lock:
            if self._stop.is_set():
                return
            self._stop.set()
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        finally:
            self.finished.emit()

    async def _run_async(self) -> None:
        with self._state_lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
            if self._stop.is_set():
                self._loop = self._task = None
                return
        events = (
            self._chat.autofill_async(self._lot)
            if self._autofill
            else self._chat.ask_async(self._question, self._lot)
        )
        try:
            async for event in events:
                if self._stop.is_set():
                    break
                match event.kind:
                    case "text":
                        self.text.emit(event.text)
                    case "searching":
                        self.status.emit(strings.RESEARCH_SEARCHING)
                    case "reading":
                        self.status.emit(strings.RESEARCH_READING)
                    case "photos":
                        self.photos.emit(event.text)
                    case "no_search":
                        self.note.emit(strings.RESEARCH_NO_SEARCH)
                    case "refused":
                        self.refused.emit()
                    case "done":
                        self.done.emit(event.sources)
                    case "filled":
                        self.filled.emit(event.values)
        except asyncio.CancelledError:
            pass  # a deliberate Stop, not an API failure
        except MissingApiKeyError:
            self.failed.emit(strings.RESEARCH_NO_KEY)
        except ce.AuthenticationError, ce.PermissionDeniedError:
            self.failed.emit(strings.RESEARCH_BAD_KEY)
        except ce.RateLimitError:
            self.failed.emit(strings.RESEARCH_BUSY)
        except ce.APIStatusError as e:
            message = _api_message(e)
            log.warning("Research request failed %s: %s", e.status_code, message)
            if e.status_code == 400 and "api key" in message.lower():
                self.failed.emit(strings.RESEARCH_BAD_KEY)
            elif e.status_code == 402:  # prepaid billing with no credit left
                self.failed.emit(strings.RESEARCH_NO_CREDIT)
            else:
                self.failed.emit(strings.RESEARCH_API_ERROR.format(error=message))
        except ce.APIConnectionError:
            self.failed.emit(strings.RESEARCH_OFFLINE)
        except errors.ClientError as e:  # 4xx
            log.warning("Research request rejected %s: %s", e.code, e.message)
            if e.code == 429:
                self.failed.emit(strings.RESEARCH_BUSY)
            elif e.code in (400, 401, 403) and "key" in (e.message or "").lower():
                self.failed.emit(strings.RESEARCH_BAD_KEY)
            else:
                self.failed.emit(strings.RESEARCH_API_ERROR.format(error=e.message))
        except (errors.APIError, ResearchFailedError) as e:  # 5xx, or mid-stream
            log.warning("Research failed: %s", e)
            self.failed.emit(strings.RESEARCH_API_ERROR.format(error=e))
        except httpx.TransportError:
            self.failed.emit(strings.RESEARCH_OFFLINE)
        except Exception:
            log.exception("Research failed")
            self.failed.emit(strings.RESEARCH_FAILED)
        finally:
            try:
                await events.aclose()
            finally:
                with self._state_lock:
                    self._loop = self._task = None


class ResearchPanel(QFrame):
    closed = Signal()
    apply_requested = Signal(dict)  # reviewed auto-fill values: {key: value}

    def __init__(self, lot_provider: Callable[[], Lot | None]) -> None:
        super().__init__()
        self.setObjectName("researchPanel")
        self.setMinimumWidth(theme.RESEARCH_MIN_WIDTH)
        self._lot_provider = lot_provider
        self._custom_fields: list[CustomField] = []
        self._chat = ResearchChat()
        self._turns: list[_Turn] = []
        self._job: _Job | None = None
        self._pending_fill: tuple[dict, Lot] | None = None
        self._has_lot = False
        self._has_lot = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

        title = QLabel(strings.RESEARCH)
        title.setObjectName("cardTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("hint")
        close = QPushButton()
        close.setObjectName("iconButton")
        close.setAccessibleName(strings.RESEARCH_CLOSE_TIP)
        theme.set_icon(close, "close")
        close.setToolTip(strings.RESEARCH_CLOSE_TIP)
        close.clicked.connect(self.closed)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, 1)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        # Empty page: what research does and one button to start it
        # (auto-fill is always in the toolbar below).
        badge = QFrame()
        badge.setObjectName("emptyIcon")
        badge.setFixedSize(56, 56)
        badge_icon = QLabel()
        badge_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_icon(badge_icon, "sparkle", "accent", QSize(26, 26))
        QVBoxLayout(badge).addWidget(badge_icon)
        empty_title = QLabel(strings.RESEARCH_EMPTY_TITLE)
        empty_title.setObjectName("cardTitle")
        self.start_btn = QPushButton(strings.RESEARCH_START)
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.research_lot)
        start_hint = QLabel(strings.RESEARCH_START_HINT)
        start_hint.setObjectName("hint")
        start_hint.setWordWrap(True)
        start_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(12, 0, 12, 0)
        empty_layout.addStretch(1)
        empty_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(empty_title, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(start_hint)
        empty_layout.addSpacing(10)
        empty_layout.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(2)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(empty)
        self.stack.addWidget(self.transcript)

        self.status = QLabel()
        self.status.setObjectName("hint")

        # Photos go along so Gemini can see the item; can be switched off.
        self.photos_toggle = QCheckBox(strings.RESEARCH_INCLUDE_PHOTOS)
        self.photos_toggle.setChecked(True)
        self.photos_toggle.setToolTip(strings.RESEARCH_INCLUDE_PHOTOS_TIP)
        self.photos_toggle.toggled.connect(
            lambda on: setattr(self._chat, "include_photos", on)
        )
        self.autofill_btn = QPushButton(strings.AUTOFILL)
        self.autofill_btn.setToolTip(strings.AUTOFILL_TIP)
        theme.set_icon(self.autofill_btn, "sparkle")
        self.autofill_btn.clicked.connect(self.autofill)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(self.photos_toggle)
        tools.addStretch(1)
        tools.addWidget(self.autofill_btn)

        self.question = QLineEdit()
        self.question.setPlaceholderText(strings.RESEARCH_ASK_PLACEHOLDER)
        self.question.returnPressed.connect(self._ask_typed)
        self.ask_btn = QPushButton(strings.RESEARCH_ASK)
        self.ask_btn.setObjectName("primary")
        self.ask_btn.clicked.connect(self._ask_or_stop)
        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.ask_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)
        layout.addLayout(tools)
        layout.addLayout(ask_row)

        self.reset(None)

    # -- public -------------------------------------------------------------

    def reset(self, lot_number: int | None) -> None:
        """Start a fresh conversation for another lot (or none)."""
        if self._job is not None:
            self._job.stop()  # finishes on its own; its signals are ignored
            self._job = None
        self._pending_fill = None
        self._chat = ResearchChat(
            custom_fields=self._custom_fields,
            include_photos=self.photos_toggle.isChecked(),
        )
        self._turns = []
        self.transcript.clear()
        self.stack.setCurrentIndex(0)
        self.status.clear()
        self._has_lot = lot_number is not None
        self.subtitle.setText(
            strings.RESEARCH_SUBTITLE.format(n=lot_number) if self._has_lot else ""
        )
        self.question.setEnabled(self._has_lot)
        self._set_busy(False)

    def research_lot(self) -> None:
        self._ask(RESEARCH_REQUEST, label=strings.RESEARCH_TURN_LABEL)

    def autofill(self) -> None:
        """Ask Gemini for field values, then let the user review them."""
        self._ask(AUTOFILL_REQUEST, label=strings.AUTOFILL_TURN_LABEL, fill=True)

    def set_custom_fields(self, fields: list[CustomField]) -> None:
        """Custom fields from Settings: sent with the lot and auto-filled."""
        self._custom_fields = list(fields)
        self._chat.custom_fields = list(fields)

    # -- asking -------------------------------------------------------------

    def _ask_typed(self) -> None:
        text = self.question.text().strip()
        if text and self._job is None:
            self.question.clear()
            self._ask(text)

    def _ask_or_stop(self) -> None:
        if self._job is not None:
            self._job.stop()
            self.status.setText(strings.RESEARCH_STOPPING)
            self.ask_btn.setEnabled(False)
        else:
            self._ask_typed()

    def _ask(self, question: str, label: str | None = None, *, fill=False) -> None:
        lot = self._lot_provider()
        if lot is None or self._job is not None:
            return
        turn = _Turn(question=label or question)
        self._turns.append(turn)
        self.stack.setCurrentIndex(1)
        self.status.setText(
            strings.AUTOFILL_WORKING if fill else strings.RESEARCH_THINKING
        )
        self._set_busy(True)
        self._render()

        job = _Job(self._chat, question, lot, autofill=fill)
        self._job = job
        mine = lambda: self._job is job
        # Signals come from the worker thread; queue them onto the UI thread.
        queued = Qt.ConnectionType.QueuedConnection
        job.text.connect(lambda t: mine() and self._on_text(turn, t), queued)
        job.status.connect(lambda s: mine() and self.status.setText(s), queued)
        job.done.connect(lambda src: mine() and self._on_done(turn, src), queued)
        job.filled.connect(lambda v: mine() and self._on_filled(turn, v), queued)
        job.photos.connect(lambda n: mine() and setattr(turn, "photos", int(n)), queued)
        job.refused.connect(
            lambda: mine() and self._on_notice(turn, strings.RESEARCH_REFUSED),
            queued,
        )
        job.failed.connect(lambda msg: mine() and self._on_notice(turn, msg), queued)
        job.note.connect(lambda msg: mine() and setattr(turn, "note", msg), queued)
        job.finished.connect(lambda: mine() and self._on_finished(turn), queued)
        job.finished.connect(job.deleteLater, queued)
        job.start()

    def _on_text(self, turn: _Turn, text: str) -> None:
        turn.answer += text
        self.status.setText(strings.RESEARCH_WRITING)
        if not self._render_timer.isActive():
            self._render_timer.start(RENDER_MS)

    def _on_done(self, turn: _Turn, sources: list) -> None:
        turn.sources = sources

    def _on_notice(self, turn: _Turn, message: str) -> None:
        turn.notice = message

    def _on_finished(self, turn: _Turn) -> None:
        self._job = None
        if not turn.answer and not turn.notice:
            turn.notice = strings.RESEARCH_STOPPED
        self.status.clear()
        self._set_busy(False)
        self._render()
        self.question.setFocus()
        self._review_fill()

    def _set_busy(self, busy: bool) -> None:
        self.ask_btn.setText(strings.RESEARCH_STOP if busy else strings.RESEARCH_ASK)
        self.ask_btn.setObjectName("ghostBordered" if busy else "primary")
        self.ask_btn.style().unpolish(self.ask_btn)
        self.ask_btn.style().polish(self.ask_btn)
        self.ask_btn.setEnabled(self._has_lot)
        self.start_btn.setEnabled(self._has_lot and not busy)
        self.autofill_btn.setEnabled(self._has_lot and not busy)

    # -- rendering ----------------------------------------------------------

    def _render(self) -> None:
        bar = self.transcript.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 8
        parts = []
        for turn in self._turns:
            parts.append(f"**{strings.RESEARCH_YOU}** {turn.question}")
            if turn.photos:
                parts.append(f"*{strings.RESEARCH_PHOTOS_SENT.format(n=turn.photos)}*")
            if turn.answer:
                parts.append(turn.answer)
            if turn.notice:
                parts.append(f"*{turn.notice}*")
            elif turn.note and turn.answer:
                parts.append(f"*{turn.note}*")
            if turn.sources:
                links = "\n".join(f"- [{t}]({u})" for t, u in turn.sources)
                parts.append(f"**{strings.RESEARCH_SOURCES}**\n\n{links}")
            parts.append("---")
        self.transcript.setMarkdown("\n\n".join(parts[:-1]))
        if at_bottom:
            bar.setValue(bar.maximum())

    # -- auto-fill ----------------------------------------------------------

    def _on_filled(self, turn: _Turn, values: dict) -> None:
        lot = self._lot_provider()
        if not values or lot is None:
            turn.answer = strings.AUTOFILL_NOTHING
            return
        turn.answer = strings.AUTOFILL_FOUND.format(
            fields=", ".join(self._label(key) for key in values)
        )
        self._render()
        # Shown once this turn has finished (see _on_finished).
        self._pending_fill = (values, lot)

    def _review_fill(self) -> None:
        pending, self._pending_fill = self._pending_fill, None
        if pending is None:
            return
        values, lot = pending
        dialog = AutofillDialog(values, lot, self._custom_fields, self.window())
        try:
            if dialog.exec() and (chosen := dialog.selected()):
                self.apply_requested.emit(chosen)
        finally:
            dialog.deleteLater()

    def _label(self, key: str) -> str:
        labels = {k: label for k, label, _hint in AUTOFILL_FIELDS}
        labels |= {f.key: f.label for f in self._custom_fields}
        return labels.get(key, key)
