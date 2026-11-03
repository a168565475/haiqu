"""2026-10-29 管材公式真实浏览器验收的显式隔离配置。"""
import os
import tempfile
from pathlib import Path

from config.settings import *  # noqa: F403

if os.environ.get("TUBE_FORMULA_BROWSER_QA") != "20261029":
    raise RuntimeError("隔离浏览器配置需要显式设置本任务标记。")

TUBE_FORMULA_BROWSER_ROOT = Path("/app/_tmp/tube-formula-browser-20261029")
DATABASES["default"]["NAME"] = "postgres"
DATABASES["default"]["TEST"]["NAME"] = "test_haiqu_tube_browser_20261029"
DATABASES["default"]["CONN_MAX_AGE"] = 0
MEDIA_ROOT = TUBE_FORMULA_BROWSER_ROOT / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TUBE_FORMULA_BROWSER_ROOT)
CACHES = {alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tube-browser-" + alias}
          for alias in CACHES}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
FILE_VIRUS_SCAN_ENABLED = False
DEV_AUTO_LOGIN_ENABLED = False
ACCESS_MANAGEMENT_ENABLED = False
SALES_ACCESS_ENABLED = False
MODULE_ACCESS_ENABLED = False
ACCESS_RESOURCE_SCOPES_ENABLED = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080",
                        "http://localhost:18029", "http://127.0.0.1:18029"]
