"""Find companies that publish jobs on a supported job-board platform, and register them as sources.

Platforms (all public, no key needed): Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee.

Modes
  (default)         look for boards for existing sources that have no adapter yet
  --catalog         probe the built-in catalogue of companies that hire in India and ADD new sources
  --names-file F    same as --catalog but with your own list (one company name per line)
  --platforms a,b   only probe these platforms (e.g. --platforms ashby,smartrecruiters,workable,recruitee)

Dry-run unless --apply. A board is only accepted when it can be tied to the company:
  * Greenhouse, SmartRecruiters, Workable: the company name the platform registers equals the company name
    (ignoring Inc/Corp/Ltd...)
  * Lever, Ashby (and Recruitee when it gives no name): the company name appears as a whole word in at least two
    sample postings
Catalogue/names-file additions must also have at least one job in the configured country (India by default).
Anything uncertain is printed as NEEDS REVIEW so you can confirm it on the Sources page.
"""
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from jobs.adapters import board_url, get_adapter
from jobs.adapters.http import FetchError, NotFoundError, RateLimitedError, get_json
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


PLATFORMS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee")
# Checked when --platforms isn't given. Workable is left out: it refuses requests (HTTP 429) after a few dozen
# lookups, which also blocks fetching for a while. It can still be checked with --platforms workable.
DEFAULT_PLATFORMS = ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def candidates(name, platform=""):
    out = [norm(name), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), *EXTRA_SLUGS.get(name, [])]
    if platform == "smartrecruiters":  # identifiers there are usually CamelCase: 'UrbanCompany', 'BoschGroup'
        words = re.findall(r"[A-Za-z0-9]+", name)
        out += ["".join(w[:1].upper() + w[1:] for w in words), "".join(words)]
    if platform == "recruitee":  # a sub-domain: letters, digits and '-' only
        out = [c for c in out if _DNS_LABEL.match(c)]
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def mentions(company, texts):
    """True when the company name appears as a whole word in at least two of the sample texts (or the only one)."""
    texts = [t for t in texts if t]
    if not texts or len(norm(company)) < 4:
        return False
    pattern = re.compile(rf"\b{re.escape(company)}\b", re.I)
    return sum(1 for t in texts if pattern.search(t)) >= min(2, len(texts))


def probe_greenhouse(slug, company):
    try:
        data = get_json(f"{settings.GREENHOUSE_API_BASE}/v1/boards/{slug}", attempts=1)
    except NotFoundError:
        return None
    name = core_name(data.get("name") or "")
    match = bool(name) and name == core_name(company)
    return {"adapter": "greenhouse", "board": slug, "verified": match, "detail": f"board name: {data.get('name')!r}"}


def probe_lever(slug, company, region="global"):
    base = settings.LEVER_API_BASE_EU if region == "eu" else settings.LEVER_API_BASE
    try:
        data = get_json(f"{base}/v0/postings/{slug}", params={"mode": "json", "limit": 5}, attempts=1)
    except NotFoundError:
        return None
    if not isinstance(data, list) or not data:
        return None
    verified = mentions(company, [(p.get("descriptionPlain") or "") + " " + (p.get("text") or "") for p in data])
    return {
        "adapter": "lever", "board": slug, "region": region, "verified": verified,
        "detail": f"{len(data)}+ postings, e.g. {data[0].get('text')!r}",
    }


def probe_ashby(slug, company):
    try:
        data = get_json(f"{settings.ASHBY_API_BASE}/posting-api/job-board/{slug}", attempts=1)
    except NotFoundError:
        return None
    jobs = [j for j in (data or {}).get("jobs") or [] if isinstance(j, dict)] if isinstance(data, dict) else []
    if not jobs:
        return None
    sample = jobs[:5]
    verified = mentions(company, [(j.get("descriptionPlain") or "") + " " + (j.get("title") or "") for j in sample])
    return {"adapter": "ashby", "board": slug, "verified": verified,
            "detail": f"{len(jobs)} postings, e.g. {sample[0].get('title')!r}"}


def probe_smartrecruiters(slug, company):
    try:
        data = get_json(f"{settings.SMARTRECRUITERS_API_BASE}/v1/companies/{slug}/postings", params={"limit": 5}, attempts=1)
    except NotFoundError:
        return None
    content = (data or {}).get("content") if isinstance(data, dict) else None
    if not content:
        return None  # unknown identifiers answer with an empty list
    registered = ((content[0] or {}).get("company") or {}).get("name") or ""
    match = bool(core_name(registered)) and core_name(registered) == core_name(company)
    return {"adapter": "smartrecruiters", "board": slug, "verified": match,
            "detail": f"company name: {registered!r}, {data.get('totalFound', len(content))} postings"}


