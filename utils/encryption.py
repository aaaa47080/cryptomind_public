"""
加密工具模組
用於安全地加密和解密用戶 API Key

安全設計：
- 正式環境只接受外部注入的金鑰，不會讀取或建立本機金鑰檔
- 開發環境可使用權限為 0600 的本機金鑰檔
- 檔案型金鑰與外部管理金鑰不可混用輪換，避免資料永久無法解密
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 金鑰檔案路徑（與 JWT keys 同一目錄）
KEYS_DIR = Path(__file__).parent.parent / "config"
KEYS_FILE = KEYS_DIR / "api_key_encryption.json"


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() in {
        "production",
        "prod",
    }


def _ensure_keys_dir():
    """確保金鑰目錄存在"""
    KEYS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(KEYS_DIR, 0o700)


def _derive_key_from_secret(secret: str) -> bytes:
    """Derive a Fernet key from an externally managed high-entropy secret."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"PiCryptoMiner_API_Key_Derivation",
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def _load_or_create_encryption_key() -> bytes:
    """
    載入或建立加密金鑰

    優先順序（安全性從高到低）：
    1. 從環境變數 API_KEY_ENCRYPTION_SECRET 載入（生產環境首選）
    2. 從金鑰檔案載入（本地開發用）
    3. 建立新金鑰並儲存到檔案（僅本地開發，絕不用於生產）
    """
    import logging

    logger = logging.getLogger(__name__)

    # ── 1. 環境變數（最高優先級 — 生產環境應使用此方式）───────────────
    env_secret = os.getenv("API_KEY_ENCRYPTION_SECRET")
    if env_secret:
        if _is_production() and len(env_secret) < 32:
            raise RuntimeError(
                "API_KEY_ENCRYPTION_SECRET must be at least 32 characters in production."
            )
        return _derive_key_from_secret(env_secret)

    if _is_production():
        raise RuntimeError(
            "API_KEY_ENCRYPTION_SECRET is required in production; "
            "refusing to create a file-backed encryption key."
        )

    _ensure_keys_dir()

    # ── 2. 金鑰檔案（本地開發用）────────────────────────────────────
    if KEYS_FILE.exists():
        try:
            with open(KEYS_FILE, "r") as f:
                data = json.load(f)
                if data.get("key"):
                    # 從 base64 解碼
                    logger.warning(
                        "⚠️ Using file-based API key encryption key. "
                        "For production, set API_KEY_ENCRYPTION_SECRET environment variable instead."
                    )
                    return base64.urlsafe_b64decode(data["key"])
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error("Failed to load encryption key file: %s", exc)

    # ── 3. 建立新金鑰（僅本地開發）────────────────────────────────────
    # 如果走到了這裡，表示既沒有 env var 也沒有金鑰檔案
    # 這在本地開發環境是正常的，但強烈警告不要在已有真實用戶資料的環境這樣做
    logger.warning(
        "🔑 No API key encryption key found. Generating a new one. "
        "WARNING: This will make any previously stored API keys unreadable! "
        "Set API_KEY_ENCRYPTION_SECRET environment variable to preserve existing keys."
    )
    new_key = Fernet.generate_key()
    _save_encryption_key(new_key)
    return new_key


def _save_encryption_key(key: bytes, update_rotation_time: bool = True):
    """儲存加密金鑰到檔案"""
    if _is_production():
        raise RuntimeError("File-backed encryption keys are disabled in production.")

    _ensure_keys_dir()

    # 保留舊資料中的 created_at
    existing_data = {}
    if KEYS_FILE.exists():
        try:
            with open(KEYS_FILE, "r") as f:
                existing_data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            existing_data = {}

    data = {
        "key": base64.urlsafe_b64encode(key).decode(),
        "created_at": existing_data.get(
            "created_at", datetime.now(timezone.utc).isoformat()
        ),
        "version": existing_data.get("version", 1),
    }

    if update_rotation_time:
        data["last_rotation"] = datetime.now(timezone.utc).isoformat()
    elif existing_data.get("last_rotation"):
        data["last_rotation"] = existing_data["last_rotation"]

    # 使用原子寫入避免損壞
    temp_file = KEYS_FILE.with_suffix(".tmp")
    fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, KEYS_FILE)
        os.chmod(KEYS_FILE, 0o600)
    except OSError:
        temp_file.unlink(missing_ok=True)
        raise


