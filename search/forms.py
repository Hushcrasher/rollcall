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
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_countries import countries

from contributions.models import Discipline
from games.models import Engine, Genre


def _country_choices() -> list[tuple[str, str]]:
    """A callable, so Django rebuilds the list per access. Passing `countries`
    directly freezes the translated names at import (it is Iterable, and
    normalize_choices checks Iterable before callable)."""
    return list(countries)


class TypeaheadSelectMultiple(forms.SelectMultiple):
    """Renders only the *selected* options — a hidden input plus a chip each —
    next to an htmx-backed search box.

    Subclasses SelectMultiple purely for its `value_from_datadict` (which reads
    `data.getlist(name)`), so the field still receives, and still posts, the
    repeated `?engines=3&engines=7` params a checkbox list would.
    """

    template_name = "search/widgets/typeahead_select.html"

    def __init__(self, *, url_name: str, placeholder: Any, attrs: Any = None) -> None:
        super().__init__(attrs)
        self.url_name = url_name
        self.placeholder = placeholder

    def get_context(self, name: str, value: Any, attrs: Any) -> dict[str, Any]:
        # Deliberately does NOT call super().get_context(): Select.get_context()
        # runs self.optgroups(), which materialises *every* choice — the 249
        # <input>s this widget exists to not send.
        return {
            "widget": {
                "name": name,
                "attrs": self.build_attrs(self.attrs, attrs),
                "chips": self._chips(value),
                "url": reverse(self.url_name),
                "placeholder": self.placeholder,
            }
        }

    def _chips(self, value: Any) -> list[tuple[str, Any]]:
        """(value, label) for each selected value, in querystring order.

        The label is looked up in `self.choices`, never derived from the raw
        value: a value with no matching choice renders no chip, so junk in the
        querystring can't reach the page. That matters for countries —
        `Country("ZZ")` is truthy but its `.name` is `""`, so a
        `Country(code).name` lookup would render a blank, nameless chip.

        Iterating `self.choices` per render is also what keeps country names
        translated: the choices are a callable, so this re-evaluates them in the
        active language rather than reusing names frozen at import.
        """
        labels = {str(choice): label for choice, label in self.choices}
        return [(v, labels[v]) for v in map(str, value or []) if v in labels]


class RecruiterSearchForm(forms.Form):
    discipline = forms.ModelChoiceField(
        queryset=Discipline.objects.all(), required=False, label=_("Discipline")
    )
    engines = forms.ModelMultipleChoiceField(
        queryset=Engine.objects.all(),
        required=False,
        label=_("Engines"),
        widget=TypeaheadSelectMultiple(
            url_name="search:engine_autocomplete", placeholder=_("Search engines…")
        ),
        help_text=_("Matches games using any of the selected."),
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        required=False,
        label=_("Genres"),
        widget=TypeaheadSelectMultiple(
            url_name="search:genre_autocomplete", placeholder=_("Search genres…")
        ),
        # The data caveat is honest, not cosmetic: IGDB-only games currently
        # carry no genre data (ROADMAP "Non-Steam facet coverage"), so this
        # filter excludes credits on non-Steam games.
        help_text=_(
            "Matches games in any of the selected. Genre data currently covers "
            "Steam-linked games only."
        ),
    )
    countries = forms.MultipleChoiceField(
        choices=_country_choices,
        required=False,
        label=_("Countries"),
        widget=TypeaheadSelectMultiple(
            url_name="search:country_autocomplete", placeholder=_("Search countries…")
        ),
        help_text=_("Where the person is — any of the selected."),
    )
    # min 1, not 0: "0" reads as "I don't care about rating" but means "must
    # HAVE rating data" — leave the field blank to not filter on rating.
    min_rating = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        label=_("Min. rating (%)"),
        # Same honest caveat as genres: the current data carries ratings for
        # Steam-linked games only, so any value here excludes non-Steam credits.
        help_text=_("Rating data currently covers Steam-linked games only."),
    )
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Worked on a game since (year)")
    )
    open_to_work = forms.BooleanField(required=False, label=_("Open to work only"))

    def typeahead_fields(self) -> list[forms.BoundField]:
        """The facets the template renders as chips + a search box.

        Enumerated, for the same reason `clean()` is: sniffing for
        `TypeaheadSelectMultiple` widgets instead would blind the guard aimed at
        exactly this. Swap a widget back and the sniffed list silently drops the
        field, so `test_empty_form_does_not_ship_a_choice_per_country` sees a
        small payload and passes (mutation-tested both ways). Sibling chip tests
        do fail, so the swap isn't invisible — but the guard that names the
        regression goes quiet. Listed here, the same swap renders the checkbox
        list and that guard fails loudly.
        """
        return [self["engines"], self["genres"], self["countries"]]

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
