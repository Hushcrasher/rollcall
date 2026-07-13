"""Recruiter search filters (docs/01-DESIGN.md §3.6). Every field optional."""

from django import forms
from django.utils.translation import gettext_lazy as _

from contributions.models import Discipline
from games.models import Engine, Genre


class RecruiterSearchForm(forms.Form):
    discipline = forms.ModelChoiceField(
        queryset=Discipline.objects.all(), required=False, label=_("Discipline")
    )
    engine = forms.ModelChoiceField(
        queryset=Engine.objects.all(), required=False, label=_("Engine")
    )
    genre = forms.ModelChoiceField(queryset=Genre.objects.all(), required=False, label=_("Genre"))
    min_rating = forms.IntegerField(
        required=False, min_value=0, max_value=100, label=_("Min. rating (%)")
    )
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Worked since (year)")
    )
    open_to_work = forms.BooleanField(required=False, label=_("Open to work only"))
