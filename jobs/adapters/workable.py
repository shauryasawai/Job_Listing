"""Workable public jobs widget  (the feed behind every apply.workable.com careers page)

GET https://apply.workable.com/api/v1/widget/accounts/{subdomain}?details=true
Returns the account's published jobs, with descriptions, in ONE request. No key needed.
"""
from django.conf import settings
from django.utils.dateparse import parse_date, parse_datetime
from datetime import datetime, time, timezone

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import clean_text, html_to_text


def _when(value):
    if not value:
        return None
    dt = parse_datetime(value)
    if dt:
        return dt
    d = parse_date(value[:10])
    return datetime.combine(d, time(), tzinfo=timezone.utc) if d else None


class WorkableAdapter(BaseAdapter):
    key = "workable"
    label = "Workable"

    def fetch_jobs(self):
        account = self.source.board
        if not account:
            raise FetchError("No Workable account name configured for this source.")
        data = get_json(f"{settings.WORKABLE_API_BASE}/api/v1/widget/accounts/{account}", params={"details": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FetchError("Unexpected Workable response (no 'jobs' list).")
        out = []
        for item in data["jobs"]:
            if not isinstance(item, dict):
                continue
            main = ", ".join(p for p in (item.get("city"), item.get("state"), item.get("country")) if p)
            locations, country = [main], item.get("country") or ""
            for loc in item.get("locations") or []:
                if isinstance(loc, dict):
                    locations.append(", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p))
                    country = country or loc.get("countryCode") or ""
            parts = [html_to_text(item.get(k) or "") for k in ("description", "requirements", "benefits")]
            if item.get("education"):
                parts.append(f"Education: {item['education']}")
            out.append(RawJob(
                external_id=str(item.get("shortcode") or item.get("code") or "") or None,
                title=item.get("title") or "",
                url=item.get("url") or item.get("shortlink") or item.get("application_url") or "",
                description=clean_text("\n\n".join(p for p in parts if p)),
                location=main,
                locations=[l for l in dict.fromkeys(locations) if l],
                country=country,
                employment_type=item.get("employment_type") or "",
                workplace_type="remote" if item.get("telecommuting") else "",
                department=item.get("department") or item.get("function") or "",
                seniority=item.get("experience") or "",
                posted_at=_when(item.get("published_on") or item.get("created_at")),
            ))
        return out
