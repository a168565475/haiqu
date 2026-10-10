"""Stage 1 scope extension: isolated database, no main-database migrations."""
from .permissions_test_settings import *  # noqa: F403
DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_access_scopes_20260929'}  # noqa: F405
ACCESS_RESOURCE_SCOPES_ENABLED = True
SALES_ACCESS_ENABLED = True
MODULE_ACCESS_ENABLED = True
