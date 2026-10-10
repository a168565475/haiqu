from .permissions_scopes_test_settings import *  # noqa: F403
DATABASES['default']['NAME'] = 'test_haiqu_access_scopes_20260929'  # noqa: F405
SESSION_COOKIE_NAME = 'access_scopes_preview_session'
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8187', 'http://localhost:8187']
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
MEDIA_ROOT = BASE_DIR / '.tmp' / 'access-scopes-media'  # noqa: F405
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
