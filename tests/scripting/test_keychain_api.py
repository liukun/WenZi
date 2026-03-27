"""Tests for wz.keychain encrypted vault API."""

import json
import os
from unittest.mock import patch


MOCK_MASTER_KEY_B64 = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="  # 32 bytes b64


class TestKeychainAPIInit:
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_loads_existing_master_key(self, mock_get, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        assert api._master_key is not None
        assert len(api._master_key) == 32
        mock_get.assert_called_once_with("scripting.vault.master_key")

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=None)
    def test_generates_master_key_when_absent(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        assert api._master_key is not None
        assert len(api._master_key) == 32
        mock_set.assert_called_once()
        import base64
        stored_b64 = mock_set.call_args[0][1]
        assert len(base64.b64decode(stored_b64)) == 32

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=False)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=None)
    def test_degrades_when_keychain_unavailable(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        assert api._master_key is None


class TestKeychainAPICRUD:
    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_set_get_roundtrip(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        assert api.set("token", "secret123") is True
        assert api.get("token") == "secret123"

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_delete_removes_key(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        api.set("token", "secret123")
        api.delete("token")
        assert api.get("token") is None

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_delete_missing_key_is_noop(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        api.delete("nonexistent")

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_keys_returns_stored_keys(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        api.set("a", "1")
        api.set("b", "2")
        assert sorted(api.keys()) == ["a", "b"]
        api.delete("a")
        assert api.keys() == ["b"]

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_get_missing_key_returns_none(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        assert api.get("nonexistent") is None

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_set_overwrites_existing(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        api.set("token", "old")
        api.set("token", "new")
        assert api.get("token") == "new"

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_degraded_mode_when_no_master_key(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        api = KeychainAPI(vault_path=str(tmp_path / "keychain.json"))
        api._master_key = None
        assert api.get("token") is None
        assert api.set("token", "value") is False
        api.delete("token")


class TestKeychainAPIEdgeCases:
    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_corrupt_entry_returns_none(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        vault_path = str(tmp_path / "keychain.json")
        with open(vault_path, "w") as f:
            json.dump({"bad_key": "not-valid-base64!!!"}, f)

        api = KeychainAPI(vault_path=vault_path)
        assert api.get("bad_key") is None

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_aad_mismatch_returns_none(self, mock_get, mock_set, tmp_path):
        """Swapping encrypted entries between keys should fail decryption."""
        from wenzi.scripting.api.keychain import KeychainAPI

        vault_path = str(tmp_path / "keychain.json")
        api = KeychainAPI(vault_path=vault_path)
        api.set("key_a", "secret_a")
        api.set("key_b", "secret_b")

        with api._lock:
            blob_a = api._data["key_a"]
            blob_b = api._data["key_b"]
            api._data["key_a"] = blob_b
            api._data["key_b"] = blob_a

        assert api.get("key_a") is None
        assert api.get("key_b") is None

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_corrupt_vault_file_starts_empty(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        vault_path = str(tmp_path / "keychain.json")
        with open(vault_path, "w") as f:
            f.write("{{{not json")

        api = KeychainAPI(vault_path=vault_path)
        assert api.keys() == []

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_atomic_write_uses_tmp_and_replace(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        vault_path = str(tmp_path / "keychain.json")
        api = KeychainAPI(vault_path=vault_path)
        api.set("token", "secret")
        api.flush_sync()

        assert os.path.isfile(vault_path)
        assert not os.path.isfile(vault_path + ".tmp")

        with open(vault_path, "r") as f:
            data = json.load(f)
        assert "token" in data
        assert data["token"] != "secret"

    @patch("wenzi.scripting.api.keychain.keychain_set", return_value=True)
    @patch("wenzi.scripting.api.keychain.keychain_get", return_value=MOCK_MASTER_KEY_B64)
    def test_persistence_across_instances(self, mock_get, mock_set, tmp_path):
        from wenzi.scripting.api.keychain import KeychainAPI

        vault_path = str(tmp_path / "keychain.json")
        api1 = KeychainAPI(vault_path=vault_path)
        api1.set("token", "persisted_secret")
        api1.flush_sync()

        api2 = KeychainAPI(vault_path=vault_path)
        assert api2.get("token") == "persisted_secret"
