import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import dossier, kpi, output
from simple_auction.services.config import Config
from simple_auction.services.output import Completion, OutputLog
from simple_auction.ui import main_page
from simple_auction.ui.output_page import OutputPage

TODAY = date(2025, 3, 12)  # a Wednesday


def at(day: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute).astimezone()


def ready_lot(number: int = 1) -> Lot:
    packet = dossier.empty() | {
        "status": "Documented",
        "research_complete": True,
        "review_approved": True,
        "required_shots": list(dossier.SHOTS),
    }
    return Lot(
        number,
        title="Arsenal SAM7SF",
        condition="Excellent",
        make="Arsenal",
        model="SAM7SF",
        gun_type="Rifle",
        photos=[Path("a.jpg")],
        dossier=packet,
    )


def test_a_lot_with_nothing_outstanding_is_complete():
    assert output.is_complete(ready_lot())
    assert not output.is_complete(Lot(1))
    assert not output.is_complete(ready_lot(), duplicate=True)
    broken = ready_lot()
    broken.dossier = {"version": 99}
    assert not output.is_complete(broken)


def test_history_is_saved_and_counted_per_day(tmp_path):
    path = tmp_path / "data" / output.FILE_NAME
    history = OutputLog(path)
    assert history.record(ready_lot(1), 41000, at(TODAY))
    assert not history.record(ready_lot(1), 41000, at(TODAY, 10))  # only once
    assert history.record(ready_lot(2), 41000, at(TODAY - timedelta(days=1)))
    assert history.count_on(TODAY) == 1

    reopened = OutputLog(path)
    assert [(c.auction, c.lot, c.title, c.gun_type) for c in reopened.completions] == [
        (41000, 2, "Arsenal SAM7SF", "Rifle"),
        (41000, 1, "Arsenal SAM7SF", "Rifle"),
    ]
    assert reopened.count_on(TODAY) == 1


def test_a_lot_that_is_reopened_stops_counting_and_can_count_again(tmp_path):
    history = OutputLog(tmp_path / output.FILE_NAME)
    history.record(ready_lot(1), 41000, at(TODAY))
    assert history.discard(41000, 1)
    assert not history.discard(41000, 1)
    assert history.count_on(TODAY) == 0
    assert history.record(ready_lot(1), 41000, at(TODAY, 15))
    assert OutputLog(tmp_path / output.FILE_NAME).count_on(TODAY) == 1


def test_an_unreadable_history_is_set_aside_not_overwritten(tmp_path):
    path = tmp_path / output.FILE_NAME
    path.write_text("{not json")
    history = OutputLog(path)
    assert history.completions == []
    assert not path.exists()
    assert [p.read_text() for p in tmp_path.glob("output.json.invalid-*")] == [
        "{not json"
    ]
    history.record(ready_lot(1), 41000, at(TODAY))
    assert json.loads(path.read_text())["completions"][0]["lot"] == 1


