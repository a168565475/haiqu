"""Stage 6 browser QA only; never points at the ERP business database."""
from .access_preview_settings import *  # noqa: F403
DATABASES['default']['NAME'] = 'test_haiqu_access_stage6_20260928'  # noqa: F405
SALES_ACCESS_ENABLED = True
MODULE_ACCESS_ENABLED = True
SESSION_COOKIE_NAME = 'access_stage6_preview_session'
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8186', 'http://localhost:8186']
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
MEDIA_ROOT = BASE_DIR / '.tmp' / 'access-stage6-media'  # noqa: F405
