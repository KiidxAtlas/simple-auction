from datetime import date, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from simple_auction.services import kpi
from simple_auction.services.output import Completion
from simple_auction.ui.output_page import OutputPage

TODAY = date(2025, 3, 12)


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0).astimezone()


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def started_and_filled():
    filled = [
        Completion(41000, 1, at(TODAY)),
        Completion(41000, 2, at(TODAY - timedelta(days=3))),
    ]
    started = filled + [
        Completion(41000, 3, at(TODAY, 10)),
        Completion(41000, 4, at(TODAY - timedelta(days=1))),
        Completion(41000, 5, at(TODAY - timedelta(days=5))),
    ]
    return kpi.report(filled, TODAY), kpi.report(started, TODAY)


def test_funnel_counts_started_filled_and_in_progress():
    filled, started = started_and_filled()
    f = kpi.funnel(filled, started)
    assert (f.started_total, f.started_today) == (5, 2)
    assert (f.filled_total, f.filled_today) == (2, 1)
    assert f.in_progress_total == 3


def test_in_progress_never_goes_negative():
    filled, started = started_and_filled()
    f = kpi.funnel(started, filled)  # deliberately inverted
    assert f.in_progress_total == 0


def test_page_shows_started_filled_and_in_progress(app):
    filled, started = started_and_filled()
    page = OutputPage()
    page.show_report(filled, None, TODAY, started_report=started)
    table = page.funnel
    assert table.rowCount() == 3
    assert [table.item(r, 0).text() for r in range(3)] == [
        "Started",
        "Information filled",
        "In progress (started, not yet filled)",
    ]
    assert [table.item(0, c).text() for c in (1, 2)] == ["2", "5"]
    assert [table.item(1, c).text() for c in (1, 2)] == ["1", "2"]
    assert [table.item(2, c).text() for c in (1, 2)] == ["—", "3"]
    assert not page.funnel_frame.isHidden()
    page.deleteLater()


def test_page_without_started_counts_hides_the_funnel(app):
    filled, _started = started_and_filled()
    page = OutputPage()
    page.show_report(filled, None, TODAY)  # the old three-argument call
    assert page.funnel_frame.isHidden()
    assert page.cards["started"].isHidden() and page.cards["backlog"].isHidden()
    assert page.cards["today"].value.text() == str(filled.today)
    page.deleteLater()


def test_overview_leads_with_today_and_keeps_detail_folded(app):
    filled, started = started_and_filled()
    page = OutputPage()
    page.show_report(filled, None, TODAY, started_report=started)
    assert [page.cards[n].value.text() for n in ("started", "today", "backlog")] == [
        "2",
        "1",
        "3",
    ]
    assert page.detail.isHidden()
    page.more.click()
    assert not page.detail.isHidden()
    page.deleteLater()


def test_historical_labels_say_information_filled(app):
    page = OutputPage()
    titles = [card.title.text() for card in page.cards.values()]
    assert "Information filled today" in titles
    assert page.recent.horizontalHeaderItem(0).text() == "Information filled"
    page.deleteLater()