def test_a_failed_write_does_not_lose_the_count_or_raise(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the folder should be")
    history = OutputLog(blocker / output.FILE_NAME)
    assert history.record(ready_lot(1), 41000, at(TODAY))
    assert history.count_on(TODAY) == 1


def test_report_totals_streaks_and_pace():
    def done(days_ago: int, hour: int, minute: int = 0, lot: int = 1, auction=41000):
        return Completion(
            auction,
            lot,
            at(TODAY - timedelta(days=days_ago), hour, minute),
            "T",
            "Rifle",
        )

    completions = [
        done(0, 9, 0, 1),
        done(0, 9, 20, 2),
        done(0, 14, 0, 3, auction=42000),  # long break: not part of the pace
        done(1, 10, 0, 4),
        done(2, 10, 0, 5),
        done(9, 11, 0, 6),
        done(40, 11, 0, 7),
    ]
    r = kpi.report(completions, TODAY)
    assert (r.total, r.today, r.yesterday) == (7, 3, 1)
    assert r.week == 5  # Monday 10th onwards: today, yesterday and 2 days ago
    assert r.month == 6
    assert (r.last_7, r.last_30) == (5, 6)
    assert (r.streak, r.longest_streak) == (3, 3)
    assert r.active_days == 5
    assert r.best is not None and (r.best.day, r.best.count) == (TODAY, 3)
    assert r.best.auctions == (41000, 42000)
    assert r.median_minutes_between == 20
    assert r.average_last_30 == pytest.approx(6 / 30)
    assert len(r.trend) == 30 and r.trend[-1] == (TODAY, 3)
    assert r.by_weekday[TODAY.weekday()] == 3
    assert r.by_hour[9] == 2
    assert r.by_auction == [(41000, 6), (42000, 1)]
    assert [d.day for d in r.days][:2] == [TODAY, TODAY - timedelta(days=1)]
    assert r.recent[0].lot == 3


def test_a_streak_survives_a_day_with_nothing_yet():
    yesterday = Completion(1, 1, at(TODAY - timedelta(days=1)))
    before = Completion(1, 2, at(TODAY - timedelta(days=2)))
    r = kpi.report([yesterday, before], TODAY)
    assert r.today == 0 and r.streak == 2
    stale = kpi.report([Completion(1, 3, at(TODAY - timedelta(days=3)))], TODAY)
    assert stale.streak == 0 and stale.longest_streak == 1


def test_an_empty_history_reports_zeroes():
    r = kpi.report([], TODAY)
    assert (r.total, r.today, r.streak, r.best, r.first_day) == (0, 0, 0, None, None)
    assert r.median_minutes_between is None


def test_pipeline_counts_ready_lots_and_what_blocks_the_rest():
    stuck = Lot(2, title="Only a title")
    result = kpi.pipeline({41000: [ready_lot(1), stuck]})
    assert (result.total, result.ready) == (2, 1)
    assert result.auctions == [kpi.AuctionProgress(41000, 2, 1)]
    blockers = dict(result.blockers)
    assert blockers["Missing photos"] == 1 and blockers["Missing condition"] == 1


def test_history_access_is_saved_in_settings(tmp_path):
    path = tmp_path / "config.json"
    assert Config.load(path).history_access is False
    Config(history_access=True).save(path)
    assert Config.load(path).history_access is True


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    saved = Config.save
    monkeypatch.setattr(
        Config, "save", lambda self, path=tmp_path / "config.json": saved(self, path)
    )
    win = main_page.MainPage(
        Config(base_dir=tmp_path / "base", photos_dir=tmp_path / "photos")
    )
    yield win
    win._autosave.stop()
    win.close()
    win.deleteLater()
    app.processEvents()


def test_output_is_hidden_until_the_key_is_entered_in_settings(window, monkeypatch):
    assert window.started_chip.text() == "0 started"
    assert window.nav_output.isHidden()
    window.show_workspace(output=True)  # also refused when asked for directly
    assert window.pages.currentWidget() is window.splitter

    saved_keys = []
    monkeypatch.setattr(main_page.api_key, "save", saved_keys.append)

    def enter_key(dialog):
        dialog.key.setText("root")
        return True

    monkeypatch.setattr(main_page.SettingsDialog, "exec", enter_key)
    window.open_settings()
    assert saved_keys == []  # the access key is never stored as an API key
    assert window.config.history_access
    assert not window.nav_output.isHidden()
    assert Config.load(
        Path(window.config.base_dir).parent / "config.json"
    ).history_access

    window.nav_output.click()
    assert window.pages.currentWidget() is window.output_page
    assert window.nav_output.isChecked()
    window.nav_catalogue.click()
    assert window.pages.currentWidget() is window.splitter

    # Locking again takes the page away, even while it is open.
    window.nav_output.click()
    monkeypatch.setattr(
        main_page.SettingsDialog,
        "exec",
        lambda dialog: dialog.lock_history.click() or True,
    )
    window.open_settings()
    assert window.nav_output.isHidden()
    assert window.pages.currentWidget() is window.splitter


def test_a_wrong_key_does_not_unlock_and_is_kept_as_the_api_key(window, monkeypatch):
    saved_keys = []
    monkeypatch.setattr(main_page.api_key, "save", saved_keys.append)
    monkeypatch.setattr(main_page.research, "forget_search_check", lambda: None)

    def enter_key(dialog):
        dialog.key.setText("not-root")
        return True

    monkeypatch.setattr(main_page.SettingsDialog, "exec", enter_key)
    window.open_settings()
    assert saved_keys == ["not-root"]
    assert not window.config.history_access
    assert window.nav_output.isHidden()


def test_started_and_info_filled_lots_count_once_each_in_the_header(window):
    window._clear()
    window._track_progress(41000, Lot(41001, desc="Stock cracked"))
    assert window.started_chip.text() == "1 started"
    assert window.info_chip.text() == "0 filled in"
    window._track_progress(41000, Lot(41001, desc="Stock cracked"))  # saved again
    assert window.started_chip.text() == "1 started"

    filled = Lot(41001, title="Arsenal SAM7SF", condition="Good", make="Arsenal")
    window._track_progress(41000, filled)
    assert window.info_chip.text() == "1 filled in"
    assert OutputLog(window.output.path).count_on(output.today()) == 1

    window._track_progress(41000, Lot(41001))  # cleared again
    assert window.started_chip.text() == "0 started"
    assert window.info_chip.text() == "0 filled in"


def test_photos_alone_and_default_lots_are_not_started():
    assert not output.is_started(Lot(1))
    assert not output.is_started(Lot(1, photos=[Path("a.jpg")]))
    assert not output.is_started(Lot(1, dossier=dossier.empty()))
    assert not output.is_started(Lot(1, ca_legality="N/A", c_and_r=False))
    assert output.is_started(Lot(1, serial="SN-1"))
    assert output.is_started(Lot(1, ca_legality="Legal for CA"))
    assert output.is_started(Lot(1, custom={"finish": "Blued"}))
    assert output.is_started(Lot(1, dossier=dossier.empty() | {"status": "Documented"}))


def test_info_filled_needs_title_condition_and_identity_only():
    assert output.is_info_filled(Lot(1, title="A", condition="Good", model="M"))
    assert output.is_info_filled(Lot(1, title="A", condition="Good", serial="1"))
    assert not output.is_info_filled(Lot(1, title="A", condition="Good"))
    assert not output.is_info_filled(Lot(1, condition="Good", make="Arsenal"))
    assert not output.is_info_filled(Lot(1, title="A", make="Arsenal"))


def test_track_drops_a_lot_that_leaves_a_stage_and_counts_it_again_later(tmp_path):
    history = OutputLog(tmp_path / output.FILE_NAME)
    full = ready_lot(1)
    history.track(full, 41000, at(TODAY))
    assert (history.count_on(TODAY), history.started_on(TODAY)) == (1, 1)
    history.track(Lot(1, desc="Only a note"), 41000, at(TODAY, 10))
    assert (history.count_on(TODAY), history.started_on(TODAY)) == (0, 1)
    history.track(Lot(1), 41000, at(TODAY, 11))
    assert history.started_on(TODAY) == 0
    history.track(full, 41000, at(TODAY, 12))
    assert OutputLog(tmp_path / output.FILE_NAME).count_on(TODAY) == 1


def test_forget_removes_deleted_lots_from_both_stages(tmp_path):
    history = OutputLog(tmp_path / output.FILE_NAME)
    history.track(ready_lot(1), 41000, at(TODAY))
    history.track(ready_lot(2), 41000, at(TODAY))
    assert history.forget(41000, [1])
    assert [c.lot for c in history.started] == [2]
    assert [c.lot for c in history.completions] == [2]
    assert history.forget(41000)
    assert history.started == [] and history.completions == []
    assert not history.forget(41000)


def test_version_one_history_counts_as_started_and_info_filled(tmp_path):
    path = tmp_path / output.FILE_NAME
    row = {
        "auction": 41000,
        "lot": 1,
        "at": at(TODAY).isoformat(),
        "title": "T",
        "gun_type": "Rifle",
    }
    path.write_text(json.dumps({"version": 1, "completions": [row]}))
    history = OutputLog(path)
    assert [c.lot for c in history.started] == [1]
    assert history.count_on(TODAY) == 1
    saved = json.loads(path.read_text())
    assert saved["version"] == output.VERSION and len(saved["started"]) == 1


def test_adopting_the_host_rows_replaces_local_history(tmp_path):
    path = tmp_path / output.FILE_NAME
    history = OutputLog(path)
    history.track(ready_lot(9), 41000, at(TODAY))  # stale local copy
    row = {"auction": 41000, "lot": 1, "at": at(TODAY).isoformat(), "title": "T"}
    assert history.adopt({"started": [row], "info": [row]})
    assert [c.lot for c in OutputLog(path).completions] == [1]
    assert not history.adopt({"started": [row], "info": [row]})
    assert history.adopt({"started": [], "info": []})
    assert OutputLog(path).started == []


def test_output_page_shows_the_history(window):
    window.config.history_access = True
    window.output.record(ready_lot(41001), 41000)
    window.show_workspace(output=True)
    page = window.output_page
    assert isinstance(page, OutputPage)
    assert page.cards["today"].value.text() == "1"
    assert page.cards["total"].value.text() == "1"
    assert page.days.rowCount() == 1
    assert page.recent.item(0, 1).text() == "41000 / 41001"
    assert page.empty.isHidden()