def probe_workable(slug, company):
    try:
        data = get_json(f"{settings.WORKABLE_API_BASE}/api/v1/widget/accounts/{slug}", attempts=1)
    except NotFoundError:
        return None
    if not isinstance(data, dict) or not data.get("jobs"):
        return None
    registered = data.get("name") or ""
    match = bool(core_name(registered)) and core_name(registered) == core_name(company)
    return {"adapter": "workable", "board": slug, "verified": match,
            "detail": f"account name: {registered!r}, {len(data['jobs'])} postings"}


def probe_recruitee(slug, company):
    try:  # one attempt: a sub-domain that doesn't exist may not even resolve
        data = get_json(settings.RECRUITEE_API_BASE.format(company=slug) + "/api/offers/", attempts=1)
    except RateLimitedError:
        raise
    except FetchError:
        return None
    offers = [o for o in (data or {}).get("offers") or [] if isinstance(o, dict)] if isinstance(data, dict) else []
    if not offers:
        return None
    registered = offers[0].get("company_name") or ""
    if registered:
        verified = core_name(registered) == core_name(company)
        detail = f"company name: {registered!r}, {len(offers)} postings"
    else:
        verified = mentions(company, [(o.get("description") or "") + " " + (o.get("title") or "") for o in offers[:5]])
        detail = f"{len(offers)} postings, e.g. {offers[0].get('title')!r}"
    return {"adapter": "recruitee", "board": slug, "verified": verified, "detail": detail}


PROBES = {
    "greenhouse": probe_greenhouse, "lever": probe_lever, "ashby": probe_ashby,
    "smartrecruiters": probe_smartrecruiters, "workable": probe_workable, "recruitee": probe_recruitee,
}


# Some platforms (Workable especially) allow only a few requests a minute from one computer.
MIN_GAP = {"workable": 2.0, "recruitee": 0.5}   # seconds between requests to that platform
COOLDOWN = 60                                    # pause once after the first 429, then skip the platform


class Limiter:
    """Tracks platforms that said 'too many requests'. After a second 429 a platform is skipped for the rest of
    the run and the companies it never checked are remembered so they can be re-checked later."""

    def __init__(self, notify=lambda msg: None, sleep=None):
        self.strikes, self.disabled, self.unchecked, self.last = {}, set(), {}, {}
        self.notify, self.sleep = notify, sleep or (lambda seconds: time.sleep(seconds))

    def wait_turn(self, platform):
        gap = MIN_GAP.get(platform, 0)
        if gap:
            elapsed = time.monotonic() - self.last.get(platform, 0)
            if elapsed < gap:
                self.sleep(gap - elapsed)
        self.last[platform] = time.monotonic()

    def limited(self, platform):
        """Called on a 429. Returns True to retry after a pause, False once the platform is skipped."""
        self.strikes[platform] = self.strikes.get(platform, 0) + 1
        if self.strikes[platform] == 1:
            self.notify(f"{platform} says 'too many requests': pausing {COOLDOWN}s, then continuing...")
            self.sleep(COOLDOWN)
            return True
        self.disabled.add(platform)
        self.notify(f"{platform} is still refusing requests: skipping it for the rest of this run.")
        return False


def find_board(name, delay, include_eu, platforms=PLATFORMS, limiter=None):
    """Best match across platforms and slug variants (a verified hit beats an unverified one)."""
    limiter = limiter or Limiter()
    hit = None
    for platform in platforms:
        if platform in limiter.disabled:
            limiter.unchecked.setdefault(platform, []).append(name)
            continue
        tries = [(platform, slug) for slug in candidates(name, platform)]
        if platform == "lever" and include_eu:
            tries += [("lever-eu", slug) for slug in candidates(name, platform)]
        for kind, slug in tries:
            res = None
            while True:
                limiter.wait_turn(platform)
                try:
                    res = probe_lever(slug, name, "eu") if kind == "lever-eu" else PROBES[kind](slug, name)
                except RateLimitedError:
                    if limiter.limited(platform):
                        continue
                    limiter.unchecked.setdefault(platform, []).append(name)
                break
            if platform in limiter.disabled:
                break
            time.sleep(delay)
            if res and (hit is None or (res["verified"] and not hit["verified"])):
                hit = res
            if hit and hit["verified"]:
                return hit
    return hit


def public_url(hit):
    return board_url(hit["adapter"], hit["board"], hit.get("region", "global"))


def config_for(hit):
    cfg = {"board": hit["board"]}
    if hit.get("region") == "eu":
        cfg["region"] = "eu"
    return cfg


