import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from google.genai import errors
from google.genai._gaos.lib import compat_errors as ce
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
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
    RESEARCH_REQUEST,
    MissingApiKeyError,
    ResearchChat,
    ResearchFailedError,
)
from simple_auction.ui import strings, theme

log = logging.getLogger(__name__)

RENDER_MS = 60  # batch streamed text into one repaint


@dataclass
class _Turn:
    question: str
    answer: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)
    notice: str = ""  # why the answer is missing or cut short
    note: str = ""  # about how the answer was made (e.g. without web search)


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
    refused = Signal()
    note = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, chat: ResearchChat, question: str, lot: Lot) -> None:
        super().__init__()
        self._chat, self._question, self._lot = chat, question, lot
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
        events = self._chat.ask_async(self._question, self._lot)
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
                    case "no_search":
                        self.note.emit(strings.RESEARCH_NO_SEARCH)
                    case "refused":
                        self.refused.emit()
                    case "done":
                        self.done.emit(event.sources)
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

    def __init__(self, lot_provider: Callable[[], Lot | None]) -> None:
        super().__init__()
        self.setObjectName("researchPanel")
        self.setMinimumWidth(theme.RESEARCH_MIN_WIDTH)
        self._lot_provider = lot_provider
        self._chat = ResearchChat()
        self._turns: list[_Turn] = []
        self._job: _Job | None = None
        self._has_lot = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

        title = QLabel(strings.RESEARCH)
        title.setObjectName("cardTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("hint")
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setToolTip(strings.RESEARCH_CLOSE_TIP)
        close.clicked.connect(self.closed)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, 1)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        # Empty page: one button to start.
        self.start_btn = QPushButton(strings.RESEARCH_START)
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.research_lot)
        start_hint = QLabel(strings.RESEARCH_START_HINT)
        start_hint.setObjectName("hint")
        start_hint.setWordWrap(True)
        start_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(start_hint)
        empty_layout.addStretch(2)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(empty)
        self.stack.addWidget(self.transcript)

        self.status = QLabel()
        self.status.setObjectName("hint")

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
        layout.addLayout(ask_row)

        self.reset(None)

    # -- public -------------------------------------------------------------

    def reset(self, lot_number: int | None) -> None:
        """Start a fresh conversation for another lot (or none)."""
        if self._job is not None:
            self._job.stop()  # finishes on its own; its signals are ignored
            self._job = None
        self._chat = ResearchChat()
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

    def _ask(self, question: str, label: str | None = None) -> None:
        lot = self._lot_provider()
        if lot is None or self._job is not None:
            return
        turn = _Turn(question=label or question)
        self._turns.append(turn)
        self.stack.setCurrentIndex(1)
        self.status.setText(strings.RESEARCH_THINKING)
        self._set_busy(True)
        self._render()

        job = _Job(self._chat, question, lot)
        self._job = job
        mine = lambda: self._job is job
        # Signals come from the worker thread; queue them onto the UI thread.
        queued = Qt.ConnectionType.QueuedConnection
        job.text.connect(lambda t: mine() and self._on_text(turn, t), queued)
        job.status.connect(lambda s: mine() and self.status.setText(s), queued)
        job.done.connect(lambda src: mine() and self._on_done(turn, src), queued)
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

    def _set_busy(self, busy: bool) -> None:
        self.ask_btn.setText(strings.RESEARCH_STOP if busy else strings.RESEARCH_ASK)
        self.ask_btn.setObjectName("ghostBordered" if busy else "primary")
        self.ask_btn.style().unpolish(self.ask_btn)
        self.ask_btn.style().polish(self.ask_btn)
        self.ask_btn.setEnabled(self._has_lot)
        self.start_btn.setEnabled(self._has_lot and not busy)

    # -- rendering ----------------------------------------------------------

    def _render(self) -> None:
        bar = self.transcript.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 8
        parts = []
        for turn in self._turns:
            parts.append(f"**{strings.RESEARCH_YOU}** {turn.question}")
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
