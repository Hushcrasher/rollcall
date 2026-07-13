"""Contribution CRUD. Creating a credit requires a verified email (design
non-negotiable #6); editing/deleting is restricted to the owner."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import CreateView, DeleteView, UpdateView

from contributions.forms import ContributionForm
from contributions.models import Contribution


class EmailVerifiedRequiredMixin(LoginRequiredMixin):
    """Bounce logged-in-but-unverified users to the verification notice."""

    request: Any  # provided by the Django CBV this is mixed into

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if user.is_authenticated and not user.is_email_verified:
            messages.error(request, _("Please verify your email before adding credits."))
            return redirect("accounts:verification_sent")
        return super().dispatch(request, *args, **kwargs)


class _OwnerProfileRedirectMixin:
    # `request` is provided by the Django CBV this is mixed into; typed loosely
    # so `self.request.user` (added by middleware) resolves.
    request: Any

    def get_success_url(self) -> str:
        return reverse("accounts:profile", kwargs={"slug": self.request.user.slug})


class ContributionCreateView(EmailVerifiedRequiredMixin, _OwnerProfileRedirectMixin, CreateView):
    model = Contribution
    form_class = ContributionForm
    template_name = "contributions/contribution_form.html"

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        form.instance.user = self.request.user
        messages.success(self.request, _("Credit added."))
        return super().form_valid(form)


class ContributionUpdateView(LoginRequiredMixin, _OwnerProfileRedirectMixin, UpdateView):
    model = Contribution
    form_class = ContributionForm
    template_name = "contributions/contribution_form.html"

    def get_queryset(self) -> QuerySet[Contribution]:
        return Contribution.objects.filter(user=self.request.user)  # owner-only

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        messages.success(self.request, _("Credit updated."))
        return super().form_valid(form)


class ContributionDeleteView(LoginRequiredMixin, _OwnerProfileRedirectMixin, DeleteView):
    model = Contribution
    template_name = "contributions/contribution_confirm_delete.html"

    def get_queryset(self) -> QuerySet[Contribution]:
        return Contribution.objects.filter(user=self.request.user)  # owner-only

    def form_valid(self, form: Any) -> HttpResponse:
        messages.success(self.request, _("Credit deleted."))
        return super().form_valid(form)