def count_matching(hit, name):
    """(total jobs, jobs in the configured country) for a board, without saving anything."""
    probe = Source(company_name=name, adapter_key=hit["adapter"], configuration_json=config_for(hit))
    adapter = get_adapter(probe)
    adapter.with_details = False  # counting only: skip per-job description calls where a platform needs them
    jobs = adapter.fetch_jobs()
    return len(jobs), sum(1 for j in jobs if matches_country_filter(j))


LABELS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters",
          "workable": "Workable", "recruitee": "Recruitee"}


def platform_names(opts):
    names = [LABELS[p] for p in opts["platforms"]]
    return "any supported job board" if set(opts["platforms"]) >= set(DEFAULT_PLATFORMS) else "/".join(names)


class Command(BaseCommand):
    help = "Find job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee) for more companies. Use --apply to save verified matches."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Save results (default is a dry run).")
        parser.add_argument("--all", action="store_true", help="Also re-check sources that already have an adapter.")
        parser.add_argument("--catalog", action="store_true", help="Probe the built-in catalogue of India-hiring companies.")
        parser.add_argument("--names-file", help="Text file with one company name per line.")
        parser.add_argument("--limit", type=int, default=0, help="Only probe the first N companies.")
        parser.add_argument("--delay", type=float, default=0.25, help="Seconds between requests.")
        parser.add_argument("--eu", action="store_true", help="Also probe Lever's EU region.")
        parser.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS),
                            help=f"Comma-separated platforms to probe (default: {', '.join(DEFAULT_PLATFORMS)}; "
                                 f"also available: workable).")
        parser.add_argument("--any-country", action="store_true", help="Add boards even if they have no jobs in the configured country.")

    def make_limiter(self):
        self.limiter = Limiter(notify=lambda m: self.stdout.write(self.style.WARNING(f"  ... {m}")))
        return self.limiter

    def report_unchecked(self):
        import os
        for platform, names in sorted(self.limiter.unchecked.items()):
            names = list(dict.fromkeys(names))
            path = os.path.join(str(settings.BASE_DIR), f"unchecked_{platform}.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(names) + "\n")
            self.stdout.write(self.style.WARNING(
                f"\n{len(names)} companies were not checked on {LABELS[platform]} because it limited requests. "
                f"Their names are saved in {os.path.basename(path)}. Re-check them later (after ~15 minutes) with:\n"
                f"  python manage.py refresh_sources --skip-removal --platforms {platform} --names-file {os.path.basename(path)}"))

    def handle(self, *args, **opts):
        self.make_limiter()
        wanted = [p.strip().lower() for p in (opts.get("platforms") or "").split(",") if p.strip()]
        bad = [p for p in wanted if p not in PLATFORMS]
        if bad or not wanted:
            raise CommandError(f"Unknown platform(s): {', '.join(bad) or '(none)'}. Choose from: {', '.join(PLATFORMS)}.")
        opts["platforms"] = tuple(p for p in PLATFORMS if p in wanted)
        if opts["catalog"] or opts["names_file"]:
            return self.handle_new_companies(opts)
        qs = Source.objects.all() if opts["all"] else Source.objects.filter(adapter_key=Source.ADAPTER_NONE)
        found = review = 0
        for source in qs:
            try:
                hit = find_board(source.company_name, opts["delay"], opts["eu"], opts["platforms"], self.limiter)
            except FetchError as exc:
                self.stdout.write(self.style.ERROR(f"{source.company_name:<24} error: {exc}"))
                continue
            if hit is None:
                self.stdout.write(f"{source.company_name:<24} no board found on {platform_names(opts)}")
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
        self.stdout.write(f"Probing {len(names)} companies on {platform_names(opts)} (country filter: {country})...\n")
        for name in names:
            try:
                hit = find_board(name, opts["delay"], opts["eu"], opts["platforms"], self.limiter)
                if hit is None:
                    skipped = [LABELS[p] for p, n in self.limiter.unchecked.items() if name in n]
                    self.stdout.write(f"{name:<26} not on {platform_names(opts)}" if not skipped
                                      else f"{name:<26} not found ({'/'.join(skipped)} not checked: too many requests)")
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
                note = f"has no jobs in {country}" if total == 0 else f"has {total} jobs but none in {country}"
                self.stdout.write(f"{name:<26} {hit['adapter']}:{hit['board']} {note}: skipped")
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
        self.report_unchecked()
        verb = "added" if opts["apply"] and (opts["catalog"] or opts["names_file"]) else "verified"
        tail = "" if opts["apply"] else " (dry run: add --apply to save)"
        extra = f", {nojobs} had no jobs in {settings.JOB_COUNTRY_FILTER}" if nojobs else ""
        self.stdout.write(f"\n{found} {verb}{tail}, {review} need manual review{extra}.")
