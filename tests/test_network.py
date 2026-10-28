import base64
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

import pytest
from PIL import Image

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, network, output, shipping
from simple_auction.services.config import Config
from simple_auction.services.importer import Sheet


@pytest.fixture
def config(tmp_path):
    cfg = Config(base_dir=tmp_path / "host", photos_dir=tmp_path / "photos")
    path = excel.auction_path(cfg.auctions_dir, 41000)
    excel.create_auction(path)
    from simple_auction.services.lot_details import details_path

    catalogue.add(
        path,
        details_path(cfg.data_dir, 41000),
        [Lot(41000, title="Original", make="Maker", model="Model")],
    )
    return cfg


@pytest.fixture
def host(config):
    host = network.Host(
        config, network.new_code(), port=0, bind="127.0.0.1", discovery=False
    )
    yield host
    host.close()


@pytest.fixture
def clients(host, tmp_path):
    result = [
        network.Client(
            f"127.0.0.1:{host.port}",
            host.code,
            identity=host.db.identity,
            cache=tmp_path / f"client{i}",
        )
        for i in range(2)
    ]
    for client in result:
        client.snapshot()
    return result


def record(client, number=41000):
    return next(
        v for v in client.snapshot()["auctions"]["41000"] if v["lot_number"] == number
    )


def batch():
    headers = [
        "Bidder Number",
        "Name",
        "Shipping Address",
        "City",
        "State",
        "Zip",
        "Lot",
        "Description",
    ]
    sheet = Sheet(
        headers,
        [
            ["1", "Jane", "12 Main", "Boston", "MA", "02108", "1", "Vase"],
            ["2", "Sam", "13 Main", "Boston", "MA", "02108", "2", "Clock"],
        ],
    )
    return shipping.build_batch(
        sheet, shipping.guess_mapping(headers), "Shipping test", "source.csv", "US"
    )


def save_batch(client, data, expected=None):
    return client.request(
        "save_shipping",
        key=network.shipping_key(data["auction"]),
        batch=data,
        expected=expected,
    )


def test_initial_migration_preserves_originals_and_fields(config, host, clients):
    a, b = clients
    assert record(a) == record(b)
    assert record(a)["make"] == "Maker"
    assert (
        excel.load_auction(excel.auction_path(config.auctions_dir, 41000))[0].title
        == "Original"
    )
    old = record(a)
    lot = a.materialize(old)
    lot.title = "Updated"
    a.save_lot(41000, lot, old)
    assert record(b)["title"] == "Updated"
    # Reopening a database does not re-import stale workbook snapshots.
    reopened = network.Database(config)
    with reopened.transaction() as db:
        assert reopened.snapshot(db)["auctions"]["41000"][0]["title"] == "Updated"


def test_simultaneous_lot_creation_gets_unique_numbers(clients):
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(lambda c: c.request("new_lot", auction=41000), clients))
    assert {v["lot_number"] for v in result} == {41001, 41002}


def test_same_lot_conflict_retains_winner_and_independent_lots_save(clients):
    a, b = clients
    original = record(a)
    one, two = a.materialize(original), b.materialize(original)
    one.title, two.title = "Alice", "Bob"
    a.save_lot(41000, one, original)
    with pytest.raises(network.Conflict, match="Someone else changed"):
        b.save_lot(41000, two, original)
    assert two.title == "Bob"
    assert record(b)["title"] == "Alice"
    # Exact retry succeeds after a lost response.
    assert a.save_lot(41000, one, original)["title"] == "Alice"


def test_synced_photo_names_follow_lot_order_without_changing_open_drafts(
    clients, tmp_path
):
    a, b = clients
    sources = []
    for color in ("red", "blue"):
        source = tmp_path / f"camera-{color}.png"
        Image.new("RGB", (160, 120), color).save(source)
        sources.append(source)
    original = record(a)
    lot = a.materialize(original)
    lot.photos = sources
    saved = a.save_lot(41000, lot, original)
    draft = b.materialize(saved)
    assert [p.name for p in draft.photos] == ["41000.jpg", "41000-1.jpg"]
    before = [p.read_bytes() for p in draft.photos]

    reordered = a.materialize(saved)
    reordered.photos.reverse()
    updated = a.save_lot(41000, reordered, saved)
    latest = b.materialize(updated)
    assert [p.name for p in latest.photos] == ["41000.jpg", "41000-1.jpg"]
    assert [p.read_bytes() for p in latest.photos] == before[::-1]
    assert [p.read_bytes() for p in draft.photos] == before

    latest.photos = latest.photos[1:]
    reduced = a.save_lot(41000, latest, updated)
    reopened = network.Client(
        b.address, b.code, identity=b.identity, cache=b.cache
    ).materialize(reduced)
    assert [p.name for p in reopened.photos] == ["41000.jpg"]
    assert reopened.photos[0].read_bytes() == before[0]


