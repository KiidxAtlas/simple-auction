import csv
import io
import json

import pytest

from simple_auction.services import shipping, storage

HEADERS = [
    "Bidder Number",
    "First Name",
    "Last Name",
    "Email",
    "Shipping Address",
    "Shipping City",
    "Shipping State",
    "Shipping Zip",
    "Lot Number",
    "Lot Title",
]
ROWS = [
    [
        "0042",
        "Jane",
        "Doe",
        "jane@example.test",
        "12 Main St",
        "Boston",
        "MA",
        "02108",
        "12A",
        "Vase, blue",
    ],
    [
        "0042",
        "Jane",
        "Doe",
        "jane@example.test",
        "12 Main St",
        "Boston",
        "MA",
        "02108",
        "45",
        "Clock",
    ],
    [
        "0050",
        "Sam",
        "Doe",
        "sam@example.test",
        "18 First St",
        "Boston",
        "MA",
        "02108",
        "78",
        "Chair",
    ],
]


@pytest.fixture
def report(tmp_path):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Auction October 9"])
    writer.writerow(HEADERS)
    writer.writerows(ROWS)
    path = tmp_path / "auction.csv"
    path.write_text(stream.getvalue(), encoding="utf-8-sig")
    return path


@pytest.fixture
def batch(report):
    sheet = shipping.read_report(report)
    return shipping.build_batch(
        sheet, shipping.guess_mapping(sheet.headers), "October 9", report.name, "US"
    )


def pack(package):
    package.weight_oz = 32.5
    package.length, package.width, package.height = 12, 8, 6
    package.packed = True


def test_csv_import_groups_by_bidder_preserves_ids_lots_and_postal_codes(batch):
    assert len(batch.buyers) == 2
    jane = batch.buyers[0]
    assert jane.id == "0042"
    assert jane.name == "Jane Doe"
    assert jane.zip == "02108"
    assert jane.country == "US"
    assert jane.lots == {"12A": "Vase, blue", "45": "Clock"}
    assert jane.packages[0].lots == ["12A", "45"]


def test_shipping_columns_take_precedence_over_generic_address_columns():
    mapping = shipping.guess_mapping(
        ["Address", "City", "Zip", "Shipping Address", "Shipping City", "Shipping Zip"]
    )
    assert (mapping["address1"], mapping["city"], mapping["zip"]) == (3, 4, 5)


def test_duplicate_rows_dont_create_duplicate_lots_and_email_can_identify_buyers(
    report,
):
    sheet = shipping.read_report(report)
    sheet.rows.append(sheet.rows[0])
    mapping = shipping.guess_mapping(sheet.headers)
    mapping["buyer_id"] = None
    batch = shipping.build_batch(sheet, mapping, "Auction 1", "source.csv", "US")
    assert len(batch.buyers) == 2
    assert batch.buyers[0].id == "jane@example.test"
    assert len(batch.buyers[0].lots) == 2


@pytest.mark.parametrize(
    "column,value,message",
    [
        (4, "99 Other St", "conflicting"),
        (0, "0050", "conflicting"),
        (8, "78", "more than one buyer"),
        (0, "", None),
    ],
)
def test_import_rejects_conflicts_without_partial_success(
    report, column, value, message
):
    sheet = shipping.read_report(report)
    sheet.rows[1][column] = value
    if message is None:
        sheet.rows[1][3] = ""  # no bidder ID or fallback email
        message = "missing buyer"
    with pytest.raises(shipping.ShippingError, match=message):
        shipping.build_batch(
            sheet, shipping.guess_mapping(sheet.headers), "auction", "file.csv", "US"
        )


def test_incomplete_address_blocks_export_but_can_be_corrected(batch):
    buyer = batch.buyers[0]
    buyer.zip = ""
    pack(buyer.packages[0])
    assert not shipping.ready_packages(batch)
    assert "postal code" in " ".join(shipping.problems(buyer, buyer.packages[0]))
    buyer.zip = "02108"
    assert len(shipping.ready_packages(batch)) == 1


def test_split_export_one_row_per_box_excludes_pickups_and_remembers_export(
    batch, tmp_path
):
    buyer = batch.buyers[0]
    buyer.packages[0].lots = ["12A"]
    buyer.packages.append(shipping.Package(lots=["45"]))
    for package in buyer.packages:
        pack(package)
    batch.buyers[1].pickup = True
    pack(batch.buyers[1].packages[0])
    progress = shipping.batch_path(tmp_path / "shipping", batch.auction)
    shipping.save_batch(progress, batch)
    output = tmp_path / "pirate-ship.csv"
    updated = shipping.export_batch(batch, progress, output)
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(row["Name"] == "Jane Doe" and row["Zip"] == "02108" for row in rows)
    assert rows[0]["Weight (Pounds)"] == "2.03125"
    assert rows[0]["Order ID"] != rows[1]["Order ID"]
    assert not buyer.packages[0].exported_at  # original unchanged on failure or success
    loaded = shipping.load_batch(progress)
    assert loaded == updated
    assert not shipping.ready_packages(loaded)
    assert all(p.exported_file == str(output) for p in loaded.buyers[0].packages)
    with pytest.raises(shipping.ShippingError, match="No new"):
        shipping.export_batch(loaded, progress, tmp_path / "second.csv")


