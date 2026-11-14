"""Diagnose OpenAI summary problems without spending tokens: which key is loaded, from where, and whether
OpenAI accepts it for the configured model (GET /models/{model} is free)."""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.summarizer import explain_openai_error


def mask(key):
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "(too short to be a real key)"


class Command(BaseCommand):
    help = "Check the OpenAI key and model used for AI summaries (free: no tokens are used)."

    def handle(self, *args, **opts):
        key = settings.OPENAI_API_KEY or ""
        source = getattr(settings, "OPENAI_API_KEY_SOURCE", "unknown")
        out = self.stdout
        out.write(f"Key loaded from : {source}")
        if not key:
            out.write(self.style.ERROR("No key: set OPENAI_API_KEY=sk-... in .env (next to manage.py) and restart the server."))
            return
        out.write(f"Key             : {mask(key)}  ({len(key)} characters)")
        problems = []
        if not key.startswith("sk-"):
            problems.append("it doesn't start with 'sk-'")
        if any(c.isspace() for c in key):
            problems.append("it contains spaces or line breaks")
        if any(c in key for c in "\"'#<>"):
            problems.append("it contains quotes, '#' or angle brackets (copied with extra text?)")
        if not key.isascii():
            problems.append("it contains non-ASCII characters (copied from a formatted document?)")
        for p in problems:
            out.write(self.style.WARNING(f"Suspicious key: {p}."))
        if "OVERRIDES" in source:
            out.write(self.style.WARNING(
                "An OPENAI_API_KEY environment variable is set in Windows/your shell, so the value in .env is IGNORED. "
                "Remove it (Windows: Settings → System → About → Advanced system settings → Environment Variables, "
                "or `setx OPENAI_API_KEY \"\"` then open a new terminal), or put the correct key there."))
        out.write(f"Model           : {settings.OPENAI_MODEL}")
        out.write(f"API base URL    : {settings.OPENAI_BASE_URL}")
        try:
            resp = requests.get(f"{settings.OPENAI_BASE_URL}/models/{settings.OPENAI_MODEL}",
                                headers={"Authorization": f"Bearer {key}"}, timeout=(10, 30))
        except requests.RequestException as exc:
            out.write(self.style.ERROR(f"Could not reach OpenAI: {exc.__class__.__name__}. Check your internet/proxy/firewall."))
            return
        if resp.status_code == 200:
            out.write(self.style.SUCCESS(f"OK: OpenAI accepts this key and the model '{settings.OPENAI_MODEL}' is available."))
            out.write("If summaries still fail, the account may be out of credit (HTTP 429 insufficient_quota): check billing.")
        else:
            out.write(self.style.ERROR(explain_openai_error(resp)))