def test_shared_saves_publish_ordered_photos_in_auction_folder(
    clients, config, host, tmp_path
):
    client = clients[0]
    original = record(client)
    sources = []
    for color in ("red", "blue"):
        source = tmp_path / f"{color}.png"
        Image.new("RGB", (160, 120), color).save(source)
        sources.append(source)
    originals = [source.read_bytes() for source in sources]
    lot = client.materialize(original)
    lot.photos = sources
    saved = client.save_lot(41000, lot, original)
    folder = config.auction_photos_dir(41000)
    expected = [host.db.asset(digest).read_bytes() for digest in saved["photos"]]
    assert (folder / "41000.jpg").read_bytes() == expected[0]
    assert (folder / "41000-1.jpg").read_bytes() == expected[1]

    other = client.request("new_lot", auction=41000, step=config.step)
    other_lot = client.materialize(other)
    other_lot.photos = [sources[0]]
    client.save_lot(41000, other_lot, other)
    neighbor = folder / f"{other_lot.lot_number}.jpg"
    neighbor_bytes = neighbor.read_bytes()

    reordered = client.materialize(saved)
    reordered.photos.reverse()
    updated = client.save_lot(41000, reordered, saved)
    assert (folder / "41000.jpg").read_bytes() == expected[1]
    assert (folder / "41000-1.jpg").read_bytes() == expected[0]
    reordered.photos = reordered.photos[1:]
    client.save_lot(41000, reordered, updated)
    assert (folder / "41000.jpg").read_bytes() == expected[0]
    assert not (folder / "41000-1.jpg").exists()
    assert neighbor.read_bytes() == neighbor_bytes
    assert [source.read_bytes() for source in sources] == originals

    current = client.snapshot()["auctions"]["41000"]
    client.request("delete", auction=41000, numbers=[41000], expected=current)
    assert not (folder / "41000.jpg").exists()
    assert neighbor.read_bytes() == neighbor_bytes
    entry = next(
        entry for entry in client.request("recovery_list") if entry["kind"] == "lots"
    )
    client.request("recovery_restore", id=entry["id"])
    assert (folder / "41000.jpg").read_bytes() == expected[0]
    assert all(host.db.asset(digest).is_file() for digest in saved["photos"])


def test_opening_shared_database_publishes_existing_unopened_lots(config):
    from simple_auction.services import image

    db = network.Database(config)
    digests = [
        db.store_photo(image.conform(Image.new("RGB", (160, 120), color)))
        for color in ("red", "blue")
    ]
    # Model an older shared catalogue: assets and records, no public copies.
    with db.transaction() as conn:
        for lot, digest in zip((41000, 41001), digests):
            db.put(
                conn,
                "lot",
                f"41000/{lot}",
                {**network.lot_data(Lot(lot)), "photos": [digest]},
            )
    folder = config.auction_photos_dir(41000)
    assert not folder.exists()
    network.Database(config)
    for lot, digest in zip((41000, 41001), digests):
        assert (folder / f"{lot}.jpg").read_bytes() == db.asset(digest).read_bytes()
    (folder / "41001.jpg").write_bytes(b"stale copy")
    network.Database(config)
    assert (folder / "41001.jpg").read_bytes() == db.asset(digests[1]).read_bytes()


def test_failed_photo_folder_update_keeps_shared_data_and_resumes_on_restart(
    clients, config, host, tmp_path, monkeypatch
):
    client = clients[0]
    original = record(client)
    source = tmp_path / "red.png"
    Image.new("RGB", (160, 120), "red").save(source)
    lot = client.materialize(original)
    lot.photos = [source]
    folder = config.auction_photos_dir(41000)

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(network.storage, "commit", disk_full)
        with pytest.raises(network.NetworkError, match="catalogue was saved"):
            client.save_lot(41000, lot, original)
    with host.db.connect() as conn:
        saved = host.db.get(conn, "lot", "41000/41000")
    expected = host.db.asset(saved["photos"][0]).read_bytes()
    network.Database(config)
    assert (folder / "41000.jpg").read_bytes() == expected

    with monkeypatch.context() as patch:
        patch.setattr(network.storage, "commit", disk_full)
        with pytest.raises(network.NetworkError, match="catalogue was saved"):
            client.request("delete", auction=41000, numbers=None, expected=[saved])
    assert (folder / "41000.jpg").read_bytes() == expected
    network.Database(config)
    assert not (folder / "41000.jpg").exists()
    assert host.db.asset(saved["photos"][0]).read_bytes() == expected


