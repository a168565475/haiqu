"""Isolated stage 6 integration and rollout rehearsal database."""
from .permissions_test_settings import *  # noqa: F403
DATABASES['default']['TEST'] = {'NAME': 'test_haiqu_access_stage6_20260928'}  # noqa: F405
