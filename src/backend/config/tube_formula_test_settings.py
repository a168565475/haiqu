"""20261029 管材公式定向测试：独占 PostgreSQL、缓存与媒体目录。"""
from pathlib import Path

from .settings import *  # noqa: F403

DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_tube_formulas_20261029'}  # noqa: F405
MEDIA_ROOT = Path('/tmp/haiqu-tube-formulas-20261029/media')
CACHES = {
    alias: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': f'tube-formulas-20261029-{alias}'}
    for alias in CACHES  # noqa: F405
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
DEV_AUTO_LOGIN_ENABLED = False
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
