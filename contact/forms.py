from django import forms
from django.utils.translation import gettext_lazy as _

from contact.models import Report


class ContactForm(forms.Form):
    subject = forms.CharField(max_length=255, label=_("Subject"))
    message = forms.CharField(widget=forms.Textarea, label=_("Message"))


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["target_type", "target_id", "reason"]
        widgets = {"reason": forms.Textarea}
