"""Account creation, shared by the signup page and the declare funnel.

The three steps below must stay together — a funnel that created an account
without sending the verification email, or without logging in, would strand the
member. Keeping them in one place is what stops the two call sites drifting.
"""

from django.contrib.auth import login
from django.http import HttpRequest

from accounts.emails import send_verification_email
from accounts.forms import SignupForm
from accounts.models import User


def create_and_login(request: HttpRequest, form: SignupForm) -> User:
    """Create the account, send the verification email, log the user in.

    Auto-login is deliberate: the gate is on creating contributions, not on
    logging in.
    """
    user: User = form.save()
    send_verification_email(request, user)
    login(request, user)
    return user
