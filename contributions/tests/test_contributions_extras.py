"""Unit tests for contributions/templatetags/contributions_extras.py's
`employer_id` filter — the value written to `data-selected` on
_employer_field.html, which the JS forwards to games:game_employers as
`?selected=` (both the credit form and the declare funnel share this filter).

Three-way contract: `""` = unknown, `"none"` = known to have no employer,
`"<pk>"` = that company."""

from datetime import date

import pytest

from accounts.models import User
from contributions.forms import ContributionForm
from contributions.models import Contribution, Discipline
from contributions.templatetags.contributions_extras import employer_id
from games.models import Company, Game

pytestmark = pytest.mark.django_db


def test_employer_id_reads_a_bound_forms_posted_value() -> None:
    """A validation-error re-render (edit or funnel step 2 POST): the raw
    posted value must survive, independent of whether the rest of the form
    is valid."""
    company = Company.objects.create(name="Rogue Titan Games", source=Company.Source.MANUAL)

    form = ContributionForm(data={"company": str(company.pk)})

    assert employer_id(form) == str(company.pk)


def test_employer_id_reads_the_funnels_session_draft_initial() -> None:
    """Declare funnel step 2: unbound, no saved instance, `initial` taken
    from the session draft — form.instance.company_id is always None here,
    so the pk has to come from the initial-backed BoundField instead."""
    company = Company.objects.create(name="Rogue Titan Games", source=Company.Source.MANUAL)

    form = ContributionForm(initial={"company": str(company.pk)})

    assert employer_id(form) == str(company.pk)


def test_employer_id_reads_the_edit_forms_instance() -> None:
    """Editing a saved credit: unbound, with a real instance carrying the
    saved company."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    company = Company.objects.create(name="Rogue Titan Games", source=Company.Source.MANUAL)
    contribution = Contribution(game=game, company=company)

    form = ContributionForm(instance=contribution)

    assert employer_id(form) == str(company.pk)


def test_employer_id_is_empty_with_nothing_saved_or_chosen() -> None:
    """Unknown, not "no employer": a blank form has never been through the
    employer question, so the endpoint applies its developer-first default."""
    form = ContributionForm()

    assert employer_id(form) == ""


def test_employer_id_is_empty_for_a_funnel_draft_that_only_has_a_game() -> None:
    """Step 2 rendered straight after step 1: the draft carries the game and
    nothing else, so the employer is unknown and the default applies."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)

    form = ContributionForm(initial={"game": str(game.pk)})

    assert employer_id(form) == ""


def test_employer_id_is_none_when_editing_a_credit_saved_without_a_company() -> None:
    """Known empty, not unknown: `""` here would let the JS load the select
    with no `?selected=`, preselect the developer and write its pk back into
    the hidden field — saving a typo fix would silently add an employer the
    member never entered (spec §1: the edit form never silently changes one)."""
    user = User.objects.create_user(email="e@example.com", password="x", display_name="E")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    credit = Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Programming"),
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )

    form = ContributionForm(instance=credit)

    assert employer_id(form) == "none"


def test_employer_id_is_none_when_the_member_posted_no_company() -> None:
    """A bound form is a submission: an empty `company` is the member having
    picked `No employer / freelance`, not an absence of information."""
    form = ContributionForm(data={"company": ""})

    assert employer_id(form) == "none"


def test_employer_id_is_none_for_a_funnel_draft_that_chose_no_employer() -> None:
    """Step 2 re-rendered after the member went through it once: the draft
    carries `company: ""`, which records the choice."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)

    form = ContributionForm(initial={"game": str(game.pk), "company": ""})

    assert employer_id(form) == "none"
