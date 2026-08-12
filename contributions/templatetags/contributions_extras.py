"""Template helpers for contributions/_employer_field.html."""

from django import template

from contributions.forms import ContributionForm
from games.models import Company

register = template.Library()


@register.filter
def employer_label(form: ContributionForm) -> str:
    """The employer name shown back on the `.chosen` line of
    contributions/_employer_field.html.

    Scoped to `ContributionForm` specifically (the type hint above is the
    contract, not a suggestion) — it reads `form.instance.company` and
    `form["company"]`, so a form without those would raise `AttributeError`.
    The single call site (`_employer_field.html`, included only by
    `contribution_form.html` and `declare_details.html`) always passes one;
    there is no other caller to guard against.

    `form.instance.company` is right whenever `_post_clean` has actually
    populated the instance — editing an existing credit, or re-rendering an
    invalid POST. It is wrong on the declare funnel's step 2: there the form
    is unbound with `initial` taken from the session draft, so
    `form["company"].value()` is a pk string while `form.instance` is a fresh,
    unsaved `Contribution()` whose `company` is always None — rendering
    `form.instance.company` in that case prints the literal string "None"
    rather than the employer's name, so the pk has to be resolved by hand.
    """
    if form.instance.company_id:
        return str(form.instance.company)
    value = form["company"].value()
    if not value or not str(value).isdecimal():
        return ""
    company = Company.objects.filter(pk=value).first()
    return str(company) if company is not None else ""
