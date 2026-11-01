"""Run orchestration: create/guard runs, collect per source, record results.
Summaries are NOT generated here: they are produced on demand (see views.job_summary)."""
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from .adapters import get_adapter
from .adapters.http import FetchError
from .models import FetchRun, Source, SourceRunResult
from .pipeline import upsert_jobs

log = logging.getLogger("jobs.runner")


class RunInProgress(Exception):
    def __init__(self, run):
        super().__init__(f"Run #{run.pk} is already {run.status}")
        self.run = run


# ------------------------------------------------------------------ creation / locking
def _release_stale_runs():
    cutoff = timezone.now() - timedelta(minutes=settings.STALE_RUN_MINUTES)
    FetchRun.objects.filter(active_marker=True, heartbeat_at__lt=cutoff).update(
        status=FetchRun.STATUS_FAILED,
        active_marker=None,
        completed_at=timezone.now(),
        error_summary="Run stopped responding (worker restarted or crashed) and was released.",
    )


def create_run(trigger, user=None, source_ids=None):
    """Create a queued run, or raise RunInProgress. The unique active_marker is the guard."""
    _release_stale_runs()
    try:
        with transaction.atomic():
            return FetchRun.objects.create(
                trigger_type=trigger,
                status=FetchRun.STATUS_QUEUED,
                active_marker=True,
                triggered_by=user if getattr(user, "is_authenticated", False) else None,
                source_ids=list(source_ids) if source_ids else None,
            )
    except IntegrityError:
        current = FetchRun.objects.filter(active_marker=True).first()
        if current is None:  # finished between the failed insert and the lookup: try once more
            return create_run(trigger, user, source_ids)
        raise RunInProgress(current)


def _claim(run_id):
    """Atomically move queued -> running. Returns the run, or None if someone else has it."""
    now = timezone.now()
    n = FetchRun.objects.filter(pk=run_id, status=FetchRun.STATUS_QUEUED).update(
        status=FetchRun.STATUS_RUNNING, started_at=now, heartbeat_at=now, current_step="Starting"
    )
    return FetchRun.objects.get(pk=run_id) if n else None


def _progress(run, step, **fields):
    run.current_step = step[:200]
    run.heartbeat_at = timezone.now()
    for k, v in fields.items():
        setattr(run, k, v)
    run.save(update_fields=["current_step", "heartbeat_at", *fields.keys()])


# ------------------------------------------------------------------ execution
def execute_run(run_id):
    """Execute a queued run. Safe to call from a thread, the worker, or the CLI."""
    run = _claim(run_id)
    if run is None:
        return None
    try:
        _execute(run)
    except Exception as exc:  # last-resort guard: never leave the lock held
        log.exception("Run %s crashed", run.pk)
        run.status = FetchRun.STATUS_FAILED
        run.error_summary = f"Run crashed: {exc.__class__.__name__}: {exc}"[:2000]
    finally:
        run.completed_at = timezone.now()
        run.current_step = ""
        run.active_marker = None
        run.save()
    log.info("Run %s finished: %s | created=%s updated=%s", run.pk, run.status, run.jobs_created, run.jobs_updated)
    return run


def _execute(run):
    qs = Source.objects.filter(active=True)
    if run.source_ids:
        qs = qs.filter(pk__in=run.source_ids)
    sources = list(qs.order_by("company_name"))
    run.total_sources = len(sources)
    run.save(update_fields=["total_sources"])

    errors = []
    for index, source in enumerate(sources, start=1):
        _progress(run, f"Collecting {source.company_name} ({index}/{len(sources)})")
        _collect_source(run, source, errors)
        if index < len(sources) and settings.SOURCE_DELAY_SECONDS > 0:
            time.sleep(settings.SOURCE_DELAY_SECONDS)

    if run.total_sources == 0:
        run.status = FetchRun.STATUS_COMPLETED
        errors.append("No active sources to collect.")
    elif run.successful_sources == 0 and run.failed_sources > 0:
        run.status = FetchRun.STATUS_FAILED
    elif run.failed_sources > 0:
        run.status = FetchRun.STATUS_WITH_ERRORS
    else:
        run.status = FetchRun.STATUS_COMPLETED
    if run.skipped_sources:
        errors.append(f"{run.skipped_sources} source(s) skipped: no adapter configured.")
    run.error_summary = "\n".join(errors)[:4000]


def _collect_source(run, source, errors):
    now = timezone.now()
    result = SourceRunResult.objects.create(fetch_run=run, source=source, started_at=now)
    source.last_attempt_at = now
    try:
        adapter = get_adapter(source)
        if adapter is None:
            result.status = SourceRunResult.STATUS_SKIPPED
            result.error_message = "No adapter configured for this source."
            source.last_status = Source.STATUS_SKIPPED
            source.last_error = result.error_message
            run.skipped_sources += 1
        else:
            raw_jobs = adapter.fetch_jobs()
            stats = upsert_jobs(source, raw_jobs)
            result.status = SourceRunResult.STATUS_SUCCESS
            result.discovered_count, result.created_count = stats.discovered, stats.created
            result.updated_count, result.skipped_count = stats.updated, stats.skipped
            result.filtered_count = stats.filtered
            result.closed_count, result.warnings = stats.closed, stats.warning
            source.last_status, source.last_error = Source.STATUS_SUCCESS, ""
            source.last_success_at, source.consecutive_failures = timezone.now(), 0
            run.successful_sources += 1
            run.jobs_discovered += stats.discovered
            run.jobs_created += stats.created
            run.jobs_updated += stats.updated
    except FetchError as exc:
        _mark_failed(run, source, result, str(exc), errors)
    except Exception as exc:  # one broken adapter must never stop the others
        log.exception("Unexpected error collecting %s", source.company_name)
        _mark_failed(run, source, result, f"Unexpected error ({exc.__class__.__name__}): {exc}", errors)
    finally:
        result.completed_at = timezone.now()
        result.save()
        source.save()
        run.save()
    log.info(
        "run=%s source=%s(%s) status=%s found=%s india_kept=%s new=%s updated=%s",
        run.pk, source.pk, source.company_name, result.status, result.discovered_count,
        result.discovered_count - result.filtered_count, result.created_count, result.updated_count,
    )


def _mark_failed(run, source, result, message, errors):
    message = message[:1000]
    result.status = SourceRunResult.STATUS_FAILED
    result.error_message = message
    source.last_status, source.last_error = Source.STATUS_FAILED, message
    source.consecutive_failures += 1
    run.failed_sources += 1
    errors.append(f"{source.company_name}: {message}")


# ------------------------------------------------------------------ entry points
def start_in_thread(run_id):
    def target():
        try:
            execute_run(run_id)
        finally:
            close_old_connections()

    threading.Thread(target=target, name=f"fetch-run-{run_id}", daemon=True).start()


def process_queue():
    """Execute every queued run (used by the worker)."""
    for run in FetchRun.objects.filter(status=FetchRun.STATUS_QUEUED).order_by("created_at"):
        execute_run(run.pk)


def maybe_schedule_daily():
    """Create today's scheduled run once the configured time has passed. Restart-safe."""
    hh, mm = (int(x) for x in settings.DAILY_FETCH_TIME.split(":"))
    now_local = timezone.localtime()
    due = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_local < due:
        return None
    if FetchRun.objects.filter(trigger_type=FetchRun.TRIGGER_SCHEDULED, created_at__gte=due).exists():
        return None
    try:
        return create_run(FetchRun.TRIGGER_SCHEDULED)
    except RunInProgress:
        return None  # retried on the next loop
