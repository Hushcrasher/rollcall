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
from games.models import Engine, Game, Genre


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


class GameTypeaheadSelectMultiple(TypeaheadSelectMultiple):
    """Chip labels from a targeted query instead of from `self.choices`.

    `TypeaheadSelectMultiple._chips()` builds a {value: label} map by iterating
    every choice — fine for Engine, Genre and the 249 countries, ruinous for
    Game: the catalogue is ~391k rows and would be materialised on every render
    of the home page. Looking up only the selected ids keeps the property the
    base class exists for — a label is never derived from the raw value, so an
    unknown id renders no chip — at a cost bounded by the selection.
    """

    def _chips(self, value: Any) -> list[tuple[str, Any]]:
        # Filtered BEFORE the query, not after: `?games=abc` reaching `pk__in`
        # as a string raises ValueError — a 500 on a public page from a
        # hand-typed URL. isascii() is part of the guard, not decoration:
        # "²".isdigit() is True and int("²") raises.
        ids = [v for v in map(str, value or []) if v.isascii() and v.isdigit()]
        if not ids:
            return []
        labels = {
            str(pk): title
            for pk, title in Game.objects.filter(pk__in=ids).values_list("pk", "title")
        }
        # `ids` order, not the queryset's: chips render in querystring order.
        return [(v, labels[v]) for v in ids if v in labels]


class RecruiterSearchForm(forms.Form):
    discipline = forms.ModelChoiceField(
        queryset=Discipline.objects.all(), required=False, label=_("Their role")
    )
    engines = forms.ModelMultipleChoiceField(
        queryset=Engine.objects.all(),
        required=False,
        label=_("Game engine"),
        widget=TypeaheadSelectMultiple(
            url_name="search:engine_autocomplete", placeholder=_("Search engines…")
        ),
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        required=False,
        label=_("Game genre"),
        widget=TypeaheadSelectMultiple(
            url_name="search:genre_autocomplete", placeholder=_("Search genres…")
        ),
        # The data caveat is honest, not cosmetic: IGDB-only games currently
        # carry no genre data (ROADMAP "Non-Steam facet coverage"), so this
        # filter excludes credits on non-Steam games. Surfaced once, in the
        # template's shared footnote, not per field (spec 2026-08-21-search-chrome §2).
    )
    games = forms.ModelMultipleChoiceField(
        queryset=Game.objects.all(),
        required=False,
        label=_("Specific games"),
        widget=GameTypeaheadSelectMultiple(
            url_name="search:game_filter_autocomplete", placeholder=_("Search games…")
        ),
        # The alternative to engines/genres/min_rating, not a companion to
        # them — clean() below refuses both at once (spec 2026-08-24 §7).
    )
    countries = forms.MultipleChoiceField(
        choices=_country_choices,
        required=False,
        label=_("Based in"),
        widget=TypeaheadSelectMultiple(
            url_name="search:country_autocomplete", placeholder=_("Search countries…")
        ),
    )
    # min 1, not 0: "0" reads as "I don't care about rating" but means "must
    # HAVE rating data" — leave the field blank to not filter on rating.
    min_rating = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        label=_("Minimum player rating (%)"),
        # Same honest caveat as genres: the current data carries ratings for
        # Steam-linked games only — surfaced in the template's shared footnote
        # (spec 2026-08-21-search-chrome §2), not repeated here per field.
    )
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Credited since (year)")
    )
    open_to_work = forms.BooleanField(required=False, label=_("Open to work only"))

    def criteria_fields(self) -> list[forms.BoundField]:
        """The three game criteria, in the order a recruiter reaches for them
        (spec 2026-08-24 §3): genre is the coarsest facet, engine the
        specialist's. `games` is deliberately absent — it is the alternative to
        this group, not a member of it, and the template renders it on its own
        so the two cards can never be looped into one row by accident."""
        return [self["genres"], self["min_rating"], self["engines"]]

    def person_fields(self) -> list[forms.BoundField]:
        """Row 2 — who they are."""
        return [self["discipline"], self["countries"], self["year_from"], self["open_to_work"]]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            # A field-level error already told the user what's wrong; adding
            # "pick a filter" on top would tell them to do what they just did.
            return cleaned
        # The two ways of naming games are alternatives, not filters that
        # compose: adding a genre to a list of named games can only narrow it
        # into nonsense. Enumerated, like has_filter below — a loop over the
        # criteria would fail OPEN the day a fourth one is added.
        criteria = any([cleaned.get("genres"), cleaned.get("min_rating"), cleaned.get("engines")])
        if criteria and cleaned.get("games"):
            raise forms.ValidationError(
                _("Filter either by game criteria or by specific games, not both.")
            )
        # Every field on this form is a filter — add new ones here. Kept
        # explicit on purpose: a generic loop over self.fields fails OPEN the
        # moment a non-filter field (say, `sort`) is added.
        has_filter = any(
            [
                cleaned.get("discipline"),
                cleaned.get("engines"),
                cleaned.get("genres"),
                cleaned.get("games"),
                cleaned.get("countries"),
                cleaned.get("min_rating"),
                cleaned.get("year_from"),
                cleaned.get("open_to_work"),
            ]
        )
        if not has_filter:
            raise forms.ValidationError(_("Pick at least one filter."))
        return cleaned
