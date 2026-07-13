from django import forms
from django.utils.translation import gettext_lazy as _


class ContactForm(forms.Form):
    subject = forms.CharField(max_length=255, label=_("Subject"))
    message = forms.CharField(widget=forms.Textarea, label=_("Message"))
