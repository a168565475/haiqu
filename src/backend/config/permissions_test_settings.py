"""Isolated permissions QA database; never select the live database as TEST.NAME."""
from .settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {"NAME": "test_haiqu_access_stage2_20260928"}  # noqa: F405
ACCESS_MANAGEMENT_ENABLED = True
DEV_AUTO_LOGIN_ENABLED = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
