"""Contact relay — email to the target without ever exposing their address
(docs/01-DESIGN.md §3.6, docs/04 §10). Reply-To = sender; per-sender rate limit.
"""

from typing import Any

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contact.models import ContactRequest

pytestmark = pytest.mark.django_db

MESSAGE = {"subject": "Role at our studio", "message": "We'd love to talk."}


@pytest.fixture
def sender() -> User:
    return User.objects.create_user(
        email="recruiter@studio.example",
        password="x",
        display_name="Recruiter",
        role=User.Role.RECRUITER,
    )


@pytest.fixture
def target() -> User:
    return User.objects.create_user(
        email="candidate@example.com", password="x", display_name="Candidate"
    )


def _url(target: User) -> str:
    return reverse("contact:contact", kwargs={"slug": target.slug})


def test_contact_requires_login(client: Client, target: User) -> None:
    assert client.get(_url(target)).status_code == 302


def test_sending_relays_an_email_with_reply_to_sender(
    client: Client, sender: User, target: User
) -> None:
    client.force_login(sender)

    response = client.post(_url(target), MESSAGE)

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["candidate@example.com"]  # delivered to the target
    assert sent.reply_to == ["recruiter@studio.example"]  # replies go to the sender
    assert ContactRequest.objects.filter(sender=sender, recipient=target).count() == 1


def test_response_never_exposes_the_target_email(
    client: Client, sender: User, target: User
) -> None:
    client.force_login(sender)
    response = client.post(_url(target), MESSAGE, follow=True)
    assert b"candidate@example.com" not in response.content


def test_contact_form_page_never_exposes_the_target_email(
    client: Client, sender: User, target: User
) -> None:
    client.force_login(sender)
    response = client.get(_url(target))
    assert response.status_code == 200
    assert b"candidate@example.com" not in response.content


def test_non_contactable_target_cannot_be_contacted(
    client: Client, sender: User, target: User
) -> None:
    User.objects.filter(pk=target.pk).update(contactable=False)
    client.force_login(sender)

    response = client.post(_url(target), MESSAGE)

    assert len(mail.outbox) == 0
    assert ContactRequest.objects.count() == 0
    assert response.status_code in (403, 404)


def test_rate_limit_blocks_excess_sends(
    client: Client, sender: User, target: User, settings: Any
) -> None:
    settings.CONTACT_RATE_LIMIT_PER_DAY = 2
    client.force_login(sender)

    for _ in range(2):
        client.post(_url(target), MESSAGE)
    third = client.post(_url(target), MESSAGE)

    assert ContactRequest.objects.filter(sender=sender).count() == 2  # third blocked
    assert len(mail.outbox) == 2
    assert third.status_code in (302, 429)


def test_cannot_contact_yourself(client: Client, sender: User) -> None:
    client.force_login(sender)
    response = client.post(_url(sender), MESSAGE)
    assert len(mail.outbox) == 0
    assert response.status_code in (403, 404)
