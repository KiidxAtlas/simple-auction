import base64
import json
import socket

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_network import batch

from simple_auction.services import network, shipping
from simple_auction.services.config import Config
from simple_auction.ui import main_page
from simple_auction.ui.settings import SettingsDialog


@pytest.fixture
def app(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    monkeypatch.setattr(main_page.api_key, "saved", lambda: None)
    return app


@pytest.fixture
def host(app, tmp_path):
    cfg = Config(base_dir=tmp_path / "host", photos_dir=tmp_path / "hostphotos")
    host = network.Host(
        cfg, network.new_code(), port=0, bind="127.0.0.1", discovery=False
    )
    yield host
    host.close()


@pytest.fixture
def windows(app, host, tmp_path):
    windows = []
    for i in range(2):
        settings = network.Sharing(
            "join", f"127.0.0.1:{host.port}", network.PORT, host.code, host.db.identity
        )
        cfg = Config(
            base_dir=tmp_path / f"client{i}",
            photos_dir=tmp_path / f"pics{i}",
            sharing=settings,
        )
        page = main_page.MainPage(cfg)
        page._ui_state = QSettings(
            str(tmp_path / f"window{i}.ini"), QSettings.Format.IniFormat
        )
        page._network_timer.stop()
        page.show()
        windows.append(page)
    app.processEvents()
    yield windows
    for page in windows:
        page._autosave.stop()
        page.shipping._save_timer.stop()
        page.form._dirty = False
        page.shipping.dirty = False
        page.close()
        page.deleteLater()
    app.processEvents()


def poll(window):
    window._poll_shared()
    worker = window._poll_worker
    assert worker is not None
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(8000, loop.quit)
    loop.exec()
    QApplication.instance().processEvents()
    assert window._poll_worker is None


def test_two_windows_share_create_edit_photos_and_excel(windows, tmp_path, monkeypatch):
    a, b = windows
    a.create_auction()
    a.form.title.setText("Shared title")
    source = tmp_path / "new.png"
    Image.new("RGB", (160, 120), "blue").save(source)
    a.form._photos = [source]
    assert a.flush()
    poll(b)
    b.open_lot(a.auction_no, a.lot_no)
    assert b.form.title.text() == "Shared title"
    assert len(b.form.collect().photos) == 1
    with Image.open(b.form.collect().photos[0]) as img:
        assert img.format == "JPEG"
    b.form.owner.setText("Other person")
    assert b.flush()
    poll(a)
    assert a.form.owner.text() == "Other person"
    output = tmp_path / "export.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    a.export_auction(a.auction_no)
    from simple_auction.services.excel import load_auction

    lots = load_auction(output)
    assert lots[0].owner == "Other person" and lots[0].title == "Shared title"


def test_conflicting_draft_is_retained_and_explicit_reload_resolves(
    windows, monkeypatch
):
    a, b = windows
    a.create_auction()
    poll(b)
    b.open_lot(a.auction_no, a.lot_no)
    a.form.title.setText("Alice")
    b.form.title.setText("Bob draft")
    assert a.flush()
    assert not b.flush()
    poll(b)
    assert b.form.title.text() == "Bob draft" and b.form.is_dirty()
    assert "your edits kept" in b.network_status.text()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    b.reload_shared()
    assert b.form.title.text() == "Alice" and not b.form.is_dirty()


def test_shipping_ui_merges_updates_and_recovers_failed_download(
    windows, tmp_path, monkeypatch
):
    a, b = windows
    initial = network.batch_data(batch())
    key = network.shipping_key(initial["auction"])
    a.client.request("save_shipping", key=key, batch=initial, expected=None)
    for window in windows:
        assert window.shipping.activate()
        window.shipping.buyers.setCurrentCell(0 if window is a else 1, 0)
    a.shipping.measurements["weight_lb"].setText("2.5")
    b.shipping.measurements["weight_lb"].setText("3")
    assert a.shipping.flush() and b.shipping.flush()
    poll(a)
    assert [v.packages[0].weight_oz for v in a.shipping.batch.buyers] == [40, 48]
    for window in windows:
        for key in ("length", "width", "height"):
            window.shipping.measurements[key].setText("10")
        window.shipping.ready_next.click()
        assert window.shipping.flush()
    poll(a)
    output = tmp_path / "ship.csv"
    actual_write = main_page.storage.atomic_write

    def fail_output(path, data):
        if path == output:
            raise OSError("disk full")
        return actual_write(path, data)

    monkeypatch.setattr(main_page.storage, "atomic_write", fail_output)
    with pytest.raises(shipping.ShippingError, match="host saved"):
        a.shipping._export_batch(output, True)
    assert a.shipping._pending_export_path().exists()
    poll(a)
    assert "Recover" in a.shipping.export_button.text()
    monkeypatch.setattr(main_page.storage, "atomic_write", actual_write)
    saved = a.shipping._export_batch(output, True)
    assert output.is_file() and not a.shipping._pending_export_path().exists()
    assert all(p.exported_at for buyer in saved.buyers for p in buyer.packages)
    poll(b)
    assert not b.shipping._ready()
    export = b.shipping._last_export()
    raw = b.client.request(
        "download_export", id=export.exported_file.removeprefix("shared:")
    )
    assert base64.b64decode(raw) == output.read_bytes()


def test_settings_host_toggle_and_real_pairing_test(app, host, tmp_path):
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    app.processEvents()
    widget = dialog.network
    assert not widget.enabled.isChecked()
    widget.enabled.setChecked(True)
    widget.host_toggle.setChecked(True)
    assert widget.host_panel.isVisible() and not widget.join_panel.isVisible()
    settings = widget.value()
    assert (
        settings.mode == "host"
        and len(settings.code) == 6
        and settings.code.isascii()
        and settings.code.isdigit()
    )
    widget.host_toggle.setChecked(False)
    widget.address.setText(f"127.0.0.1:{host.port}")
    widget.code.setText(host.code)
    widget.test_connection()
    assert "Connected" in widget.status.text()
    assert widget.value().share_id == host.db.identity
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_saving_host_settings_starts_server_and_switching_off_stops_it(
    app, tmp_path, monkeypatch
):
    path = tmp_path / "config.json"
    save = Config.save
    monkeypatch.setattr(Config, "save", lambda self: save(self, path))
    actual_host = network.Host
    monkeypatch.setattr(
        network,
        "Host",
        lambda config, code, port: actual_host(
            config, code, port, bind="127.0.0.1", discovery=False
        ),
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    page = main_page.MainPage(
        Config(base_dir=tmp_path / "data", photos_dir=tmp_path / "pics")
    )
    page._ui_state = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)

    def host_settings(dialog):
        dialog.network.enabled.setChecked(True)
        dialog.network.host_toggle.setChecked(True)
        dialog.network.port.setText(str(port))
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", host_settings)
    page.open_settings()
    assert page.host and page.client.snapshot()["identity"] == page.host.db.identity
    page.create_auction()
    saved = Config.load(path)
    identity = page.host.db.identity
    code = saved.sharing.code
    assert saved.sharing.mode == "host"
    page.close()
    page.deleteLater()
    app.processEvents()
    # Reopening after an app update or power cycle restores hosting without Settings.
    page = main_page.MainPage(Config.load(path))
    page._ui_state = QSettings(
        str(tmp_path / "reopened.ini"), QSettings.Format.IniFormat
    )
    assert page.host and page.host.code == code
    assert page.host.db.identity == identity
    assert len(page.client.snapshot()["auctions"]) == 1

    def disable(dialog):
        dialog.network.enabled.setChecked(False)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", disable)
    page.open_settings()
    assert page.host is None and isinstance(page.client, network.LocalClient)
    assert len(page.client.snapshot()["auctions"]) == 1
    assert Config.load(path).sharing.mode == "off"
    page.close()
    page.deleteLater()
    app.processEvents()


def test_disconnected_client_can_open_settings_and_keep_unsaved_draft(
    windows, monkeypatch
):
    a, b = windows
    a.create_auction()
    poll(b)
    b.open_lot(a.auction_no, a.lot_no)
    b.form.title.setText("Keep this draft")
    original_request = b.client.request

    def offline(*args, **kwargs):
        raise network.NetworkError("host unavailable")

    monkeypatch.setattr(b.client, "request", offline)
    assert not b.flush()

    def save_settings(dialog):
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", save_settings)
    save = Config.save
    monkeypatch.setattr(
        Config, "save", lambda self: save(self, self.base_dir / "config.json")
    )
    b.open_settings()
    assert b.form.title.text() == "Keep this draft"
    assert b.form.is_dirty()
    backups = list((b.config.data_dir / "shared-drafts").glob("*.json"))
    assert (
        backups
        and json.loads(backups[-1].read_text())["lot"]["title"] == "Keep this draft"
    )
    monkeypatch.setattr(b.client, "request", original_request)
    assert b.flush()


def test_pending_export_can_be_recovered_after_restarting_shipping_page(
    windows, tmp_path, monkeypatch
):
    a, _ = windows
    data = network.batch_data(batch())
    key = network.shipping_key(data["auction"])
    a.client.request("save_shipping", key=key, batch=data, expected=None)
    page = a.shipping
    page.activate()
    actual_request = a.client.request
    dropped = False

    def lose_response(op, **args):
        nonlocal dropped
        result = actual_request(op, **args)
        if op == "export_shipping" and not dropped:
            dropped = True
            raise network.NetworkError("Lost export response")
        return result

    monkeypatch.setattr(a.client, "request", lose_response)
    with pytest.raises(network.NetworkError):
        page._export_batch(tmp_path / "lost.csv", False)
    monkeypatch.setattr(a.client, "request", actual_request)
    restarted = main_page.ShippingPage(page.folder)
    restarted.set_connection(a.client, True)
    try:
        assert restarted.activate()
        assert not restarted._ready()
        assert restarted.export_button.isEnabled()
        assert "Recover" in restarted.export_button.text()
        recovered = restarted._export_batch(tmp_path / "recovered.csv", False)
        assert all(p.exported_at for b in recovered.buyers for p in b.packages)
        assert (tmp_path / "recovered.csv").exists()
        assert not restarted._pending_export_path().exists()
    finally:
        restarted.deleteLater()
        QApplication.instance().processEvents()


@pytest.mark.parametrize("mode", ["host", "join"])
def test_legacy_pairing_is_displayed_as_six_digits_without_forgetting_it(
    app, tmp_path, mode
):
    legacy = "saved-code-from-the-previous-version"
    settings = network.Sharing(mode, "127.0.0.1", network.PORT, legacy)
    dialog = SettingsDialog(Config(base_dir=tmp_path, sharing=settings), [])
    try:
        field = dialog.network.host_code if mode == "host" else dialog.network.code
        assert field.text() == network.pairing_code(legacy)
        assert len(field.text()) == 6
        assert dialog.sharing().code == legacy
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_saved_client_reconnects_when_host_returns_at_new_address(
    app, tmp_path, monkeypatch
):
    save = Config.save
    monkeypatch.setattr(
        Config, "save", lambda self: save(self, self.base_dir / "config.json")
    )
    find_hosts = network.find_hosts
    monkeypatch.setattr(
        network,
        "find_hosts",
        lambda timeout=1.5: find_hosts(timeout, destinations=["127.0.0.1"]),
    )
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    cfg = Config(base_dir=tmp_path / "host", photos_dir=tmp_path / "host-pics")
    original = network.Host(cfg, "000042", port=0, bind="127.0.0.1", discovery=False)
    old_port = original.port
    identity = original.db.identity
    original.close()
    joining = Config(
        base_dir=tmp_path / "client",
        photos_dir=tmp_path / "client-pics",
        sharing=network.Sharing(
            "join", f"127.0.0.1:{old_port}", network.PORT, "000042", identity
        ),
    )
    joining.save()
    path = joining.base_dir / "config.json"
    page = main_page.MainPage(Config.load(path))
    page._ui_state = QSettings(str(tmp_path / "client.ini"), QSettings.Format.IniFormat)
    page._network_timer.stop()
    moved = stranger = reopened = None
    try:
        assert (
            warnings == []
        )  # A saved connection waits quietly for a late-starting host.
        assert Config.load(path).sharing == joining.sharing
        # Another computer can occupy the old address after DHCP changes. Its
        # database must never be adopted, even if it happens to use the same PIN.
        stranger_cfg = Config(
            base_dir=tmp_path / "stranger", photos_dir=tmp_path / "stranger-pics"
        )
        stranger = network.Host(
            stranger_cfg, "000042", port=old_port, bind="127.0.0.1", discovery=False
        )
        moved = network.Host(cfg, "000042", port=0, bind="127.0.0.1", discovery=True)
        moved.db.dispatch("new_auction", {})
        page.client._next_discovery = (
            0  # Avoid waiting for the offline discovery cooldown in this test.
        )
        poll(page)
        address = f"http://127.0.0.1:{moved.port}"
        assert page.client.address == address
        assert page.client.identity == identity != stranger.db.identity
        assert "Connected" in page.network_status.text()
        saved = Config.load(path).sharing
        assert (saved.address, saved.code, saved.share_id) == (
            address,
            "000042",
            identity,
        )
        assert len(page._shared_snapshot["auctions"]) == 1
        page.close()
        page.deleteLater()
        app.processEvents()
        page = None
        reopened = main_page.MainPage(Config.load(path))
        reopened._ui_state = QSettings(
            str(tmp_path / "restarted.ini"), QSettings.Format.IniFormat
        )
        reopened._network_timer.stop()
        assert reopened.client.address == address
        assert reopened.client.identity == identity
        assert "Connected" in reopened.network_status.text()
        moved.close()
        poll(reopened)
        assert "Reconnecting automatically" in reopened.network_status.text()
        assert Config.load(path).sharing == saved
        assert warnings == []
    finally:
        for window in (page, reopened):
            if window is not None:
                window.close()
                window.deleteLater()
        if stranger:
            stranger.close()
        if moved:
            moved.close()
        app.processEvents()
