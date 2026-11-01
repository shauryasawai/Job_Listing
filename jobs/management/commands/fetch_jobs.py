from django.core.management.base import BaseCommand

from jobs.models import FetchRun
from jobs.runner import RunInProgress, create_run, execute_run


class Command(BaseCommand):
    help = "Run one collection now, synchronously (cron-friendly: `0 2 * * * python manage.py fetch_jobs`)."

    def add_arguments(self, parser):
        parser.add_argument("--manual", action="store_true", help="Record the run as manual instead of scheduled.")

    def handle(self, *args, **opts):
        trigger = FetchRun.TRIGGER_MANUAL if opts["manual"] else FetchRun.TRIGGER_SCHEDULED
        try:
            run = create_run(trigger)
        except RunInProgress as exc:
            self.stdout.write(self.style.WARNING(f"Not started: {exc}"))
            return
        run = execute_run(run.pk)
        self.stdout.write(
            f"Run #{run.pk} {run.status}: {run.successful_sources} ok, {run.failed_sources} failed, "
            f"{run.skipped_sources} skipped; {run.jobs_created} new, {run.jobs_updated} updated"
        )
        if run.error_summary:
            self.stdout.write(run.error_summary)
