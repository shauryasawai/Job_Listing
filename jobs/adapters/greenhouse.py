"""Greenhouse Job Board API  (https://docs.greenhouse.io/job-board)

GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
returns every published job (with description, departments, offices) in ONE request,
so a full collection costs a single call per company.
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import html_to_text, unescape_html_content



class GreenhouseAdapter(BaseAdapter):
    key = "greenhouse"
    label = "Greenhouse"

    def fetch_jobs(self):
        board = self.source.board
        if not board:
            raise FetchError("No Greenhouse board token configured for this source.")
        data = get_json(f"{settings.GREENHOUSE_API_BASE}/v1/boards/{board}/jobs", params={"content": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise FetchError("Unexpected Greenhouse response (no 'jobs' key).")
        out = []
        for item in data["jobs"]:
            if not isinstance(item, dict):
                continue
            # Prospect posts ("general application") have no internal_job_id: not real openings.
            if item.get("internal_job_id") is None:
                continue
            location = (item.get("location") or {}).get("name") or ""
            extra = []
            for office in item.get("offices") or []:
                extra += [office.get("location") or "", office.get("name") or ""]
            departments = ", ".join(d.get("name", "") for d in item.get("departments") or [] if d.get("name"))
            description = html_to_text(unescape_html_content(item.get("content") or ""))
            updated = item.get("updated_at")
            out.append(
                RawJob(
                    external_id=str(item["id"]) if item.get("id") is not None else None,
                    title=item.get("title") or "",
                    url=item.get("absolute_url") or "",
                    description=description,
                    location=location,
                    locations=[x for x in extra if x],
                    department=departments,
                    # The API has no workplace field; only record it when the location itself says so.
                    workplace_type="remote" if "remote" in location.lower() else "",
                    source_updated_at=parse_datetime(updated) if updated else None,
                )
            )
        return out
