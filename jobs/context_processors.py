import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

LOGO_FILES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.svg")


def brand_logo():
    """URL of the logo: a file saved in jobs/static/jobs/img/ wins, else BRAND_LOGO_URL (may be empty)."""
    for name in LOGO_FILES:
        path = finders.find(f"jobs/img/{name}")
        if path:
            try:
                return f"{static('jobs/img/' + name)}?v={int(os.path.getmtime(path))}"
            except OSError:
                pass
    return getattr(settings, "BRAND_LOGO_URL", "") or ""


def assets(request):
    """Adds `asset_version` (cache-busting for app.css / app.js) and `brand_logo` to every template."""
    from .views import asset_version

    return {"asset_version": asset_version(), "brand_logo": brand_logo()}
