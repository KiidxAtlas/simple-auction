"""Started and info-filled history is kept by the host and shared by clients.

These tests use the real host database, HTTP client and local output log."""

import sqlite3
from dataclasses import replace
from datetime import datetime

import pytest

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, network, output
from simple_auction.services.config import Config
from simple_auction.services.lot_details import details_path


@pytest.fixture
def config(tmp_path):
    cfg = Config(base_dir=tmp_path / "host", photos_dir=tmp_path / "photos")
    path = excel.auction_path(cfg.auctions_dir, 41000)
    excel.create_auction(path)
    catalogue.add(
        path,
        details_path(cfg.data_dir, 41000),
        [Lot(1, title="Original", make="Maker", model="Model")],
    )
    return cfg


@pytest.fixture
def host(config):
    host = network.Host(
        config, network.new_code(), port=0, bind="127.0.0.1", discovery=False
    )
    yield host
    host.close()


def make_client(host, cache):
    client = network.Client(
        f"127.0.0.1:{host.port}",
        host.code,
        identity=host.db.identity,
        cache=cache,
    )
    client.snapshot()
    return client


@pytest.fixture
def client(host, tmp_path):
    return make_client(host, tmp_path / "client")


def save(client, number=1, **changes):
    snapshot = client.snapshot()
    record = next(v for v in snapshot["auctions"]["41000"] if v["lot_number"] == number)
    lot = replace(Lot(**{k: v for k, v in record.items() if k != "photos"}), **changes)
    return client.save_lot(41000, lot, record)


def stages(snapshot):
    return (
        [r["lot"] for r in snapshot["output"]["started"]],
        [r["lot"] for r in snapshot["output"]["info"]],
    )


def test_imported_lots_and_saved_edits_are_counted_by_stage(client):
    # The imported lot has make and model, but no title-and-condition yet.
    assert stages(client.snapshot()) == ([1], [])

    save(client, condition="Good")
    snapshot = client.snapshot()
    assert stages(snapshot) == ([1], [1])
    assert snapshot["output"]["info"][0]["title"] == "Original"

    # Saving again changes nothing: one row per lot and stage, same time.
    first = snapshot["output"]["info"][0]["at"]
    save(client, condition="Good", desc="Stock cracked")
    again = client.snapshot()["output"]
    assert stages(client.snapshot()) == ([1], [1])
    assert again["info"][0]["at"] == first


def test_clearing_a_lot_removes_its_output(client):
    save(client, condition="Good")
    save(client, title="", condition="", make="", model="")
    assert stages(client.snapshot()) == ([], [])


def test_deleted_lots_stay_deleted_for_every_client(host, client, tmp_path):
    save(client, condition="Good")
    other = make_client(host, tmp_path / "other")
    assert stages(other.snapshot()) == ([1], [1])

    snapshot = client.snapshot()
    client.request(
        "delete",
        auction=41000,
        numbers=[1],
        expected=snapshot["auctions"]["41000"],
    )
    assert stages(client.snapshot()) == ([], [])
    assert stages(other.snapshot()) == ([], [])

    # A client that still holds the old history adopts the host's answer.
    local = output.OutputLog(tmp_path / "output.json")
    local.track(Lot(1, title="Original", condition="Good", make="Maker"), 41000)
    assert local.has(41000, 1)
    assert local.adopt(other.snapshot()["output"])
    assert local.completions == [] and local.started == []


def test_local_history_keeps_host_rows_across_restarts(client, tmp_path):
    save(client, condition="Good")
    path = tmp_path / "cache" / output.FILE_NAME
    local = output.OutputLog(path)
    assert local.adopt(client.snapshot()["output"])

    restarted = output.OutputLog(path)  # e.g. offline after a restart
    assert [c.lot for c in restarted.started] == [1]
    assert [c.lot for c in restarted.completions] == [1]
    assert restarted.completions[0].title == "Original"


def test_existing_databases_get_their_output_once_from_saved_lots(config, host):
    with host.db.connect() as db:
        db.execute("DELETE FROM meta WHERE key='output'")
        db.execute("DELETE FROM records WHERE kind='output'")
    reopened = network.Database(config)
    snapshot = reopened.dispatch("snapshot", {})
    assert [r["lot"] for r in snapshot["output"]["started"]] == [1]
    assert snapshot["output"]["info"] == []