# 全域金鑰快取
_encryption_key_cache = None
_decrypt_warning_cache: set[str] = set()


def _load_existing_encryption_key() -> bytes | None:
    """Load an existing encryption key without creating a new one."""
    import logging

    logger = logging.getLogger(__name__)

    # ── 1. 環境變數優先（生產環境）──────────────────────────────────
    env_secret = os.getenv("API_KEY_ENCRYPTION_SECRET")
    if env_secret:
        if _is_production() and len(env_secret) < 32:
            raise RuntimeError(
                "API_KEY_ENCRYPTION_SECRET must be at least 32 characters in production."
            )
        return _derive_key_from_secret(env_secret)

    if _is_production():
        return None

    _ensure_keys_dir()

    # ── 2. 金鑰檔案（本地開發）──────────────────────────────────────
    if KEYS_FILE.exists():
        try:
            with open(KEYS_FILE, "r") as f:
                data = json.load(f)
                if data.get("key"):
                    logger.warning(
                        "⚠️ Using file-based API key encryption key. "
                        "Set API_KEY_ENCRYPTION_SECRET for production."
                    )
                    return base64.urlsafe_b64decode(data["key"])
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error("Failed to load encryption key file: %s", exc)

    return None


def _get_fernet(create_if_missing: bool = False) -> Fernet | None:
    """取得 Fernet 實例；只有寫入路徑允許建立新金鑰。"""
    global _encryption_key_cache

    if _encryption_key_cache is None:
        key = _load_existing_encryption_key()
        if key is None and create_if_missing:
            key = _load_or_create_encryption_key()
        _encryption_key_cache = key

    if _encryption_key_cache is None:
        return None

    return Fernet(_encryption_key_cache)


def encrypt_api_key(plaintext: str) -> str:
    """
    加密 API Key

    Args:
        plaintext: 原始 API Key

    Returns:
        加密後的字串（base64 編碼）
    """
    if not plaintext:
        return ""

    fernet = _get_fernet(create_if_missing=True)
    encrypted = fernet.encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_api_key(encrypted: str) -> str:
    """
    解密 API Key

    Args:
        encrypted: 加密後的字串

    Returns:
        原始 API Key
    """
    if not encrypted:
        return ""

    try:
        fernet = _get_fernet(create_if_missing=False)
        if fernet is None:
            return ""

        decoded = base64.urlsafe_b64decode(encrypted.encode())
        decrypted = fernet.decrypt(decoded)
        return decrypted.decode()
    except (ValueError, TypeError, InvalidToken):
        import logging

        cache_key = encrypted[:16]
        if cache_key not in _decrypt_warning_cache:
            logging.getLogger(__name__).warning(
                "Stored API key could not be decrypted; treating it as unavailable"
            )
            _decrypt_warning_cache.add(cache_key)
        return ""
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Unexpected API key decrypt failure: {e}")
        return ""


