"""材料收发真实数据副本验收；禁止连接业务主库。"""
import os
from pathlib import Path

from config.settings import *  # noqa: F403

if os.environ.get("MATERIAL_TRANSFER_AUDIT_QA") != "20261112":
    raise RuntimeError("材料收发验收配置只允许显式启用。")

DATABASES["default"]["NAME"] = "qa_material_transfer_audit_20261112"
DATABASES["default"]["CONN_MAX_AGE"] = 0
CACHES = {alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                  "LOCATION": "material-transfer-audit-" + alias} for alias in CACHES}
MEDIA_ROOT = Path("/qa/tmp/media")
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEV_AUTO_LOGIN_ENABLED = False
PURCHASE_TRACKING_WECOM_ENABLED = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:18213", "http://127.0.0.1:18212"]
SESSION_COOKIE_NAME = "material_transfer_audit_session"
