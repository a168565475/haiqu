"""Stage 2 tests use their own database and enable only isolated deletion QA."""
from .permissions_scopes_test_settings import *  # noqa: F403
DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_access_deletion_20260929'}  # noqa: F405
WORK_REPORT_DELETION_ENABLED = True
