"""The Output page: lots started and information filled, with history behind it.

Only offered once history access has been unlocked in Settings. The page leads
with today's three numbers, then the 30-day trend; everything else sits behind
"Show detail" so the overview stays readable.
"""

from datetime import date, datetime, timedelta

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services.kpi import Day, Funnel, Pipeline, Report
from simple_auction.services.kpi import funnel as build_funnel
from simple_auction.ui import strings, theme

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ROW_HEIGHT = 30
TABLE_MAX_ROWS = 10
RECENT_SHOWN = 6
BLOCKERS_SHOWN = 4
CONTENT_WIDTH = 1120
# Charts with more bars than this label only today's bar and the peak.
LABEL_ALL_BARS = 12


def clock(at: datetime) -> str:
    return f"{at.hour % 12 or 12}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"


def long_date(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b %Y}"


def duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m" if minutes else "—"


def hour_label(hour: int) -> str:
    return f"{hour % 12 or 12}{'a' if hour < 12 else 'p'}"


def versus_yesterday(today: int, yesterday: int) -> str:
    diff = today - yesterday
    if diff > 0:
        return f"▲ {diff} on yesterday ({yesterday})"
    if diff < 0:
        return f"▼ {-diff} on yesterday ({yesterday})"
    return f"Same as yesterday ({yesterday})"