def test_partial_export_leaves_unpacked_boxes_for_next_export(batch, tmp_path):
    pack(batch.buyers[0].packages[0])
    progress = shipping.batch_path(tmp_path, batch.auction)
    shipping.save_batch(progress, batch)
    updated = shipping.export_batch(batch, progress, tmp_path / "first.csv")
    pack(updated.buyers[1].packages[0])
    shipping.save_batch(progress, updated)
    second = tmp_path / "second.csv"
    shipping.export_batch(updated, progress, second)
    rows = list(csv.DictReader(io.StringIO(second.read_text(encoding="utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["Name"] == "Sam Doe"


def test_lot_missing_from_plan_and_duplicate_assignments_block_ready(batch):
    buyer = batch.buyers[0]
    pack(buyer.packages[0])
    buyer.packages[0].lots.remove("45")
    assert not shipping.ready_packages(batch)
    buyer.packages.append(shipping.Package(lots=["12A", "45"]))
    pack(buyer.packages[1])
    assert not shipping.ready_packages(batch)


@pytest.mark.parametrize("include_measurements", [False, True])
def test_csv_and_export_ledger_roll_back_together_on_progress_write_failure(
    batch, tmp_path, monkeypatch, include_measurements
):
    pack(batch.buyers[0].packages[0])
    progress = shipping.batch_path(tmp_path, batch.auction)
    shipping.save_batch(progress, batch)
    before = progress.read_bytes()
    output = tmp_path / "labels.csv"
    real_write = storage.atomic_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if path == progress and not failed:
            failed = True
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(storage, "atomic_write", fail_once)
    with pytest.raises(OSError, match="disk full"):
        shipping.export_batch(
            batch, progress, output, include_measurements=include_measurements
        )
    assert progress.read_bytes() == before
    assert not output.exists()
    assert len(shipping.ready_packages(batch)) == 1


def test_stale_batch_cannot_reexport_and_existing_csv_is_preserved(batch, tmp_path):
    pack(batch.buyers[0].packages[0])
    progress = shipping.batch_path(tmp_path, batch.auction)
    shipping.save_batch(progress, batch)
    output = tmp_path / "old.csv"
    output.write_text("keep me")
    with pytest.raises(shipping.ShippingError, match="new CSV filename"):
        shipping.export_batch(batch, progress, output)
    assert output.read_text() == "keep me"
    shipping.export_batch(batch, progress, tmp_path / "new.csv")
    with pytest.raises(shipping.ShippingError, match="changed on disk"):
        shipping.export_batch(batch, progress, tmp_path / "stale.csv")


@pytest.mark.parametrize("raw", [b"broken json", b"{}", b'{"version": 2}', b"[]"])
def test_bad_progress_is_reported_and_never_overwritten(batch, tmp_path, raw):
    progress = tmp_path / "batch.json"
    progress.write_bytes(raw)
    with pytest.raises(shipping.ShippingError, match="left unchanged"):
        shipping.save_batch(progress, batch)
    assert progress.read_bytes() == raw


def test_invalid_stored_measurements_and_country_fail_safely(batch):
    data = json.loads(shipping.encode(batch))
    data["buyers"][0]["packages"][0]["weight_oz"] = "bad weight"
    with pytest.raises(shipping.ShippingError, match="invalid package"):
        shipping.decode(json.dumps(data).encode())
    buyer = batch.buyers[0]
    pack(buyer.packages[0])
    buyer.country = "USA"
    assert not shipping.ready_packages(batch)


def test_empty_and_malformed_csv_have_useful_errors(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("")
    with pytest.raises(shipping.ShippingError, match="empty"):
        shipping.read_report(path)
    path.write_text('Name,Address\n"unterminated')
    with pytest.raises(shipping.ShippingError, match="Cannot read"):
        shipping.read_report(path)


def test_address_export_needs_no_packing_and_omits_measurement_columns(batch, tmp_path):
    assert not shipping.ready_packages(batch)
    assert len(shipping.ready_packages(batch, include_measurements=False)) == 2
    progress = shipping.batch_path(tmp_path, batch.auction)
    shipping.save_batch(progress, batch)
    output = tmp_path / "addresses.csv"
    updated = shipping.export_batch(batch, progress, output, include_measurements=False)
    rows = list(csv.DictReader(io.StringIO(output.read_text(encoding="utf-8-sig"))))
    assert len(rows) == 2
    assert rows[0]["Zip"] == "02108"
    assert set(rows[0]) == set(shipping.CSV_HEADERS[:8] + ["Order ID"])
    assert not shipping.ready_packages(updated, include_measurements=False)
    assert shipping.load_batch(progress) == updated
    assert all(not p.packed for b in updated.buyers for p in b.packages)
    with pytest.raises(shipping.ShippingError, match="No new"):
        shipping.export_batch(
            updated, progress, tmp_path / "again.csv", include_measurements=False
        )


def test_address_export_excludes_pickup_and_invalid_addresses(batch):
    batch.buyers[0].pickup = True
    assert len(shipping.ready_packages(batch, include_measurements=False)) == 1
    batch.buyers[1].zip = ""
    assert not shipping.ready_packages(batch, include_measurements=False)
    assert "postal code" in " ".join(
        shipping.problems(
            batch.buyers[1], batch.buyers[1].packages[0], include_measurements=False
        )
    )
