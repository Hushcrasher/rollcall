from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from accounts.github import extract_login
from accounts.images import ProcessedImage, process_image
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

    def clean_email(self) -> str:
        # Stored lowercase so "John@X.com" and "john@x.com" are one account —
        # phones autocapitalize, and login matches the stored value exactly.
        # The Lower(email) unique constraint on the model is the DB backstop.
        return self.cleaned_data["email"].lower()


class EmailAuthenticationForm(AuthenticationForm):
    """Login form labelled for email (the USERNAME_FIELD is `email`)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Email")
        self.fields["username"].widget = forms.EmailInput(attrs={"autofocus": True})

    def clean_username(self) -> str:
        # Emails are stored lowercase (SignupForm / UserManager); fold the
        # login input the same way so case never locks a member out.
        return self.cleaned_data["username"].lower()


class RecruiterApplicationForm(forms.ModelForm):
    class Meta:
        model = RecruiterApplication
        fields = ["full_name", "company_name", "work_email", "linkedin_url", "message"]


class ProfileForm(forms.ModelForm):
    """The profile fields + the three visibility booleans (docs/01-DESIGN.md §3.4),
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
        # A field with a `default` (e.g. country) keeps its old value when its
        # key is omitted from POST; only an explicit empty value clears it —
        # unlike the checkboxes, which an omitted key turns off.
        fields = [
            "display_name",
            "bio",
            "location",
            "country",
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


class PortfolioImageForm(forms.Form):
    """FileField, not ImageField: the pipeline does the validating, so its
    messages stay the single source of truth (accounts/images.py)."""

    image = forms.FileField(label=_("Image"))
    caption = forms.CharField(label=_("Caption"), max_length=140, required=False)

    def clean_image(self) -> ProcessedImage:
        return process_image(self.cleaned_data["image"], max_side=2560, thumbnail=True)
