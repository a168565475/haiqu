"""Stage 4 regression database, separate from stage 3 browser fixtures."""
from .permissions_test_settings import *  # noqa: F403

DATABASES["default"]["TEST"] = {"NAME": "test_haiqu_access_stage4_20260928"}  # noqa: F405