def test_photos_transfer_and_removal_are_version_checked(clients, tmp_path, host):
    a, b = clients
    src = tmp_path / "new.png"
    Image.new("RGB", (160, 120), "red").save(src)
    original = record(a)
    lot = a.materialize(original)
    lot.photos = [src]
    updated = a.save_lot(41000, lot, original)
    other = b.materialize(record(b))
    assert len(other.photos) == 1
    with Image.open(other.photos[0]) as img:
        assert img.format == "JPEG"
    assert (
        other.photos[0].read_bytes() == host.db.asset(updated["photos"][0]).read_bytes()
    )
    stale = a.materialize(updated)
    other.photos = []
    b.save_lot(41000, other, updated)
    stale.title = "Stale photo editor"
    with pytest.raises(network.Conflict):
        a.save_lot(41000, stale, updated)
    assert not b.materialize(record(b)).photos
    # Old immutable images survive conflict and can recover a draft.
    assert host.db.asset(updated["photos"][0]).is_file()


def test_different_buyers_merge_and_same_buyer_conflicts(clients):
    a, b = clients
    initial = save_batch(a, network.batch_data(batch()))
    alice, bob = deepcopy(initial), deepcopy(initial)
    alice["buyers"][0]["packages"][0]["weight_oz"] = 32
    bob["buyers"][1]["packages"][0]["weight_oz"] = 48
    save_batch(a, alice, initial)
    merged = save_batch(b, bob, initial)
    assert [buyer["packages"][0]["weight_oz"] for buyer in merged["buyers"]] == [32, 48]
    stale = deepcopy(initial)
    stale["buyers"][0]["packages"][0]["weight_oz"] = 64
    with pytest.raises(network.Conflict, match="Jane"):
        save_batch(b, stale, initial)


def test_export_atomic_deduplication_retry_and_download(clients):
    a, b = clients
    original = save_batch(a, network.batch_data(batch()))
    key = network.shipping_key(original["auction"])
    ident = uuid4().hex
    result = a.request(
        "export_shipping", key=key, id=ident, expected=original, measurements=False
    )
    retry = b.request(
        "export_shipping", key=key, id=ident, expected=original, measurements=False
    )
    assert result == retry
    assert b.request("download_export", id=ident) == result["csv"]
    rows = list(
        csv.DictReader(io.StringIO(base64.b64decode(result["csv"]).decode("utf-8-sig")))
    )
    assert len(rows) == 2 and rows[0]["Zip"] == "02108"
    with pytest.raises(network.Conflict):
        b.request(
            "export_shipping",
            key=key,
            id=uuid4().hex,
            expected=original,
            measurements=False,
        )
    with pytest.raises(network.NetworkError, match="No new shipments"):
        b.request(
            "export_shipping",
            key=key,
            id=uuid4().hex,
            expected=result["batch"],
            measurements=False,
        )
    modified = deepcopy(result["batch"])
    modified["buyers"][0]["packages"][0]["exported_at"] = ""
    with pytest.raises(network.NetworkError):
        save_batch(b, modified, result["batch"])


def test_failed_export_rolls_back_ledger(clients, host, monkeypatch):
    original = save_batch(clients[0], network.batch_data(batch()))
    key = network.shipping_key(original["auction"])

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shipping, "prepare_export", fail)
    with pytest.raises(network.NetworkError, match="disk full"):
        clients[0].request(
            "export_shipping",
            key=key,
            id=uuid4().hex,
            expected=original,
            measurements=False,
        )
    assert clients[1].request("get_shipping", key=key) == original
    with host.db.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0


