// Railway Infrastructure as Code for COI Network.
// Preview with `railway config plan`, apply with `railway config apply` (see .railway/README.md).
import { bucket, defineRailway, github, postgres, project, ref, service } from "railway/iac";

const REPO = "friendm/yolo-ironman";
const BRANCH = "master";

// Secrets and per-deployment settings live in the environment's Shared Variables,
// so the web service and the worker read the same values and nothing secret is in git.
const SHARED = [
  "DJANGO_SECRET_KEY",
  "SITE_URL",
  "DJANGO_ALLOWED_HOSTS",
  "DJANGO_CSRF_TRUSTED_ORIGINS",
  "TWILIO_ACCOUNT_SID",
  "TWILIO_AUTH_TOKEN",
  "TWILIO_FROM_NUMBER",
  "EMAIL_HOST",
  "EMAIL_PORT",
  "EMAIL_HOST_USER",
  "EMAIL_HOST_PASSWORD",
  "DEFAULT_FROM_EMAIL",
  "ADMIN_DIGEST_EMAILS",
  "ANTHROPIC_API_KEY",
] as const;

export default defineRailway((ctx) => {
  const db = postgres("postgres");
  // Private, S3-compatible storage for uploaded documents (served through 10-minute presigned URLs).
  const documents = bucket("documents", { region: "iad" });

  const env = {
    DJANGO_DEBUG: "0",
    DATABASE_URL: db.env.DATABASE_URL,
    S3_BUCKET: ref(documents, "BUCKET"),
    S3_ACCESS_KEY_ID: ref(documents, "ACCESS_KEY_ID"),
    S3_SECRET_ACCESS_KEY: ref(documents, "SECRET_ACCESS_KEY"),
    S3_ENDPOINT_URL: ref(documents, "ENDPOINT"),
    S3_REGION: ref(documents, "REGION"),
    S3_ADDRESSING_STYLE: "virtual",
    ...Object.fromEntries(SHARED.map((name) => [name, ctx.shared[name]])),
  };

  const web = service("web", {
    source: github(REPO, { branch: BRANCH }),
    build: "python manage.py collectstatic --noinput",
    preDeploy: "sh scripts/release.sh",
    start: "gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 60",
    healthcheck: "/healthz",
    env,
  });

  // Django-Q2 worker: document extraction, notifications, and the daily and hourly jobs.
  const worker = service("worker", {
    source: github(REPO, { branch: BRANCH }),
    start: "python manage.py qcluster",
    deploy: { restartPolicyType: "ALWAYS" },
    env,
  });

  return project("coi-network", {
    resources: [db, documents, web, worker],
  });
});
