"""Template helpers for contributions/_employer_field.html."""

from django import template
from django.utils.safestring import SafeString

from contributions.forms import ContributionForm
from games.models import Company

register = template.Library()


@register.filter
def employer_label(form: ContributionForm) -> str | SafeString:
    """The employer name shown back on the `.chosen` line of
    contributions/_employer_field.html.

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
