"""Contribution form — game required in the POC, optional employer company,
discipline, free job title, and MM/YYYY dates (docs/01-DESIGN.md §3.3)."""

from datetime import date
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from contributions.models import Contribution
from games.models import Game


class MonthInput(forms.DateInput):
    """A text box, not the native month picker: the picker renders in the
    browser's locale ("février 2026"), and the site's date format is MM/YYYY
    everywhere (spec 2026-08-21-credit-form-v2 §3)."""

    input_type = "text"

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        base = {
            "inputmode": "numeric",
            "placeholder": "MM/YYYY",
            "pattern": "[0-9]{2}/[0-9]{4}",
            "autocomplete": "off",
        }
        super().__init__(attrs={**base, **(attrs or {})}, format="%m/%Y")


class MonthYearField(forms.DateField):
    """Stores month/year precision as a DATE with day forced to 01 (native SQL
    range/overlap ops matter for the future vouching system). Accepts MM/YYYY
    and, for older clients and tests, the legacy YYYY-MM."""

    widget = MonthInput
    default_error_messages = {"invalid": _("Enter a month as MM/YYYY, e.g. 08/2024.")}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("input_formats", ["%m/%Y", "%Y-%m"])
        super().__init__(**kwargs)

    def prepare_value(self, value: Any) -> Any:
        # BoundField.value() calls this directly (it does not go through the
        # widget), so an edit form's initial `date` must be re-formatted here
        # to display as MM/YYYY rather than the ORM's raw date object.
        if isinstance(value, date):
            return value.strftime("%m/%Y")
        return value


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
        fields = ["game", "company", "discipline", "job_title", "start_date", "end_date", "country"]
        widgets = {"company": forms.HiddenInput}
        help_texts = {"country": _("Where this work happened.")}

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date can't be before the start date."))
        return cleaned