def test_pairing_identity_disconnect_and_input_boundaries(host, clients):
    address = f"127.0.0.1:{host.port}"
    with pytest.raises(network.NetworkError, match="Pairing code"):
        network.Client(address, f"{(int(host.code) + 1) % 1_000_000:06d}").snapshot()
    with pytest.raises(network.Conflict, match="different host"):
        network.Client(address, host.code, identity=uuid4().hex).snapshot()
    with pytest.raises(network.NetworkError):
        clients[0].request("photo", hash="../../config.json")
    for address in [
        "8.8.8.8",
        "https://127.0.0.1",
        "http://user:password@127.0.0.1",
        "127.0.0.1/evil",
        "example.com",
    ]:
        with pytest.raises(ValueError):
            network.endpoint(address)
    host.close()
    # Prevent the fixture from stopping the same host twice.
    host.close = lambda: None
    # Without a copy on this computer there is nothing to work from.
    stranger = network.Client(
        f"127.0.0.1:{host.port}",
        host.code,
        identity=host.db.identity,
        cache=clients[0].cache.parent / "never-connected",
    )
    with pytest.raises(network.Unavailable, match="unavailable"):
        stranger.snapshot()
    # A client that connected before keeps working from its saved copy.
    snapshot = clients[0].snapshot()
    assert clients[0].offline
    assert snapshot["identity"] == host.db.identity
    assert "41000" in snapshot["auctions"]
    with pytest.raises(network.Unavailable, match="Not connected to the host"):
        clients[0].request("recovery_list")


def test_udp_find_host_without_exposing_pairing_code(config):
    host = network.Host(
        config, network.new_code(), port=0, bind="127.0.0.1", discovery=True
    )
    try:
        found = network.find_hosts(0.4, destinations=["127.0.0.1"])
        assert len(found) == 1
        assert found[0]["identity"] == host.db.identity
        assert found[0]["address"] == f"http://127.0.0.1:{host.port}"
        assert host.code not in json.dumps(found)
    finally:
        host.close()


def test_corrupt_source_aborts_import_without_marking_migrated(config):
    path = excel.auction_path(config.auctions_dir, 42000)
    path.write_bytes(b"broken excel")
    with pytest.raises(catalogue.CatalogueReadError):
        network.Database(config)
    assert path.read_bytes() == b"broken excel"
    path.unlink()
    db = network.Database(config)
    with db.transaction() as conn:
        assert len(db.snapshot(conn)["auctions"]) == 1


def test_sharing_settings_roundtrip_and_invalid_modes(tmp_path):
    path = tmp_path / "config.json"
    settings = network.Sharing(
        "join", "192.168.1.20", network.PORT, network.new_code(), uuid4().hex
    )
    Config(base_dir=tmp_path, sharing=settings).save(path)
    assert Config.load(path).sharing == settings
    from simple_auction.services.config import ConfigFileError

    for mode in ["unknown", 42]:
        path.write_text(json.dumps({"sharing": {"mode": mode}}))
        with pytest.raises(ConfigFileError):
            Config.load(path)


def test_corrupt_database_is_reported_without_overwriting(tmp_path):
    config = Config(base_dir=tmp_path, photos_dir=tmp_path / "photos")
    path = config.data_dir / "shared.sqlite3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"broken database")
    with pytest.raises(network.NetworkError, match="will not switch"):
        network.Database(config)
    assert path.read_bytes() == b"broken database"


def test_six_digit_codes_preserve_leading_zeros_and_legacy_pairings(
    config, tmp_path, monkeypatch
):
    monkeypatch.setattr(network.secrets, "randbelow", lambda limit: 42)
    assert network.new_code() == "000042"
    for code in ["12345", "1234567", "123abc", "１２３４５６"]:
        with pytest.raises(ValueError):
            network.Sharing(mode="host", code=code).validate()
    legacy = "saved-code-from-the-previous-version"
    config.sharing = network.Sharing(mode="host", code=legacy)
    path = tmp_path / "saved-config.json"
    config.save(path)
    with_host = network.Host(
        Config.load(path), legacy, port=0, bind="127.0.0.1", discovery=False
    )
    try:
        short = network.pairing_code(legacy)
        assert len(short) == 6 and short.isascii() and short.isdigit()
        address = f"127.0.0.1:{with_host.port}"
        assert (
            network.Client(address, legacy).snapshot()["identity"]
            == with_host.db.identity
        )
        assert (
            network.Client(address, short).snapshot()["identity"]
            == with_host.db.identity
        )
        assert Config.load(path).sharing.code == legacy
    finally:
        with_host.close()


