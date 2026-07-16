"""Recruiter search filters (docs/01-DESIGN.md §3.6). Every field optional,
but at least one is required, so the open search has no filterless "list
everyone" submit.

That rule is a UX guard, NOT an anti-scraping boundary: `?min_rating=1` is a
legal filter that matches nearly everyone, and no rule can tell "no-op" from
"merely broad". The real mitigations are the view's IP rate limit
(`SEARCH_RATELIMIT`), pagination, and `profile_public` — see
docs/02-ARCHITECTURE.md §5, which already concedes public pages can't be fully
protected."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _
from django_countries import countries

from contributions.models import Discipline
from games.models import Engine, Genre


def _country_choices() -> list[tuple[str, str]]:
    """A callable, so Django rebuilds the list per access. Passing `countries`
    directly freezes the translated names at import (it is Iterable, and
    normalize_choices checks Iterable before callable)."""
    return list(countries)


class RecruiterSearchForm(forms.Form):
    discipline = forms.ModelChoiceField(
        queryset=Discipline.objects.all(), required=False, label=_("Discipline")
    )
    engines = forms.ModelMultipleChoiceField(
        queryset=Engine.objects.all(),
        required=False,
        label=_("Engines"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Matches games using any of the selected."),
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        required=False,
        label=_("Genres"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Matches games in any of the selected."),
    )
    countries = forms.MultipleChoiceField(
        choices=_country_choices,
        required=False,
        label=_("Countries"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Where the person is — any of the selected."),
    )
    # min 1, not 0: "0" reads as "I don't care about rating" but means "must
    # HAVE rating data" — leave the field blank to not filter on rating.
    min_rating = forms.IntegerField(
        required=False, min_value=1, max_value=100, label=_("Min. rating (%)")
    )
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Worked since (year)")
    )
    open_to_work = forms.BooleanField(required=False, label=_("Open to work only"))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            # A field-level error already told the user what's wrong; adding
            # "pick a filter" on top would tell them to do what they just did.
            return cleaned
        # Every field on this form is a filter — add new ones here. Kept
        # explicit on purpose: a generic loop over self.fields fails OPEN the
        # moment a non-filter field (say, `sort`) is added.
        has_filter = any(
            [
                cleaned.get("discipline"),
                cleaned.get("engines"),
                cleaned.get("genres"),
                cleaned.get("countries"),
                cleaned.get("min_rating"),
                cleaned.get("year_from"),
                cleaned.get("open_to_work"),
            ]
        )
        if not has_filter:
            raise forms.ValidationError(_("Pick at least one filter."))
        return cleaned
