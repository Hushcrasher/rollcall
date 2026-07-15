from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from accounts.github import extract_login
from accounts.models import GitHubSnapshot, GitHubYearlyContribution, RecruiterApplication, User

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
    """Profile + the three visibility booleans (docs/01-DESIGN.md §3.4),
    plus an optional GitHub handle (stored parsed as a login)."""

    github_url = forms.CharField(
        required=False,
        label=_("GitHub profile URL"),
        help_text=_(
            "Optional — shown as 'Public side projects'. e.g. https://github.com/yourhandle"
        ),
    )

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["github_url"].initial = str(self.instance.github_login)

    def clean_github_url(self) -> str:
        raw = self.cleaned_data.get("github_url", "").strip()
        if not raw:
            return ""
        login = extract_login(raw)
        if login is None:
            raise forms.ValidationError(_("Enter a valid GitHub profile URL or username."))
        return login

    def save(self, commit: bool = True) -> User:
        user: Any = super().save(commit=False)
        new_login = self.cleaned_data.get("github_url", "")
        if new_login != user.github_login:
            user.github_login = new_login
            if commit:
                GitHubSnapshot.objects.filter(user=user).delete()
                GitHubYearlyContribution.objects.filter(user=user).delete()
        if commit:
            user.save()
        return user
