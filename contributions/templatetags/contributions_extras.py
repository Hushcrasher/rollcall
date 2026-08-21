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


# The "no employer" sentinel of the `data-selected` / `?selected=` contract
# below. Read by games.views.game_employers, which documents the same three
# states from the endpoint's side — the two must not drift.
NO_EMPLOYER = "none"


@register.filter
def employer_id(form: ContributionForm) -> str:
    """`data-selected` on _employer_field.html — what the credit-form/funnel JS
    forwards to games:game_employers as `?selected=` to preselect on load.

    Three-way, because "no employer" and "we haven't asked yet" need different
    answers from the endpoint:

    - `"<pk>"` — that company.
    - `NO_EMPLOYER` — the employer is known to be empty: a bound form whose
      `company` came back empty (the member picked `No employer / freelance`),
      a saved credit being edited with no company, or a funnel draft that has
      been through step 2 (`"company"` present in `initial`, empty). Returning
      `""` here would send no `?selected=` at all, the endpoint would preselect
      the developer, and the JS's `sync()` would write its pk into the hidden
      field — so saving a typo fix on a freelance credit would silently stamp
      the developer as employer (spec §1: the edit form never silently changes
      an employer).
    - `""` — genuinely unknown (a blank new form, or the funnel right after the
      game step): the endpoint's developer-first default is what's wanted.

    Opposite precedence from employer_label above, and for the same reason:
    `form["company"].value()` reads the BoundField's value regardless of
    *why* the form is unbound — a real instance's model_to_dict-derived
    initial (editing) or the funnel's session-draft initial — and a bound
    form's raw posted value (a validation-error re-render) without waiting
    on `_post_clean`. `form.instance.company_id` is the fallback: it only
    disagrees with the above when the posted value didn't survive field
    validation (e.g. a stray "__other"), in which case emitting it as
    `data-selected` would be wrong anyway.
    """
    value = form["company"].value()
    if value and str(value).isdecimal():
        return str(value)
    if form.instance.company_id:
        return str(form.instance.company_id)
    asked = form.is_bound or form.instance.pk is not None or "company" in form.initial
    return NO_EMPLOYER if asked else ""
