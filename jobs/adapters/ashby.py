"""Ashby public Job Posting API  (https://developers.ashbyhq.com/docs/public-job-posting-api)

GET https://api.ashbyhq.com/posting-api/job-board/{job_board_name}
Returns every listed job, with its full description, in ONE request. No key needed.
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import clean_text, html_to_text

_TYPES = {"FullTime": "Full-time", "PartTime": "Part-time", "Intern": "Internship", "Contract": "Contract",
          "Temporary": "Contract"}


def _place(loc_name, address):
    post = (address or {}).get("postalAddress") or {}
    parts = [post.get("addressLocality"), post.get("addressRegion"), post.get("addressCountry")]
    text = ", ".join(p for p in parts if p)
    return text or (loc_name or ""), post.get("addressCountry") or ""


class AshbyAdapter(BaseAdapter):
    key = "ashby"
    label = "Ashby"

    def fetch_jobs(self):
        board = self.source.board
        if not board:
            raise FetchError("No Ashby job board name configured for this source.")
        data = get_json(f"{settings.ASHBY_API_BASE}/posting-api/job-board/{board}")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FetchError("Unexpected Ashby response (no 'jobs' list).")
        out = []
        for item in data["jobs"]:
            if not isinstance(item, dict) or item.get("isListed") is False:
                continue
            main, country = _place(item.get("location"), item.get("address"))
            locations = [item.get("location") or "", main]
            for sec in item.get("secondaryLocations") or []:
                if isinstance(sec, dict):
                    text, c = _place(sec.get("location"), sec.get("address"))
                    locations += [sec.get("location") or "", text]
                    country = country or c
            workplace = (item.get("workplaceType") or "").lower()
            if not workplace and item.get("isRemote"):
                workplace = "remote"
            published = item.get("publishedAt") or ""
            out.append(RawJob(
                external_id=str(item.get("id") or "") or None,
                title=item.get("title") or "",
                url=item.get("jobUrl") or item.get("applyUrl") or "",
                description=clean_text(item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml") or "")),
                location=item.get("location") or main,
                locations=[l for l in dict.fromkeys(locations) if l],
                country=country,
                employment_type=_TYPES.get(item.get("employmentType") or "", item.get("employmentType") or ""),
                workplace_type={"onsite": "on-site"}.get(workplace, workplace),
                department=item.get("department") or item.get("team") or "",
                posted_at=parse_datetime(published) if published else None,
            ))
        return out
