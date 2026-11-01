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

## AI summaries: on demand, with caps

* A fetch **never** calls OpenAI. Jobs show a free excerpt (the start of the posting) until someone clicks
  **Summarise with AI** on the job row or in the detail panel.
* `SUMMARY_DAILY_CAP_PER_USER` (default 30) and `SUMMARY_DAILY_CAP_GLOBAL` (default 100) limit summaries per day; the
  count resets at local midnight (`TIME_ZONE`). `0` turns summaries off. The remaining quota is shown in the dashboard,
  and the server enforces it, so it can't be bypassed from the browser.
* Already-summarised jobs cost nothing to view. If a posting changes materially afterwards, the summary is flagged
  *stale* and can be regenerated (it counts toward the cap). Failed OpenAI calls don't use up quota.
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

## Production notes

* `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and the HTTPS options in `.env.example`.
* PostgreSQL (`POSTGRES_*`, `pip install "psycopg[binary]"`), `gunicorn jobagg.wsgi`, and `collectstatic` (WhiteNoise).
* `OPENAI_API_KEY` is read from the environment only; never sent to the browser or logged. Pick `OPENAI_MODEL` from the
  models available to your account.

## Tests

`python manage.py test jobs`: 48 tests (adapters on the documented Greenhouse/Lever response shapes, India filter,
internship detection, de-duplication, change detection, run locking, failure isolation, on-demand summaries and caps,
add-company, board discovery, API permissions). Network calls are mocked.
