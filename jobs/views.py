"""Dashboard shell + JSON API. All endpoints require an authenticated session."""
import json
import os
from urllib.parse import urlsplit
import re
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .adapters import ADAPTERS, get_adapter, parse_board_url
from .adapters.http import FetchError
from .geo import matches_country_filter
from .extract import experience_label
from .geo import REMOTE
from .models import FetchRun, Job, RoleSummary, Source, SourceRunResult, SummaryLog
from .quota import quota_for
from .runner import RunInProgress, cancel_run, create_run, release_stale_runs, start_in_thread
from . import summarizer

BOARD_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


# ------------------------------------------------------------------ helpers
def api(view):
    """JSON 401 instead of a login redirect for API calls."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required."}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def admin_api(view):
    @wraps(view)
    @api
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"error": "Administrator access required."}, status=403)
        return view(request, *args, **kwargs)

    return wrapper


def iso(dt):
    return dt.isoformat() if dt else None


def body_json(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def serialize_job(job, detail=False):
    data = {
        "id": job.pk,
        "title": job.title,
        "company": job.company_name,
        "source_id": job.source_id,
        "location": job.location,
        "employment_type": job.employment_type,
        "workplace_type": job.workplace_type,
        "department": job.department,
        "summary": job.summary if job.summary_status == Job.SUMMARY_AI else "",
        "summary_status": job.summary_status,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
        "experience": experience_label(job.experience_min, job.experience_max),
        "qualification": job.qualification,
        "cities": [c for c in job.cities.split(",") if c],
        "role_key": job.role_hash[:16],
        "sector": job.source.sector,
        "is_notice": job.source.adapter_key == Source.ADAPTER_NOTICE,
        "excerpt": "" if job.summary_status == Job.SUMMARY_AI else summarizer.excerpt(job.original_description),
        "job_url": job.job_url,
        "posted_at": iso(job.posted_at),
        "first_seen_at": iso(job.first_seen_at),
        "last_seen_at": iso(job.last_seen_at),
        "status": job.status,
    }
    if detail:
        data.update(
            description=job.original_description,
            external_job_id=job.external_job_id,
            source_updated_at=iso(job.source_updated_at),
            summary_model=job.summary_model,
            summarised_at=iso(job.summarised_at),
            updated_at=iso(job.updated_at),
            source={"id": job.source_id, "name": job.company_name, "careers_url": job.source.careers_url},
        )
    return data


def serialize_source(source, admin):
    data = {
        "id": source.pk,
        "company": source.company_name,
        "careers_url": source.careers_url,
        "adapter": source.adapter_key,
        "active": source.active,
        "last_status": source.last_status,
        "last_attempt_at": iso(source.last_attempt_at),
        "last_success_at": iso(source.last_success_at),
        "job_count": getattr(source, "job_count", None),
        "sector": source.sector,
    }
    if admin:
        data.update(board=source.board, region=source.region, last_error=source.last_error,
                    consecutive_failures=source.consecutive_failures,
                    notice_url=source.notice_url, pdf_only=source.pdf_only)
    return data


def serialize_run(run, with_results=False):
    data = {
        "id": run.pk,
        "trigger": run.trigger_type,
        "status": run.status,
        "is_active": run.is_active,
        "cancel_requested": run.cancel_requested,
        "current_step": run.current_step,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "completed_at": iso(run.completed_at),
        "total_sources": run.total_sources,
        "successful_sources": run.successful_sources,
        "failed_sources": run.failed_sources,
        "skipped_sources": run.skipped_sources,
        "jobs_discovered": run.jobs_discovered,
        "jobs_created": run.jobs_created,
        "jobs_updated": run.jobs_updated,
        "error_summary": run.error_summary,
        "triggered_by": run.triggered_by.get_username() if run.triggered_by_id else None,
    }
    if with_results:
        data["results"] = [
            {
                "source_id": r.source_id,
                "company": r.source.company_name,
                "status": r.status,
                "discovered": r.discovered_count,
                "created": r.created_count,
                "updated": r.updated_count,
                "skipped": r.skipped_count,
                "outside_country": r.filtered_count,
                "over_cap": r.trimmed_count,
                "closed": r.closed_count,
                "error": r.error_message,
                "warnings": r.warnings,
                "started_at": iso(r.started_at),
                "completed_at": iso(r.completed_at),
            }
            for r in run.results.select_related("source")
        ]
    return data


# ------------------------------------------------------------------ pages
@login_required
@ensure_csrf_cookie
def index(request):
    return render(request, "jobs/index.html", {"asset_version": asset_version()})


def asset_version():
    """Changes whenever app.js or app.css changes, so browsers load the new files instead of a cached old copy."""
    from django.contrib.staticfiles import finders

    stamps = []
    for name in ("jobs/js/app.js", "jobs/css/app.css"):
        path = finders.find(name)
        try:
            stamps.append(int(os.path.getmtime(path)))
        except (TypeError, OSError):
            pass
    return max(stamps) if stamps else 0


# ------------------------------------------------------------------ API
@require_GET
@api
def me(request):
    return JsonResponse({
        "username": request.user.get_username(),
        "email": request.user.email,
        "is_admin": request.user.is_staff,
        "ai_enabled": summarizer.ai_enabled(),
        "quota": quota_for(request.user),
        "country_filter": settings.JOB_COUNTRY_FILTER,
        "max_jobs_per_company": settings.MAX_JOBS_PER_COMPANY,
        "run_mode": settings.RUN_MODE,
        "daily_fetch_time": settings.DAILY_FETCH_TIME,
        "time_zone": settings.TIME_ZONE,
    })


@require_GET
@api
def jobs_list(request):
    p = request.GET
    qs = Job.objects.select_related("source")
    status = p.get("status", "active")
    if status in (Job.STATUS_ACTIVE, Job.STATUS_POSSIBLY_CLOSED, Job.STATUS_ARCHIVED):
        qs = qs.filter(status=status)
    q = p.get("q", "").strip()
    if q:
        for term in q.split()[:6]:
            qs = qs.filter(
                Q(title__icontains=term) | Q(company_name__icontains=term)
                | Q(location__icontains=term) | Q(summary__icontains=term)
            )
    if p.get("sector") in (Source.SECTOR_PRIVATE, Source.SECTOR_GOVERNMENT):
        qs = qs.filter(source__sector=p["sector"])
    if p.get("source", "").isdigit():
        qs = qs.filter(source_id=int(p["source"]))
    if p.get("employment_type"):
        qs = qs.filter(employment_type__iexact=p["employment_type"])
    if p.get("workplace_type"):
        qs = qs.filter(workplace_type__iexact=p["workplace_type"])
    if p.get("location", "").strip():
        qs = qs.filter(location__icontains=p["location"].strip())
    city = p.get("city", "").strip()
    if city:
        qs = qs.filter(cities__icontains=f",{city},")
    exp = p.get("experience", "").strip()
    if exp:
        if not exp.isdigit() or int(exp) > 50:
            return JsonResponse({"error": "experience must be a whole number of years."}, status=400)
        years = int(exp)
        fits = Q(experience_min__lte=years) & (Q(experience_max__gte=years) | Q(experience_max__isnull=True))
        unknown = Q(experience_min__isnull=True)
        if p.get("include_unspecified", "1") == "1":
            fits |= unknown
        elif years <= 1:
            fits |= unknown & Q(employment_type="Internship")  # internships rarely state experience
        qs = qs.filter(fits)
    if p.get("discovered", "").isdigit():
        qs = qs.filter(first_seen_at__gte=timezone.now() - timedelta(days=int(p["discovered"])))
    order = {"company": ("company_name", "title"), "title": ("title",)}.get(p.get("ordering"), ("-first_seen_at", "-id"))
    qs = qs.order_by(*order)

    try:
        size = max(1, min(int(p.get("page_size", 25)), 100))
        page_no = max(1, int(p.get("page", 1)))
    except ValueError:
        return JsonResponse({"error": "page and page_size must be integers."}, status=400)
    paginator = Paginator(qs, size)
    try:
        page = paginator.page(page_no)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    return JsonResponse({
        "count": paginator.count,
        "page": page.number,
        "page_size": size,
        "num_pages": paginator.num_pages,
        "results": [serialize_job(j) for j in page.object_list],
    })


@require_GET
@api
def job_detail(request, pk):
    job = get_object_or_404(Job.objects.select_related("source"), pk=pk)
    return JsonResponse(serialize_job(job, detail=True))


@require_GET
@api
def filters(request):
    base = Job.objects.filter(status=Job.STATUS_ACTIVE)
    companies = (
        base.values("source_id", "company_name").annotate(n=Count("id")).order_by("company_name")
    )
    return JsonResponse({
        "companies": [{"id": c["source_id"], "name": c["company_name"], "count": c["n"]} for c in companies],
        "sectors": {row["source__sector"]: row["n"] for row in base.values("source__sector").annotate(n=Count("id"))},
        "employment_types": sorted(set(base.exclude(employment_type="").values_list("employment_type", flat=True))),
        "workplace_types": sorted(set(base.exclude(workplace_type="").values_list("workplace_type", flat=True))),
        "cities": _city_counts(base),
    })


def _city_counts(qs):
    counts = {}
    for encoded in qs.exclude(cities="").values_list("cities", flat=True):
        for c in encoded.split(","):
            if c:
                counts[c] = counts.get(c, 0) + 1
    ordered = sorted((c for c in counts if c != REMOTE), key=lambda c: (-counts[c], c))
    if REMOTE in counts:
        ordered.append(REMOTE)
    return [{"name": c, "count": counts[c]} for c in ordered]


@require_GET
@api
def overview(request):
    release_stale_runs()
    now = timezone.now()
    last = FetchRun.objects.exclude(status__in=FetchRun.ACTIVE_STATUSES).first()
    active = FetchRun.objects.filter(active_marker=True).first()
    return JsonResponse({
        "jobs_active": Job.objects.filter(status=Job.STATUS_ACTIVE).count(),
        "jobs_possibly_closed": Job.objects.filter(status=Job.STATUS_POSSIBLY_CLOSED).count(),
        "jobs_new_24h": Job.objects.filter(first_seen_at__gte=now - timedelta(hours=24)).count(),
        "active_run": serialize_run(active) if active else None,
        "last_run": serialize_run(last) if last else None,
    })


def _sources_payload(request):
    qs = Source.objects.annotate(job_count=Count("jobs", filter=Q(jobs__status=Job.STATUS_ACTIVE)))
    return {
        "adapters": [{"key": k, "label": c.label} for k, c in ADAPTERS.items()],
        "results": [serialize_source(s, request.user.is_staff) for s in qs],
    }


@require_http_methods(["GET", "POST"])
@api
def sources(request):
    if request.method == "GET":
        return JsonResponse(_sources_payload(request))
    if not request.user.is_staff:
        return JsonResponse({"error": "Administrator access required."}, status=403)
    return _source_create(request)


def _valid_page_url(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc) and len(url) <= 500


def _config_from(data, current=None):
    """(adapter_key, configuration_json, error) from request data; current = existing Source or None."""
    adapter = data.get("adapter", current.adapter_key if current else Source.ADAPTER_NONE)
    if adapter == Source.ADAPTER_NONE:
        return adapter, {}, None
    if adapter not in ADAPTERS:
        return None, None, "Unknown adapter."
    if adapter == Source.ADAPTER_NOTICE:
        url = str(data.get("url", current.notice_url if current else "")).strip()
        if not _valid_page_url(url):
            return None, None, "Enter the full address of the official page that lists the notices (starting with https://)."
        pdf_only = bool(data.get("pdf_only", current.pdf_only if current else True))
        return adapter, {"url": url, "pdf_only": pdf_only}, None
    board = str(data.get("board", current.board if current else "")).strip()
    region = data.get("region", current.region if current else "global")
    if not BOARD_RE.match(board):
        return None, None, "Board/site name may contain only letters, digits, '-', '_' and '.'."
    if region not in ("global", "eu"):
        return None, None, "Region must be 'global' or 'eu'."
    return adapter, {"board": board, **({"region": "eu"} if adapter == Source.ADAPTER_LEVER and region == "eu" else {})}, None


NO_NOTICES_HINT = ("No recruitment notices were found on that page. Use the page that lists the notices themselves "
                   "(for example a 'Recruitment' or 'Advertisements' page), try unticking 'only PDF links', or use the "
                   "site's RSS feed. Pages that build their list with JavaScript can't be read.")


def _source_create(request):
    """Add a company (Greenhouse/Lever board link) or a government notice page. It is test-fetched first."""
    data = body_json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
    name = str(data.get("company_name", "")).strip()[:120]
    if not name:
        return JsonResponse({"error": "Enter the company or organisation name."}, status=400)
    if Source.objects.filter(company_name__iexact=name).exists():
        return JsonResponse({"error": f"{name} is already in the list."}, status=409)

    if data.get("kind") == "government":
        adapter_key, cfg, err = _config_from({"adapter": Source.ADAPTER_NOTICE, "url": data.get("url", ""),
                                              "pdf_only": data.get("pdf_only", True)})
        if err:
            return JsonResponse({"error": err}, status=400)
        if Source.objects.filter(adapter_key=adapter_key, configuration_json__url=cfg["url"]).exists():
            return JsonResponse({"error": "That page is already added under another name."}, status=409)
        source = Source(company_name=name, careers_url=cfg["url"], adapter_key=adapter_key,
                        configuration_json=cfg, sector=Source.SECTOR_GOVERNMENT)
    else:
        link = str(data.get("board_url", "")).strip()
        parsed = parse_board_url(link)
        if not parsed:
            return JsonResponse({"error": "Paste a Greenhouse link (boards.greenhouse.io/NAME) or a Lever link (jobs.lever.co/NAME)."}, status=400)
        adapter_key, board, region = parsed
        if Source.objects.filter(adapter_key=adapter_key, configuration_json__board=board).exists():
            return JsonResponse({"error": "That job board is already added under another name."}, status=409)
        cfg = {"board": board, **({"region": "eu"} if adapter_key == "lever" and region == "eu" else {})}
        source = Source(company_name=name, careers_url=link, adapter_key=adapter_key, configuration_json=cfg)
    try:
        jobs = get_adapter(source).fetch_jobs()
    except FetchError as exc:
        return JsonResponse({"error": f"Could not read that page: {exc}"}, status=400)
    if source.adapter_key == Source.ADAPTER_NOTICE and not jobs:
        return JsonResponse({"error": NO_NOTICES_HINT}, status=400)
    kept = sum(1 for j in jobs if matches_country_filter(j))
    source.save()
    payload = serialize_source(source, True)
    cap = settings.MAX_JOBS_PER_COMPANY
    payload.update(found=len(jobs), matching=kept, kept=min(kept, cap) if cap > 0 else kept,
                   sample=[j.title for j in jobs[:3]])
    return JsonResponse(payload, status=201)


@require_POST
@admin_api
def sources_bulk_active(request):
    """Turn collection on or off for many sources in one request: {"active": true|false, "ids": [1, 2, ...]}."""
    data = body_json(request)
    if data is None or not isinstance(data.get("active"), bool):
        return JsonResponse({"error": "Send active: true or false."}, status=400)
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return JsonResponse({"error": "ids must be a non-empty list of source ids."}, status=400)
    qs = Source.objects.filter(pk__in=set(ids))
    changed = qs.exclude(active=data["active"]).update(active=data["active"])
    return JsonResponse({"active": data["active"], "matched": qs.count(), "changed": changed})


@require_http_methods(["PATCH", "POST"])
@admin_api
def source_update(request, pk):
    source = get_object_or_404(Source, pk=pk)
    data = body_json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
    if "active" in data:
        source.active = bool(data["active"])
    if any(k in data for k in ("adapter", "board", "region", "url", "pdf_only")):
        adapter, cfg, err = _config_from(data, source)
        if err:
            return JsonResponse({"error": err}, status=400)
        source.adapter_key, source.configuration_json = adapter, cfg
        if adapter == Source.ADAPTER_NOTICE:
            source.sector = Source.SECTOR_GOVERNMENT
    if data.get("sector") in (Source.SECTOR_PRIVATE, Source.SECTOR_GOVERNMENT):
        source.sector = data["sector"]
    source.save()
    return JsonResponse(serialize_source(source, True))


@require_http_methods(["POST"])
@admin_api
def source_test(request, pk):
    """Dry-run one source: fetch and count, store nothing. Tests unsaved form values if given."""
    source = get_object_or_404(Source, pk=pk)
    data = body_json(request) or {}
    if data.get("adapter"):
        adapter, cfg, err = _config_from(data)
        if err or adapter == Source.ADAPTER_NONE:
            return JsonResponse({"ok": False, "error": err or "Choose an adapter first."})
        source = Source(company_name=source.company_name, adapter_key=adapter, configuration_json=cfg)  # unsaved
    adapter = get_adapter(source)
    if adapter is None:
        return JsonResponse({"ok": False, "error": "No adapter configured for this source."})
    try:
        jobs = adapter.fetch_jobs()
    except FetchError as exc:
        return JsonResponse({"ok": False, "error": str(exc)})
    if source.adapter_key == Source.ADAPTER_NOTICE and not jobs:
        return JsonResponse({"ok": False, "error": NO_NOTICES_HINT})
    return JsonResponse({"ok": True, "count": len(jobs), "sample": [j.title for j in jobs[:5]]})


@require_http_methods(["GET", "POST"])
@api
def fetch_runs(request):
    if request.method == "GET":
        release_stale_runs()
        runs = FetchRun.objects.select_related("triggered_by")[:30]
        return JsonResponse({"results": [serialize_run(r) for r in runs]})

    if not request.user.is_staff:
        return JsonResponse({"error": "Administrator access required."}, status=403)
    data = body_json(request) or {}
    ids = data.get("source_ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        return JsonResponse({"error": "source_ids must be a list of integers."}, status=400)
    try:
        run = create_run(FetchRun.TRIGGER_MANUAL, user=request.user, source_ids=ids or None)
    except RunInProgress as exc:
        return JsonResponse({"error": "A fetch is already in progress.", "run": serialize_run(exc.run)}, status=409)
    if settings.RUN_MODE == "thread":
        start_in_thread(run.pk)
    return JsonResponse(serialize_run(run), status=202)


@require_GET
@api
def fetch_run_detail(request, pk):
    run = get_object_or_404(FetchRun.objects.select_related("triggered_by"), pk=pk)
    return JsonResponse(serialize_run(run, with_results=True))


@require_POST
@admin_api
def fetch_run_cancel(request, pk):
    """Stop a fetch: released at once if nothing is running it, otherwise it stops before its next company."""
    run = get_object_or_404(FetchRun, pk=pk)
    outcome = cancel_run(run, request.user)
    run.refresh_from_db()
    body = serialize_run(run)
    body["outcome"] = outcome
    return JsonResponse(body)


@require_POST
@api
def job_summary(request, pk):
    """AI summary for ONE job, on the user's request. Summaries are stored permanently per role:
    a role is summarised at most once, ever. Reuse is free and does not count toward the daily caps."""
    job = get_object_or_404(Job.objects.select_related("source"), pk=pk)

    def reply(reused=False, status=200):
        body = serialize_job(job, detail=True)
        body["quota"] = quota_for(request.user)
        body["reused"] = reused
        return JsonResponse(body, status=status)

    if job.source.adapter_key == Source.ADAPTER_NOTICE:
        return JsonResponse({"error": "Government notices are official documents: open the notice for eligibility, "
                                      "age limit and last date. AI summaries are not generated for them."}, status=400)
    if job.summary_status == Job.SUMMARY_AI and job.summary:
        return reply(reused=True)  # already stored: never regenerated
    stored = RoleSummary.objects.filter(role_hash=job.role_hash).first() if job.role_hash else None
    if stored:
        _apply_summary(job, stored)
        return reply(reused=True)

    if not summarizer.ai_enabled():
        return JsonResponse({"error": "AI summaries are turned off: no OpenAI API key is configured."}, status=503)
    if not job.original_description.strip():
        return JsonResponse({"error": "This posting has no description to summarise."}, status=400)

    # Reserve a slot first so concurrent clicks can't overshoot the cap.
    with transaction.atomic():
        log = SummaryLog.objects.create(user=request.user, job=job)
        q = quota_for(request.user)
        over = q["user_used"] > q["user_cap"] or q["global_used"] > q["global_cap"]
        if over:
            transaction.set_rollback(True)
    if over:
        who = "your" if q["user_used"] > q["user_cap"] else "the team's"
        return JsonResponse(
            {"error": f"Daily AI summary limit reached ({who} limit). It resets at midnight.", "quota": quota_for(request.user)},
            status=429,
        )
    try:
        result = summarizer.ai_summary(job.title, job.company_name, job.location, job.original_description)
    except summarizer.SummaryAuthError as exc:
        log.delete()
        return JsonResponse({"error": str(exc)}, status=503)
    except summarizer.SummaryError as exc:
        log.delete()
        return JsonResponse({"error": f"OpenAI could not summarise this job right now ({exc}). Try again."}, status=502)

    role_hash = job.role_hash or ""
    stored, _ = RoleSummary.objects.get_or_create(
        role_hash=role_hash or f"job-{job.pk}",
        defaults={"title": job.title[:300], "summary": result.text, "model": result.model},
    )  # if two people summarised the same role at the same moment, the first stored summary wins
    _apply_summary(job, stored)
    log.model, log.prompt_tokens, log.completion_tokens = result.model, result.prompt_tokens, result.completion_tokens
    log.save(update_fields=["model", "prompt_tokens", "completion_tokens"])
    return reply()


def _apply_summary(job, stored):
    """Attach a stored role summary to this job and to every other posting of the same role."""
    now = timezone.now()
    job.summary, job.summary_status, job.summary_model, job.summarised_at = stored.summary, Job.SUMMARY_AI, stored.model, now
    job.save(update_fields=["summary", "summary_status", "summary_model", "summarised_at", "updated_at"])
    if job.role_hash:
        Job.objects.filter(role_hash=job.role_hash).exclude(pk=job.pk).exclude(summary_status=Job.SUMMARY_AI).update(
            summary=stored.summary, summary_status=Job.SUMMARY_AI, summary_model=stored.model, summarised_at=now
        )
