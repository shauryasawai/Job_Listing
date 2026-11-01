from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.geo import is_india
from jobs.models import Job


class Command(BaseCommand):
    help = "Delete stored jobs located outside the configured country (from before the filter existed). Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        if settings.JOB_COUNTRY_FILTER in ("", "ALL"):
            self.stdout.write("JOB_COUNTRY_FILTER is ALL: nothing to prune.")
            return
        # Only location text is stored, so cities/states/"India" are matched (no country code is available here).
        doomed = [pk for pk, loc in Job.objects.values_list("pk", "location") if not is_india("", [loc])]
        self.stdout.write(f"{len(doomed)} stored jobs look to be outside {settings.JOB_COUNTRY_FILTER}.")
        for loc in sorted({l for pk, l in Job.objects.filter(pk__in=doomed[:2000]).values_list("pk", "location")})[:8]:
            self.stdout.write(f"  e.g. location: {loc!r}")
        if opts["apply"] and doomed:
            for i in range(0, len(doomed), 500):
                Job.objects.filter(pk__in=doomed[i:i + 500]).delete()
            self.stdout.write(self.style.SUCCESS("Deleted."))
        elif doomed:
            self.stdout.write("Dry run: add --apply to delete them.")
