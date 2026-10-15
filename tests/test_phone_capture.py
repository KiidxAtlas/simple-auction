import http.client
import io
import socket
import time
from urllib.parse import urlsplit

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from simple_auction.services import phone_capture


def image_bytes(format="JPEG", size=(60, 40)):
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format)
    return output.getvalue()


@pytest.fixture
def session(tmp_path):
    capture = phone_capture.PhoneCaptureSession(41000, tmp_path, "127.0.0.1")
    capture.start()
    yield capture
    capture.stop()


def request(session, path=None, *, body=None, headers=None, method=None):
    url = urlsplit(session.url)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
    connection.request(
        method or ("POST" if body is not None else "GET"),
        path or url.path,
        body=body,
        headers=headers or {},
    )
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def upload(session, body=None, shot="overall", headers=None):
    return request(
        session,
        urlsplit(session.url).path + f"upload/?shot={shot}",
        body=image_bytes() if body is None else body,
        headers=headers or {"Content-Type": "image/jpeg"},
    )


def test_lot_page_is_self_contained_and_token_private(session):
    status, page, headers = request(session)
    assert status == 200
    assert b"Lot 41000" in page
    assert all(label.encode() in page for label in phone_capture.SHOTS.values())
    assert b"Nothing is sent until" in page
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert b"https://" not in page
    assert len(urlsplit(session.url).path.split("/")[1]) >= 40
    assert request(session, "/wrong/")[0] == 404
    assert request(session, "/../../etc/passwd")[0] == 404
    assert not session.photos


def test_preparation_orients_photo_and_strips_private_metadata():
    source = Image.new("RGB", (60, 40), "red")
    exif = Image.Exif()
    exif[274] = 6  # Native camera orientation.
    exif[315] = "Private photographer name"
    output = io.BytesIO()
    source.save(output, "JPEG", exif=exif)
    prepared = phone_capture.prepare_image(output.getvalue())
    with Image.open(io.BytesIO(prepared)) as image:
        assert image.size == (40, 60)
        assert not image.getexif()
    assert b"Private photographer" not in prepared


def test_animation_is_rejected():
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        output,
        "PNG",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
    )
    with pytest.raises(ValueError, match="still photo"):
        phone_capture.prepare_image(output.getvalue())


def test_session_capabilities_are_independent(session, tmp_path):
    other = phone_capture.PhoneCaptureSession(42000, tmp_path, "127.0.0.1")
    other.start()
    try:
        assert urlsplit(session.url).path != urlsplit(other.url).path
        assert request(other, urlsplit(session.url).path)[0] == 404
        assert b"Lot 42000" in request(other)[1]
    finally:
        other.stop()


def test_chunked_and_ambiguous_length_requests_rejected(session):
    url = urlsplit(session.url)
    for framing in [
        "Transfer-Encoding: chunked\r\nContent-Length: 1",
        "Content-Length: 1\r\nContent-Length: 1",
    ]:
        connection = socket.create_connection((url.hostname, url.port), timeout=3)
        try:
            connection.sendall(
                (
                    f"POST {url.path}upload/?shot=overall HTTP/1.1\r\n"
                    f"Host: {url.netloc}\r\nContent-Type: image/jpeg\r\n"
                    f"{framing}\r\n\r\nx"
                ).encode()
            )
            response = http.client.HTTPResponse(connection)
            response.begin()
            assert response.status == 400
            response.read()
        finally:
            connection.close()
    assert not session.photos


def test_upload_verifies_normalizes_and_freezes_lot(session, tmp_path):
    assert (
        upload(
            session,
            image_bytes("PNG"),
            "serial",
            {"Content-Type": "image/png", "X-Filename": "../../other.png"},
        )[0]
        == 201
    )
    assert session.lot_number == 41000
    with pytest.raises(AttributeError):
        session.lot_number = 999
    [photo] = session.photos
    assert photo.shot == "serial"
    assert photo.path.parent == tmp_path
    assert photo.path.suffix == ".jpg"
    with Image.open(photo.path) as image:
        assert image.format == "JPEG"
        assert image.size == (60, 40)
        assert not image.getexif()
    snapshot = session.photos
    snapshot.clear()
    assert len(session.photos) == 1
    session.stop()
    assert photo.path.exists()  # Lifetime belongs to caller, not listener.
    with pytest.raises((ConnectionError, OSError)):
        upload(session)


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "image/jpeg", "Origin": "https://attacker.example"},
        {"Content-Type": "image/jpeg", "Host": "attacker.example"},
        {"Content-Type": "image/jpeg", "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_foreign_origin_and_dns_rebinding_rejected(session, headers):
    assert upload(session, headers=headers)[0] == 403
    assert not session.photos


def test_rejects_invalid_images_types_shots_and_oversize(session, monkeypatch):
    assert upload(session, b"not an image")[0] == 422
    assert upload(session, image_bytes("GIF"))[0] == 422
    assert upload(session, headers={"Content-Type": "image/heic"})[0] == 415
    assert upload(session, shot="../../elsewhere")[0] == 400
    assert upload(session, shot="overall&lot=999")[0] == 400
    monkeypatch.setattr(phone_capture, "MAX_PIXELS", 10)
    assert upload(session)[0] == 422
    assert not session.photos
    assert (
        request(
            session,
            urlsplit(session.url).path + "upload/?shot=overall",
            method="POST",
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": str(phone_capture.MAX_IMAGE_BYTES + 1),
            },
        )[0]
        == 413
    )


