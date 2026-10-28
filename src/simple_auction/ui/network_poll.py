"""Refresh shared state without blocking painting or typing.

The same poll reconnects after the host was unreachable and sends the edits
made meanwhile, so nothing in the window ever waits for the network.
"""

import logging

from PySide6.QtCore import QThread

from simple_auction.services import network

log = logging.getLogger(__name__)

# Photo downloads per poll, so lots can still be opened after going offline.
PREFETCH = 24


class NetworkPoll(QThread):
    def __init__(self, client, shipping_key, current_key, baseline):
        super().__init__()
        self.client = client
        self.shipping_key = shipping_key
        self.current_key = current_key
        self.baseline = baseline
        self.connection = None
        self.result = None
        self.synced = None
        self.error = None

    def run(self):
        try:
            local = isinstance(self.client, network.LocalClient)
            # Each poll gets its own client, with a short connection timeout.
            client = (
                self.client
                if local
                else network.Client(
                    self.client.address,
                    self.client.code,
                    identity=self.client.identity,
                    cache=self.client.cache,
                    history=self.client.history,
                )
            )
            self.connection = client
            if not local:
                client._next_discovery = self.client._next_discovery
            client.timeout = 3
            queued = not local and client.pending()
            snapshot = client.snapshot()
            if client.offline:
                # Unreachable: the copy kept on this computer, nothing else.
                self.result = (snapshot, None, None, None)
                return
            if queued:
                client.timeout = 30  # uploads can carry many photos
                self.synced = client.sync()
                client.timeout = 3
                # Uploads the output history counted offline, under the
                # numbers the host just assigned (see Client._upload).
                snapshot = client.snapshot()
            batch = (
                client.request("get_shipping", key=self.shipping_key)
                if self.shipping_key
                else None
            )
            lot = None
            record = None
            if self.current_key:
                auction, number = self.current_key
                record = next(
                    (
                        v
                        for v in snapshot["auctions"].get(str(auction), [])
                        if v["lot_number"] == number
                    ),
                    None,
                )
                if record is not None and record != self.baseline:
                    lot = client.materialize(record)
            if not local:
                try:
                    client.prefetch(snapshot, PREFETCH)
                except network.NetworkError, OSError:
                    log.warning(
                        "Downloading photos for offline use failed", exc_info=True
                    )
            self.result = (snapshot, batch, record, lot)
        except Exception as e:  # noqa: BLE001 - report failures to the GUI without terminating Qt
            self.error = e
