from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class CredentialError(Exception):
    code = "ENCRYPTION_UNAVAILABLE"
    message = "企业微信加密配置不可用，请管理员检查加密密钥并重新保存凭据。"

    def __init__(self):
        super().__init__(self.message)


@sensitive_variables()
def _fernet():
    keys = getattr(settings, "WECOM_FERNET_KEYS", [])
    if isinstance(keys, str):
        keys = [key.strip() for key in keys.split(",") if key.strip()]
    if not keys:
        raise CredentialError()
    try:
        return MultiFernet([Fernet(key.encode("ascii") if isinstance(key, str) else key) for key in keys])
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CredentialError() from exc


def encryption_ready():
    try:
        _fernet()
    except CredentialError:
        return False
    return True


@sensitive_variables()
def encrypt_secret(plaintext):
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise CredentialError()
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


@sensitive_variables()
def decrypt_secret(ciphertext):
    if not isinstance(ciphertext, str) or not ciphertext:
        raise CredentialError()
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise CredentialError() from exc