def mask_api_key(api_key: str) -> str:
    """
    遮蔽 API Key 用於顯示

    Args:
        api_key: 原始 API Key

    Returns:
        遮蔽後的字串，如 "sk-****...****abc123"
    """
    if not api_key or len(api_key) < 8:
        return "****"

    # 保留前綴和後綴
    prefix_len = min(4, len(api_key) // 4)
    suffix_len = min(4, len(api_key) // 4)

    prefix = api_key[:prefix_len]
    suffix = api_key[-suffix_len:]

    return f"{prefix}****...****{suffix}"


def rotate_encryption_key() -> dict:
    """
    輪換加密金鑰（管理員功能）

    這會：
    1. 生成新金鑰
    2. 重新加密所有現有 API Keys
    3. 更新金鑰檔案

    Returns:
        {"success": bool, "re_encrypted_count": int}
    """
    import asyncio
    import logging

    from core.orm.models import UserApiKey
    from core.orm.session import get_session_factory

    logger_enc = logging.getLogger(__name__)

    if os.getenv("API_KEY_ENCRYPTION_SECRET"):
        raise RuntimeError(
            "Encryption key is externally managed; rotate it through the secret "
            "manager and a controlled data-migration deployment."
        )
    if _is_production():
        raise RuntimeError("File-backed encryption-key rotation is disabled in production.")

    old_fernet = _get_fernet()
    if old_fernet is None:
        raise RuntimeError("No existing encryption key is available for rotation.")

    new_key = Fernet.generate_key()
    new_fernet = Fernet(new_key)

    async def _do_rotation():
        global _encryption_key_cache
        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(UserApiKey.id, UserApiKey.encrypted_key)
            )
            rows = result.fetchall()

            re_encrypted_count = 0
            for row in rows:
                key_id = row[0]
                old_encrypted = row[1]

                try:
                    decoded = base64.urlsafe_b64decode(old_encrypted.encode())
                    plaintext = old_fernet.decrypt(decoded).decode()

                    new_encrypted = new_fernet.encrypt(plaintext.encode())
                    new_encoded = base64.urlsafe_b64encode(new_encrypted).decode()

                    from sqlalchemy import update

                    await session.execute(
                        update(UserApiKey)
                        .where(UserApiKey.id == key_id)
                        .values(encrypted_key=new_encoded)
                    )
                    re_encrypted_count += 1

                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except Exception as e:
                    logger_enc.error(f"Failed to re-encrypt key {key_id}: {e}")

            await session.commit()

            _encryption_key_cache = new_key
            _save_encryption_key(new_key, update_rotation_time=True)

            logger_enc.info(
                f"🔑 API key encryption rotated, re-encrypted {re_encrypted_count} keys"
            )

            return {"success": True, "re_encrypted_count": re_encrypted_count}

    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(_do_rotation())
    except RuntimeError:
        return asyncio.run(_do_rotation())


def get_key_rotation_status() -> dict:
    """
    取得金鑰輪換狀態

    Returns:
        Dictionary with rotation status information

    Notes:
        當 API_KEY_ENCRYPTION_SECRET 環境變數設定時（生產環境建議），
        金鑰由外部管理，輪換責任在外部部署流程。此函式仍回報
        ``exists=True`` 讓 ops 監控（admin panel / health check）
        能正確顯示「金鑰已就緒」，而非誤報為「未設定」。
    """
    _ensure_keys_dir()

    # 環境變數模式：金鑰存在但由外部管理，無檔案 metadata 可查
    if os.getenv("API_KEY_ENCRYPTION_SECRET"):
        return {
            "exists": True,
            "source": "env_var",
            "created_at": None,
            "last_rotation": None,
            "version": 1,
            "should_rotate": False,
        }

    if not KEYS_FILE.exists():
        return {"exists": False, "last_rotation": None, "should_rotate": True}

    try:
        with open(KEYS_FILE, "r") as f:
            data = json.load(f)

        return {
            "exists": True,
            "created_at": data.get("created_at"),
            "last_rotation": data.get("last_rotation"),
            "version": data.get("version", 1),
        }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to read key status: {e}")
        return {"exists": True, "error": str(e), "should_rotate": True}


def should_rotate_api_key_encryption(interval_days: int = 90) -> bool:
    """
    檢查是否需要輪換 API Key 加密金鑰

    Args:
        interval_days: 輪換間隔（預設 90 天）

    Returns:
        True 如果需要輪換
    """
    from datetime import timedelta

    status = get_key_rotation_status()

    if not status.get("exists"):
        return False  # 沒有金鑰檔案，不需要輪換

    last_rotation = status.get("last_rotation")
    if not last_rotation:
        # 沒有 last_rotation 記錄，可能是舊版本
        # 檢查 created_at
        created_at = status.get("created_at")
        if created_at:
            try:
                created = datetime.fromisoformat(created_at)
                if datetime.utcnow() > created + timedelta(days=interval_days):
                    return True
            except (ValueError, TypeError):
                pass
        return False

    try:
        last_rot = datetime.fromisoformat(last_rotation)
        next_rotation = last_rot + timedelta(days=interval_days)
        return datetime.utcnow() >= next_rotation
    except (ValueError, TypeError):
        return True
