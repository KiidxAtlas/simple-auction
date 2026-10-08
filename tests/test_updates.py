"""Checks for verified, installer-based desktop updates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from simple_auction.services import updates


def test_update_staging_path_is_private_and_sanitized(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    path = updates.update_staging_path("../v 1.2.3", "Windows")
    assert path.parent == tmp_path / "simple-auction-updates"
    assert path.name == "SimpleAuction-Setup-v-1.2.3.exe"


def test_windows_installer_launches_detached(tmp_path: Path, monkeypatch) -> None:
    current = tmp_path / "SimpleAuction.exe"
    installer = tmp_path / "SimpleAuction-Setup-1.2.3.exe"
    current.write_bytes(b"current")
    installer.write_bytes(b"installer")
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(updates.platform, "system", lambda: "Windows")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", str(current))
    monkeypatch.setattr(
        updates.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs))
    )

    assert updates.can_install_update_windows()
    assert updates.launch_windows_installer(installer)
    args, kwargs = calls[0]
    assert args == [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/CLOSEAPPLICATIONS",
    ]
    assert kwargs["close_fds"] is True


def test_running_from_source_never_launches_installer(
    tmp_path: Path, monkeypatch
) -> None:
    installer = tmp_path / "SimpleAuction-Setup-1.2.3.exe"
    installer.write_bytes(b"installer")
    monkeypatch.setattr(updates.platform, "system", lambda: "Windows")
    monkeypatch.delattr(updates.sys, "frozen", raising=False)
    assert not updates.launch_windows_installer(installer)


def test_version_comparison() -> None:
    assert updates._compare_versions("0.2.0", "0.1.9") > 0
    assert updates._compare_versions("v0.10.0", "0.9.0") > 0
    assert updates._compare_versions("1.0", "1.0.0") == 0
    assert updates._compare_versions("0.1.0", "0.1.1") < 0
    # A pre-release counts as older than the final release.
    assert updates._compare_versions("1.2.3rc1", "1.2.3") < 0


class _OfflineResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        """Like a real response: hands out the bytes once, then b"" at the end."""
        if size < 0:
            size = len(self._payload)
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk


def _release_payload(digest: str, *, sidecar: bool = True) -> bytes:
    artifact = {
        "name": "SimpleAuction-Setup-99.0.0.exe",
        "browser_download_url": "https://example.invalid/SimpleAuction-Setup-99.0.0.exe",
    }
    if digest:
        artifact["digest"] = digest
    assets = [
        artifact,
        {
            "name": "SimpleAuction-macOS.dmg",
            "browser_download_url": "https://example.invalid/SimpleAuction-macOS.dmg",
        },
    ]
    if sidecar:
        assets.append(
            {
                "name": "SimpleAuction-Setup-99.0.0.exe.sha256",
                "browser_download_url": (
                    "https://example.invalid/SimpleAuction-Setup-99.0.0.exe.sha256"
                ),
            }
        )
    return json.dumps(
        {"tag_name": "v99.0.0", "body": "notes", "assets": assets}
    ).encode()


def _serve(monkeypatch, *payloads: bytes) -> None:
    responses = iter(_OfflineResponse(p) for p in payloads)
    monkeypatch.setattr(
        updates.urllib.request, "urlopen", lambda *_args, **_kwargs: next(responses)
    )


def test_update_check_uses_verified_sha256_sidecar_offline(monkeypatch) -> None:
    expected = "a" * 64
    monkeypatch.setattr(updates.platform, "system", lambda: "Windows")
    _serve(
        monkeypatch,
        _release_payload(""),
        f"{expected}  SimpleAuction-Setup-99.0.0.exe\n".encode(),
    )

    info = updates.check_for_updates()

    assert info is not None
    assert info.is_newer and info.version == "99.0.0"
    assert info.url.endswith("SimpleAuction-Setup-99.0.0.exe")
    assert info.sha256 == expected


def test_update_check_rejects_sidecar_for_different_artifact(monkeypatch) -> None:
    monkeypatch.setattr(updates.platform, "system", lambda: "Windows")
    _serve(monkeypatch, _release_payload(""), f"{'b' * 64}  Other.exe\n".encode())

    info = updates.check_for_updates()

    assert info is not None
    assert info.sha256 is None


def test_update_check_rejects_malformed_api_digest_and_uses_sidecar(
    monkeypatch,
) -> None:
    expected = "c" * 64
    monkeypatch.setattr(updates.platform, "system", lambda: "Windows")
    _serve(
        monkeypatch,
        _release_payload("sha256:not-a-digest"),
        f"{expected}  SimpleAuction-Setup-99.0.0.exe\n".encode(),
    )

    info = updates.check_for_updates()

    assert info is not None
    assert info.sha256 == expected


def test_update_check_picks_the_dmg_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
    _serve(monkeypatch, _release_payload(""))

    info = updates.check_for_updates()

    assert info is not None
    assert info.url.endswith("SimpleAuction-macOS.dmg")
    assert info.sha256 is None  # no .dmg.sha256 published in this payload


def test_download_rejects_checksum_mismatch(tmp_path: Path, monkeypatch) -> None:
    _serve(monkeypatch, b"installer bytes")
    dest = tmp_path / "SimpleAuction-Setup-1.0.0.exe"

    assert not updates.download_update("https://x", dest, expected_sha256="0" * 64)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []  # no partial file left behind


def test_download_keeps_verified_file(tmp_path: Path, monkeypatch) -> None:
    payload = b"installer bytes"
    _serve(monkeypatch, payload)
    dest = tmp_path / "SimpleAuction-Setup-1.0.0.exe"

    expected = hashlib.sha256(payload).hexdigest()
    assert updates.download_update("https://x", dest, expected_sha256=expected)
    assert dest.read_bytes() == payload


def _load_build_script() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "build_standalone.py"
    spec = importlib.util.spec_from_file_location("build_standalone", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_build_manifest_and_platform_commands_are_complete(
    tmp_path: Path,
) -> None:
    build = _load_build_script()
    manifest = dict(build.DATA_FILES)
    assert manifest == {
        "src/simple_auction/ui/styles.qss": "simple_auction/ui",
        "assets/icon.png": "assets",
    }
    for source in manifest:
        assert (build.ROOT / source).exists()
    assert (build.ROOT / "assets" / "icon.ico").exists()

    windows = build.build_command("Windows")
    macos = build.build_command("Darwin")
    for cmd in (windows, macos):
        assert "--clean" in cmd and "--windowed" in cmd
        assert "--collect-submodules=google.genai" in cmd
        for source in manifest:
            assert any(source in argument for argument in cmd)
    assert "--onedir" in windows and "--onefile" not in windows
    assert str(build.ROOT / "assets" / "icon.ico") in windows
    assert "--osx-bundle-identifier" in macos
    assert str(build.ROOT / "assets" / "icon.png") in macos

    artifact = tmp_path / "SimpleAuction.exe"
    artifact.write_bytes(b"release artifact")
    sidecar = build.write_sha256(artifact)
    assert sidecar.name == "SimpleAuction.exe.sha256"
    assert sidecar.read_text(encoding="ascii") == (
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  SimpleAuction.exe\n"
    )
