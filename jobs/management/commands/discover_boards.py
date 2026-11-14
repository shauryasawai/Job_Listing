"""Find companies that publish jobs on Greenhouse or Lever, and register them as sources.

Modes
  (default)         look for boards for existing sources that have no adapter yet
  --catalog         probe the built-in catalogue of companies that hire in India and ADD new sources
  --names-file F    same as --catalog but with your own list (one company name per line)

Dry-run unless --apply. A board is only accepted when it can be tied to the company:
  * Greenhouse: the board's registered name equals the company name (ignoring Inc/Corp/Ltd...)
  * Lever:      the company name appears as a whole word in at least two sample postings
Catalogue/names-file additions must also have at least one job in the configured country (India by default).
Anything uncertain is printed as NEEDS REVIEW so you can confirm it on the Sources page.
"""
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.adapters import get_adapter
from jobs.adapters.http import FetchError, NotFoundError, get_json
from jobs.geo import matches_country_filter
from jobs.models import Source
from jobs.seed_data import CATALOG, EXTRA_SLUGS

SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "llc", "ltd", "limited", "plc",
            "gmbh", "ag", "group", "holdings", "technologies", "technology", "systems", "labs", "pvt", "private"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def core_name(s):
    """'Stripe, Inc.' -> 'stripe'; 'Cisco Systems' -> 'cisco'. Used for strict name equality."""
    return "".join(w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in SUFFIXES)


def candidates(name):
    out = [norm(name), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), *EXTRA_SLUGS.get(name, [])]
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def probe_greenhouse(slug, company):
    try:
        data = get_json(f"{settings.GREENHOUSE_API_BASE}/v1/boards/{slug}")
    except NotFoundError:
        return None
    name = core_name(data.get("name") or "")
    match = bool(name) and name == core_name(company)
    return {"adapter": "greenhouse", "board": slug, "verified": match, "detail": f"board name: {data.get('name')!r}"}


def probe_lever(slug, company, region):
    base = settings.LEVER_API_BASE_EU if region == "eu" else settings.LEVER_API_BASE
    try:
        data = get_json(f"{base}/v0/postings/{slug}", params={"mode": "json", "limit": 5})
    except NotFoundError:
        return None
    if not isinstance(data, list) or not data:
        return None
    pattern = re.compile(rf"\b{re.escape(company)}\b", re.I)
    mentions = sum(1 for p in data if pattern.search((p.get("descriptionPlain") or "") + " " + (p.get("text") or "")))
    verified = len(norm(company)) >= 4 and mentions >= min(2, len(data))
    return {
        "adapter": "lever", "board": slug, "region": region, "verified": verified,
        "detail": f"{len(data)}+ postings, e.g. {data[0].get('text')!r}",
    }


def find_board(name, delay, include_eu):
    """Best match across slug variants and both platforms (a verified hit beats an unverified one)."""
    hit = None
    for slug in candidates(name):
        probes = [lambda s=slug: probe_greenhouse(s, name), lambda s=slug: probe_lever(s, name, "global")]
        if include_eu:
            probes.append(lambda s=slug: probe_lever(s, name, "eu"))
        for probe in probes:
            res = probe()
            time.sleep(delay)
            if res and (hit is None or (res["verified"] and not hit["verified"])):
                hit = res
            if hit and hit["verified"]:
                return hit
    return hit


def public_url(hit):
    if hit["adapter"] == "greenhouse":
        return f"https://boards.greenhouse.io/{hit['board']}"
    host = "jobs.eu.lever.co" if hit.get("region") == "eu" else "jobs.lever.co"
    return f"https://{host}/{hit['board']}"


def config_for(hit):
    cfg = {"board": hit["board"]}
    if hit.get("region") == "eu":
        cfg["region"] = "eu"
    return cfg


def count_matching(hit, name):
    """(total jobs, jobs in the configured country) for a board, without saving anything."""
    probe = Source(company_name=name, adapter_key=hit["adapter"], configuration_json=config_for(hit))
    jobs = get_adapter(probe).fetch_jobs()
    return len(jobs), sum(1 for j in jobs if matches_country_filter(j))


