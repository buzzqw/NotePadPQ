"""Storage for credentials using the operating-system keyring when available."""

from __future__ import annotations

_SERVICE = "NotePadPQ"


def get_secret(key: str, default: str = "") -> str:
    """Read a secret and migrate an older QSettings value when possible."""
    try:
        import keyring

        value = keyring.get_password(_SERVICE, key)
        if value is not None:
            return value

        from config.settings import Settings
        legacy = Settings.instance().get(key, default) or default
        if legacy:
            try:
                keyring.set_password(_SERVICE, key, str(legacy))
                Settings.instance().set(key, "")
            except Exception:
                pass
        return str(legacy)
    except Exception:
        from config.settings import Settings
        return str(Settings.instance().get(key, default) or default)


def set_secret(key: str, value: str) -> None:
    """Store a secret in the keyring, with a compatibility fallback."""
    try:
        import keyring

        if value:
            keyring.set_password(_SERVICE, key, value)
        else:
            try:
                keyring.delete_password(_SERVICE, key)
            except Exception:
                pass
        from config.settings import Settings
        Settings.instance().set(key, "")
    except Exception:
        from config.settings import Settings
        Settings.instance().set(key, value)


def delete_secret(key: str) -> None:
    """Delete a credential from both the keyring and legacy storage."""
    set_secret(key, "")
