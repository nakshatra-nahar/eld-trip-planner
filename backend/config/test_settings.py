"""Settings for the test suite: production settings (DEBUG off) with a throwaway key."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")

from .settings import *  # noqa: F403
