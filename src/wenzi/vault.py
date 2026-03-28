"""wenzi.vault — secret storage backed by a single macOS Keychain entry.

All secrets (provider API keys, plugin tokens, etc.) are stored as a
JSON-serialised dictionary in a single macOS Keychain entry under the
account name ``secrets``.

This module is intentionally self-contained: it does NOT import from
``wenzi.config`` to avoid circular-import issues.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

_SECRETS_ACCOUNT = "secrets"


# ---------------------------------------------------------------------------
# Private wrappers around wenzi.keychain (lazy-imported to avoid import-time
# PyObjC failures in headless / test environments).
# ---------------------------------------------------------------------------


def _keychain_get(account: str) -> Optional[str]:
    from wenzi.keychain import _keychain_get as _kc_get

    return _kc_get(account)


def _keychain_set(account: str, value: str) -> bool:
    from wenzi.keychain import _keychain_set as _kc_set

    return _kc_set(account, value)


# ---------------------------------------------------------------------------
# Vault class
# ---------------------------------------------------------------------------


class Vault:
    """Secret key-value store backed by a single macOS Keychain entry.

    All secrets are serialised as a JSON dictionary and stored in one
    Keychain item.  Thread-safe with lazy loading.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._loaded = False
        self._lock = threading.RLock()

    # -- loading / saving ---------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        raw = _keychain_get(_SECRETS_ACCOUNT)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    self._data = data
                    logger.debug("Loaded vault: %d keys", len(self._data))
            except Exception:
                logger.warning("Failed to parse secrets from Keychain", exc_info=True)

    def _save(self) -> bool:
        """Serialise and write all secrets to Keychain.  Returns True on success."""
        try:
            raw = json.dumps(self._data, ensure_ascii=False)
            return _keychain_set(_SECRETS_ACCOUNT, raw)
        except Exception:
            logger.warning("Failed to save secrets to Keychain", exc_info=True)
            return False

    # -- public CRUD --------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """Return the value for *key*, or None."""
        with self._lock:
            self._ensure_loaded()
            return self._data.get(key)

    def set(self, key: str, value: str) -> bool:
        """Store *value* under *key*.  Returns True on success."""
        with self._lock:
            self._ensure_loaded()
            self._data[key] = value
            return self._save()

    def delete(self, key: str) -> None:
        """Remove *key*.  Silent no-op if missing."""
        with self._lock:
            self._ensure_loaded()
            if key in self._data:
                del self._data[key]
                self._save()

    def delete_prefix(self, prefix: str) -> None:
        """Remove all keys starting with *prefix*."""
        with self._lock:
            self._ensure_loaded()
            to_remove = [k for k in self._data if k.startswith(prefix)]
            for k in to_remove:
                del self._data[k]
            if to_remove:
                self._save()

    def keys(self) -> List[str]:
        """Return all stored key names."""
        with self._lock:
            self._ensure_loaded()
            return list(self._data.keys())

    def flush_sync(self) -> None:
        """No-op retained for backward compatibility.

        The old file-backed vault deferred writes to disk; the new
        Keychain-backed vault writes immediately on every mutation.
        """


# ---------------------------------------------------------------------------
# Thread-safe singleton
# ---------------------------------------------------------------------------

_vault: Optional[Vault] = None
_vault_lock = threading.Lock()


def get_vault() -> Vault:
    """Return the shared Vault singleton (double-checked locking)."""
    global _vault
    if _vault is None:
        with _vault_lock:
            if _vault is None:
                _vault = Vault()
    return _vault


def shutdown_vault() -> None:
    """Flush pending vault writes.  Call during app shutdown."""
    v = _vault
    if v is not None:
        v.flush_sync()
