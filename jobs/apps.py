from django.apps import AppConfig
from django.core import checks
from django.db.backends.signals import connection_created


def _sqlite_pragmas(sender, connection, **kwargs):
    # WAL lets the web process read while a background run writes.
    if connection.vendor == "sqlite":
        cur = connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "jobs"

    def ready(self):
        from django.conf import settings

        from .defaults import apply_defaults

        apply_defaults(settings)  # never crash on an outdated settings.py
        connection_created.connect(_sqlite_pragmas)
        checks.register(_check_settings_up_to_date)


def _check_settings_up_to_date(app_configs, **kwargs):
    from .defaults import MISSING

    if not MISSING:
        return []
    return [
        checks.Warning(
            "jobagg/settings.py is older than the jobs app: missing " + ", ".join(MISSING) + ".",
            hint="Built-in defaults (and your .env values) are being used. Replace jobagg/settings.py with the one "
                 "from the latest download to silence this warning.",
            id="jobs.W001",
        )
    ]