class Command(BaseCommand):
    help = "Find Greenhouse/Lever boards for more companies. Use --apply to save verified matches."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Save results (default is a dry run).")
        parser.add_argument("--all", action="store_true", help="Also re-check sources that already have an adapter.")
        parser.add_argument("--catalog", action="store_true", help="Probe the built-in catalogue of India-hiring companies.")
        parser.add_argument("--names-file", help="Text file with one company name per line.")
        parser.add_argument("--limit", type=int, default=0, help="Only probe the first N companies.")
        parser.add_argument("--delay", type=float, default=0.25, help="Seconds between requests.")
        parser.add_argument("--eu", action="store_true", help="Also probe Lever's EU region.")
        parser.add_argument("--any-country", action="store_true", help="Add boards even if they have no jobs in the configured country.")

    def handle(self, *args, **opts):
        if opts["catalog"] or opts["names_file"]:
            return self.handle_new_companies(opts)
        qs = Source.objects.all() if opts["all"] else Source.objects.filter(adapter_key=Source.ADAPTER_NONE)
        found = review = 0
        for source in qs:
            try:
                hit = find_board(source.company_name, opts["delay"], opts["eu"])
            except FetchError as exc:
                self.stdout.write(self.style.ERROR(f"{source.company_name:<24} error: {exc}"))
                continue
            if hit is None:
                self.stdout.write(f"{source.company_name:<24} no Greenhouse/Lever board found")
            elif hit["verified"]:
                found += 1
                self.stdout.write(self.style.SUCCESS(f"{source.company_name:<24} {hit['adapter']}:{hit['board']}  ({hit['detail']})"))
                if opts["apply"]:
                    source.adapter_key, source.configuration_json = hit["adapter"], config_for(hit)
                    source.save(update_fields=["adapter_key", "configuration_json"])
            else:
                review += 1
                self.stdout.write(self.style.WARNING(f"{source.company_name:<24} NEEDS REVIEW {hit['adapter']}:{hit['board']} ({hit['detail']})"))
        self.summary(found, review, 0, opts)

    def handle_new_companies(self, opts):
        if opts["names_file"]:
            with open(opts["names_file"], encoding="utf-8") as fh:
                names = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        else:
            names = list(CATALOG)
        known = {s.company_name.lower() for s in Source.objects.all()}
        known_boards = {(s.adapter_key, s.board) for s in Source.objects.exclude(adapter_key=Source.ADAPTER_NONE)}
        names = [n for n in names if n.lower() not in known]
        if opts["limit"]:
            names = names[: opts["limit"]]
        country = settings.JOB_COUNTRY_FILTER
        added = review = nojobs = 0
        self.stdout.write(f"Probing {len(names)} companies (country filter: {country})...\n")
        for name in names:
            try:
                hit = find_board(name, opts["delay"], opts["eu"])
                if hit is None:
                    self.stdout.write(f"{name:<26} not on Greenhouse/Lever")
                    continue
                if not hit["verified"]:
                    review += 1
                    self.stdout.write(self.style.WARNING(f"{name:<26} NEEDS REVIEW {hit['adapter']}:{hit['board']} ({hit['detail']})"))
                    continue
                if (hit["adapter"], hit["board"]) in known_boards:
                    self.stdout.write(f"{name:<26} board already added under another name")
                    continue
                total, local = count_matching(hit, name)
            except FetchError as exc:
                self.stdout.write(self.style.ERROR(f"{name:<26} error: {exc}"))
                continue
            if local == 0 and not opts["any_country"]:
                nojobs += 1
                self.stdout.write(f"{name:<26} {hit['adapter']}:{hit['board']} has {total} jobs but none in {country}: skipped")
                continue
            added += 1
            cap = settings.MAX_JOBS_PER_COMPANY
            kept_note = f" (latest {cap} kept)" if cap > 0 and local > cap else ""
            self.stdout.write(self.style.SUCCESS(f"{name:<26} {hit['adapter']}:{hit['board']}  {local} of {total} jobs match {country}{kept_note}"))
            if opts["apply"]:
                Source.objects.create(company_name=name, careers_url=public_url(hit), adapter_key=hit["adapter"],
                                      configuration_json=config_for(hit))
                known_boards.add((hit["adapter"], hit["board"]))
        self.summary(added, review, nojobs, opts)

    def summary(self, found, review, nojobs, opts):
        verb = "added" if opts["apply"] and (opts["catalog"] or opts["names_file"]) else "verified"
        tail = "" if opts["apply"] else " (dry run: add --apply to save)"
        extra = f", {nojobs} had no jobs in {settings.JOB_COUNTRY_FILTER}" if nojobs else ""
        self.stdout.write(f"\n{found} {verb}{tail}, {review} need manual review{extra}.")
