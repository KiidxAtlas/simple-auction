"""Short-lived, private-LAN-only phone intake. No catalogue files are changed.

The caller owns the dedicated temporary directory and must retain it until the
accepted photos have been saved. Each session serves only its own inline page
and accepts bounded image bodies; filenames and lot numbers never come from HTTP.
"""

import hmac
import io
import secrets
import socket
import threading
import time
import warnings
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from simple_auction.services.network import private_address

SESSION_SECONDS = 600
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_SESSION_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 30_000_000
MAX_PHOTOS = 24
SHOTS = {
    "overall": "Overall view",
    "opposite": "Opposite side",
    "markings": "Maker / model markings",
    "serial": "Serial number close-up",
    "defects": "Defects / wear close-up",
    "details": "Condition / other details",
}
MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class CapturedPhoto:
    path: Path
    shot: str


def prepare_image(data: bytes) -> bytes:
    """Decode, bound dimensions, orient, and strip metadata before saving JPEG."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Photo is empty or larger than 12 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Use a JPEG, PNG or WebP photo.")
                if (
                    image.width * image.height > MAX_PIXELS
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("Use a still photo of at most 30 megapixels.")
                image.load()
                oriented = ImageOps.exif_transpose(image).convert("RGB")
                output = io.BytesIO()
                oriented.save(output, "JPEG", quality=92)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("The file is not a readable, supported photo.") from error


class PhoneCaptureSession:
    """One immutable target lot, one random capability, one bounded HTTP worker.

    Bind a specific private interface, never all interfaces. start()/stop() are
    explicit and one-shot. Expiry closes the listener even without UI polling.
    stop() interrupts incomplete bodies and waits for the worker to finish.
    """

    def __init__(
        self,
        lot_number: int,
        directory: Path,
        address: str,
        *,
        lifetime: float = SESSION_SECONDS,
    ) -> None:
        if type(lot_number) is not int or lot_number <= 0:
            raise ValueError("A saved lot number is required.")
        if not private_address(address):
            raise ValueError("Select a private local IPv4 address.")
        if not 0 < lifetime <= SESSION_SECONDS:
            raise ValueError("Invalid session lifetime.")
        self._lot_number = lot_number
        self._directory = Path(directory)
        if not self._directory.is_dir():
            raise ValueError("The capture directory must exist.")
        self.address = address
        self._lifetime = lifetime
        self._token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._photos: list[CapturedPhoto] = []
        self._bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: HTTPServer | None = None
        self._connection: socket.socket | None = None
        self._expires = 0.0
        self._expiry_timer: threading.Timer | None = None

    @property
    def lot_number(self) -> int:
        return self._lot_number

    @property
    def active(self) -> bool:
        return (
            self._thread is not None
            and not self._stop.is_set()
            and time.monotonic() < self._expires
        )

    @property
    def remaining(self) -> int:
        return max(0, int(self._expires - time.monotonic()))

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Phone intake has not started.")
        return f"http://{self.address}:{self._server.server_port}/{self._token}/"

    @property
    def photos(self) -> list[CapturedPhoto]:
        with self._lock:
            return list(self._photos)

    def start(self) -> None:
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError("Phone sessions cannot be restarted.")
        session = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def log_message(self, *_args):
                pass  # Never log the capability URL or phone metadata.

            def handle(self):
                session._connection = self.connection
                try:
                    super().handle()
                except OSError, TimeoutError:
                    pass
                finally:
                    session._connection = None

            def do_GET(self):
                self._dispatch(False)

            def do_POST(self):
                self._dispatch(True)

            def _reply(
                self, status, body, content_type="text/plain; charset=utf-8", nonce=""
            ):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Connection", "close")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                    "connect-src 'self'; img-src 'self' blob:; "
                    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def _dispatch(self, upload):
                def fail(status, message):
                    self._reply(status, message.encode())

                origin = f"http://{session.address}:{session._server.server_port}"
                if (
                    not private_address(self.client_address[0])
                    or self.headers.get("Host") != origin.removeprefix("http://")
                    or self.headers.get("Origin", origin) != origin
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"
                ):
                    return fail(403, "Local phone access only.")
                if not session.active:
                    return fail(410, "This photo session has ended.")
                try:
                    parsed = urlsplit(self.path)
                except ValueError:
                    return fail(400, "Invalid request path.")
                expected = f"/{session._token}/" + ("upload/" if upload else "")
                if not hmac.compare_digest(parsed.path.encode(), expected.encode()):
                    return fail(404, "Photo session not found.")
                if not upload:
                    if parsed.query:
                        return fail(404, "Not found.")
                    nonce = secrets.token_urlsafe(16)
                    return self._reply(
                        200,
                        _phone_page(session.lot_number, nonce).encode(),
                        "text/html; charset=utf-8",
                        nonce,
                    )
                try:
                    query = parse_qs(
                        parsed.query, strict_parsing=True, max_num_fields=1
                    )
                except ValueError:
                    return fail(400, "Select a guided shot.")
                shot = query.get("shot", [""])[0]
                if set(query) != {"shot"} or shot not in SHOTS:
                    return fail(400, "Select a guided shot.")
                if (
                    self.headers.get("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length", [])) != 1
                ):
                    return fail(400, "Send a single image with a content length.")
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    return fail(400, "Invalid image length.")
                if not 0 < length <= MAX_IMAGE_BYTES:
                    return fail(413, "Use a photo smaller than 12 MiB.")
                if self.headers.get("Content-Type", "").lower() not in MIME_TYPES:
                    return fail(415, "Use JPEG, PNG or WebP (not HEIC).")
                with session._lock:
                    full = (
                        len(session._photos) >= MAX_PHOTOS
                        or session._bytes + length > MAX_SESSION_BYTES
                    )
                if full:
                    return fail(413, "This session's photo limit has been reached.")
                data = self.rfile.read(length)
                if len(data) != length:
                    return fail(400, "Incomplete photo. Please retry.")
                try:
                    prepared = prepare_image(data)
                except ValueError as error:
                    return fail(422, str(error))
                with session._lock:
                    if not session.active:
                        return fail(410, "This photo session has ended.")
                    if session._bytes + len(prepared) > MAX_SESSION_BYTES:
                        return fail(413, "This session's photo limit has been reached.")
                    path = session._directory / f"{secrets.token_hex(16)}.jpg"
                    try:
                        path.write_bytes(prepared)
                    except OSError:
                        path.unlink(missing_ok=True)
                        return fail(
                            500, "Could not store photo on the computer. Please retry."
                        )
                    session._photos.append(CapturedPhoto(path, shot))
                    session._bytes += max(length, len(prepared))
                self._reply(
                    201, b"Photo received. Check it on the computer before saving."
                )

        self._server = HTTPServer((self.address, 0), Handler)
        self._server.timeout = 0.2
        self._expires = time.monotonic() + self._lifetime
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="phone-capture"
        )
        self._expiry_timer = threading.Timer(self._lifetime, self.stop)
        self._expiry_timer.daemon = True
        self._thread.start()
        self._expiry_timer.start()

    def _run(self):
        try:
            while not self._stop.is_set() and time.monotonic() < self._expires:
                self._server.handle_request()
        finally:
            self._stop.set()
            self._server.server_close()
            self._expiry_timer.cancel()

    def stop(self) -> None:
        self._stop.set()
        if self._expiry_timer is not None:
            self._expiry_timer.cancel()
        connection = self._connection
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)


def _phone_page(lot_number: int, nonce: str) -> str:
    """Self-contained page; native file input works over HTTP without camera APIs."""
    options = "".join(
        f'<option value="{key}">{label}</option>' for key, label in SHOTS.items()
    )
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>Photos for lot {lot_number}</title>
<style nonce="{nonce}">
:root{{font:16px/1.5 system-ui,-apple-system,sans-serif;color:#182c38;background:#f1f5f5}}
*{{box-sizing:border-box}}[hidden]{{display:none!important}}
body{{margin:0}}main{{max-width:34rem;margin:auto;padding:24px 18px 36px}}
header{{margin-bottom:24px}}.brand{{font-size:.75rem;font-weight:750;letter-spacing:.14em;
text-transform:uppercase;color:#526774;margin:0 0 18px}}
.lot{{display:inline-block;padding:5px 12px;border:1px solid #c7d8da;border-radius:99px;
background:#e4eff0;color:#24535b;font-size:.875rem;font-weight:700}}
h1{{font-size:clamp(1.8rem,7vw,2.4rem);line-height:1.15;letter-spacing:-.04em;margin:12px 0}}
p{{margin:8px 0}}.muted,.help{{color:#526774}}.help{{font-size:.875rem}}
.card{{background:#fff;border:1px solid #d7e1e4;border-radius:20px;padding:20px;
box-shadow:0 8px 28px #18313a08}}
.section-label{{display:block;font-size:.75rem;font-weight:750;letter-spacing:.08em;
text-transform:uppercase;color:#526774;margin-bottom:8px}}
select,input,button{{font:inherit;max-width:100%}}
select{{width:100%;min-height:48px;padding:10px 12px;border:1px solid #a8bcc3;
border-radius:10px;color:inherit;background:#fff}}
.picker{{margin-top:22px;padding:18px;border:1px dashed #8daab3;border-radius:14px;
background:#f6f9fa}}.picker-title{{font-weight:700;margin-bottom:4px}}
.photo-actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}}
.photo-actions button{{flex:1 1 8rem;padding:10px 14px;border:1px solid #b3c8ce;
background:#fff;color:#183d47}}
.preview{{margin:18px 0 0;border:1px solid #d7e1e4;border-radius:14px;overflow:hidden}}
.preview img{{display:block;width:100%;max-height:24rem;object-fit:contain;background:#edf2f3}}
figcaption{{display:flex;align-items:center;gap:12px;padding:10px 12px}}
#filename{{overflow-wrap:anywhere;flex:1;font-size:.875rem}}
button{{min-height:48px;cursor:pointer;border-radius:10px;border:0;font-weight:700}}
button:disabled,input:disabled,select:disabled{{cursor:default;opacity:.6}}
#remove{{padding:8px 12px;background:#edf2f3;color:#244b56}}
#send{{width:100%;margin-top:20px;padding:14px;background:#166477;color:white}}
#send:not(:disabled):hover{{background:#104d5c}}
:focus-visible{{outline:3px solid #238ca8;outline-offset:3px}}
#status{{font-size:.875rem;margin:12px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;
color:#526774}}
#status[data-state=success]{{color:#166047;background:#eaf6ef;padding:12px;border-radius:10px}}
#status[data-state=error]{{color:#942c2c;background:#fff0ef;padding:12px;border-radius:10px}}
.next{{display:flex;gap:12px;margin:22px 2px;color:#526774;font-size:.875rem}}
.next strong{{display:block;color:#182c38;margin-bottom:3px}}
.step{{flex:none;display:grid;place-items:center;width:28px;height:28px;border-radius:50%;
background:#dfeaec;color:#24535b;font-weight:750}}
details{{border-top:1px solid #d0dde1;padding:14px 2px;font-size:.875rem;color:#526774}}
summary{{cursor:pointer;min-height:32px;font-weight:650;color:#244b56}}
details p{{margin:8px 0 0}}
@media(min-width:540px){{main{{padding-top:40px}}.card{{padding:26px}}}}
</style>
</head>
<body><main>
<header><p class="brand">Simple Auction · Photo intake</p>
<span class="lot">Lot {lot_number}</span>
<h1>Add a photo.<br>Keep cataloguing.</h1>
<p class="muted">Take a clear photo, check it, then send it to the computer.</p></header>
<section class="card" aria-label="Add a lot photo">
<label class="section-label" for="shot">1 · Choose a view</label>
<select id="shot">{options}</select>
<p class="help">Start with the whole item, then capture markings and details.</p>
<div class="picker">
<p class="picker-title">2 · Add a photo</p>
<p id="formats" class="help">JPEG, PNG or WebP · up to 12 MiB. No HEIC.</p>
<div class="photo-actions">
<button id="take" type="button" aria-describedby="formats">Take picture</button>
<button id="choose" type="button" aria-describedby="formats">Choose file</button>
</div>
<input id="photo" type="file" accept="image/jpeg,image/png,image/webp"
aria-label="Choose an existing photo" hidden>
<input id="camera" type="file" accept="image/jpeg,image/png,image/webp"
capture="environment" aria-label="Take a picture" hidden>
</div>
<figure id="preview-box" class="preview" hidden>
<img id="preview" alt="Selected photo preview">
<figcaption><span id="filename"></span><button id="remove" type="button">Remove</button></figcaption>
</figure>
<button id="send" type="button" disabled>Send photo to lot {lot_number}</button>
<p id="status" role="status" aria-live="polite">Nothing is sent until you press Send photo.</p>
</section>
<div class="next"><span class="step" aria-hidden="true">✓</span><div>
<strong>Finish on the computer</strong>
Review received photos and choose Add photos to keep them. Sending does not save them to the lot yet.
</div></div>
<details><summary>Photo tips</summary><p>Use even light and sharp focus. Fill the frame with the
item or marking. Do not include people or paperwork. Check the lot number before sending.
Identification is optional and requires a separate reviewed research request.</p></details>
<details><summary>Private Wi-Fi · temporary link</summary><p>This page sends photos only to
the computer that showed the QR code, not to an AI service. Use trusted private Wi-Fi:
local HTTP is not encrypted. The link expires 10 minutes after the computer starts the session.
Keep this page private.</p></details>
</main>
<script nonce="{nonce}">
const photo=document.getElementById('photo'),send=document.getElementById('send'),
status=document.getElementById('status'),preview=document.getElementById('preview'),
previewBox=document.getElementById('preview-box'),filename=document.getElementById('filename'),
remove=document.getElementById('remove'),shot=document.getElementById('shot'),
camera=document.getElementById('camera'),take=document.getElementById('take'),
choose=document.getElementById('choose');
let previewURL,busy=false,selectedFile;
take.onclick=()=>{{if(!busy){{camera.value='';camera.click();}}}};
choose.onclick=()=>{{if(!busy){{photo.value='';photo.click();}}}};
function message(text,state=''){{status.textContent=text;status.dataset.state=state;}}
function clearPhoto(){{
if(previewURL) URL.revokeObjectURL(previewURL);
previewURL=undefined;preview.removeAttribute('src');previewBox.hidden=true;
photo.value='';camera.value='';selectedFile=undefined;filename.textContent='';send.disabled=true;
}}
function validFile(file){{
if(!file)return false;
if(!['image/jpeg','image/png','image/webp'].includes(file.type)){{
message('Choose JPEG, PNG or WebP. HEIC is not supported.','error');return false;}}
if(!file.size||file.size>{MAX_IMAGE_BYTES}){{
message('Choose a non-empty photo no larger than 12 MiB.','error');return false;}}
return true;
}}
function selectPhoto(input){{
if(busy)return;
const file=input.files[0];
if(!file)return;
clearPhoto();
if(!validFile(file))return;
selectedFile=file;
previewURL=URL.createObjectURL(file);preview.src=previewURL;
filename.textContent=file.name;previewBox.hidden=false;send.disabled=false;
message('Ready to send. Check the photo and lot number first.');
}}
photo.onchange=()=>selectPhoto(photo);
camera.onchange=()=>selectPhoto(camera);
remove.onclick=()=>{{if(busy)return;clearPhoto();
message('Photo removed. Take or choose another.');choose.focus();}};
send.onclick=async()=>{{
if(busy)return;
const file=selectedFile;if(!validFile(file))return;
busy=true;send.disabled=true;photo.disabled=true;camera.disabled=true;
take.disabled=true;choose.disabled=true;shot.disabled=true;remove.disabled=true;
send.textContent='Sending…';message('Sending photo. Keep this page open.');
try{{const response=await fetch(location.pathname+'upload/?shot='+
encodeURIComponent(shot.value),{{method:'POST',
headers:{{'Content-Type':file.type}},body:file}});
const result=await response.text();
if(response.ok){{clearPhoto();message(result+' You can send another photo.','success');}}
else{{message(result,'error');send.disabled=false;}}
}}catch(error){{
message('Connection lost or session ended. Check the computer before retrying.','error');
send.disabled=false;
}}finally{{busy=false;photo.disabled=false;camera.disabled=false;
take.disabled=false;choose.disabled=false;shot.disabled=false;remove.disabled=false;
send.textContent='Send photo to lot {lot_number}';}}
}};
</script></body></html>'''
