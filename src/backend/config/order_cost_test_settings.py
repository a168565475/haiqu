"""订单成本任务的独占测试库和媒体、缓存隔离。"""
from pathlib import Path

from .settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {"NAME": "test_order_cost_20261026_397c"}  # noqa: F405
MEDIA_ROOT = Path("/tmp/order-cost-20261026-397c-media")
CACHES = {
    alias: {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": f"order-cost-20261026-397c-{alias}",
    }
    for alias in CACHES  # noqa: F405
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEV_AUTO_LOGIN_ENABLED = False