def test_short_code_limits_incorrect_attempts_and_recovers(host):
    client = network.Client(f"127.0.0.1:{host.port}", "wrong-pairing-code")
    for _ in range(12):
        with pytest.raises(network.NetworkError, match="Pairing code"):
            client.snapshot()
    with pytest.raises(network.NetworkError, match="Too many incorrect"):
        client.snapshot()
    client.code = host.code
    with pytest.raises(network.NetworkError, match="Too many incorrect"):
        client.snapshot()
    with host._auth_lock:
        host._auth_failures = network.deque(
            (stamp - 61, peer) for stamp, peer in host._auth_failures
        )
    assert client.snapshot()["identity"] == host.db.identity


def test_oversized_shared_photos_are_fixed_when_the_database_opens(config):
    import os

    from simple_auction.constants import PHOTO_MAX_BYTES
    from simple_auction.services import image

    db = network.Database(config)
    buf = io.BytesIO()
    big = Image.frombytes("RGB", (2400, 1800), os.urandom(2400 * 1800 * 3))
    big.save(buf, "JPEG", quality=95)
    old = db.store_photo(buf.getvalue())
    good = db.store_photo(image.conform(Image.new("RGB", (400, 300), "blue")))
    with db.transaction() as conn:
        key = "41000/41000"
        record = db.get(conn, "lot", key)
        db.put(conn, "lot", key, {**record, "photos": [old, good]})

    reopened = network.Database(config)

    with reopened.transaction() as conn:
        first, second = reopened.get(conn, "lot", key)["photos"]
    assert first != old
    assert second == good  # already compliant: same photo, same hash
    fixed = reopened.asset(first)
    assert fixed.stat().st_size <= PHOTO_MAX_BYTES
    with Image.open(fixed) as img:
        assert img.width <= 1024 and img.height <= 768
    assert reopened.asset(old).is_file()  # the old copy stays for stale clients
    again = network.Database(config)  # a second pass changes nothing
    with again.transaction() as conn:
        assert again.get(conn, "lot", key)["photos"] == [first, second]


def lots_of(client, auction):
    return {v["lot_number"]: v for v in client.snapshot()["auctions"][str(auction)]}


def test_offline_edits_are_kept_and_sync_through_host_checks(
    config, host, clients, tmp_path
):
    a, b = clients
    photo = tmp_path / "offline.png"
    Image.new("RGB", (160, 120), "green").save(photo)
    a.offline = True  # the host is out of reach
    original = record(a)
    lot = a.materialize(original)
    lot.title, lot.photos = "Edited offline", [photo]
    saved = a.commit_lot(41000, lot, original)
    assert saved["title"] == "Edited offline" and len(saved["photos"]) == 1
    created = a.new_lot(41000, config.step)
    assert created["lot_number"] == 41001
    auction = a.new_auction(config.step)
    first = a.new_lot(auction, config.step)
    first_lot = a.materialize(first)
    first_lot.title = "In a new auction"
    a.commit_lot(auction, first_lot, first)
    # Browsing offline shows the queued edits, photos included.
    view = a.snapshot()
    assert view["pending"] == 5
    assert lots_of(a, 41000)[41000]["title"] == "Edited offline"
    assert a.materialize(lots_of(a, 41000)[41000]).photos[0].is_file()
    assert lots_of(a, auction)[first["lot_number"]]["title"] == "In a new auction"
    # A restarted app reads the same queue from disk.
    restarted = network.Client(a.address, a.code, identity=a.identity, cache=a.cache)
    restarted.offline = True
    assert restarted.snapshot() == view

    # Meanwhile, others took the numbers this computer picked.
    taken_lot = b.request("new_lot", auction=41000)["lot_number"]
    taken_auction = b.request("new_auction")
    assert (taken_lot, taken_auction) == (41001, auction)

    a.offline = False
    result = a.sync()
    assert result["conflicts"] == []
    assert result["synced"] == 5
    new_auction = result["auctions"][auction]
    assert new_auction != auction
    assert result["lots"][(41000, 41001)] == (41000, 41002)
    assert result["lots"][(auction, first["lot_number"])] == (new_auction, new_auction)
    host_lots = lots_of(b, 41000)
    assert host_lots[41000]["title"] == "Edited offline"
    assert b.materialize(host_lots[41000]).photos[0].read_bytes()
    assert set(host_lots) == {41000, 41001, 41002}
    assert lots_of(b, new_auction)[new_auction]["title"] == "In a new auction"
    assert lots_of(b, taken_auction) == {}  # the other computer's auction untouched
    assert a.pending() == 0 and a.sync()["synced"] == 0


