# Railway setup

`railway.ts` defines the whole Railway project: Postgres, a private storage bucket for documents,
the `web` service (gunicorn), and the `worker` service (Django-Q2). Railway's CLI reads it; Railway
does not read it during deploys.

## First deploy

1. Install the Railway CLI (5.42.1 or newer), then from the repository root:

   ```bash
   railway login
   railway link            # pick or create the project and environment
   cd .railway && npm install && cd ..
   railway config plan     # preview
   railway config apply    # create the database, bucket, and both services
   ```

2. In the Railway dashboard, open the environment's **Shared Variables** and add:

   | Variable | Value |
   | --- | --- |
   | `DJANGO_SECRET_KEY` | a long random string (required) |
   | `DJANGO_ADMIN_URL` | a secret path for Django's data admin, e.g. the output of `python -c "import secrets; print(secrets.token_urlsafe(16))"`. Leave unset to switch the data admin off |
   | `SITE_URL` | your public URL, e.g. `https://app.example.com` (required for links in SMS and email) |
   | `DJANGO_ALLOWED_HOSTS` | your custom domain, if any (the Railway domain is allowed automatically) |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` + your custom domain, if any |
   | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Twilio credentials |
   | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | Postmark or Resend SMTP |
   | `ADMIN_DIGEST_EMAILS` | comma-separated admin emails for the hourly digest |
   | `ANTHROPIC_API_KEY` | for document reading |

   Database and bucket credentials are wired automatically.

3. Generate a public domain for `web` (service **Settings → Networking**), or add your own.

4. Create your admin account from the web service's shell:

   ```bash
   railway ssh --service web
   python manage.py createsuperuser
   ```

5. In Twilio, set the phone number's incoming message webhook to `https://<your domain>/hooks/twilio/inbound`.

Every deploy of `web` runs `scripts/release.sh` first (migrations, cache table, job schedules), and
Railway waits for `/healthz` to answer before switching traffic.

## Changing the setup

Edit `railway.ts`, then run `railway config plan` and `railway config apply`. Check the types with
`npm run check` in this folder.
