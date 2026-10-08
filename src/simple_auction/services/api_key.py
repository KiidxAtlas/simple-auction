"""The Gemini API key entered in Settings, kept in the OS keychain (macOS
Keychain) so it's never stored as plain text. A key in .env is the fallback."""

import os

import keyring
import keyring.errors

_SERVICE = "simple-auction"
_USER = "gemini-api-key"


def saved() -> str | None:
    """The key saved from Settings, if any."""
    try:
        return keyring.get_password(_SERVICE, _USER)
    except keyring.errors.KeyringError:
        return None


def current() -> str | None:
    """The key to use: Settings first, then GEMINI_API_KEY / GOOGLE_API_KEY."""
    return (
        saved()
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or None
    )


def save(key: str) -> None:
    keyring.set_password(_SERVICE, _USER, key)


def forget() -> None:
    try:
        keyring.delete_password(_SERVICE, _USER)
    except keyring.errors.PasswordDeleteError:
        pass
