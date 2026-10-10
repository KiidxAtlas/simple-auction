import base64
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from PIL import Image

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, network, shipping
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
    with pytest.raises(network.NetworkError, match="unavailable"):
        clients[0].snapshot()


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
