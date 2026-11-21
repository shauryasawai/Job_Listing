"""Recruitee public Careers Site API

GET https://{company}.recruitee.com/api/offers/
Returns every published offer, with description and requirements, in ONE request. No key needed.
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import clean_text, html_to_text

_TYPES = {"fulltime": "Full-time", "parttime": "Part-time", "internship": "Internship", "contract": "Contract",
          "temporary": "Contract", "freelance": "Contract"}


def _when(value):
    if not value:
        return None
    return parse_datetime(value.replace(" UTC", "+00:00").replace(" ", "T", 1))


class RecruiteeAdapter(BaseAdapter):
    key = "recruitee"
    label = "Recruitee"

    def fetch_jobs(self):
        company = self.source.board
        if not company:
            raise FetchError("No Recruitee company name configured for this source.")
        data = get_json(settings.RECRUITEE_API_BASE.format(company=company) + "/api/offers/")
        if not isinstance(data, dict) or not isinstance(data.get("offers"), list):
            raise FetchError("Unexpected Recruitee response (no 'offers' list).")
        out = []
        for item in data["offers"]:
            if not isinstance(item, dict) or (item.get("status") not in (None, "published")):
                continue
            main = item.get("location") or ", ".join(p for p in (item.get("city"), item.get("country")) if p)
            locations, country = [main], item.get("country_code") or ""
            for loc in item.get("locations") or []:
                if isinstance(loc, dict):
                    locations.append(", ".join(p for p in (loc.get("city"), loc.get("state"), loc.get("country")) if p))
                    country = country or loc.get("country_code") or ""
            code = (item.get("employment_type_code") or "").split("_")[0].lower()
            out.append(RawJob(
                external_id=str(item.get("id") or "") or None,
                title=item.get("title") or "",
                url=item.get("careers_url") or "",
                description=clean_text("\n\n".join(html_to_text(item.get(k) or "") for k in ("description", "requirements"))),
                location=main,
                locations=[l for l in dict.fromkeys(locations) if l],
                country=country,
                employment_type=_TYPES.get(code, item.get("employment_type_code") or ""),
                workplace_type="remote" if item.get("remote") else ("hybrid" if item.get("hybrid") else ""),
                department=item.get("department") or "",
                seniority=item.get("experience_code") or "",
                posted_at=_when(item.get("published_at") or item.get("created_at")),
            ))
        return out
