"""Stage 5 isolated browser verification; never uses business data."""
from .access_preview_settings import *  # noqa: F403
DATABASES['default']['NAME'] = 'test_haiqu_access_stage5_20260928'  # noqa: F405
SALES_ACCESS_ENABLED = True
MODULE_ACCESS_ENABLED = True
SESSION_COOKIE_NAME = 'access_stage5_preview_session'
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8185', 'http://localhost:8185']
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
MEDIA_ROOT = BASE_DIR / '.tmp' / 'access-stage5-media'  # noqa: F405
