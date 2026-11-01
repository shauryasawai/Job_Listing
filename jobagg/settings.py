"""Django settings for the Job Portal Aggregator."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Tiny .env loader (no extra dependency). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- core
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jobagg.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "jobagg.wsgi.application"

if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 30},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# ---------------------------------------------------------------- security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    # Turn these on once the site is served over HTTPS (behind a TLS-terminating proxy, keep the header line).
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
    if env_bool("DJANGO_BEHIND_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------- aggregator
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_PRICE_IN_PER_1M = float(env("OPENAI_PRICE_IN_PER_1M", "0") or 0)
OPENAI_PRICE_OUT_PER_1M = float(env("OPENAI_PRICE_OUT_PER_1M", "0") or 0)
SUMMARY_MAX_INPUT_CHARS = int(env("SUMMARY_MAX_INPUT_CHARS", "12000"))
# AI summaries are NEVER generated automatically; a user asks for each one.
# Daily caps (reset at local midnight, TIME_ZONE). 0 = no summaries allowed.
SUMMARY_DAILY_CAP_PER_USER = int(env("SUMMARY_DAILY_CAP_PER_USER", "30"))
SUMMARY_DAILY_CAP_GLOBAL = int(env("SUMMARY_DAILY_CAP_GLOBAL", "100"))

# Keep only jobs located in this country. "IN" (India, default) or "ALL" to keep everything.
JOB_COUNTRY_FILTER = env("JOB_COUNTRY_FILTER", "IN").upper()

DAILY_FETCH_TIME = env("DAILY_FETCH_TIME", "02:00")
RUN_MODE = env("RUN_MODE", "thread")  # "thread" | "queue"
STALE_RUN_MINUTES = int(env("STALE_RUN_MINUTES", "90"))

SOURCE_DELAY_SECONDS = float(env("SOURCE_DELAY_SECONDS", "1.0"))
MISSING_CHECKS_BEFORE_CLOSED = int(env("MISSING_CHECKS_BEFORE_CLOSED", "3"))
MATERIAL_CHANGE_THRESHOLD = float(env("MATERIAL_CHANGE_THRESHOLD", "0.95"))

# Override only for testing or when routing through a proxy/mirror.
GREENHOUSE_API_BASE = env("GREENHOUSE_API_BASE", "https://boards-api.greenhouse.io").rstrip("/")
LEVER_API_BASE = env("LEVER_API_BASE", "https://api.lever.co").rstrip("/")
LEVER_API_BASE_EU = env("LEVER_API_BASE_EU", "https://api.eu.lever.co").rstrip("/")

HTTP_CONNECT_TIMEOUT = 10
HTTP_READ_TIMEOUT = 45
HTTP_MAX_ATTEMPTS = 3
CONTACT_URL = env("CONTACT_URL", "https://example.com/contact")
USER_AGENT = f"JobAggregatorBot/1.0 (+{CONTACT_URL})"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "loggers": {"jobs": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
