"""Admin configuration guards.

`UserAdmin.fieldsets` lists User's fields explicitly, so a field missing from
it is invisible and uneditable for staff. No Django system check catches that
(a `blank=True` field is valid whether or not admin declares it), hence the
guard below.
"""

from django.contrib.admin.utils import flatten_fieldsets

from accounts.admin import UserAdmin
from accounts.models import User


def test_all_editable_user_fields_are_reachable_in_admin() -> None:
    declared = set(flatten_fieldsets(UserAdmin.fieldsets))
    meta = User._meta  # ty: ignore[unresolved-attribute]  (metaclass-added attr)
    editable = {
        f.name for f in meta.get_fields() if getattr(f, "editable", False) and not f.auto_created
    }
    assert editable - declared == set()
