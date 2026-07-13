from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from accounts.models import RecruiterApplication, User

CONSENT_LABEL = _(
    "I understand my profile and credits will be public and accessible to "
    "recruiters — that is the point of the platform."
)


class SignupForm(UserCreationForm):
    consent = forms.BooleanField(required=True, label=CONSENT_LABEL)

    class Meta:
        model = User
        fields = ["email", "display_name"]


class EmailAuthenticationForm(AuthenticationForm):
    """Login form labelled for email (the USERNAME_FIELD is `email`)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Email")
        self.fields["username"].widget = forms.EmailInput(attrs={"autofocus": True})


class RecruiterApplicationForm(forms.ModelForm):
    class Meta:
        model = RecruiterApplication
        fields = ["full_name", "company_name", "work_email", "linkedin_url", "message"]


class SettingsForm(forms.ModelForm):
    """Profile + the three visibility booleans (docs/01-DESIGN.md §3.4)."""

    class Meta:
        model = User
        fields = [
            "display_name",
            "bio",
            "location",
            "avatar",
            "profile_public",
            "contactable",
            "open_to_work",
        ]
