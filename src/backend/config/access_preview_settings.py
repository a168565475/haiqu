"""Local browser acceptance only. Never points at the business database."""
from .settings import *  # noqa: F403

DATABASES["default"]["NAME"] = "test_haiqu_access_stage2_20260928"  # noqa: F405
ACCESS_MANAGEMENT_ENABLED = True
DEV_AUTO_LOGIN_ENABLED = False
SESSION_COOKIE_NAME = "access_preview_session"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8183", "http://localhost:8183"]
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
MEDIA_ROOT = BASE_DIR / ".tmp" / "access-stage3-media"  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