def test_photo_count_and_total_budget_are_bounded(session, monkeypatch):
    monkeypatch.setattr(phone_capture, "MAX_SESSION_BYTES", 2)
    assert upload(session)[0] == 413
    monkeypatch.setattr(phone_capture, "MAX_SESSION_BYTES", 1024 * 1024)
    monkeypatch.setattr(phone_capture, "MAX_PHOTOS", 1)
    assert upload(session)[0] == 201
    assert upload(session)[0] == 413
    assert len(session.photos) == 1


def test_sessions_expire_and_cannot_restart(tmp_path):
    session = phone_capture.PhoneCaptureSession(
        41000, tmp_path, "127.0.0.1", lifetime=0.15
    )
    session.start()
    assert session.active
    time.sleep(0.4)
    assert not session.active
    assert session._thread is not None and not session._thread.is_alive()
    with pytest.raises(RuntimeError):
        session.start()
    session.stop()


def test_stop_interrupts_partial_upload(session):
    url = urlsplit(session.url)
    connection = socket.create_connection((url.hostname, url.port), timeout=3)
    connection.sendall(
        (
            f"POST {url.path}upload/?shot=overall HTTP/1.1\r\n"
            f"Host: {url.netloc}\r\nContent-Type: image/jpeg\r\n"
            "Content-Length: 100\r\n\r\nx"
        ).encode()
    )
    time.sleep(0.05)
    started = time.monotonic()
    session.stop()
    connection.close()
    assert time.monotonic() - started < 1
    assert not session._thread.is_alive()
    assert not session.photos


def test_expiry_interrupts_a_stalled_upload(tmp_path):
    capture = phone_capture.PhoneCaptureSession(
        41000, tmp_path, "127.0.0.1", lifetime=0.2
    )
    capture.start()
    url = urlsplit(capture.url)
    connection = socket.create_connection((url.hostname, url.port), timeout=3)
    connection.sendall(
        (
            f"POST {url.path}upload/?shot=overall HTTP/1.1\r\n"
            f"Host: {url.netloc}\r\nContent-Type: image/jpeg\r\n"
            "Content-Length: 100\r\n\r\nx"
        ).encode()
    )
    time.sleep(0.5)
    assert not capture.active
    assert not capture._thread.is_alive()
    assert not capture.photos
    connection.close()
    capture.stop()


@pytest.mark.parametrize("address", ["0.0.0.0", "8.8.8.8", "example.com", "::"])
def test_public_or_wildcard_bind_rejected(tmp_path, address):
    with pytest.raises(ValueError):
        phone_capture.PhoneCaptureSession(41000, tmp_path, address)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def make_dialog(monkeypatch):
    from simple_auction.ui import phone_capture_dialog

    monkeypatch.setattr(phone_capture_dialog, "local_addresses", lambda: ["127.0.0.1"])
    dialog = phone_capture_dialog.PhoneCaptureDialog(41000)
    dialog.show()
    assert dialog._session is None
    dialog.start_button.click()
    return dialog


def test_dialog_reviews_and_retains_only_accepted_photos(app, monkeypatch):
    dialog = make_dialog(monkeypatch)
    try:
        assert dialog._session is not None and dialog._session.active
        assert not dialog.add_button.isEnabled()
        assert not dialog.qr.pixmap().isNull()
        assert upload(dialog._session)[0] == 201
        assert upload(dialog._session, shot="serial")[0] == 201
        dialog._refresh()
        assert dialog.received.count() == 2
        discarded = dialog.received.item(1).data(Qt.ItemDataRole.UserRole)
        dialog.received.item(1).setCheckState(Qt.CheckState.Unchecked)
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert not dialog._session.active
        assert len(dialog.photos) == 1 and dialog.photos[0].exists()
        assert not discarded.exists()
        assert not dialog.link.text()
        retained = dialog.photos[0]
        dialog.cleanup_photos()
        assert not retained.exists()
        assert dialog.photos == []
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_dialog_reject_and_window_close_remove_received_files(app, monkeypatch):
    dialog = make_dialog(monkeypatch)
    assert upload(dialog._session)[0] == 201
    [photo] = dialog._session.photos
    dialog.close()
    assert not dialog._session.active
    assert not photo.path.exists()
    assert dialog.photos == []
    dialog.deleteLater()
    app.processEvents()


def test_dialog_without_private_network_is_actionable(app, monkeypatch):
    from simple_auction.ui import phone_capture_dialog

    monkeypatch.setattr(phone_capture_dialog, "local_addresses", list)
    dialog = phone_capture_dialog.PhoneCaptureDialog(41000)
    dialog.show()
    assert dialog._session is None
    assert not dialog.start_button.isEnabled()
    assert "No private LAN" in dialog.status.text()
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()
