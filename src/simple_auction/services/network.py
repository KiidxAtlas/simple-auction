"""Local sharing: one host owns a SQLite database and immutable photo files.

Clients never open the host's database directly. Every mutation checks the
record the editor originally opened, inside a serialized database transaction.
"""

import base64
import hashlib
import hmac
import io
import ipaddress
import json
import re
import secrets
import socket
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from PIL import Image

from simple_auction.models import Lot
from simple_auction.services import (
    catalogue,
    excel,
    image,
    lot_details,
    numbering,
    shipping,
    storage,
)

PORT = 8765
DISCOVERY_PORT = 8766
MAGIC = b"simple-auction-discover-v1"
MAX_BODY = 64 * 1024 * 1024
PHOTO_LIMIT = 40


class NetworkError(shipping.ShippingError):
    """Sharing failed; the caller must keep its unsaved edits."""


class Unavailable(NetworkError):
    """The saved host is temporarily unreachable; rediscovery can help."""


class Conflict(NetworkError):
    """Another editor changed the same record."""


@dataclass
class Sharing:
    mode: str = "off"
    address: str = ""
    port: int = PORT
    code: str = ""
    share_id: str = ""

    def validate(self):
        if self.mode not in {"off", "host", "join"}:
            raise ValueError("Unknown sharing mode")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Sharing port must be between 1024 and 65535")
        if any(
            not isinstance(v, str) for v in (self.address, self.code, self.share_id)
        ):
            raise ValueError("Invalid sharing settings")
        if self.mode != "off" and not valid_code(self.code):
            raise ValueError("Use the pairing code shown by the host")
        if self.mode == "join":
            endpoint(self.address, self.port)
        if self.share_id and not re.fullmatch(r"[a-f0-9]{32}", self.share_id):
            raise ValueError("Invalid host identity")


def new_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def valid_code(code):
    # Keep already saved pairings valid when either computer updates first.
    return isinstance(code, str) and bool(
        re.fullmatch(r"(?:[0-9]{6}|[A-Za-z0-9_-]{16,64})", code)
    )


def pairing_code(code):
    """A stable six-digit display code, including for pre-update hosts."""
    if not valid_code(code):
        raise ValueError("Use the six-digit pairing code shown by the host")
    if re.fullmatch(r"[0-9]{6}", code):
        return code
    return f"{int(hashlib.sha256(code.encode()).hexdigest(), 16) % 1_000_000:06d}"