class BarChart(QWidget):
    """A small bar chart in the current theme's colors."""

    def __init__(self, accessible_name: str, height: int = 170) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(accessible_name)
        self._bars: list[tuple[str, int]] = []
        self._label_every = 1
        self._from_end = True
        self._highlight: int | None = None

    def set_bars(
        self,
        bars: list[tuple[str, int]],
        label_every: int = 1,
        highlight: int | None = None,
        from_end: bool = True,
    ) -> None:
        self._bars, self._label_every = bars, label_every
        self._highlight, self._from_end = highlight, from_end
        self.setAccessibleDescription(", ".join(f"{k}: {v}" for k, v in bars))
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._bars:
            return
        colors = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = painter.fontMetrics()
        top = metrics.height() + 4
        bottom = metrics.height() + 8
        plot_h = max(1, self.height() - top - bottom)
        base = top + plot_h
        peak = max(1, max(v for _k, v in self._bars))
        slot = self.width() / len(self._bars)
        bar_w = max(2.0, min(slot * 0.6, 34.0))
        label_all = len(self._bars) <= LABEL_ALL_BARS

        # Soft guides at the peak and half way, then the baseline.
        guide = QColor(colors.border)
        painter.setPen(guide)
        for fraction in (1.0, 0.5):
            y = base - plot_h * fraction
            painter.drawLine(0, int(y), self.width(), int(y))
        painter.drawLine(0, base, self.width(), base)

        soft = QColor(colors.accent)
        soft.setAlphaF(0.45)
        for i, (label, value) in enumerate(self._bars):
            x = i * slot + (slot - bar_w) / 2
            height = plot_h * value / peak
            key = i == self._highlight
            if value:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colors.accent) if key else soft)
                painter.drawRoundedRect(QRectF(x, base - height, bar_w, height), 4, 4)
                show_value = label_all or key or value == peak
                if show_value and metrics.horizontalAdvance(str(value)) <= slot * 3:
                    painter.setPen(QColor(colors.text if key else colors.muted))
                    painter.drawText(
                        QRectF(i * slot - slot, base - height - top, slot * 3, top - 2),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                        str(value),
                    )
            step = len(self._bars) - 1 - i if self._from_end else i
            if step % self._label_every == 0:
                painter.setPen(QColor(colors.text if key else colors.muted))
                painter.drawText(
                    QRectF(i * slot - slot, base + 6, slot * 3, metrics.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )
        painter.end()


class Card(QFrame):
    """A number with a title and a short note.

    kind: "hero" for today's headline numbers, "stat" for the compact strip,
    "card" for the detail section.
    """

    def __init__(self, title: str, kind: str = "card") -> None:
        super().__init__()
        self.setObjectName({"hero": "kpiHero", "stat": "kpiStat"}.get(kind, "kpiCard"))
        layout = QVBoxLayout(self)
        if kind == "hero":
            layout.setContentsMargins(20, 16, 20, 16)
            layout.setSpacing(4)
        else:
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("kpiLabel")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.note = QLabel()
        self.note.setObjectName("kpiNote")
        self.note.setWordWrap(True)
        for widget in (self.title, self.value, self.note):
            layout.addWidget(widget)
        layout.addStretch(1)

    def set(self, value: str, note: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.setAccessibleName(f"{self.title.text()}: {value}. {note}")


class OutputPage(QScrollArea):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.setWidget(body)
        outer = QHBoxLayout(body)
        outer.setContentsMargins(28, 24, 28, 32)
        content = QWidget()
        content.setMaximumWidth(CONTENT_WIDTH)
        outer.addStretch(0)
        outer.addWidget(content, 1)
        outer.addStretch(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # -- heading ----------------------------------------------------------
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(strings.OUTPUT_NAV)
        title.setObjectName("settingsPageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("hint")
        self.subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        refresh = QPushButton("Refresh")
        theme.set_icon(refresh, "refresh")
        refresh.clicked.connect(self.refresh_requested)
        head.addWidget(refresh, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)

        self.empty = QLabel(
            "Nothing tracked yet. A lot counts as started once it has saved "
            "information, and as information filled once its title, condition and "
            "identifying details are in. Photos are not needed for either."
        )
        self.empty.setObjectName("hint")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

        # -- today: the three numbers that matter -----------------------------
        self.cards: dict[str, Card] = {
            "started": Card("Started today", "hero"),
            "today": Card("Information filled today", "hero"),
            "backlog": Card("In progress", "hero"),
        }
        self.cards["today"].setProperty("accent", True)
        hero = QHBoxLayout()
        hero.setSpacing(14)
        for card in self.cards.values():
            hero.addWidget(card, 1)
        layout.addLayout(hero)

        # -- trend, with the period totals underneath -------------------------
        self.trend = BarChart("Lots information filled per day, last 30 days", 190)
        stats = QHBoxLayout()
        stats.setSpacing(10)
        for name, text in (
            ("week", "This week"),
            ("month", "This month"),
            ("streak", "Streak"),
            ("best", "Best day"),
            ("total", "All time"),
        ):
            self.cards[name] = Card(text, "stat")
            stats.addWidget(self.cards[name], 1)
        trend_body = QWidget()
        trend_layout = QVBoxLayout(trend_body)
        trend_layout.setContentsMargins(0, 0, 0, 0)
        trend_layout.setSpacing(14)
        trend_layout.addWidget(self.trend)
        trend_layout.addLayout(stats)
        layout.addWidget(self._section("Information filled, last 30 days", trend_body))

        # -- catalogue readiness and the latest lots --------------------------
        catalogue = QWidget()
        catalogue_layout = QVBoxLayout(catalogue)
        catalogue_layout.setContentsMargins(0, 0, 0, 0)
        catalogue_layout.setSpacing(8)
        self.ready_value = QLabel("—")
        self.ready_value.setObjectName("kpiReady")
        self.ready_note = QLabel()
        self.ready_note.setObjectName("kpiNote")
        self.ready_bar = QProgressBar()
        self.ready_bar.setObjectName("kpiProgress")
        self.ready_bar.setTextVisible(False)
        self.ready_bar.setFixedHeight(8)
        self.blockers = self._table(["Holding lots back", "Lots"])
        self.blockers.horizontalHeader().hide()
        blockers_title = QLabel("Most common blockers")
        blockers_title.setObjectName("kpiLabel")
        for widget in (self.ready_value, self.ready_bar, self.ready_note):
            catalogue_layout.addWidget(widget)
        catalogue_layout.addSpacing(6)
        catalogue_layout.addWidget(blockers_title)
        catalogue_layout.addWidget(self.blockers)
        catalogue_layout.addStretch(1)

        self.recent = self._table(["Information filled", "Lot", "Title"])
        self.recent.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        recent_box = QWidget()
        recent_layout = QVBoxLayout(recent_box)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.addWidget(self.recent)
        recent_layout.addStretch(1)
        layout.addLayout(
            self._pair(
                self._section("Ready to publish", catalogue),
                self._section("Latest information filled", recent_box),
            )
        )

        # -- everything else, on request --------------------------------------
        self.more = QPushButton()
        self.more.setObjectName("kpiMore")
        self.more.setCheckable(True)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.toggled.connect(self._show_detail)
        layout.addWidget(self.more, 0, Qt.AlignmentFlag.AlignHCenter)

        self.detail = QWidget()
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(18)

        self.funnel = self._table(["Stage", "Today", "All time"])
        funnel_note = QLabel(
            "Started includes lots that are already filled. In progress is the "
            "current backlog. Blank and deleted lots are left out."
        )
        funnel_note.setObjectName("hint")
        funnel_note.setWordWrap(True)
        funnel_body = QWidget()
        funnel_layout = QVBoxLayout(funnel_body)
        funnel_layout.setContentsMargins(0, 0, 0, 0)
        funnel_layout.setSpacing(10)
        funnel_layout.addWidget(self.funnel)
        funnel_layout.addWidget(funnel_note)
        self.funnel_frame = self._section("Started vs information filled", funnel_body)

        averages = QGridLayout()
        averages.setSpacing(10)
        for i, (name, text) in enumerate(
            (
                ("per_active", "Average per working day"),
                ("per_day", "Average, last 30 days"),
                ("pace", "Typical pace"),
                ("active", "Working days"),
            )
        ):
            self.cards[name] = Card(text, "stat")
            averages.addWidget(self.cards[name], i // 2, i % 2)
        averages_body = QWidget()
        averages_body.setLayout(averages)
        detail.addLayout(
            self._pair(self.funnel_frame, self._section("Pace", averages_body))
        )

        self.weekday = BarChart("Lots information filled by weekday", 150)
        self.hours = BarChart("Lots information filled by hour of day", 150)
        detail.addLayout(
            self._pair(
                self._section("By weekday", self.weekday),
                self._section("By time of day", self.hours),
            )
        )
        self.days = self._table(
            ["Date", "Lots", "First", "Last", "Time span", "Auctions"]
        )
        detail.addWidget(self._section("Daily history", self.days))
        self.auctions = self._table(
            ["Auction", "Information filled", "Lots now", "Ready now", "Progress"]
        )
        self.types = self._table(["Type", "Information filled"])
        detail.addLayout(
            self._pair(
                self._section("By auction", self.auctions),
                self._section("By type", self.types),
            )
        )
        layout.addWidget(self.detail)
        layout.addStretch(1)
        self._show_detail(False)

    # -- building blocks ----------------------------------------------------

    def _show_detail(self, shown: bool) -> None:
        self.detail.setVisible(shown)
        self.more.setText("Hide detail  ▴" if shown else "Show detail  ▾")

    @staticmethod
    def _section(title: str, content: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(20, 16, 20, 18)
        inner.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        inner.addWidget(heading)
        inner.addWidget(content)
        return frame

    @staticmethod
    def _pair(left: QWidget, right: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(left, 1)
        row.addWidget(right, 1)
        return row

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("kpiTable")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        table.horizontalHeader().setFixedHeight(ROW_HEIGHT)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.setAccessibleName(" / ".join(headers))
        return table

    @staticmethod
    def _fill(
        table: QTableWidget,
        rows: list[list[str]],
        numeric: tuple[int, ...] = (),
        max_rows: int = TABLE_MAX_ROWS,
    ) -> None:
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                if c in numeric:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(r, c, item)
        shown = min(max(len(rows), 1), max_rows)
        header = 0 if table.horizontalHeader().isHidden() else 1
        table.setFixedHeight(ROW_HEIGHT * (shown + header) + 4)

    # -- data ---------------------------------------------------------------

    def show_report(
        self,
        report: Report,
        pipeline: Pipeline | None,
        today: date,
        started_report: Report | None = None,
    ) -> None:
        self.subtitle.setText(
            f"{long_date(today)} · "
            + (
                f"tracking since {long_date(report.first_day)}"
                if report.first_day
                else "nothing tracked yet"
            )
        )
        started_total = started_report.total if started_report else 0
        self.empty.setVisible(report.total == 0 and started_total == 0)
        self._fill_today(report, started_report)
        self._fill_stats(report)
        self.trend.set_bars(
            [(f"{d.day}/{d.month}", n) for d, n in report.trend],
            label_every=7,
            highlight=len(report.trend) - 1,
        )
        self.weekday.set_bars(
            list(zip(WEEKDAYS, report.by_weekday, strict=True)),
            highlight=today.weekday(),
        )
        self.hours.set_bars(
            [(hour_label(h), n) for h, n in enumerate(report.by_hour)],
            label_every=3,
            from_end=False,
        )
        self._fill(self.days, [self._day_row(d) for d in report.days], (1,))
        self._fill(
            self.recent,
            [
                [
                    f"{c.day.day} {c.day:%b} · {clock(c.at)}",
                    f"{c.auction} / {c.lot}",
                    c.title or "Untitled lot",
                ]
                for c in report.recent[:RECENT_SHOWN]
            ],
            max_rows=RECENT_SHOWN,
        )
        self._fill(self.types, [[name, str(n)] for name, n in report.by_type], (1,))
        self._fill_pipeline(report, pipeline)
        self.funnel_frame.setVisible(started_report is not None)
        if started_report is not None:
            self._fill_funnel(build_funnel(report, started_report))

    def _fill_today(self, report: Report, started_report: Report | None) -> None:
        cards = self.cards
        cards["today"].set(
            str(report.today), versus_yesterday(report.today, report.yesterday)
        )
        for name in ("started", "backlog"):
            cards[name].setVisible(started_report is not None)
        if started_report is None:
            return
        cards["started"].set(
            str(started_report.today),
            versus_yesterday(started_report.today, started_report.yesterday),
        )
        cards["backlog"].set(
            str(build_funnel(report, started_report).in_progress_total),
            "Started, information not yet filled",
        )

    def _fill_funnel(self, funnel: Funnel) -> None:
        self._fill(
            self.funnel,
            [
                ["Started", str(funnel.started_today), str(funnel.started_total)],
                [
                    "Information filled",
                    str(funnel.filled_today),
                    str(funnel.filled_total),
                ],
                [
                    "In progress (started, not yet filled)",
                    "—",
                    str(funnel.in_progress_total),
                ],
            ],
            (1, 2),
        )

    def _fill_stats(self, report: Report) -> None:
        cards = self.cards
        cards["week"].set(str(report.week), f"Last 7 days: {report.last_7}")
        cards["month"].set(str(report.month), f"Last 30 days: {report.last_30}")
        cards["streak"].set(
            strings.count(report.streak, "day"),
            f"Longest: {strings.count(report.longest_streak, 'day')}",
        )
        best = report.best
        cards["best"].set(
            str(best.count) if best else "—",
            f"{best.day.day} {best.day:%b %Y}" if best else "",
        )
        cards["total"].set(
            str(report.total),
            f"Over {strings.count(report.active_days, 'working day')}",
        )
        cards["per_active"].set(
            f"{report.average_per_active_day:.1f}", "Days with at least one lot"
        )
        cards["per_day"].set(f"{report.average_last_30:.1f}", "Idle days included")
        pace = report.median_minutes_between
        cards["pace"].set(
            "—" if pace is None else f"{pace:.0f} min",
            "Median gap between lots; breaks over 2h ignored",
        )
        cards["active"].set(str(report.active_days), "Days with output")

    @staticmethod
    def _day_row(day: Day) -> list[str]:
        return [
            long_date(day.day),
            str(day.count),
            clock(day.first),
            clock(day.last),
            duration(day.last - day.first) if day.count > 1 else "—",
            ", ".join(map(str, day.auctions)),
        ]

    def _fill_pipeline(self, report: Report, pipeline: Pipeline | None) -> None:
        if pipeline is None:
            self.ready_value.setText("—")
            self.ready_note.setText("The catalogue could not be read.")
            self.ready_bar.setRange(0, 1)
            self.ready_bar.setValue(0)
        else:
            share = pipeline.ready / pipeline.total if pipeline.total else 0
            self.ready_value.setText(f"{pipeline.ready} of {pipeline.total} lots")
            self.ready_note.setText(
                f"{share:.0%} ready, photos included · "
                f"{pipeline.total - pipeline.ready} still need work across "
                f"{strings.count(len(pipeline.auctions), 'auction')}"
            )
            self.ready_bar.setRange(0, max(pipeline.total, 1))
            self.ready_bar.setValue(pipeline.ready)
        blockers = pipeline.blockers[:BLOCKERS_SHOWN] if pipeline else []
        self._fill(
            self.blockers,
            [[label, str(n)] for label, n in blockers]
            or [["Nothing is holding lots back" if pipeline else "—", ""]],
            (1,),
            max_rows=BLOCKERS_SHOWN,
        )

        logged = dict(report.by_auction)
        rows = []
        if pipeline is not None:
            for p in pipeline.auctions:
                share = f"{p.ready / p.total:.0%}" if p.total else "—"
                rows.append(
                    [
                        str(p.auction),
                        str(logged.pop(p.auction, 0)),
                        str(p.total),
                        str(p.ready),
                        share,
                    ]
                )
        # Auctions that had output but have since been deleted.
        rows += [[str(a), str(n), "—", "—", "—"] for a, n in sorted(logged.items())]
        self._fill(self.auctions, rows, (1, 2, 3, 4))
