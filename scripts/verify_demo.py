"""Exercise the full local Compose flow against HTTP, PostgreSQL, worker, and Mailpit."""

import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta

import requests

BASE = os.getenv("DEMO_BASE_URL", "http://localhost:8000")
MAILPIT = os.getenv("DEMO_MAILPIT_URL", "http://localhost:8025")
PASSWORD = os.environ["DEMO_PASSWORD"]


def check(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text[:600])
    return response


def csrf_post(session, path, data, *, json=False, expected=200):
    headers = {"X-CSRFToken": session.cookies["csrftoken"]}
    method = session.post
    return check(
        method(BASE + path, json=data if json else None, data=None if json else data, headers=headers),
        expected,
    )


def mail_for(address, subject, contains=""):
    for _ in range(30):
        messages = requests.get(MAILPIT + "/api/v1/messages", timeout=5).json()["messages"]
        for message in messages:
            if message["Subject"] == subject and any(row["Address"] == address for row in message["To"]):
                body = requests.get(MAILPIT + "/api/v1/message/" + message["ID"], timeout=5).json()["Text"]
                if contains in body:
                    return body
        time.sleep(0.2)
    raise AssertionError(f"No {subject!r} email to {address}")


def compose_command(command):
    subprocess.run(["docker", "compose", "exec", "-T", "web", "python", "manage.py", command], check=True)


def login(session, email, password):
    check(session.get(BASE + "/login/"))
    csrf_post(session, "/login/", {"username": email, "password": password}, expected=200)
    response = session.get(BASE + "/")
    assert response.status_code == 200 and response.url.rstrip("/") == BASE.rstrip("/")


def main():
    suffix = uuid.uuid4().hex[:10]
    caregiver_email = f"caregiver-{suffix}@example.invalid"
    organizer = requests.Session()
    login(organizer, "organizer@demo.invalid", PASSWORD)
    circle = csrf_post(
        organizer,
        "/api/v1/circles/",
        {"name": f"Smoke {suffix}", "recipient_display_name": "Jordan", "timezone": "UTC"},
        json=True,
        expected=201,
    ).json()
    circle_id = circle["id"]
    csrf_post(
        organizer,
        f"/api/v1/circles/{circle_id}/invitations/",
        {"email": caregiver_email, "role": "caregiver"},
        json=True,
        expected=201,
    )
    invitation = mail_for(caregiver_email, "Shared Care Planner invitation")
    invite_path = re.search(r"/invite/[^\s]+/", invitation).group()

    caregiver = requests.Session()
    check(caregiver.get(BASE + "/signup/"))
    csrf_post(
        caregiver,
        "/signup/",
        {"email": caregiver_email, "password1": PASSWORD, "password2": PASSWORD},
    )
    verification = mail_for(caregiver_email, "Verify your Shared Care Planner account")
    verify_path = re.search(r"/verify/[^\s]+/", verification).group()
    check(caregiver.get(BASE + verify_path))
    check(caregiver.get(BASE + invite_path))
    csrf_post(caregiver, invite_path, {})
    members = check(organizer.get(BASE + f"/api/v1/circles/{circle_id}/members/")).json()
    caregiver_id = next(row["user_id"] for row in members if row["email"] == caregiver_email)

    def create_task(title, minutes_ago, category):
        local = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        response = csrf_post(
            organizer,
            f"/api/v1/circles/{circle_id}/tasks/",
            {
                "title": title,
                "category": category,
                "frequency": "daily",
                "local_time": local.strftime("%H:%M"),
                "start_date": local.date().isoformat(),
                "assigned_to": caregiver_id,
                "grace_minutes": 30,
            },
            json=True,
            expected=201,
        )
        return response.json()["id"]

    private_title = f"Private medication {suffix}"
    create_task(private_title, 2, "medication")
    compose_command("run_scheduler_once")
    compose_command("deliver_notifications")
    due_mail = mail_for(caregiver_email, "Care task reminder")
    assert private_title not in due_mail
    alerts = check(caregiver.get(BASE + f"/api/v1/circles/{circle_id}/notifications/")).json()
    assert any(row["kind"] == "due" for row in alerts)
    occurrences = check(caregiver.get(BASE + f"/api/v1/circles/{circle_id}/occurrences/")).json()
    first = next(row for row in occurrences if row["title"] == private_title)
    csrf_post(
        caregiver,
        f"/api/v1/occurrences/{first['id']}/actions/",
        {"action": "acknowledge"},
        json=True,
    )

    create_task(f"Unacknowledged check-in {suffix}", 35, "care")
    compose_command("run_scheduler_once")
    compose_command("deliver_notifications")
    escalation_mail = mail_for("organizer@demo.invalid", "Care task unacknowledged", f"/circle/{circle_id}/")
    assert "has not been acknowledged" in escalation_mail.lower()
    organizer_alerts = check(organizer.get(BASE + f"/api/v1/circles/{circle_id}/notifications/")).json()
    assert any(row["kind"] == "escalation" for row in organizer_alerts)
    print(
        f"PASS: circle {circle_id}, invitation, verified caregiver, generic email, in-app alert, acknowledgement, organizer escalation"
    )


if __name__ == "__main__":
    main()
