"""Lever Postings API  (https://github.com/lever/postings-api)

GET https://api.lever.co/v0/postings/{site}?mode=json&skip=N&limit=M   (EU: api.eu.lever.co)
Paginated with skip/limit. Only published postings are returned.
"""
from datetime import datetime, timezone

from django.conf import settings

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import clean_text, html_to_text

PAGE = 100
MAX_PAGES = 100  # hard stop: 10,000 postings per site


def _description(item):
    parts = [item.get("descriptionPlain") or html_to_text(item.get("description") or "")]
    for block in item.get("lists") or []:
        heading = block.get("text") or ""
        body = html_to_text(block.get("content") or "")
        parts.append(f"{heading}\n{body}".strip())
    parts.append(item.get("additionalPlain") or html_to_text(item.get("additional") or ""))
    return clean_text("\n\n".join(p for p in parts if p))


class LeverAdapter(BaseAdapter):
    key = "lever"
    label = "Lever"

    def fetch_jobs(self):
        site = self.source.board
        if not site:
            raise FetchError("No Lever site name configured for this source.")
        base = (settings.LEVER_API_BASE_EU if self.source.region == "eu" else settings.LEVER_API_BASE) + "/v0/postings"
        out, skip = [], 0
        for _ in range(MAX_PAGES):
            page = get_json(f"{base}/{site}", params={"mode": "json", "skip": skip, "limit": PAGE})
            if not isinstance(page, list):
                raise FetchError("Unexpected Lever response (expected a list of postings).")
            for item in page:
                if not isinstance(item, dict):
                    continue
                cats = item.get("categories") or {}
                workplace = (item.get("workplaceType") or "").lower()
                created = item.get("createdAt")
                out.append(
                    RawJob(
                        external_id=item.get("id"),
                        title=item.get("text") or "",
                        url=item.get("hostedUrl") or "",
                        description=_description(item),
                        location=cats.get("location") or "",
                        locations=list(cats.get("allLocations") or []),
                        country=item.get("country") or "",
                        employment_type=cats.get("commitment") or "",
                        department=cats.get("department") or cats.get("team") or "",
                        workplace_type="" if workplace in ("", "unspecified") else workplace,
                        posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                        if isinstance(created, (int, float))
                        else None,
                    )
                )
            if len(page) < PAGE:
                break
            skip += PAGE
        return out
