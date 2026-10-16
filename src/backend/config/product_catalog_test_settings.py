"""独立产品管理任务专用测试库；Django 默认创建并销毁，不复用业务库。"""
from .settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {  # noqa: F405
    "NAME": "test_haiqu_product_catalog_20261016_2ebd7b22",
}
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "configuration": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "product-catalog-test-configuration"},
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEV_AUTO_LOGIN_ENABLED = False
