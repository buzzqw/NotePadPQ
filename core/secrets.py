"""Storage for credentials using the operating-system keyring."""

from __future__ import annotations

_SERVICE = "NotePadPQ"


class SecretStorageUnavailable(RuntimeError):
    """Raised when the operating-system keyring cannot safely store a secret."""


def _clear_legacy_secret(key: str) -> None:
    from config.settings import Settings
    Settings.instance().set(key, "")


def get_secret(key: str, default: str = "") -> str:
    """Read a secret, migrating a legacy QSettings value only when safe."""
    try:
        import keyring
    except Exception:
        return default

    try:
        value = keyring.get_password(_SERVICE, key)
    except Exception:
        return default
    if value is not None:
        return value

    # One-time migration prevents old releases from leaving plaintext behind.
    from config.settings import Settings
    legacy = Settings.instance().get(key, "") or ""
    if not legacy:
        return default
    try:
        keyring.set_password(_SERVICE, key, str(legacy))
    except Exception:
        return default
    _clear_legacy_secret(key)
    return str(legacy)


def set_secret(key: str, value: str) -> None:
    """Store a secret in the keyring or fail without a plaintext fallback."""
    try:
        import keyring
    except Exception:
        raise SecretStorageUnavailable("Il portachiavi di sistema non e disponibile")

    try:
        if value:
            keyring.set_password(_SERVICE, key, value)
        else:
            try:
                keyring.delete_password(_SERVICE, key)
            except Exception:
                pass
    except Exception as exc:
        raise SecretStorageUnavailable("Impossibile salvare nel portachiavi di sistema") from exc
    _clear_legacy_secret(key)


def delete_secret(key: str) -> None:
    """Delete a credential from both the keyring and legacy storage."""
    set_secret(key, "")
