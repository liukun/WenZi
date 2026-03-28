"""Tests for wenzi.vault — Keychain-backed secret storage."""

import json
from unittest.mock import patch


class TestVaultLoadAndSave:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_empty_keychain_starts_empty(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        assert v.keys() == []

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get")
    def test_loads_existing_secrets(self, mock_get, mock_set):
        from wenzi.vault import Vault

        stored = json.dumps({"a": "1", "b": "2"})
        mock_get.return_value = stored
        v = Vault()
        assert sorted(v.keys()) == ["a", "b"]
        assert v.get("a") == "1"

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value="not json")
    def test_malformed_json_starts_empty(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        assert v.keys() == []


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
    def test_delete_missing_key_is_noop(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.delete("nonexistent")  # should not raise

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
    def test_set_returns_false_when_keychain_fails(self, mock_get, mock_set):
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


class TestVaultPersistence:
    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get", return_value=None)
    def test_set_calls_keychain_set(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v = Vault()
        v.set("token", "secret")
        # First call is from _ensure_loaded (get), subsequent from _save (set)
        saved = mock_set.call_args[0][1]
        data = json.loads(saved)
        assert data["token"] == "secret"

    @patch("wenzi.vault._keychain_set", return_value=True)
    @patch("wenzi.vault._keychain_get")
    def test_persistence_across_instances(self, mock_get, mock_set):
        from wenzi.vault import Vault

        v1 = Vault()
        mock_get.return_value = None
        v1.set("token", "persisted")

        # Second instance reads what the first wrote
        saved_json = mock_set.call_args[0][1]
        mock_get.return_value = saved_json
        v2 = Vault()
        assert v2.get("token") == "persisted"


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
