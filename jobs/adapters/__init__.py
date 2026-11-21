"""Adapter registry. To support a new portal/platform, add a class and register it here."""
import re
from urllib.parse import parse_qs, urlsplit

from .ashby import AshbyAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .notice_board import NoticeBoardAdapter
from .recruitee import RecruiteeAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .workable import WorkableAdapter

ADAPTERS = {cls.key: cls for cls in (GreenhouseAdapter, LeverAdapter, AshbyAdapter, SmartRecruitersAdapter,
                                     WorkableAdapter, RecruiteeAdapter, NoticeBoardAdapter)}


def get_adapter(source):
    cls = ADAPTERS.get(source.adapter_key)
    return cls(source) if cls else None


_GH_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"}
_LEVER_HOSTS = {"jobs.lever.co": "global", "jobs.eu.lever.co": "eu"}
_ASHBY_HOSTS = {"jobs.ashbyhq.com"}
_SR_HOSTS = {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}
_WORKABLE_HOSTS = {"apply.workable.com"}
_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def board_url(adapter, board, region="global"):
    """The public careers page for a board (what a person would open in a browser)."""
    return {
        "greenhouse": f"https://boards.greenhouse.io/{board}",
        "lever": f"https://{'jobs.eu.lever.co' if region == 'eu' else 'jobs.lever.co'}/{board}",
        "ashby": f"https://jobs.ashbyhq.com/{board}",
        "smartrecruiters": f"https://jobs.smartrecruiters.com/{board}",
        "workable": f"https://apply.workable.com/{board}/",
        "recruitee": f"https://{board}.recruitee.com/",
    }.get(adapter, "")


def parse_board_url(url):
    """'https://jobs.lever.co/acme/123' -> ('lever', 'acme', 'global'); None if not a supported job board link.
    Supported: Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Recruitee."""
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
    elif host in _ASHBY_HOSTS:
        token, adapter, region = (segs[0] if segs else None), "ashby", "global"
    elif host in _SR_HOSTS:
        token, adapter, region = (segs[0] if segs else None), "smartrecruiters", "global"
    elif host in _WORKABLE_HOSTS:
        token, adapter, region = (segs[0] if segs and segs[0] != "j" else None), "workable", "global"
    elif host.endswith(".recruitee.com") and host.count(".") == 2 and host.split(".")[0] not in ("www", "api", "app"):
        token, adapter, region = host.split(".")[0], "recruitee", "global"
    else:
        return None
    return (adapter, token, region) if token and _TOKEN.match(token) else None
