"""Fresh compatibility database retains migration seed data for legacy TestCases."""
from .permissions_stage5_test_settings import *  # noqa: F403
DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_access_stage5_compat_20260928'}  # noqa: F405
