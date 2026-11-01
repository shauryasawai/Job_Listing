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


def get_json(url, params=None):
    """GET a URL and return parsed JSON. Retries transient failures (429/5xx/network)."""
    attempts = settings.HTTP_MAX_ATTEMPTS
    last_error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            resp = _get_session().get(
                url,
                params=params,
                timeout=(settings.HTTP_CONNECT_TIMEOUT, settings.HTTP_READ_TIMEOUT),
            )
        except requests.RequestException as exc:
            last_error = f"network error: {exc.__class__.__name__}"
            log.warning("GET %s attempt %d/%d failed: %s", url, attempt, attempts, last_error)
        else:
            code = resp.status_code
            if code == 200:
                try:
                    return resp.json()
                except ValueError:
                    raise FetchError(f"{url} returned a non-JSON response")
            if code == 404:
                raise NotFoundError(f"Not found (404): {url}")
            if code in (401, 403):
                raise BlockedError(
                    f"Access refused (HTTP {code}). The portal does not allow this request; "
                    "disable the source or ask the employer for permission/API access."
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
