"""Normalisation, de-duplication and upsert of collected jobs."""
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from .adapters.text import clean_text
from .geo import matches_country_filter
from .models import Job

_TRACKING = re.compile(r"^(utm_|gh_src|gh_jid_src|lever-source|ref$|source$)", re.I)
CHUNK = 400


def canonical_url(url):
    """http(s) only; lower-case host; drop fragment, tracking params and trailing slash."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


@dataclass
class NormalisedJob:
    dedupe_key: str
    external_job_id: str
    title: str
    location: str
    employment_type: str
    workplace_type: str
    department: str
    seniority: str
    description: str
    url: str
    posted_at: object
    source_updated_at: object
    content_hash: str


_INTERN = re.compile(r"\b(interns?|internships?|trainees?|apprentices?)\b", re.I)


def normalise_employment_type(raw_type, title):
    """Map platform wording to a small, filterable set. A title like 'SDE Intern' wins."""
    t = (raw_type or "").lower()
    if _INTERN.search(title or "") or "intern" in t:
        return "Internship"
    if "full" in t:
        return "Full-time"
    if "part" in t:
        return "Part-time"
    if any(w in t for w in ("contract", "temp", "freelance", "consult")):
        return "Contract"
    return (raw_type or "").strip()[:80]


def _clip(value, length):
    return clean_text(value or "").replace("\n", " ")[:length]


def normalise(raw):
    """Return a NormalisedJob, or None if the record is unusable."""
    title = _clip(raw.title, 300)
    url = canonical_url(raw.url)
    if not title or not url:
        return None
    description = clean_text(raw.description)[:100_000]
    location = _clip(raw.location, 300)
    ext = _clip(raw.external_id, 200) if raw.external_id else ""
    if ext:
        key = f"id:{ext}"
    else:
        key = f"url:{url}"[:600]
    digest = hashlib.sha256(f"{title}\n{location}\n{description}".encode("utf-8")).hexdigest()
    return NormalisedJob(
        dedupe_key=key,
        external_job_id=ext,
        title=title,
        location=location,
        employment_type=normalise_employment_type(_clip(raw.employment_type, 80), title),
        workplace_type=_clip(raw.workplace_type, 40),
        department=_clip(raw.department, 200),
        seniority=_clip(raw.seniority, 80),
        description=description,
        url=url,
        posted_at=raw.posted_at,
        source_updated_at=raw.source_updated_at,
        content_hash=digest,
    )


_WORD = re.compile(r"\w+")


def similarity(a, b):
    """Jaccard similarity of word sets: fast and good enough to detect material rewrites."""
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    if not wa and not wb:
        return 1.0
    return len(wa & wb) / len(wa | wb)


def is_material_change(job, new):
    if job.title != new.title:
        return True
    return similarity(job.original_description, new.description) < settings.MATERIAL_CHANGE_THRESHOLD


@dataclass
class UpsertStats:
    discovered: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    filtered: int = 0  # dropped by the country filter
    closed: int = 0
    warning: str = ""


def _chunks(seq, size=CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def upsert_jobs(source, raw_jobs):
    """Insert/update jobs for one source and age-out jobs that disappeared."""
    now = timezone.now()
    stats = UpsertStats(discovered=len(raw_jobs))
    existing = {j.dedupe_key: j for j in Job.objects.filter(source=source)}
    seen, unchanged_ids, to_create, to_update = set(), [], [], []

    for raw in raw_jobs:
        if not matches_country_filter(raw):
            stats.filtered += 1
            continue
        n = normalise(raw)
        if n is None or n.dedupe_key in seen:
            stats.skipped += 1
            continue
        seen.add(n.dedupe_key)
        job = existing.get(n.dedupe_key)
        if job is None:
            to_create.append(
                Job(
                    source=source,
                    dedupe_key=n.dedupe_key,
                    external_job_id=n.external_job_id,
                    title=n.title,
                    company_name=source.company_name,
                    location=n.location,
                    employment_type=n.employment_type,
                    workplace_type=n.workplace_type,
                    department=n.department,
                    seniority=n.seniority,
                    original_description=n.description,
                    job_url=n.url,
                    posted_at=n.posted_at,
                    source_updated_at=n.source_updated_at,
                    first_seen_at=now,
                    last_seen_at=now,
                    content_hash=n.content_hash,
                )
            )
            stats.created += 1
        elif job.content_hash == n.content_hash and job.job_url == n.url:
            unchanged_ids.append(job.pk)
        else:
            material = is_material_change(job, n)
            job.title, job.location, job.job_url = n.title, n.location, n.url
            job.employment_type, job.workplace_type = n.employment_type, n.workplace_type
            job.department, job.seniority = n.department, n.seniority
            job.original_description = n.description
            job.posted_at = n.posted_at or job.posted_at
            job.source_updated_at = n.source_updated_at
            job.content_hash = n.content_hash
            job.last_seen_at, job.missed_checks, job.status = now, 0, Job.STATUS_ACTIVE
            if material and job.summary_status == Job.SUMMARY_AI:
                job.summary_stale = True  # the user can regenerate; we never do it automatically
            to_update.append(job)
            stats.updated += 1

    missing_ids = [j.pk for k, j in existing.items() if k not in seen]
    if not raw_jobs and existing:
        # An empty feed for a source that previously had jobs is more likely an outage
        # than every job closing at once: don't age anything out.
        stats.warning = "Portal returned 0 jobs although jobs were stored before; skipped closing check."
        missing_ids = []

    from django.db import transaction

    with transaction.atomic():
        Job.objects.bulk_create(to_create, batch_size=200)
        if to_update:
            Job.objects.bulk_update(
                to_update,
                [
                    "title", "location", "job_url", "employment_type", "workplace_type", "department",
                    "seniority", "original_description", "posted_at", "source_updated_at", "content_hash",
                    "last_seen_at", "missed_checks", "status", "summary_stale",
                ],
                batch_size=100,
            )
        for chunk in _chunks(unchanged_ids):
            Job.objects.filter(pk__in=chunk).update(last_seen_at=now, missed_checks=0, status=Job.STATUS_ACTIVE)
        for chunk in _chunks(missing_ids):
            Job.objects.filter(pk__in=chunk).update(missed_checks=F("missed_checks") + 1)
            stats.closed += Job.objects.filter(
                pk__in=chunk,
                status=Job.STATUS_ACTIVE,
                missed_checks__gte=settings.MISSING_CHECKS_BEFORE_CLOSED,
            ).update(status=Job.STATUS_POSSIBLY_CLOSED)
    return stats