def private_address(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.version == 4 and (
            ip.is_loopback
            or any(
                ip in net
                for net in (
                    ipaddress.ip_network("10.0.0.0/8"),
                    ipaddress.ip_network("172.16.0.0/12"),
                    ipaddress.ip_network("192.168.0.0/16"),
                    ipaddress.ip_network("169.254.0.0/16"),
                )
            )
        )
    except ValueError:
        return False


def endpoint(address, port=PORT):
    address = address.strip()
    parsed = urlsplit(address if "://" in address else "http://" + address)
    if (
        parsed.scheme != "http"
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter a local IPv4 address, such as 192.168.1.20")
    host = parsed.hostname
    if host == "localhost":
        host = "127.0.0.1"
    if not private_address(host):
        raise ValueError("Sharing connects only to local network IPv4 addresses")
    selected = parsed.port or port
    if not 1024 <= selected <= 65535:
        raise ValueError("Invalid host port")
    return f"http://{host}:{selected}"


def lot_data(lot):
    data = asdict(lot)
    data.pop("photos")
    return data


def validated_lot(data):
    if not isinstance(data, dict):
        raise TypeError("Invalid lot")
    fields = set(lot_data(Lot(1)))
    if (
        set(data) != fields
        or type(data["lot_number"]) is not int
        or data["lot_number"] < 1
    ):
        raise ValueError("Invalid lot fields")
    if data["year"] is not None and type(data["year"]) is not int:
        raise ValueError("Invalid lot year")
    if any(
        not isinstance(v, str) or len(v) > 100_000
        for k, v in data.items()
        if k not in {"year", "lot_number"}
    ):
        raise ValueError("Invalid lot text")
    return Lot(**data)


def batch_data(batch):
    return json.loads(shipping.encode(batch))


def as_batch(data):
    return shipping.decode(json.dumps(data, allow_nan=False).encode())


def shipping_key(auction):
    return shipping.batch_path(Path(), auction).stem


def number(value):
    if type(value) is not int or not 1 <= value <= 2_000_000_000:
        raise ValueError("Invalid auction or lot number")
    return value


class Database:
    def __init__(self, config):
        self.config = config
        self.path = config.data_dir / "shared.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        try:
            self._initialize()
        except sqlite3.Error as e:
            raise NetworkError(
                f"Cannot open the shared database at {self.path}: {e}. Restore a backup; the app will not switch to stale spreadsheets."
            ) from e

    def _initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,key));
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, batch TEXT NOT NULL, csv BLOB NOT NULL);
            """)
            db.execute(
                "INSERT OR IGNORE INTO meta VALUES ('identity', ?)", (uuid4().hex,)
            )
            db.execute("INSERT OR IGNORE INTO meta VALUES ('revision', '0')")
            self.identity = db.execute(
                "SELECT value FROM meta WHERE key='identity'"
            ).fetchone()[0]
        self.assets = self.config.photos_dir / ".shared" / self.identity
        self._migrate()

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            yield db

    @contextmanager
    def transaction(self):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def get(db, kind, key):
        row = db.execute(
            "SELECT data FROM records WHERE kind=? AND key=?", (kind, str(key))
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def put(db, kind, key, data):
        db.execute(
            "INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data",
            (kind, str(key), json.dumps(data, allow_nan=False)),
        )
        db.execute(
            "UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
        )

    def asset(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid photo identity")
        return self.assets / (digest + ".jpg")

    def store_photo(self, raw):
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError("Photo exceeds 12 MB")
        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "JPEG":
                raise ValueError("Shared photos must be processed JPEG images")
            img.verify()
        digest = hashlib.sha256(raw).hexdigest()
        path = self.asset(digest)
        if not path.exists():
            storage.atomic_write(path, raw)
        return digest

    def _migrate(self):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM meta WHERE key='imported'").fetchone():
                return
            # Any unreadable source aborts the transaction, leaving originals intact.
            for auction in excel.list_auctions(self.config.auctions_dir):
                self.put(db, "auction", auction, {"number": auction})
                for lot in catalogue.load(
                    excel.auction_path(self.config.auctions_dir, auction),
                    lot_details.details_path(self.config.data_dir, auction),
                ):
                    photos = [
                        self.store_photo(p.read_bytes())
                        for p in image.lot_photo_files(
                            lot.lot_number, self.config.auction_photos_dir(auction)
                        )
                    ]
                    self.put(
                        db,
                        "lot",
                        f"{auction}/{lot.lot_number}",
                        {**lot_data(lot), "photos": photos},
                    )
            folder = self.config.data_dir / "shipping"
            for journal in folder.glob(".*.json.transaction"):
                storage.recover(journal)
            for path in folder.glob("*.json"):
                batch = shipping.load_batch(path)
                self.put(db, "shipping", shipping_key(batch.auction), batch_data(batch))
            db.execute("INSERT INTO meta VALUES ('imported','1')")

    def snapshot(self, db):
        auctions = {
            key: []
            for (key,) in db.execute("SELECT key FROM records WHERE kind='auction'")
        }
        for key, raw in db.execute(
            "SELECT key,data FROM records WHERE kind='lot' ORDER BY CAST(substr(key,instr(key,'/')+1) AS INTEGER)"
        ):
            auctions[key.split("/")[0]].append(json.loads(raw))
        batches = {
            key: json.loads(raw)["auction"]
            for key, raw in db.execute(
                "SELECT key,data FROM records WHERE kind='shipping'"
            )
        }
        revision = int(
            db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
        )
        return {
            "identity": self.identity,
            "revision": revision,
            "auctions": auctions,
            "shipping": batches,
        }

    def dispatch(self, op, args):
        with self.transaction() as db:
            if op == "snapshot":
                return self.snapshot(db)
            if op == "photo":
                return base64.b64encode(self.asset(args["hash"]).read_bytes()).decode()
            if op == "new_auction":
                auctions = [
                    int(k)
                    for (k,) in db.execute(
                        "SELECT key FROM records WHERE kind='auction'"
                    )
                ]
                auction = numbering.next_auction(
                    auctions, self.config.step, self.config.start_at
                )
                self.put(db, "auction", auction, {"number": auction})
                return auction
            if op == "new_lot":
                auction = number(args["auction"])
                if self.get(db, "auction", auction) is None:
                    raise Conflict("This auction was deleted. Refresh the catalogue.")
                lots = [
                    Lot(v["lot_number"])
                    for v in self.snapshot(db)["auctions"][str(auction)]
                ]
                lot = Lot(numbering.next_lot(lots, auction, self.config.step))
                data = {**lot_data(lot), "photos": []}
                self.put(db, "lot", f"{auction}/{lot.lot_number}", data)
                return data
            if op == "save_lot":
                auction = number(args["auction"])
                lot = validated_lot(args["lot"])
                key = f"{auction}/{lot.lot_number}"
                old = self.get(db, "lot", key)
                if old is None:
                    raise Conflict("This lot was deleted. Your edits have been kept.")
                photos = args["photos"]
                if not isinstance(photos, list) or len(photos) > PHOTO_LIMIT:
                    raise ValueError("Too many photos")
                hashes = []
                for photo in photos:
                    digest = photo["hash"]
                    path = self.asset(digest)
                    if "data" in photo:
                        raw = base64.b64decode(photo["data"], validate=True)
                        if self.store_photo(raw) != digest:
                            raise ValueError(
                                "Photo identity does not match its contents"
                            )
                    elif not path.is_file():
                        raise ValueError("Photo is missing from the host")
                    hashes.append(digest)
                updated = {**lot_data(lot), "photos": hashes}
                if old != args["expected"] and old != updated:
                    raise Conflict(
                        "Someone else changed this lot. Your edits have been kept; reload the lot before saving again."
                    )
                if old != updated:
                    self.put(db, "lot", key, updated)
                return updated
            if op == "import_lots":
                auction = number(args["auction"])
                lots = [validated_lot(v) for v in args["lots"]]
                self.put(db, "auction", auction, {"number": auction})
                added = []
                for lot in lots:
                    key = f"{auction}/{lot.lot_number}"
                    if self.get(db, "lot", key) is None:
                        self.put(db, "lot", key, {**lot_data(lot), "photos": []})
                        added.append(lot_data(lot))
                return added
            if op == "delete":
                auction = number(args["auction"])
                current = self.snapshot(db)["auctions"].get(str(auction))
                if current != args["expected"]:
                    raise Conflict(
                        "The auction changed while deleting. Refresh and try again."
                    )
                numbers = args["numbers"]
                if numbers is None:
                    db.execute(
                        "DELETE FROM records WHERE kind='auction' AND key=?",
                        (str(auction),),
                    )
                    db.execute(
                        "DELETE FROM records WHERE kind='lot' AND key LIKE ?",
                        (f"{auction}/%",),
                    )
                else:
                    for n in numbers:
                        db.execute(
                            "DELETE FROM records WHERE kind='lot' AND key=?",
                            (f"{auction}/{number(n)}",),
                        )
                db.execute(
                    "UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
                )
                return True
            if op in {"get_shipping", "save_shipping", "export_shipping"}:
                key = args["key"]
                if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{24}", key):
                    raise ValueError("Invalid shipping auction")
                current = self.get(db, "shipping", key)
                if op == "get_shipping":
                    if current is None:
                        raise Conflict("Shipping auction is missing")
                    return current
                if op == "save_shipping":
                    updated = batch_data(as_batch(args["batch"]))
                    expected = args["expected"]
                    if shipping_key(updated["auction"]) != key:
                        raise ValueError("Shipping auction identity changed")
                    if current is None:
                        if expected is not None:
                            raise Conflict("This shipping auction was deleted")
                        if any(
                            p["exported_at"] or p["exported_file"]
                            for b in updated["buyers"]
                            for p in b["packages"]
                        ):
                            raise ValueError(
                                "New imports cannot contain an export history"
                            )
                    elif current != updated:
                        if expected is None:
                            raise Conflict(
                                "This auction already has shipping progress. Select it from the list."
                            )
                        expected = batch_data(as_batch(expected))
                        if any(
                            updated[k] != current[k] or expected[k] != current[k]
                            for k in ("version", "auction", "source")
                        ):
                            raise ValueError("Auction identity cannot be edited")
                        before = {b["id"]: b for b in expected["buyers"]}
                        after = {b["id"]: b for b in updated["buyers"]}
                        now = {b["id"]: b for b in current["buyers"]}
                        if before.keys() != after.keys() or now.keys() != after.keys():
                            raise Conflict("Buyer list changed; reload the auction")
                        merged = []
                        for buyer in current["buyers"]:
                            ident = buyer["id"]
                            new, base = after[ident], before[ident]
                            if new != base:
                                if buyer != base and buyer != new:
                                    raise Conflict(
                                        f"Someone else changed {buyer['name'] or 'this buyer'}. Your edits have been kept; reload before saving again."
                                    )
                                old_boxes = {p["id"]: p for p in buyer["packages"]}
                                new_boxes = {p["id"]: p for p in new["packages"]}
                                for ident, box in old_boxes.items():
                                    if (
                                        box["exported_at"]
                                        and new_boxes.get(ident) != box
                                    ):
                                        raise Conflict(
                                            "Exported packages cannot be changed"
                                        )
                                for ident, box in new_boxes.items():
                                    old_box = old_boxes.get(ident, {})
                                    if any(
                                        box[k] != old_box.get(k, "")
                                        for k in ("exported_at", "exported_file")
                                    ):
                                        raise ValueError(
                                            "Export history is managed by the host"
                                        )
                                if any(
                                    p["exported_at"] for p in buyer["packages"]
                                ) and any(
                                    new[k] != buyer[k]
                                    for k in (*shipping.ADDRESS_FIELDS, "pickup")
                                ):
                                    raise Conflict(
                                        "An exported buyer's address cannot be changed"
                                    )
                                merged.append(new)
                            else:
                                merged.append(buyer)
                        updated["buyers"] = merged
                    if current != updated:
                        self.put(db, "shipping", key, updated)
                    return updated
                export_id = args["id"]
                if not isinstance(export_id, str) or not re.fullmatch(
                    r"[a-f0-9]{32}", export_id
                ):
                    raise ValueError("Invalid export identity")
                row = db.execute(
                    "SELECT batch,csv FROM exports WHERE id=?", (export_id,)
                ).fetchone()
                if row:
                    if row[0] != key:
                        raise ValueError("Export belongs to another auction")
                    return {
                        "batch": current,
                        "csv": base64.b64encode(row[1]).decode(),
                        "id": export_id,
                    }
                if current is None or current != args["expected"]:
                    raise Conflict(
                        "Shipping progress changed. Refresh before exporting."
                    )
                measurements = args["measurements"]
                if type(measurements) is not bool:
                    raise ValueError("Invalid export option")
                raw, batch = shipping.prepare_export(
                    as_batch(current),
                    f"shared:{export_id}",
                    include_measurements=measurements,
                )
                self.put(db, "shipping", key, batch_data(batch))
                db.execute("INSERT INTO exports VALUES (?,?,?)", (export_id, key, raw))
                return {
                    "batch": batch_data(batch),
                    "csv": base64.b64encode(raw).decode(),
                    "id": export_id,
                }
            if op == "download_export":
                ident = args["id"]
                row = db.execute(
                    "SELECT csv FROM exports WHERE id=?", (ident,)
                ).fetchone()
                if row is None:
                    raise ValueError("This export is not available on this host")
                return base64.b64encode(row[0]).decode()
            raise ValueError("Unknown sharing operation")


class Host:
    def __init__(self, config, code, port=PORT, *, bind="0.0.0.0", discovery=True):
        if not valid_code(code):
            raise ValueError("Invalid pairing code")
        self.db = Database(config)
        self.code = code
        self.pairing_code = pairing_code(code)
        self._auth_lock = threading.Lock()
        self._auth_failures = deque()
        self.name = socket.gethostname()
        self.closed = threading.Event()
        self.discovery_socket = None
        self.discovery_thread = None
        host = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *args):
                pass  # Never log buyer data or pairing codes.

            def do_POST(self):
                status, result = 200, None
                try:
                    if (
                        self.path != "/rpc"
                        or not private_address(self.client_address[0])
                        or self.headers.get("Origin")
                    ):
                        raise ValueError("Only local app connections are supported")
                    status = host._authorize(
                        self.client_address[0], self.headers.get("Authorization", "")
                    )
                    if status != 200:
                        raw = json.dumps(
                            {
                                "error": (
                                    "Too many incorrect pairing attempts. Try again in a minute."
                                    if status == 429
                                    else "Pairing code does not match"
                                )
                            }
                        ).encode()
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        if status == 429:
                            self.send_header("Retry-After", "60")
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                    if self.headers.get("Content-Type") != "application/json":
                        raise ValueError("Expected JSON request")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY:
                        raise ValueError("Request exceeds sharing limit")
                    payload = json.loads(self.rfile.read(length))
                    if payload.get("identity") not in {None, "", host.db.identity}:
                        raise Conflict(
                            "This is a different host. Pair with it again in Settings."
                        )
                    result = host.db.dispatch(payload["op"], payload.get("args", {}))
                except Conflict as e:
                    status, result = 409, {"error": str(e)}
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    OSError,
                    shipping.ShippingError,
                ) as e:
                    status, result = 400, {"error": str(e)}
                except Exception:  # noqa: BLE001 - contain request failures without exposing host details
                    status, result = (
                        500,
                        {
                            "error": "The host could not complete the operation. Your edits have been kept."
                        },
                    )
                raw = json.dumps(result, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except BrokenPipeError, ConnectionResetError:
                    pass

        class Server(ThreadingHTTPServer):
            allow_reuse_port = False

        self.server = Server((bind, port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        try:
            if discovery:
                self.discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.discovery_socket.bind(("0.0.0.0", DISCOVERY_PORT))
                self.discovery_socket.settimeout(0.3)
                self.discovery_thread = threading.Thread(
                    target=self._discover, daemon=True
                )
                self.discovery_thread.start()
            self.thread.start()
        except BaseException:
            self.closed.set()
            self.server.server_close()
            if self.discovery_socket:
                self.discovery_socket.close()
            raise

    def _authorize(self, peer, authorization):
        # Bound guessing against the shorter code and bound tracking memory.
        with self._auth_lock:
            now = time.monotonic()
            while self._auth_failures and self._auth_failures[0][0] <= now - 60:
                self._auth_failures.popleft()
            if (
                len(self._auth_failures) >= 100
                or sum(address == peer for _, address in self._auth_failures) >= 12
            ):
                return 429
            provided = authorization.encode("utf-8")
            if any(
                hmac.compare_digest(provided, ("Bearer " + code).encode())
                for code in {self.code, self.pairing_code}
            ):
                return 200
            self._auth_failures.append((now, peer))
            return 401

    def _discover(self):
        while not self.closed.is_set():
            try:
                data, peer = self.discovery_socket.recvfrom(1024)
                if data == MAGIC and private_address(peer[0]):
                    raw = json.dumps(
                        {
                            "name": self.name,
                            "port": self.port,
                            "identity": self.db.identity,
                        }
                    ).encode()
                    self.discovery_socket.sendto(raw, peer)
            except TimeoutError, OSError:
                continue

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.discovery_socket:
            self.discovery_socket.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.discovery_thread:
            self.discovery_thread.join(timeout=1)


def find_hosts(timeout=1.5, *, destinations=None):
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(0.2)
        for address in destinations or ["255.255.255.255", "127.0.0.1"]:
            try:
                sock.sendto(MAGIC, (address, DISCOVERY_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, peer = sock.recvfrom(2048)
                data = json.loads(raw)
                if (
                    not private_address(peer[0])
                    or not isinstance(data["name"], str)
                    or len(data["name"]) > 255
                    or not re.fullmatch(r"[a-f0-9]{32}", data["identity"])
                ):
                    continue
                address = endpoint(peer[0], data["port"])
                previous = found.get(data["identity"])
                if previous is None or "127.0.0.1" in previous["address"]:
                    found[data["identity"]] = {**data, "address": address}
            except OSError, ValueError, KeyError, TypeError:
                continue
    return list(found.values())


class Client:
    def __init__(self, address, code, *, identity="", cache=None):
        self.address = endpoint(address)
        self.code = code
        self.identity = identity
        self.cache = cache or Path()
        self.timeout = 12
        self._next_discovery = 0.0

    def request(self, op, **args):
        raw = json.dumps(
            {"op": op, "args": args, "identity": self.identity}, allow_nan=False
        ).encode()
        if len(raw) > MAX_BODY:
            raise NetworkError(
                "Too many photos for one save (64 MB limit). Use smaller images."
            )
        req = Request(
            self.address + "/rpc",
            data=raw,
            headers={
                "Authorization": "Bearer " + self.code,
                "Content-Type": "application/json",
            },
        )
        try:
            # LAN traffic must not go through configured corporate HTTP proxies.
            with build_opener(ProxyHandler({})).open(
                req, timeout=self.timeout
            ) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise NetworkError("Host response is too large")
                return json.loads(raw)
        except HTTPError as e:
            if e.code == 401:
                raise NetworkError("Pairing code does not match the host") from None
            try:
                message = json.loads(e.read(4096))["error"]
            except ValueError, KeyError:
                message = f"Host returned error {e.code}"
            raise (Conflict if e.code == 409 else NetworkError)(message) from None
        except (URLError, TimeoutError, OSError) as e:
            raise Unavailable(
                "Host is unavailable. Reconnecting automatically; keep it awake with Simple Auction open. Your edits have been kept."
            ) from e
        except ValueError as e:
            raise NetworkError("The host sent an invalid response") from e

    def snapshot(self):
        try:
            result = self.request("snapshot")
        except NetworkError:
            # Reboots can change DHCP addresses. Only reconnect to the saved
            # database identity, then authenticate and verify before adopting it.
            if not self.identity or time.monotonic() < self._next_discovery:
                raise
            self._next_discovery = time.monotonic() + 15
            try:
                hosts = find_hosts(timeout=0.6)
            except OSError:
                raise Unavailable(
                    "Host is unavailable. Reconnecting automatically."
                ) from None
            for host in hosts:
                if host["identity"] != self.identity:
                    continue
                candidate = Client(
                    host["address"], self.code, identity=self.identity, cache=self.cache
                )
                candidate.timeout = self.timeout
                try:
                    result = candidate.request("snapshot")
                except Unavailable:
                    continue
                if result["identity"] != self.identity:
                    raise Conflict(
                        "This is a different host. Pair with it again in Settings."
                    )
                self.address = candidate.address
                break
            else:
                raise
        if self.identity and result["identity"] != self.identity:
            raise NetworkError("Host identity changed; pair again")
        self.identity = result["identity"]
        return result

    def materialize(self, data):
        lot = validated_lot({k: v for k, v in data.items() if k != "photos"})
        folder = self.cache / self.identity / "photos"
        paths = []
        for digest in data["photos"]:
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise NetworkError("Invalid shared photo identity")
            path = folder / (digest + ".jpg")
            if (
                not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raw = base64.b64decode(
                    self.request("photo", hash=digest), validate=True
                )
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise NetworkError("Downloaded photo is incomplete")
                storage.atomic_write(path, raw)
            paths.append(path)
        lot.photos = paths
        return lot

    def save_lot(self, auction, lot, expected):
        photos = []
        for path in lot.photos:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest not in expected["photos"]:
                # Apply the existing photo processing for newly added images.
                with Image.open(io.BytesIO(raw)) as img:
                    img = image.ImageOps.exif_transpose(img).convert("RGB")
                    raw = image._compress(img, int(len(raw) * image.IMAGE_SIZE_RATIO))
                digest = hashlib.sha256(raw).hexdigest()
            record = {"hash": digest}
            if digest not in expected["photos"]:
                record["data"] = base64.b64encode(raw).decode()
            photos.append(record)
        return self.request(
            "save_lot",
            auction=auction,
            lot=lot_data(lot),
            photos=photos,
            expected=expected,
        )


class LocalClient(Client):
    """Continue using the migrated database when LAN hosting is turned off."""

    def __init__(self, db, cache):
        self.db = db
        self.identity = db.identity
        self.cache = cache
        self.address = "local"
        self.code = ""

    def request(self, op, **args):
        try:
            return self.db.dispatch(op, args)
        except Conflict, NetworkError:
            raise
        except (OSError, ValueError, TypeError, sqlite3.Error) as e:
            raise NetworkError(str(e)) from e


def local_addresses():
    addresses = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if private_address(address) and not address.startswith("127."):
                addresses.add(address)
        # Selecting a LAN route doesn't send any traffic.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.255.255", 1))
            address = sock.getsockname()[0]
            if private_address(address) and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)
