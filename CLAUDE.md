# Working on COI Network

Django 5 app built from the *Vendor COI Network — MVP Build Spec*. See README.md for the layout and setup.

## Workflow
- Open a pull request against `master` after every new feature or change set; don't wait to be asked.
- One pull request per change set, with a description of what changed and how it was tested.
- Ask before adding a dependency that isn't already in `requirements.txt`.

## Before pushing
Postgres must be running (`DATABASE_URL`, default `postgresql://coi:coi@localhost:5432/coi`).

```bash
ruff check . && black --check .
pytest                      # add DJANGO_DEBUG=0 to match CI
pytest -m e2e               # Playwright, JavaScript off, 375px
python manage.py makemigrations --check --dry-run
(cd .railway && npm ci && npm run check)
```

## Conventions
- Every page must work with JavaScript disabled; no inline scripts or styles (strict CSP).
- Object-level permission checks in every view and queryset; audit every document view and download.
- Keep the vertical generic in code ("vendor", "event", "document type").
- Never send personal data to third parties beyond the extraction call (Sentry is configured to strip it).
