# COI Network

A mobile-first web app where event vendors (starting with Atlanta food trucks) keep one verified compliance
profile and share it with event organizers in one tap. Built from the *Vendor COI Network — MVP Build Spec*.

- **Vendors** (free): sign in by SMS code, upload a COI, health permit, fire inspection, and business license,
  confirm the AI-read fields, join events by link or code, share a 14-day read-only packet, and ask their
  agent for an additional-insured certificate in one tap.
- **Organizers**: create events with requirements, invite vendors, and see red / yellow / green status with
  plain-word reasons. Bulk reminders, CSV export, and a ZIP of verified documents.
- **Admins** (`/ops`): verification queue with side-by-side review, verify/reject with method and notes,
  agent-verification emails, expiration monitor, directory, document types, requirement templates, audit
  log, and pilot metrics.

Server-rendered Django with plain HTML forms and one hand-written CSS file. Every page works with JavaScript
disabled; the only script is an optional copy-to-clipboard enhancement. Strict Content Security Policy.

## Run it locally

Requires Python 3.11+ and PostgreSQL.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set DJANGO_SECRET_KEY; defaults point at postgresql://coi:coi@localhost/coi
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo      # 1 admin, 2 organizers, 5 vendors with sample documents
python manage.py runserver
```

Without Twilio credentials, SMS (including login codes) are printed to the server log. Without an email host,
email goes to the console. Without `ANTHROPIC_API_KEY`, extraction is skipped and vendors fill in an empty
form. Without `S3_BUCKET`, files are stored under `private_media/` and served through signed links that
expire in 10 minutes.

Demo logins after `seed_demo`:

| Role | Sign in with |
| --- | --- |
| Admin | phone `404-555-0100` (code in the server log) |
| Organizer | `festival@example.com` or `brewery@example.com`, password `demo-organizer-pass` |
| Vendors | phones `404-555-0101` through `404-555-0105` |

The Spring Food Truck Festival's invite code is `SPRING` (link: `/i/SPRING`).

## Background jobs

Django-Q2 uses Postgres as its broker. With `DJANGO_DEBUG=1` (or `Q_SYNC=1`) tasks run inline. In production
run a worker with `python manage.py qcluster` and create the schedules once with
`python manage.py setup_schedules`:

- **Daily, 7:00 a.m. Eastern**: mark expired documents, text 30/14/3-day expiration reminders (once each),
  recompute statuses for events in the next 30 days and standing lists.
- **Hourly**: admin digest of pending documents; send SMS held during quiet hours (9 p.m. to 8 a.m. Eastern).

Point Twilio's inbound SMS webhook at `/hooks/twilio/inbound` to record STOP / START opt-outs.

## Tests and tooling

```bash
pytest                                   # unit and integration tests
pytest -m e2e                            # Playwright smoke tests (JS disabled, 375px viewport)
ruff check . && black --check .
```

If Playwright's bundled Chromium isn't installed, point it at another build with
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome`.

## Deploy (Railway)

`.railway/railway.ts` defines the Railway project with Railway's Infrastructure as Code: managed Postgres, a
private storage bucket for documents, a `web` service (gunicorn + WhiteNoise), and a Django-Q2 `worker`.
Before each web deploy, `scripts/release.sh` runs migrations, creates the cache table, and sets up job
schedules; Railway then waits for `/healthz`. Step-by-step setup, including the shared variables to add, is in
[`.railway/README.md`](.railway/README.md). Set `SITE_URL` to the public URL; it is used in every SMS and
email link.

## Layout

| App | What's in it |
| --- | --- |
| `accounts` | Custom user (the spec's `profiles`), SMS codes, email magic links, role selection, legal pages |
| `vendors` | Vendor profile, home status card, document cards, share packet, account deletion |
| `events` | Organizations, events, requirements, vendor participation, the status rule (`events/status.py`), additional-insured requests, agent uploads, exports |
| `documents` | Document types, uploads, AI extraction (`documents/extraction.py`), COI details, share links, private file serving |
| `ops` | Admin back office, audit log, metrics, `seed_demo` |
| `notifications` | SMS/email sending and logging, quiet hours, opt-out webhook, scheduled jobs |
| `common` | Base model (uuid id, timestamps), CSP middleware, rate limiting, upload validation, template tags |

## Notes on the spec

- The vertical stays generic in code: vendor types, document types, and requirement templates are data.
- `event_requirements.required_document_types` is a many-to-many to document types rather than a `uuid[]`
  column, so the admin can manage document types without dangling ids.
- Documents have one extra status, `draft`, for an upload the vendor hasn't confirmed yet. It becomes
  `pending` on submit and only then replaces the previous version.
- An agent's uploaded certificate enters the queue linked to its event and replaces the vendor's COI only
  once an admin verifies it, so a pending agent upload never turns a vendor red.
- The product name is a placeholder (`SITE_NAME`); terms and privacy pages are placeholders that need a
  lawyer's review before launch.
