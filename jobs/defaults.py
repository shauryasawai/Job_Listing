"""Fallback values for every aggregator setting.

If jobagg/settings.py is older than the app code (e.g. only the jobs/ folder was updated), missing settings are
filled in from here, still honouring .env / environment variables, instead of crashing with AttributeError.
`manage.py check` / `runserver` prints a warning listing what was missing so settings.py can be updated."""
import os

APP_DEFAULTS = {
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4o-mini",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_PRICE_IN_PER_1M": 0.0,
    "OPENAI_PRICE_OUT_PER_1M": 0.0,
    "SUMMARY_MAX_INPUT_CHARS": 12000,
    "SUMMARY_DAILY_CAP_PER_USER": 30,
    "SUMMARY_DAILY_CAP_GLOBAL": 100,
    "JOB_COUNTRY_FILTER": "IN",
    "MAX_JOBS_PER_COMPANY": 100,
    "DAILY_FETCH_TIME": "02:00",
    "RUN_MODE": "thread",
    "STALE_RUN_MINUTES": 30,
    "SOURCE_DELAY_SECONDS": 1.0,
    "MISSING_CHECKS_BEFORE_CLOSED": 3,
    "GREENHOUSE_API_BASE": "https://boards-api.greenhouse.io",
    "LEVER_API_BASE": "https://api.lever.co",
    "LEVER_API_BASE_EU": "https://api.eu.lever.co",
    "HTTP_CONNECT_TIMEOUT": 10,
    "HTTP_READ_TIMEOUT": 45,
    "HTTP_MAX_ATTEMPTS": 3,
    "CONTACT_URL": "https://example.com/contact",
    "BRAND_LOGO_URL": "https://www.marketscope.in/_next/image?url=%2Fimg%2Flogo-marketscope.jpeg&w=96&q=75",
}

MISSING = []  # filled by apply_defaults(); reported by the system check


def _from_env(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        if isinstance(default, bool):
            return raw.lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
    except ValueError:
        return default
    return raw


def apply_defaults(settings_obj):
    """Set any missing aggregator setting on settings_obj. Returns the list of names that were missing."""
    missing = []
    for name, default in APP_DEFAULTS.items():
        if not hasattr(settings_obj, name):
            value = _from_env(name, default)
            if name in ("JOB_COUNTRY_FILTER",):
                value = str(value).upper()
            if name.endswith("_BASE") or name.endswith("_BASE_EU") or name == "OPENAI_BASE_URL":
                value = str(value).rstrip("/")
            setattr(settings_obj, name, value)
            missing.append(name)
    if not hasattr(settings_obj, "USER_AGENT"):
        settings_obj.USER_AGENT = f"JobAggregatorBot/1.0 (+{settings_obj.CONTACT_URL})"
        missing.append("USER_AGENT")
    MISSING[:] = missing
    return missing
