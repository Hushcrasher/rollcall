"""Typing helper: an HttpRequest known to carry an authenticated user.

`request.user` is added by middleware and is invisible to the static type
checker on a plain HttpRequest. Use this for login-gated views and admin
actions where the user is guaranteed present.
"""

from django.http import HttpRequest

from accounts.models import User


class AuthedHttpRequest(HttpRequest):
    user: User
