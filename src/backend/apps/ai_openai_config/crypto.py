import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from rest_framework.exceptions import APIException


class OpenAIKeyConfigError(APIException):
    status_code = 503
    default_code = "openai_key_config_unavailable"
    default_detail = "OpenAI Key 加密配置不可用。"


def _fernet() -> MultiFernet:
    configured = getattr(settings, "OPENAI_FERNET_KEYS", [])
    if isinstance(configured, str):
        configured = [configured]
    if not configured:
        raise OpenAIKeyConfigError("尚未配置 OPENAI_FERNET_KEYS，不能保存 OpenAI Key。")
    try:
        return MultiFernet([Fernet(item.encode("ascii") if isinstance(item, str) else item) for item in configured])
    except (TypeError, ValueError) as exc:
        raise OpenAIKeyConfigError("OPENAI_FERNET_KEYS 格式无效。") from exc


def encrypt_key(value: str) -> str:
    value = value.strip()
    if not value:
        raise OpenAIKeyConfigError("OpenAI Key 不能为空。")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_key(ciphertext: str) -> str:
    if not ciphertext:
        raise OpenAIKeyConfigError("OpenAI Key 尚未配置。")
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise OpenAIKeyConfigError("OpenAI Key 无法解密，请重新保存。") from exc


def key_metadata(value: str) -> tuple[str, str]:
    value = value.strip()
    if not value:
        raise OpenAIKeyConfigError("OpenAI Key 不能为空。")
    return value[-4:], hashlib.sha256(value.encode("utf-8")).hexdigest()

