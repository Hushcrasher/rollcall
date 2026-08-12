"""Step 3 of the declare funnel — the account, and the credit that survives it.

Signup auto-logs-in, so the account exists before the verification mail is ever
opened. That is why the credit becomes a row here rather than waiting in the
session: the mail is routinely opened on another device.
"""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def _with_draft(client: Client, game: Game) -> None:
    session = client.session
    session[SESSION_KEY] = {
        "game": str(game.pk),
        "company": "",
        "discipline": str(Discipline.objects.get(name="Design").pk),
        "job_title": "Level Designer",
        "start_date": "2020-01",
        "end_date": "",
    }
    session.save()


SIGNUP = {
    "email": "new@example.com",
    "display_name": "New Person",
    "password1": "a-strong-passphrase-42",
    "password2": "a-strong-passphrase-42",
    "consent": "on",
}


def test_account_step_needs_a_draft(client: Client) -> None:
    response = client.get(reverse("contributions:declare_account"))
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare")


def test_signing_up_saves_the_credit_as_pending(client: Client, game: Game) -> None:
    _with_draft(client, game)

    response = client.post(reverse("contributions:declare_account"), SIGNUP)

    credit = Contribution.objects.get()
    assert credit.status == Contribution.Status.PENDING
    assert credit.user.email == "new@example.com"
    assert credit.game == game
    assert credit.job_title == "Level Designer"
    assert response["Location"] == reverse("accounts:verification_sent")
    assert len(mail.outbox) == 1  # the verification email went out
    assert SESSION_KEY not in client.session  # the draft is consumed


def test_the_pending_credit_is_not_public_yet(client: Client, game: Game) -> None:
    _with_draft(client, game)
    client.post(reverse("contributions:declare_account"), SIGNUP)

    user = User.objects.get(email="new@example.com")
    response = client.get(user.get_absolute_url())
    assert response.status_code == 200
    assert b"Level Designer" not in response.content


def test_an_already_verified_member_gets_an_active_credit(client: Client, game: Game) -> None:
    """Reached through the log-in entry point: there is nothing to wait for."""
    from django.utils import timezone

    member = User.objects.create_user(email="known@example.com", password="x", display_name="Known")
    member.email_verified_at = timezone.now()
    member.save(update_fields=["email_verified_at"])
    client.force_login(member)
    _with_draft(client, game)

    response = client.get(reverse("contributions:declare_account"))

    credit = Contribution.objects.get()
    assert credit.status == Contribution.Status.ACTIVE
    assert credit.user == member
    assert response["Location"] == member.get_absolute_url()


def test_an_unverified_member_gets_a_pending_credit(client: Client, game: Game) -> None:
    member = User.objects.create_user(email="unv@example.com", password="x", display_name="Unv")
    assert member.email_verified_at is None
    client.force_login(member)
    _with_draft(client, game)

    client.get(reverse("contributions:declare_account"))

    assert Contribution.objects.get().status == Contribution.Status.PENDING


def test_a_half_filled_draft_goes_to_details_not_the_question(client: Client, game: Game) -> None:
    """A game was picked but step 2 was never finished — send them to fill it
    in, not back to re-pick a game the session already holds."""
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk)}
    session.save()

    response = client.get(reverse("contributions:declare_account"))

    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_details")


def test_abandoning_the_funnel_writes_nothing(client: Client, game: Game) -> None:
    """Steps 1 and 2 only ever touch the session — filling both and never
    reaching step 3 (the session expires, the tab is closed) must leave no
    trace at all: no `User`, no `Contribution`."""
    _with_draft(client, game)

    assert User.objects.count() == 0
    assert Contribution.objects.count() == 0


def test_a_head_request_does_not_write_a_credit(client: Client, game: Game) -> None:
    """`dispatch` used to run `_save_credit` for ANY method once authenticated
    — a browser prefetch/prerender (HEAD) would write outside CSRF
    protection. Only POST, and the authenticated GET the test above (and
    `test_an_already_verified_member_gets_an_active_credit` below) rely on,
    may reach the write."""
    member = User.objects.create_user(email="head@example.com", password="x", display_name="H")
    client.force_login(member)
    _with_draft(client, game)

    client.head(reverse("contributions:declare_account"))

    assert Contribution.objects.count() == 0


def test_a_stale_draft_goes_back_to_the_details_step(client: Client, game: Game) -> None:
    """The draft no longer validates — send them back to fix it rather than
    dropping the credit on the floor."""
    _with_draft(client, game)
    session = client.session
    session[SESSION_KEY]["discipline"] = ""
    session.save()

    response = client.post(reverse("contributions:declare_account"), SIGNUP)

    assert response["Location"] == reverse("contributions:declare_details")
    assert Contribution.objects.count() == 0


def test_verification_sent_names_the_waiting_credit(client: Client, game: Game) -> None:
    """The verification click collects something instead of lifting a
    restriction — it is the funnel's last exit."""
    _with_draft(client, game)
    client.post(reverse("contributions:declare_account"), SIGNUP)

    body = client.get(reverse("accounts:verification_sent")).content
    assert b"Hollow Knight" in body


def test_verification_sent_is_generic_without_a_credit(client: Client) -> None:
    user = User.objects.create_user(email="plain@example.com", password="x", display_name="P")
    client.force_login(user)
    assert b"Check your inbox" in client.get(reverse("accounts:verification_sent")).content
