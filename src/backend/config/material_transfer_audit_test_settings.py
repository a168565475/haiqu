"""材料收发审核定向测试：独占数据库，缓存与邮件均隔离。"""
from .settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {"NAME": "test_material_transfer_audit_20261112_backend"}  # noqa: F405
CACHES = {
    alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": f"transfer-audit-{alias}"}
    for alias in CACHES  # noqa: F405
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEV_AUTO_LOGIN_ENABLED = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
