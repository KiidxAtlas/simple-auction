"""Host / find host controls; networking runs off the GUI thread."""

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from simple_auction.services import network
from simple_auction.ui.background import run_io


class NetworkSettings(QFrame):
    def __init__(self, settings: network.Sharing, parent=None):
        super().__init__(parent)
        self.setObjectName("shippingCard")
        self.identity = settings.share_id
        self._host_code = (
            settings.code
            if settings.code and settings.mode in {"host", "off"}
            else network.new_code()
        )
        self._join_code = settings.code if settings.mode == "join" else ""
        layout = QVBoxLayout(self)
        title = QLabel("Local network sharing")
        title.setObjectName("shippingCardTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Share auctions, photos, and shipping on the same private network. The host must stay awake with Simple Auction open. No internet or cloud account is needed."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.enabled = QCheckBox("Share with another computer")
        self.enabled.setChecked(settings.mode != "off")
        layout.addWidget(self.enabled)
        self.host_toggle = QCheckBox("This computer is the host")
        self.host_toggle.setChecked(settings.mode == "host")
        layout.addWidget(self.host_toggle)
        self.host_panel = QFrame()
        host_layout = QFormLayout(self.host_panel)
        self.port = QLineEdit(str(settings.port))
        self.port.setValidator(QIntValidator(1024, 65535, self.port))
        host_layout.addRow("Host port", self.port)
        addresses = network.local_addresses()
        address_hint = QLabel(
            "This computer: "
            + (
                ", ".join(addresses)
                if addresses
                else "Use Find host on the other computer"
            )
        )
        address_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        address_hint.setWordWrap(True)
        host_layout.addRow(address_hint)
        self.host_code = QLineEdit(network.pairing_code(self._host_code))
        self.host_code.setFixedWidth(120)
        self.host_code.setReadOnly(True)
        copy = QPushButton("Copy pairing code")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.host_code.text())
        )
        row = QHBoxLayout()
        row.addWidget(self.host_code, 1)
        row.addWidget(copy)
        host_layout.addRow("Pairing code", row)
        host_hint = QLabel(
            "Click Save to start hosting. On the other computer, choose Find host and enter this code. Existing local auctions, photos, and shipping are copied into the shared database the first time you host."
        )
        host_hint.setWordWrap(True)
        host_hint.setObjectName("hint")
        host_layout.addRow(host_hint)
        layout.addWidget(self.host_panel)
        self.join_panel = QFrame()
        join_layout = QFormLayout(self.join_panel)
        self.address = QLineEdit(settings.address)
        self.address.setPlaceholderText("192.168.1.20:8765")
        self.address.textEdited.connect(lambda: setattr(self, "identity", ""))
        find = QPushButton("Find host")
        find.clicked.connect(self.find_hosts)
        row = QHBoxLayout()
        row.addWidget(self.address, 1)
        row.addWidget(find)
        join_layout.addRow("Host address", row)
        self.hosts = QComboBox()
        self.hosts.hide()
        self.hosts.currentIndexChanged.connect(self._choose_host)
        join_layout.addRow(self.hosts)
        self._join_display = (
            network.pairing_code(self._join_code) if self._join_code else ""
        )
        self.code = QLineEdit(self._join_display)
        self.code.setMaxLength(6)
        self.code.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9]{6}"), self.code)
        )
        self.code.setFixedWidth(120)
        self.code.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setPlaceholderText("6-digit code")
        join_layout.addRow("Pairing code", self.code)
        test = QPushButton("Test connection")
        test.clicked.connect(self.test_connection)
        join_layout.addRow(test)
        layout.addWidget(self.join_panel)
        self.status = QLabel(
            "Save once to remember this connection. Hosting and joining resume automatically when the app opens, including after updates or a reboot."
        )
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        layout.addWidget(self.status)
        self.enabled.toggled.connect(self._mode)
        self.host_toggle.toggled.connect(self._mode)
        self._mode()

    def _mode(self):
        on = self.enabled.isChecked()
        self.host_toggle.setEnabled(on)
        self.host_panel.setVisible(on and self.host_toggle.isChecked())
        self.join_panel.setVisible(on and not self.host_toggle.isChecked())

    def value(self):
        mode = (
            "off"
            if not self.enabled.isChecked()
            else ("host" if self.host_toggle.isChecked() else "join")
        )
        try:
            port = int(self.port.text())
        except ValueError:
            raise ValueError("Enter a host port between 1024 and 65535") from None
        result = network.Sharing(
            mode,
            self.address.text().strip(),
            port,
            self._host_code
            if mode in {"host", "off"}
            else (
                self._join_code
                if self._join_code and self.code.text() == self._join_display
                else self.code.text().strip()
            ),
            self.identity if mode == "join" else "",
        )
        result.validate()
        return result

    def find_hosts(self):
        try:
            hosts = run_io(
                self.window(), "Finding hosts on your network…", network.find_hosts
            )
        except OSError as e:
            self.status.setText(f"Could not search the network: {e}")
            return
        self.hosts.blockSignals(True)
        self.hosts.clear()
        self.hosts.addItem("Select a host…", None)
        for host in hosts:
            self.hosts.addItem(f"{host['name']} · {host['address']}", host)
        self.hosts.blockSignals(False)
        self.hosts.setVisible(bool(hosts))
        if len(hosts) == 1:
            self.hosts.setCurrentIndex(1)
        self.status.setText(
            "Enter the host's pairing code, then Test connection."
            if hosts
            else "No host found. Check that hosting is on and both computers are on the same network. You can also enter the host's address manually."
        )

    def _choose_host(self, *_args):
        if host := self.hosts.currentData():
            self.address.setText(host["address"])
            self.identity = host["identity"]

    def test_connection(self):
        try:
            settings = self.value()
            client = network.Client(
                network.endpoint(settings.address, settings.port),
                settings.code,
                identity=settings.share_id,
            )
            snapshot = run_io(self.window(), "Connecting to host…", client.snapshot)
            self.identity = snapshot["identity"]
            self.status.setText(
                f"Connected · {len(snapshot['auctions'])} auctions · {len(snapshot['shipping'])} shipping auctions. Click Save to join."
            )
        except (ValueError, network.NetworkError) as e:
            self.status.setText(str(e))

    def validate(self):
        try:
            self.value()
        except ValueError as e:
            QMessageBox.warning(self, "Local network sharing", str(e))
            return False
        return True