def test_output_counted_offline_syncs_under_the_numbers_the_host_assigned(
    config, host, clients, tmp_path
):
    a, b = clients
    log = output.OutputLog(tmp_path / "output.json")
    a.history = log.rows
    earlier = datetime(2026, 1, 2, 10, 0).astimezone()
    a.offline = True
    created = a.new_lot(41000, config.step)
    lot = a.materialize(created)
    lot.title, lot.condition, lot.make = "Filled offline", "Good", "Maker"
    a.commit_lot(41000, lot, created)
    log.track(lot, 41000, now=earlier)
    assert log.count_on(earlier.date()) == 1  # counted while offline

    # Another computer takes 41001 and fills it in meanwhile.
    theirs = b.request("new_lot", auction=41000)
    filled = b.materialize(theirs)
    filled.title, filled.condition, filled.make = "Theirs", "Fair", "Other"
    b.save_lot(41000, filled, theirs)

    a.offline = False
    probe = a.snapshot()
    assert probe["pending"] == 2  # history waits for the queued edits
    assert a.sync()["lots"][(41000, 41001)] == (41000, 41002)
    synced = a.snapshot()
    assert "pending" not in synced
    info = {(r["auction"], r["lot"]): r["at"] for r in synced["output"]["info"]}
    # Kept with the day it was counted, under the host's number, and never
    # credited to the other computer's lot that had the offline number.
    assert datetime.fromisoformat(info[(41000, 41002)]) == earlier
    assert datetime.fromisoformat(info[(41000, 41001)]) != earlier
    assert not (a.store().folder / "history-renumbered.json").exists()


def test_offline_edit_refused_on_host_is_kept_and_does_not_block_queue(
    config, host, clients
):
    a, b = clients
    original = record(a)
    a.offline = True
    mine = a.materialize(original)
    mine.title = "Mine"
    a.commit_lot(41000, mine, original)
    a.new_lot(41000, config.step)
    theirs = b.materialize(original)
    theirs.title = "Theirs"
    b.save_lot(41000, theirs, original)
    a.offline = False
    result = a.sync()
    assert record(b)["title"] == "Theirs"  # never overwritten
    [kept] = result["conflicts"]
    edit = json.loads((kept / "edit.json").read_text())
    assert edit["lot"]["title"] == "Mine" and "Someone else changed" in edit["error"]
    assert 41001 in lots_of(b, 41000)  # later edits still synced
    assert a.pending() == 0


def test_replayed_creation_after_lost_response_is_not_duplicated(host, clients):
    a, _ = clients
    first = a.request("new_lot", auction=41000, number=41005, request="lost-1")
    again = a.request("new_lot", auction=41000, number=41005, request="lost-1")
    assert first == again and first["lot_number"] == 41005
    assert sorted(lots_of(a, 41000)) == [41000, 41005]
    auction = a.request("new_auction", number=50000, request="lost-2")
    assert a.request("new_auction", number=50000, request="lost-2") == auction == 50000
    assert list(a.snapshot()["auctions"]).count("50000") == 1
    with pytest.raises(network.NetworkError):
        a.request("new_lot", auction=41000, request="../bad")


def test_local_auctions_missing_from_shared_catalogue_are_found_and_copied(
    config, host, clients
):
    from simple_auction.services.lot_details import details_path

    a, _ = clients
    # Workbooks made after the one-time import, or a joining computer's own.
    for auction in (52000, 53000):
        path = excel.auction_path(config.auctions_dir, auction)
        excel.create_auction(path)
        catalogue.add(
            path,
            details_path(config.data_dir, auction),
            [Lot(auction, title=f"Local {auction}")],
        )
    photos = config.auction_photos_dir(52000)
    photos.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (160, 120), "blue").save(photos / "52000.jpg")
    assert set(network.unshared_auctions(config, a.snapshot())) == {52000, 53000}
    # An auction deleted from the shared catalogue after its workbook last
    # changed stays deleted.
    a.request("import_lots", auction=53000, lots=[])
    expected = a.snapshot()["auctions"]["53000"]
    a.request("delete", auction=53000, expected=expected, numbers=None)
    deletions = a.request("recovery_list")
    found = network.unshared_auctions(config, a.snapshot(), deletions)
    assert set(found) == {52000}

    assert network.copy_local_auction(a, config, 52000) == 1
    [copied] = a.snapshot()["auctions"]["52000"]
    assert copied["title"] == "Local 52000" and len(copied["photos"]) == 1
    assert network.unshared_auctions(config, a.snapshot(), deletions) == {}
    # Copying again leaves the shared version alone.
    assert network.copy_local_auction(a, config, 52000) == 0
