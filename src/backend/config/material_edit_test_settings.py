"""20261029 原料属性编辑定向测试：隔离数据库、所有缓存和媒体。"""
from pathlib import Path

from .settings import *  # noqa: F403

DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_material_edit_20261029'}  # noqa: F405
MEDIA_ROOT = Path('/tmp/haiqu-material-edit-20261029/media')
CACHES = {
    alias: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': f'material-edit-20261029-{alias}'}
    for alias in CACHES  # noqa: F405
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
DEV_AUTO_LOGIN_ENABLED = False
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
