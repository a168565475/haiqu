"""Stage 4 browser QA only, isolated from the business database."""
from .access_preview_settings import *  # noqa: F403

DATABASES["default"]["NAME"] = "test_haiqu_access_stage4_20260928"  # noqa: F405
SALES_ACCESS_ENABLED = True
SESSION_COOKIE_NAME = "access_stage4_preview_session"
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8184", "http://localhost:8184"]
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
MEDIA_ROOT = BASE_DIR / ".tmp" / "access-stage4-media"  # noqa: F405
