"""Refresh shared state without blocking painting or typing."""

from PySide6.QtCore import QThread

from simple_auction.services import network


class NetworkPoll(QThread):
    def __init__(self, client, shipping_key, current_key, baseline):
        super().__init__()
        self.client = client
        self.shipping_key = shipping_key
        self.current_key = current_key
        self.baseline = baseline
        self.connection = None
        self.result = None
        self.error = None

    def run(self):
        try:
            # Each poll gets its own client, with a short connection timeout.
            client = (
                self.client
                if isinstance(self.client, network.LocalClient)
                else network.Client(
                    self.client.address,
                    self.client.code,
                    identity=self.client.identity,
                    cache=self.client.cache,
                )
            )
            self.connection = client
            if not isinstance(client, network.LocalClient):
                client._next_discovery = self.client._next_discovery
            client.timeout = 3
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
            self.result = (snapshot, batch, record, lot)
        except Exception as e:  # noqa: BLE001 - report failures to the GUI without terminating Qt
            self.error = e
