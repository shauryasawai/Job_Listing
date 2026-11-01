from django.core.management.base import BaseCommand

from jobs.models import Source
from jobs.seed_data import SOURCES


class Command(BaseCommand):
    help = "Load the 51 career pages from the requirements PDF into the source registry (idempotent)."

    def handle(self, *args, **opts):
        created = 0
        for name, url in SOURCES:
            _, was_created = Source.objects.get_or_create(company_name=name, defaults={"careers_url": url})
            created += was_created
        self.stdout.write(self.style.SUCCESS(f"{created} added, {len(SOURCES) - created} already present."))
        self.stdout.write("Next: python manage.py discover_boards --apply   (finds Greenhouse/Lever boards)")
