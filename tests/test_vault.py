"""Tests for wenzi.vault — single Keychain entry secret storage."""

import json
from unittest.mock import patch


class TestVaultCRUD:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_set_get_roundtrip(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        assert v.set("token", "secret123") is True
        assert v.get("token") == "secret123"

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_delete_removes_key(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.set("token", "secret123")
        v.delete("token")
        assert v.get("token") is None

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_keys_returns_stored_keys(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.set("a", "1")
        v.set("b", "2")
        assert sorted(v.keys()) == ["a", "b"]

    @patch("wenzi.vault._keychain_set", return_value=False)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_set_returns_false_on_keychain_failure(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        assert v.set("x", "y") is False


class TestVaultDeletePrefix:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_delete_prefix_removes_matching(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.set("asr.providers.groq.api_key", "key1")
        v.set("asr.providers.groq.base_url", "url1")
        v.set("asr.providers.openai.api_key", "key2")
        v.delete_prefix("asr.providers.groq.")
        assert v.get("asr.providers.groq.api_key") is None
        assert v.get("asr.providers.groq.base_url") is None
        assert v.get("asr.providers.openai.api_key") == "key2"

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_delete_prefix_no_match_is_noop(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.set("asr.providers.groq.api_key", "key1")
        v.delete_prefix("nonexistent.")
        assert v.get("asr.providers.groq.api_key") == "key1"


class TestVaultLoad:
    def test_loads_existing_data_from_keychain(self):
        existing = json.dumps({"token": "secret"})
        with patch("wenzi.vault._keychain_get", return_value=existing), \
             patch("wenzi.vault._keychain_set", return_value=True):
            from wenzi.vault import Vault

            v = Vault()
            assert v.get("token") == "secret"

    def test_handles_corrupt_keychain_data(self):
        with patch("wenzi.vault._keychain_get", return_value="not-json"), \
             patch("wenzi.vault._keychain_set", return_value=True):
            from wenzi.vault import Vault

            v = Vault()
            assert v.keys() == []

    def test_handles_empty_keychain(self):
        with patch("wenzi.vault._keychain_get", return_value=None), \
             patch("wenzi.vault._keychain_set", return_value=True):
            from wenzi.vault import Vault

            v = Vault()
            assert v.keys() == []


class TestVaultFlushSync:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_flush_sync_is_noop(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.flush_sync()  # should not raise


class TestGetVault:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_singleton_returns_same_instance(self, mock_get, mock_set):
        import wenzi.vault as vault_mod

        vault_mod._vault = None  # reset singleton
        v1 = vault_mod.get_vault()
        v2 = vault_mod.get_vault()
        assert v1 is v2
        vault_mod._vault = None  # cleanup
