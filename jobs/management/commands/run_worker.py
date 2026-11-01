import time

from django.core.management.base import BaseCommand

from jobs.runner import maybe_schedule_daily, process_queue


class Command(BaseCommand):
    help = "Long-running worker: starts the daily run at DAILY_FETCH_TIME and executes queued (manual) runs."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=15, help="Seconds between checks.")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS("Worker started. Ctrl+C to stop."))
        try:
            while True:
                try:
                    maybe_schedule_daily()
                    process_queue()
                except Exception as exc:  # keep the worker alive
                    self.stderr.write(f"worker loop error: {exc!r}")
                time.sleep(opts["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
