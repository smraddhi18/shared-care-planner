# Shared Care Planner

A private, runnable care coordination app for families. An organizer can create a care circle without requiring the person receiving care to use a phone or create an account. Family caregivers share recurring tasks, user-entered medication reminders, appointments, and acknowledgement history. It provides **no diagnosis, dosage recommendation, or emergency monitoring**. An alert means a task has not been acknowledged in this app; it does not establish whether care was given.

## Start the complete demo

Requires Docker Desktop and Docker Compose.

```bash
cp .env.example .env
# Replace DJANGO_SECRET_KEY in .env before use outside a local demo.
docker compose up --build -d
```

Open <http://localhost:8000> and the local email inbox at <http://localhost:8025>. `web`, `worker`, and `scheduler` run as separate processes. Compose starts PostgreSQL, Redis, Mailpit, and a one-shot migration service. No account or real email provider is required for the local demo.

To load synthetic data:

```bash
DEMO_PASSWORD='replace-with-a-long-demo-password' docker compose exec -e DEMO_SEED_ALLOWED=1 -e DEMO_PASSWORD web python manage.py seed_demo
```

Sign in as `organizer@demo.invalid` or `caregiver@demo.invalid` using the chosen demo password. The seed command creates one reminder about two minutes ahead and one already unacknowledged. Refresh the circle page to see in-app alerts; Mailpit displays emails. The seed command is guarded by `DEMO_SEED_ALLOWED=1` and is idempotent.

For a full invitation flow, create an account, verify it in Mailpit, create a circle, and invite a second email address. Sign up with that address, verify it, then accept the invitation. Invitation links expire after 48 hours and can be used once.

To verify that entire flow automatically against the running Compose stack, install the development dependencies and run:

```bash
pip install -r requirements-dev.txt
DEMO_PASSWORD='the-same-demo-password' python scripts/verify_demo.py
```

This creates a fresh synthetic circle and caregiver, follows the invitation and verification emails, delivers a generic medication reminder, acknowledges it, and checks an organizer escalation for a separate unacknowledged task. The script invokes scheduler and delivery commands in the web container for a deterministic result.

## Architecture

Code is organized by responsibility: `care/api/` owns REST request validation and responses; `care/web/` owns server-rendered pages and health endpoints; `care/services/` owns permission checks, transactional writes, and audit events. `care/scheduling.py` materializes and queues occurrences, while `care/notifications.py` leases and delivers durable alerts. Django models and serializers remain shared at the app boundary. The API and web modules call the same services so behavior does not diverge between interfaces.

- **Django and PostgreSQL** store users, circle membership, recurrence templates, materialized occurrences, notifications, and append-only audit events.
- **Celery beat** triggers a periodic scheduling pass; a **Celery worker** delivers pending notifications. Redis is the broker and cache. PostgreSQL notification rows are the durable source of truth. If Redis temporarily loses a scheduling message, the next tick rechecks database state.
- Recurrence uses the circle's IANA time zone. Daily and weekly occurrences retain their intended local wall time. For a spring DST gap, the occurrence moves to the first valid later minute; for a repeated hour, it uses the earlier occurrence. A unique `(template, local_date)` constraint prevents duplicates after retries or concurrent ticks.
- A due task creates separate in-app and email notification rows. Workers claim rows with a lease, retry temporary delivery errors with bounded backoff, and reclaim expired leases after a crash. A unique logical key avoids repeated queue records. Email itself is at-least-once: an SMTP server can accept a message just before a worker crashes, so recipients could receive a duplicate in that narrow case.
- When a task remains unacknowledged after its configured grace period (30 minutes by default), the scheduler alerts organizers. It rechecks task state before delivery. Email subjects and bodies omit task and medication names.
- Session authentication and CSRF protection apply to both dashboard and API. Every circle object lookup enforces active membership, and medication schedule changes require an organizer. Roles are `organizer`, `caregiver`, and `viewer`.

The product intentionally stores only a display name for the person receiving care. It does not store diagnoses or medical documents. The organizer is coordinating reminders, not making a legal or clinical determination on behalf of the recipient.

## API

OpenAPI JSON: <http://localhost:8000/api/schema/>. Interactive docs: <http://localhost:8000/api/docs/>. Sign in through the web app first; API calls use the same session and CSRF token.

Selected endpoints:

- `GET/POST /api/v1/circles/` — list or create circles
- `GET/POST /api/v1/circles/{id}/tasks/` — list or create recurring tasks
- `PATCH /api/v1/circles/{id}/tasks/{task_id}/` — edit or pause a schedule
- `GET/POST /api/v1/circles/{id}/appointments/` — list or create appointments
- `GET /api/v1/circles/{id}/occurrences/` — upcoming task occurrences
- `POST /api/v1/occurrences/{id}/actions/` — `acknowledge`, `complete`, `skip`, or `snooze`
- `POST /api/v1/circles/{id}/invitations/` — invite a caregiver or viewer
- `GET /api/v1/circles/{id}/notifications/` — in-app alerts
- `GET /api/v1/circles/{id}/audit/` — organizer-only change history
- `GET /livez/`, `GET /readyz/` — liveness and database readiness
- `GET /metrics/` — staff-only queue counts and oldest-pending age

Example task request, sent as JSON with a signed-in session and `X-CSRFToken` header:

```json
{
  "title": "Evening check-in",
  "category": "care",
  "frequency": "daily",
  "local_time": "20:00",
  "start_date": "2026-09-28",
  "assigned_to": null,
  "grace_minutes": 30
}
```

For a weekly task, set `frequency` to `weekly` and `weekdays` to integers `0` (Monday) through `6` (Sunday).

## Failure and recovery demonstration

Stop the scheduler and worker, mark one pending notification as a crashed worker's expired lease, then restart delivery:

```bash
docker compose stop scheduler worker
docker compose exec web python manage.py run_scheduler_once
docker compose exec web python manage.py simulate_worker_crash
docker compose exec web python manage.py deliver_notifications
docker compose start scheduler worker
```

Inspect `/metrics/` as a staff user or query the `Notification` model in Django admin. The stale lease is reclaimed and the notification reaches Mailpit or the in-app list. `last_error`, attempt count, and status remain visible for failed notifications.

## Quality checks

Locally, install Python 3.12 and dependencies, then run:

```bash
pip install -r requirements-dev.txt
ruff format --check .
ruff check .
mypy
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
pytest
pip-audit -r requirements.txt
```

Set `DJANGO_SECRET_KEY`, database variables, and `EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend` for local tests. CI runs against PostgreSQL and Redis. The test suite covers DST transitions, duplicate generation, circle isolation, invitation use, signup verification, API task acknowledgement, snooze behavior, notification retries, lease recovery, revocation, and escalation.

## Production configuration

Use a long random `DJANGO_SECRET_KEY`, a managed PostgreSQL database, a protected Redis instance, a real SMTP provider, and a TLS-terminating proxy. Set `DEBUG=0`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `PUBLIC_BASE_URL`, `SECURE_SSL_REDIRECT=1`, and secure SMTP credentials via environment variables or a secret manager. Run `python manage.py check --deploy` with production settings before deployment. Keep exactly one beat scheduler per environment; run one or more workers separately. Apply migrations as a distinct release step before serving traffic.

Back up PostgreSQL with `pg_dump -Fc -U care -d care > care.dump` and restore to a fresh database with `pg_restore -U care -d care --clean --if-exists care.dump`. Test restores regularly. Redis is a broker/cache; PostgreSQL is the system of record for pending alerts. Monitor `/metrics/`, worker errors, email failure rate, and queue lag. The app is a coordination aid; families should retain their existing care and emergency procedures.
