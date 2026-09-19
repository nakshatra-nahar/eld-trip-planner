"""Django settings for the stateless ELD trip-planner API.

Configuration comes from the environment, with development defaults:

    DJANGO_SECRET_KEY      secret key; required when DEBUG is off (a fixed dev key is used in DEBUG)
    DJANGO_DEBUG           "1"/"true" to enable debug (default: off; manage.py turns it on
                           for local commands such as runserver)
    ALLOWED_HOSTS          comma-separated hosts (default: localhost + .vercel.app)
    CORS_ALLOWED_ORIGINS   comma-separated origins (default: the Vite dev server)
    CORS_ALLOWED_ORIGIN_REGEXES  optional comma-separated regexes (e.g. Vercel previews)
    LOG_LEVEL              root log level (default INFO)
    PLAN_TIME_BUDGET_SECONDS  total upstream time budget for one plan request (default 25)
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# Off unless asked for, so any deployment (Vercel, Render, Docker) is safe by default.
DEBUG = env_bool("DJANGO_DEBUG", default=False)

# The API keeps no sessions or signed data, so the key protects little, but a deployment
# must still not run on a key that is published in the repository.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "django-insecure-dev-only-eld-trip-planner-key-change-me" if DEBUG else ""
)
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is off (set DJANGO_DEBUG=1 for local use).")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]", ".vercel.app"])

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",  # DRF's request.user machinery imports it; no tables are used
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = False  # URL patterns accept an optional trailing slash instead

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

# Stateless API: Django insists on a database, so configure an in-memory one that is
# never queried (Vercel's filesystem is read-only anyway).
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------- DRF

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "trips.views.api_exception_handler",
    # The API is public by design (a stateless calculator with no accounts or stored data), so
    # abuse is capped per client IP instead. Only views that set ``throttle_scope`` are limited:
    # trip planning (each call fans out to the routers) and the geocode autocomplete proxy.
    "DEFAULT_THROTTLE_CLASSES": ["trips.throttling.ClientScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "plan": os.environ.get("PLAN_RATE", "20/min"),
        "geocode": os.environ.get("GEOCODE_RATE", "60/min"),
    },
}

PLAN_TIME_BUDGET_SECONDS = float(os.environ.get("PLAN_TIME_BUDGET_SECONDS", "25"))

# ---------------------------------------------------------------- CORS

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"])
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES", [])
CORS_URLS_REGEX = r"^/api/.*$"

# ---------------------------------------------------------------- security (prod)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_SSL_REDIRECT = False  # the platform edge (Vercel) terminates TLS and redirects HTTP
    SILENCED_SYSTEM_CHECKS = [
        # No CSRF middleware: the API is stateless JSON with no cookies or session auth,
        # so there is no ambient credential for a cross-site request to ride on.
        "security.W003",
        # SSL redirect happens at the edge, before Django (see SECURE_SSL_REDIRECT).
        "security.W008",
        # HSTS includeSubDomains/preload would bind the whole parent domain; the API is
        # served from a platform subdomain we don't own, so both stay off.
        "security.W005",
        "security.W021",
    ]

# ---------------------------------------------------------------- logging

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "urllib3": {"level": "WARNING"},
    },
}
