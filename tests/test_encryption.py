import pytest


@pytest.fixture(autouse=True)
def _use_temp_key_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.encryption.KEYS_DIR", tmp_path)
    monkeypatch.setattr(
        "utils.encryption.KEYS_FILE", tmp_path / "api_key_encryption.json"
    )
    monkeypatch.setattr("utils.encryption._encryption_key_cache", None)


@pytest.mark.unit
class TestEncryptDecryptRoundtrip:
    def test_encrypt_decrypt_roundtrip(self):
        from utils.encryption import decrypt_api_key, encrypt_api_key

        plaintext = "sensitive-api-key-12345"
        encrypted = encrypt_api_key(plaintext)
        assert encrypted != plaintext
        assert decrypt_api_key(encrypted) == plaintext

    def test_encrypt_empty_string_returns_empty(self):
        from utils.encryption import encrypt_api_key

        assert encrypt_api_key("") == ""

    def test_production_never_creates_a_file_backed_key(self, monkeypatch):
        """A missing production secret must fail closed, not create a new key."""
        from utils.encryption import KEYS_FILE, encrypt_api_key

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("API_KEY_ENCRYPTION_SECRET", raising=False)

        with pytest.raises(RuntimeError, match="API_KEY_ENCRYPTION_SECRET"):
            encrypt_api_key("sensitive-api-key")

        assert not KEYS_FILE.exists()

    def test_production_rejects_short_external_encryption_secret(self, monkeypatch):
        from utils.encryption import encrypt_api_key

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_KEY_ENCRYPTION_SECRET", "too-short")

        with pytest.raises(RuntimeError, match="at least 32 characters"):
            encrypt_api_key("sensitive-api-key")

    def test_decrypt_empty_string_returns_empty(self):
        from utils.encryption import decrypt_api_key

        assert decrypt_api_key("") == ""


@pytest.mark.unit
class TestEncryptDifferentEachTime:
    def test_encrypt_produces_different_ciphertext(self):
        from utils.encryption import encrypt_api_key

        plaintext = "same-input-every-time"
        encrypted_a = encrypt_api_key(plaintext)
        encrypted_b = encrypt_api_key(plaintext)
        assert encrypted_a != encrypted_b


@pytest.mark.unit
class TestDecryptInvalidInput:
    def test_decrypt_without_configured_key_does_not_create_one(self):
        from utils.encryption import KEYS_FILE, decrypt_api_key

        result = decrypt_api_key("not-valid-base64!!!")
        assert result == ""
        assert not KEYS_FILE.exists()

    def test_decrypt_invalid_base64_returns_empty(self):
        from utils.encryption import decrypt_api_key

        result = decrypt_api_key("not-valid-base64!!!")
        assert result == ""

    def test_decrypt_valid_base64_wrong_content_returns_empty(self):
        import base64

        from utils.encryption import decrypt_api_key

        garbage = base64.urlsafe_b64encode(b"this-is-not-fernet-encrypted").decode()
        result = decrypt_api_key(garbage)
        assert result == ""


@pytest.mark.unit
class TestMaskApiKey:
    def test_mask_long_key(self):
        from utils.encryption import mask_api_key

        key = "sk-proj-abcdefghijklmnop-qrstuvwxyz"
        masked = mask_api_key(key)
        assert "****" in masked
        assert key not in masked

    def test_mask_short_key_returns_asterisks(self):
        from utils.encryption import mask_api_key

        assert mask_api_key("abc") == "****"

    def test_mask_empty_key_returns_asterisks(self):
        from utils.encryption import mask_api_key

        assert mask_api_key("") == "****"


@pytest.mark.unit
class TestKeyRotationStatus:
    def test_status_when_no_key_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("API_KEY_ENCRYPTION_SECRET", raising=False)
        import utils.encryption as enc
        from utils.encryption import get_key_rotation_status

        original_keys_file = enc.KEYS_FILE
        enc.KEYS_FILE = tmp_path / "nonexistent_keys.json"
        try:
            status = get_key_rotation_status()
            assert status["exists"] is False
            assert status["should_rotate"] is True
        finally:
            enc.KEYS_FILE = original_keys_file

    def test_status_after_key_creation(self, monkeypatch, tmp_path):
        monkeypatch.delenv("API_KEY_ENCRYPTION_SECRET", raising=False)
        import utils.encryption as enc

        original_keys_file = enc.KEYS_FILE
        enc.KEYS_FILE = tmp_path / "test_keys.json"
        try:
            from utils.encryption import (
                _load_or_create_encryption_key,
                get_key_rotation_status,
            )

            _load_or_create_encryption_key()
            status = get_key_rotation_status()
            assert status["exists"] is True
            assert "created_at" in status
            assert "last_rotation" in status
        finally:
            enc.KEYS_FILE = original_keys_file

    def test_status_with_env_var_set(self, monkeypatch):
        """env var 模式（生產建議）應回報 exists=True，否則 ops 監控盲點。"""
        monkeypatch.setenv(
            "API_KEY_ENCRYPTION_SECRET", "production-style-secret-32-chars-min!"
        )
        from utils.encryption import get_key_rotation_status

        status = get_key_rotation_status()
        assert status["exists"] is True
        assert status.get("source") == "env_var"

    def test_file_rotation_is_rejected_when_secret_is_externally_managed(
        self, monkeypatch
    ):
        """Writing a file key after env-key rotation would corrupt stored keys."""
        from utils.encryption import rotate_encryption_key

        monkeypatch.setenv(
            "API_KEY_ENCRYPTION_SECRET", "production-style-secret-32-chars-min!"
        )

        with pytest.raises(RuntimeError, match="externally managed"):
            rotate_encryption_key()
