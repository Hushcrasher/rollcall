"""Report/flag form — private moderation signal, no public accusatory content."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contact.models import Report

pytestmark = pytest.mark.django_db


@pytest.fixture
def member() -> User:
    return User.objects.create_user(email="m@example.com", password="x", display_name="M")


def test_report_requires_login(client: Client) -> None:
    assert client.get(reverse("contact:report")).status_code == 302


def test_member_can_file_a_report(client: Client, member: User) -> None:
    client.force_login(member)

    response = client.post(
        reverse("contact:report"),
        {"target_type": Report.TargetType.CONTRIBUTION, "target_id": 7, "reason": "Looks wrong."},
    )

    report = Report.objects.get()
    assert report.reporter == member
    assert report.target_type == Report.TargetType.CONTRIBUTION
    assert report.target_id == 7
    assert report.status == Report.Status.OPEN
    assert response.status_code == 302


def test_report_form_prefills_from_query_params(client: Client, member: User) -> None:
    client.force_login(member)
    response = client.get(reverse("contact:report"), {"type": Report.TargetType.USER, "id": 42})
    assert response.status_code == 200
    form = response.context["form"]
    assert form.initial["target_type"] == Report.TargetType.USER
    assert form.initial["target_id"] == 42
