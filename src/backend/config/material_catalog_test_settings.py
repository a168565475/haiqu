"""原料管理专用隔离测试库，不选择正式业务库作为测试库。"""
from .settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {  # noqa: F405
    "NAME": "test_haiqu_material_catalog_20261016_61f3347a",
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEV_AUTO_LOGIN_ENABLED = False
