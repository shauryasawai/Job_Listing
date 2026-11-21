"""Keep only sources that can actually be collected.

1. Removes every source that "Needs an adapter" (company career sites this app can't read). Their stored jobs,
   if any, are removed with them.
2. Probes the built-in catalogue of companies that hire in India (or your own list) against the public job-board
   APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee), and adds only boards that are verified to
   belong to the company AND have jobs in India.

Run it on a computer with internet access:   python manage.py refresh_sources
Preview without changing anything:             python manage.py refresh_sources --dry-run
Only the newer platforms:                      python manage.py refresh_sources --platforms ashby,smartrecruiters,workable,recruitee
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Count

from jobs.models import Source


class Command(BaseCommand):
    help = "Remove sources that need an adapter, then add verified job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee) with jobs in India."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without changing anything.")
        parser.add_argument("--skip-removal", action="store_true", help="Keep the sources that need an adapter.")
        parser.add_argument("--skip-discovery", action="store_true", help="Only remove; don't look for new companies.")
        parser.add_argument("--names-file", help="Check the companies in this file (one per line) instead of the built-in list.")
        parser.add_argument("--delay", type=float, default=0.25, help="Seconds between requests to the job-board APIs.")
        parser.add_argument("--platforms", help="Comma-separated platforms to check (default: all except workable). "
                                                "e.g. ashby,smartrecruiters,workable,recruitee")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        out = self.stdout
        if dry:
            out.write(self.style.WARNING("Dry run: nothing will be changed.\n"))

        if not opts["skip_removal"]:
            unsupported = Source.objects.filter(adapter_key=Source.ADAPTER_NONE).annotate(n=Count("jobs")).order_by("company_name")
            names = [f"{s.company_name}{f' ({s.n} jobs)' if s.n else ''}" for s in unsupported]
            if not names:
                out.write("No sources need an adapter.\n")
            else:
                out.write(f"{'Would remove' if dry else 'Removing'} {len(names)} sources that need an adapter:\n  " + ", ".join(names) + "\n")
                if not dry:
                    deleted = Source.objects.filter(adapter_key=Source.ADAPTER_NONE).delete()[1]
                    out.write(self.style.SUCCESS(f"Removed {deleted.get('jobs.Source', 0)} sources"
                                                 f" and {deleted.get('jobs.Job', 0)} stored jobs.\n"))

        if not opts["skip_discovery"]:
            out.write("\nLooking for companies whose job board has jobs in India "
                      "(this takes a while; each company is checked live on each platform)...\n")
            args = ["--names-file", opts["names_file"]] if opts["names_file"] else ["--catalog"]
            if not dry:
                args.append("--apply")
            if opts["platforms"]:
                args += ["--platforms", opts["platforms"]]
            call_command("discover_boards", *args, "--delay", str(opts["delay"]), stdout=out)

        totals = dict(Source.objects.values_list("adapter_key").annotate(n=Count("id")))
        active = Source.objects.filter(active=True).exclude(adapter_key=Source.ADAPTER_NONE).count()
        out.write("\nSources now: " + ", ".join(f"{k}: {v}" for k, v in sorted(totals.items())) + f" | switched on: {active}\n")
        if not dry:
            out.write("Next: open the dashboard and press Fetch jobs (newly added companies are switched on).\n")