def test_output_rows_are_written_in_the_host_database(config, host, client):
    save(client, condition="Good")
    with sqlite3.connect(config.data_dir / "shared.sqlite3") as db:
        keys = [
            key for (key,) in db.execute("SELECT key FROM records WHERE kind='output'")
        ]
    assert sorted(keys) == ["info/41000/1", "started/41000/1"]


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2025, 3, 10 + day, hour).astimezone()


def joined(host, cache, history=None):
    client = network.Client(
        f"127.0.0.1:{host.port}",
        host.code,
        identity=host.db.identity,
        cache=cache,
        history=history,
    )
    client.snapshot()
    return client


def test_history_counted_before_connecting_is_uploaded_with_its_date(host, tmp_path):
    save(make_client(host, tmp_path / "first"), condition="Good", title="Original")
    local = output.OutputLog(tmp_path / "output.json")
    local.track(Lot(1, title="Original", condition="Good", make="Maker"), 41000, at(0))

    snapshot = joined(host, tmp_path / "c", local.rows).snapshot()
    assert [r["at"] for r in snapshot["output"]["info"]] == [at(0).isoformat()]
    assert [r["at"] for r in snapshot["output"]["started"]] == [at(0).isoformat()]

    # Uploading again is idempotent, and a later local date never replaces it.
    local.track(Lot(1, title="Original", condition="Good", make="Maker"), 41000, at(3))
    again = joined(host, tmp_path / "c", local.rows).snapshot()["output"]
    assert [r["at"] for r in again["info"]] == [at(0).isoformat()]
    assert len(again["info"]) == len(again["started"]) == 1


def test_uploaded_history_never_brings_back_deleted_or_cleared_lots(host, tmp_path):
    client = make_client(host, tmp_path / "first")
    save(client, condition="Good")
    snapshot = client.snapshot()
    client.request(
        "delete", auction=41000, numbers=[1], expected=snapshot["auctions"]["41000"]
    )
    local = output.OutputLog(tmp_path / "output.json")
    local.track(Lot(1, title="Original", condition="Good", make="Maker"), 41000, at(0))

    # A new lot that is cleared on the host again: its local history is stale.
    fresh = client.request("new_lot", auction=41000)["lot_number"]
    local.track(Lot(fresh, title="Gone", condition="Good", make="M"), 41000, at(1))

    after = joined(host, tmp_path / "c", local.rows).snapshot()["output"]
    assert after == {"started": [], "info": []}

    # Adopting that answer drops the stale local copy as well.
    assert local.adopt(after)
    assert local.completions == [] and local.started == []


def test_uploaded_lots_still_on_the_host_are_kept_when_adopted(host, tmp_path):
    client = make_client(host, tmp_path / "first")
    save(client, condition="Good")
    local = output.OutputLog(tmp_path / "output.json")
    local.track(Lot(1, title="Original", condition="Good", make="Maker"), 41000, at(0))
    # Nothing changes: the host agrees with what was uploaded.
    assert not local.adopt(
        joined(host, tmp_path / "c", local.rows).snapshot()["output"]
    )
    assert [c.at for c in local.completions] == [at(0)]


def test_background_poll_syncs_history_and_new_host_edits(host, tmp_path):
    from simple_auction.ui.network_poll import NetworkPoll

    first = make_client(host, tmp_path / "first")
    local = output.OutputLog(tmp_path / "poll-output.json")
    local.track(Lot(1, title="Original", make="Maker"), 41000, at(0))
    second = network.Client(
        first.address,
        first.code,
        identity=first.identity,
        cache=tmp_path / "poll-cache",
        history=local.rows,
    )
    worker = NetworkPoll(second, None, None, None)
    worker.run()
    assert worker.error is None
    snapshot = worker.result[0]
    assert snapshot["output"]["started"][0]["at"] == at(0).isoformat()
    local.adopt(snapshot["output"])
    save(first, condition="Good")
    worker = NetworkPoll(second, None, None, None)
    worker.run()
    assert worker.error is None
    local.adopt(worker.result[0]["output"])
    assert local.has(41000, 1)
    snapshot = first.snapshot()
    first.request(
        "delete", auction=41000, numbers=[1], expected=snapshot["auctions"]["41000"]
    )
    worker = NetworkPoll(second, None, None, None)
    worker.run()
    assert worker.error is None
    local.adopt(worker.result[0]["output"])
    assert local.started == [] and local.completions == []
