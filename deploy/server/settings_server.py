"""服务器部署设置；业务功能开关继续继承原有环境配置。"""

import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("django-insecure", "REPLACE_")):
    raise ImproperlyConfigured("服务器必须配置独立且至少 50 字符的 DJANGO_SECRET_KEY。")

DEBUG = False
ALLOWED_HOSTS = ["erp.cnhitree.com", "localhost", "127.0.0.1", "backend"]
CSRF_TRUSTED_ORIGINS = ["https://erp.cnhitree.com"]
CORS_ALLOWED_ORIGINS = []

# 外层 Nginx 负责 TLS，内层代理保留其协议头；后端端口不发布到宿主机。
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_DOMAIN = None

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405
