"""Independent stage 5 test database. No business data initialization."""
from .permissions_test_settings import *  # noqa: F403

DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_access_stage5_20260928'}  # noqa: F405
