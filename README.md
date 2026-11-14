# Jobline: Job Portal Aggregator

Django backend + plain HTML/CSS/JS dashboard. Collects **jobs and internships located in India** from many companies
through the **Greenhouse Job Board API** and **Lever Postings API**, stores them in a database, and runs daily or on
demand. **AI summaries (OpenAI) are never generated automatically**: a user asks for each one, under daily caps.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # then edit: OPENAI_API_KEY, OPENAI_MODEL, caps
python manage.py migrate
python manage.py createsuperuser                          # superusers are dashboard administrators
python manage.py seed_sources                             # the 51 career pages from the PDF
python manage.py discover_boards --apply                  # find Greenhouse/Lever boards among those 51
python manage.py discover_boards --catalog                # dry run: ~190 more India-hiring companies
python manage.py discover_boards --catalog --apply        # add the verified ones that have India jobs
python manage.py runserver                                # http://127.0.0.1:8000
```

Sign in, open **Sources**, and press **Fetch jobs now** (admins only). For the daily schedule, also run
`python manage.py run_worker` in a second terminal.

> **Upgrading an existing install:** replace the whole project folder with the new download, keeping only your
> `.env`, `db.sqlite3` and virtual environment, then run `python manage.py migrate`. Replacing only `jobs/` leaves an
> outdated `jobagg/settings.py`. The app still runs (built-in defaults and your `.env` values are used), but
> `runserver` prints a `jobs.W001` warning listing what's missing. `python manage.py showmigrations jobs` should show
> every migration ticked.
>
> Upgrading from the first version? `python manage.py migrate` (clears the old auto-generated excerpts, keeps real
> AI summaries), then `python manage.py prune_outside_country` (dry run) / `--apply` to delete stored non-India jobs.

## Finding companies beyond the 51

Greenhouse and Lever have no public company directory, so there are three ways to grow the list:

1. **Catalogue** (`discover_boards --catalog`): about 190 Indian and global employers that commonly hire in India
   (`jobs/seed_data.py`, edit freely). Each is probed on both platforms; only boards that are *verified* and have at
   least one India job are added. Many companies simply aren't on these platforms and are ignored.
2. **Your own list**: `discover_boards --names-file companies.txt` (one name per line). Add `--eu` to also probe Lever's
   EU region, `--any-country` to keep boards with no India jobs, `--limit N` to try a few first.
3. **One company at a time**: **Sources → Add company** in the dashboard. Paste its job board link
   (`boards.greenhouse.io/NAME`, `job-boards.greenhouse.io/NAME` or `jobs.lever.co/NAME`). The board is test-fetched
   first, then added and fetched.

Verification is deliberately strict (exact Greenhouse board name; company name appearing in Lever postings), so look
at lines marked **NEEDS REVIEW**; confirm the board manually and use *Add company* if it's right.

## India filter and internships

* `JOB_COUNTRY_FILTER=IN` (default) keeps a job only if its country code is India (Lever provides one), or its
  locations mention India, an Indian city (Bengaluru, Pune, Gurugram...) or an Indian state. "Remote" alone, or
  "Remote - APAC", is **not** kept because it can't be tied to India. Set `ALL` to keep every location.
* Jobs are stored only if they pass, and each run shows how many were dropped ("Outside India" in Fetch runs).
* Job type is normalised to Full-time / Part-time / Contract / **Internship**. A title containing intern, internship,
  trainee or apprentice counts as an internship. Use the *Job type* filter to see only internships.

## Per-company limit: the latest 100 postings

`MAX_JOBS_PER_COMPANY=100` (default; `0` = no limit) applies to **every** source, including the original 51.

* The limit is applied **after** the India filter, so jobs outside India never use up a company's 100 slots.
* "Latest" means newest first by **posting date** where the platform gives one (Lever). Greenhouse doesn't expose a
  posting date, so its postings are ranked by **job id** (ids only increase, so higher = newer), then last-updated time.
  That is a heuristic, not a guarantee. Postings with neither fall back to the order the portal returned them.
* A posting that falls out of the latest 100 (because newer ones arrived, or because the limit was lowered) is
  **archived**, not deleted. It is hidden from the default list, keeps any AI summary, and comes back automatically if
  it re-enters the latest 100. See it with *Status → Over the per-company limit*. If it later disappears from the
  company's portal altogether, it is deleted after the usual `MISSING_CHECKS_BEFORE_CLOSED` grace period.
* Postings that never made the cut are not stored. *Fetch runs* shows how many were over the limit for each source.
* During the closing grace period a company can briefly show a few more than 100 active jobs (postings that just left
  the portal are kept as "active" until they have been missing for several fetches).

## Government jobs in India

Government bodies don't publish jobs through job APIs: they post **recruitment notices (mostly PDFs)** on their
official websites. (Checked November 2026: UPSC has no published job API; the National Career Service shares
vacancies only with partner portals; SSC's site builds its notice board with JavaScript.) So government sources use a
**notice page reader**:

* Point it at an official page that lists recruitment notices, or at the site's **RSS feed**. It keeps only
  recruitment notices (advertisements, vacancies, walk-ins, apprenticeships…) and drops results, admit cards, answer
  keys, syllabi, corrigenda, tenders and site menus. When a link's text is just "(1.49 MB)" or "Download", the title is
  taken from the surrounding line, as on UPSC's page.
* Each notice becomes a job: organisation, title, link to the official PDF, dates found on the page ("Last date…"),
  city if the notice names one (otherwise "India"), and experience/qualification if the notice text states them.
* **UPSC** (Recruitment Advertisements page) is added automatically by `migrate`, switched on. RBI, SBI and IBPS
  official pages are added **switched off**: I could not verify those pages from my environment, so open
  **Sources → Edit → Test connection** first, then switch them on.
* Add any other official page with **Sources → Add company → Government notice page or RSS feed**. The page is
  tested first; you'll get a clear message if it has no notices, builds its list with JavaScript, or is blocked by
  the site's robots.txt. "Only links to PDF / document notices" is on by default and gives the cleanest results; untick
  it for sites that link to HTML notice pages.
* The reader honours robots.txt, makes one request per page per run, verifies HTTPS certificates, and never logs in or
  bypasses anything.
* Use the **Sector** filter (Private companies / Government). Notices show **Open official notice**; AI summaries are
  not offered for them (the details are inside the PDF, so a summary would be guesswork). **Create post** works for
  notices too (the role is shortened, e.g. "Recruitment of 25 Junior Engineers on contract basis at Noida" →
  "25 Junior Engineers - Contractual Role"). Check eligibility and the last date in the notice before sharing.

## Filters: experience and city

* **Your experience (years):** shows roles whose stated requirement fits you: "3 - 6 years" matches 3 to 6, "3+ years"
  matches 3 and above, "Fresher" matches 0 to 1. Experience is read from the posting text (patterns like "3-5 years",
  "5+ yrs", "minimum 2 years", "Experience - 3 - 6 years", "freshers welcome"), ignoring years that aren't about
  experience ("founded 20 years ago"). Many postings don't state it, so *Include jobs that don't state experience* is
  on by default; untick it to see only roles with a stated range. Internships without a stated range count as fresher roles.
* **City:** a dropdown of the cities present in your data, with aliases merged (Bangalore → Bengaluru, Gurgaon →
  Gurugram, Bombay → Mumbai...), plus *Remote*. The search box still matches any location text.
* Each job shows its experience range as a tag, and the detail panel shows experience and qualification.

## LinkedIn / WhatsApp posts

Click **Create post** on a job (or tick several jobs and use **Create post** in the bar at the bottom) to produce
the standard format:

```
Looking For Sales Associate For Factory Automation Company (Funded Startup)

