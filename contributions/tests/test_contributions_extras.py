"""Unit tests for contributions/templatetags/contributions_extras.py's
`employer_id` filter — the company pk written to `data-selected` on
_employer_field.html, which the JS asks games:game_employers to preselect
on load (both the credit form and the declare funnel share this filter)."""

import pytest

from contributions.forms import ContributionForm
from contributions.models import Contribution
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
    form = ContributionForm()

    assert employer_id(form) == ""
