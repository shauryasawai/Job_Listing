"""Adapter registry. To support a new portal/platform, add a class and register it here."""
import re
from urllib.parse import parse_qs, urlsplit

from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .notice_board import NoticeBoardAdapter

ADAPTERS = {cls.key: cls for cls in (GreenhouseAdapter, LeverAdapter, NoticeBoardAdapter)}


def get_adapter(source):
    cls = ADAPTERS.get(source.adapter_key)
    return cls(source) if cls else None


_GH_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"}
_LEVER_HOSTS = {"jobs.lever.co": "global", "jobs.eu.lever.co": "eu"}
_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def parse_board_url(url):
    """'https://jobs.lever.co/acme/123' -> ('lever', 'acme', 'global'); None if not a Greenhouse/Lever board link."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    segs = [x for x in parts.path.split("/") if x]
    token = None
    if host in _GH_HOSTS:
        if segs[:1] == ["embed"]:  # boards.greenhouse.io/embed/job_board?for=acme
            token = (parse_qs(parts.query).get("for") or [None])[0]
        else:
            token = segs[0] if segs else None
        adapter, region = "greenhouse", "global"
    elif host in _LEVER_HOSTS:
        token = segs[0] if segs else None
        adapter, region = "lever", _LEVER_HOSTS[host]
    else:
        return None
    return (adapter, token, region) if token and _TOKEN.match(token) else None
