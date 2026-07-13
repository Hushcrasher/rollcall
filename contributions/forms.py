"""Contribution form — game required in the POC, optional employer company,
discipline, free job title, and month/year dates (docs/01-DESIGN.md §3.3)."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from contributions.models import Contribution
from games.models import Game


class MonthInput(forms.DateInput):
    """Native month picker — the browser submits 'YYYY-MM'."""

    input_type = "month"

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(attrs=attrs, format="%Y-%m")


class MonthYearField(forms.DateField):
    """Stores month/year precision as a DATE with day forced to 01 (native SQL
    range/overlap ops matter for the future vouching system)."""

    widget = MonthInput

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("input_formats", ["%Y-%m"])
        super().__init__(**kwargs)


class ContributionForm(forms.ModelForm):
    # game is nullable in the schema (future company-only credits) but required
    # in POC forms. Declared explicitly to force required + a hidden widget the
    # autocomplete fills.
    game = forms.ModelChoiceField(
        queryset=Game.objects.all(), required=True, widget=forms.HiddenInput
    )
    start_date = MonthYearField(label=_("Start (month/year)"))
    end_date = MonthYearField(label=_("End (month/year)"), required=False)

    class Meta:
        model = Contribution
        fields = ["game", "company", "discipline", "job_title", "start_date", "end_date"]
        widgets = {"company": forms.HiddenInput}

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date can't be before the start date."))
        return cleaned
