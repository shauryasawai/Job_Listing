"""Polite HTTP client: descriptive User-Agent, timeouts, bounded retries with backoff."""
import logging
import time

import requests
from django.conf import settings

log = logging.getLogger("jobs.http")


class FetchError(Exception):
    """Any failure collecting from a portal. The message is shown to administrators."""


class NotFoundError(FetchError):
    pass


class BlockedError(FetchError):
    pass


_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": settings.USER_AGENT, "Accept": "application/json"})
    return _session


MAX_PAGE_BYTES = 5 * 1024 * 1024


def _fetch(url, params=None, accept="application/json"):
    """GET with retries for transient failures (429/5xx/network). Returns the 200 response."""
    attempts = settings.HTTP_MAX_ATTEMPTS
    last_error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            resp = _get_session().get(
                url,
                params=params,
                headers={"Accept": accept},
                timeout=(settings.HTTP_CONNECT_TIMEOUT, settings.HTTP_READ_TIMEOUT),
            )
        except requests.exceptions.SSLError:
            # Never disable certificate checks; report it instead.
            raise FetchError(f"The site's security certificate could not be verified: {url}")
        except requests.RequestException as exc:
            last_error = f"network error: {exc.__class__.__name__}"
            log.warning("GET %s attempt %d/%d failed: %s", url, attempt, attempts, last_error)
        else:
            code = resp.status_code
            if code == 200:
                return resp
            if code == 404:
                raise NotFoundError(f"Not found (404): {url}")
            if code in (401, 403):
                raise BlockedError(
                    f"Access refused (HTTP {code}). The portal does not allow this request; "
                    "disable the source or ask the owner for permission/API access."
                )
            if code == 429 or code >= 500:
                last_error = f"HTTP {code}"
                log.warning("GET %s attempt %d/%d got %s", url, attempt, attempts, code)
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < attempts:
                    time.sleep(min(int(retry_after), 30))
                    continue
            else:
                raise FetchError(f"Unexpected HTTP {code} from {url}")
        if attempt < attempts:
            time.sleep(2 ** attempt)  # 2s, 4s
    raise FetchError(f"Gave up after {attempts} attempts ({last_error}): {url}")


def get_json(url, params=None):
    """GET a URL and return parsed JSON."""
    resp = _fetch(url, params)
    try:
        return resp.json()
    except ValueError:
        raise FetchError(f"{url} returned a non-JSON response")


def get_text(url):
    """GET an HTML page or RSS/Atom feed. Returns (text, content_type, final_url)."""
    resp = _fetch(url, accept="text/html,application/xhtml+xml,application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.5")
    if len(resp.content) > MAX_PAGE_BYTES:
        raise FetchError(f"Page is larger than {MAX_PAGE_BYTES // (1024 * 1024)} MB: {url}")
    ctype = resp.headers.get("Content-Type", "").lower()
    if "pdf" in ctype:
        raise FetchError("That link is a PDF, not a page that lists notices. Use the page that links to the PDFs.")
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text, ctype, resp.url
