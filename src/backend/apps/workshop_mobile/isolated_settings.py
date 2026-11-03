"""手机车间定向测试专用；不得用于运行开发或正式服务或默认测试发现。"""
from pathlib import Path

from config.settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {"NAME": "test_haiqu_mobile_workshop_20261031_backend"}  # noqa: F405
MEDIA_ROOT = Path("/app/_tmp/mobile_workshop_20261031_backend_media")
CACHES = {name: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"} for name in CACHES}  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
