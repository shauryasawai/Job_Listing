"""SmartRecruiters Posting API  (https://developers.smartrecruiters.com/docs/posting-api)

GET https://api.smartrecruiters.com/v1/companies/{company}/postings?country=in&limit=100&offset=N
    lists public postings (no key needed). The full job ad is a second call per posting:
GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}
Only postings in the configured country are listed, and descriptions are fetched for the newest
MAX_JOBS_PER_COMPANY of them, so a company costs a handful of calls rather than one per job worldwide.
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .base import BaseAdapter, RawJob
from .http import FetchError, get_json
from .text import clean_text, html_to_text

PAGE = 100
MAX_PAGES = 30
SECTIONS = ("jobDescription", "qualifications", "additionalInformation", "companyDescription")


def _label(value):
    return (value or {}).get("label") or "" if isinstance(value, dict) else ""


class SmartRecruitersAdapter(BaseAdapter):
    key = "smartrecruiters"
    label = "SmartRecruiters"
    with_details = True  # discovery turns this off: it only needs to count jobs

    def fetch_jobs(self):
        company = self.source.board
        if not company:
            raise FetchError("No SmartRecruiters company identifier configured for this source.")
        base = f"{settings.SMARTRECRUITERS_API_BASE}/v1/companies/{company}/postings"
        params = {"limit": PAGE}
        country = settings.JOB_COUNTRY_FILTER
        if country not in ("", "ALL"):
            params["country"] = country.lower()
        items, offset = [], 0
        for _ in range(MAX_PAGES):
            page = get_json(base, params={**params, "offset": offset})
            if not isinstance(page, dict) or not isinstance(page.get("content"), list):
                raise FetchError("Unexpected SmartRecruiters response (no 'content' list).")
            items += [i for i in page["content"] if isinstance(i, dict) and i.get("id")]
            offset += PAGE
            if len(page["content"]) < PAGE or offset >= (page.get("totalFound") or 0):
                break
        items.sort(key=lambda i: i.get("releasedDate") or "", reverse=True)
        cap = settings.MAX_JOBS_PER_COMPANY
        detail_ids = {i["id"] for i in (items[:cap] if cap > 0 else items)} if self.with_details else set()
        out = []
        for item in items:
            loc = item.get("location") or {}
            city_line = loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region")) if p)
            description, url = "", f"https://jobs.smartrecruiters.com/{company}/{item['id']}"
            if item["id"] in detail_ids:
                detail = get_json(f"{base}/{item['id']}")
                sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
                parts = []
                for key in SECTIONS:
                    sec = sections.get(key) or {}
                    body = html_to_text(sec.get("text") or "")
                    if body:
                        parts.append(f"{sec.get('title') or ''}\n{body}".strip())
                description = clean_text("\n\n".join(parts))
                url = (detail or {}).get("postingUrl") or url
            released = item.get("releasedDate") or ""
            out.append(RawJob(
                external_id=str(item["id"]),
                title=item.get("name") or "",
                url=url,
                description=description,
                location=city_line,
                locations=[city_line] if city_line else [],
                country=(loc.get("country") or "").upper(),
                employment_type=_label(item.get("typeOfEmployment")),
                workplace_type="remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else ""),
                department=_label(item.get("department")) or _label(item.get("function")),
                seniority=_label(item.get("experienceLevel")),
                posted_at=parse_datetime(released) if released else None,
            ))
        return out