Experience - 3 - 6 years
Location - Noida
Qualification - Bachelor's degree in Business Administration, Marketing, Sales, or a related field

Please share resumes to bhawna@marketscope.in
```

* Experience, location and qualification are pre-filled from the posting and are editable; anything the posting didn't
  state is written as "Not specified" and flagged so you can fill it in. Contract roles get "- Contractual Role".
* *Describe the company as* replaces the company name (e.g. "Factory Automation Company (Funded Startup)"); leave it
  blank to use the company name. The resume email defaults to your account email. Both are remembered in your browser.
* Several selected jobs become one post, one block per role. **Copy text**, **Share on WhatsApp** (opens WhatsApp with
  the text), or **Copy and open LinkedIn** (LinkedIn can't be pre-filled, so the text is copied for you to paste).

## AI summaries: on demand, with caps

* A fetch **never** calls OpenAI. Jobs show a free excerpt (the start of the posting) until someone clicks
  **Summarise with AI** on the job row or in the detail panel.
* `SUMMARY_DAILY_CAP_PER_USER` (default 30) and `SUMMARY_DAILY_CAP_GLOBAL` (default 100) limit summaries per day; the
  count resets at local midnight (`TIME_ZONE`). `0` turns summaries off. The remaining quota is shown in the dashboard,
  and the server enforces it, so it can't be bypassed from the browser.
* **Summaries are stored permanently per role and never regenerated.** A "role" is the same title + description, so
  one role posted in several cities, or removed and re-posted later, is summarised once, ever. Every posting of that
  role gets the stored summary for free (no AI call, no quota), including new postings collected later. Summaries live
  in the `RoleSummary` table and survive the job itself being deleted. Failed OpenAI calls don't use up quota.
* Every summary is logged (user, job, model, tokens) in `SummaryLog` for cost auditing (see the Django admin).
* The prompt treats posting text as untrusted data and forbids inventing salary, visa or deadline details.

## How collection works

1. A scheduled run (`DAILY_FETCH_TIME`) or the dashboard button creates a `FetchRun`. A unique database marker
   guarantees **only one run is active**; crashed runs are released after `STALE_RUN_MINUTES`.
2. Each active source is collected independently; one failure never stops the others. Transient errors (429/5xx/network)
   are retried with backoff; 401/403 are reported as "access refused", never worked around.
3. Jobs are filtered (country), normalised, and upserted by `source + external job id` (fallback: URL).
   `first_seen_at` is kept, `last_seen_at` refreshed.
4. A job missing from a successful fetch is marked **possibly closed** only after `MISSING_CHECKS_BEFORE_CLOSED`
   consecutive misses. An empty feed from a source that previously had jobs is treated as an outage.

## Running daily

| Option | Command |
|---|---|
| Worker (recommended) | `python manage.py run_worker`: starts the daily run at `DAILY_FETCH_TIME`, catches up after downtime, executes queued manual runs. Set `RUN_MODE=queue` so the web process never runs jobs itself. |
| Cron | `0 2 * * * cd /app && .venv/bin/python manage.py fetch_jobs` |
| Dev only | Default `RUN_MODE=thread`: the dashboard button runs the collection in a background thread of the web server. |

## API (session auth; admin-only where noted)

`GET /api/jobs` (`q, source, employment_type, workplace_type, location, discovered, status, ordering, page, page_size`),
`GET /api/jobs/{id}`, `POST /api/jobs/{id}/summary` (any signed-in user, capped), `GET /api/filters`,
`GET /api/overview`, `GET /api/me`, `GET /api/sources`, `POST /api/sources` (admin: add from board link),
`PATCH /api/sources/{id}` (admin), `POST /api/sources/{id}/test` (admin),
`GET|POST /api/fetch-runs` (POST admin; `409` if a run is active), `GET /api/fetch-runs/{id}`.

## Adding an adapter

Create `jobs/adapters/yourplatform.py` with a class extending `BaseAdapter` whose `fetch_jobs()` returns `RawJob`s
(fill `location`, `locations`, `country` so the India filter works) or raises `FetchError`; register it in
`jobs/adapters/__init__.py`. Ashby, SmartRecruiters, Workable and Recruitee also publish public job APIs and would be
natural next adapters. Prefer official APIs; check each site's terms first.

## Stuck or long fetches

* With the default `RUN_MODE=thread`, a fetch started from the dashboard runs **inside the web server**. Stopping or
  restarting `runserver` (including its automatic restart when project files change) ends the fetch. Jobs collected up
  to that point are kept.
* A fetch that sends no heartbeat for `STALE_RUN_MINUTES` (default 30) is released automatically the next time the
  dashboard loads, and shows as *Failed* with the reason in **Fetch runs**.
* Admins can press **Stop fetch** in the progress box. A fetch whose server process is gone is released at once; a
  running one stops after the company it is collecting.
* For long or unattended runs, set `RUN_MODE=queue` in `.env` and keep `python manage.py run_worker` running in a second
  terminal. Restarting the web server then no longer interrupts fetches.

## Troubleshooting AI summaries

Run `python manage.py check_openai`. It costs nothing (no tokens) and reports which key is loaded (masked), where it
came from, whether it has stray characters, and OpenAI's verdict for your `OPENAI_MODEL`. The dashboard and server log
also show OpenAI's own error message.

| Error | Meaning / fix |
|---|---|
| HTTP 401 `invalid_api_key` | Wrong, revoked or truncated key. Copy it again into `.env`, restart the server. |
| "environment variable OVERRIDES .env" | An `OPENAI_API_KEY` is set in Windows/your shell and wins over `.env`. Remove it (`setx OPENAI_API_KEY ""`, new terminal) or update it. |
| HTTP 403 | Key is valid but not allowed: restricted key without model access, project without access to the model, or unsupported region. |
| HTTP 404 / `model_not_found` | `OPENAI_MODEL` isn't available to your key; choose one your project can use. |
| HTTP 429 `insufficient_quota` | No credit on the OpenAI account: add billing. Normal 429 rate limits are retried automatically. |

`.env` lines may use quotes, `export`, and trailing `# comments`; a UTF-8 BOM (Windows Notepad) is handled.
Restart the server after editing `.env`.

## Production notes

* `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and the HTTPS options in `.env.example`.
* PostgreSQL (`POSTGRES_*`, `pip install "psycopg[binary]"`), `gunicorn jobagg.wsgi`, and `collectstatic` (WhiteNoise).
* `OPENAI_API_KEY` is read from the environment only; never sent to the browser or logged. Pick `OPENAI_MODEL` from the
  models available to your account.

## Tests

`python manage.py test jobs`: 94 tests (adapters on the documented Greenhouse/Lever response shapes, India filter,
internship detection, government notice pages and RSS feeds, experience/qualification extraction, city and experience filters, per-role summary reuse, per-company limit, de-duplication, change detection, run locking, failure isolation, on-demand summaries and caps,
add-company, board discovery, API permissions). Network calls are mocked.
