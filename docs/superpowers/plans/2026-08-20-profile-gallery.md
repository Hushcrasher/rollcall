# Profile gallery & upload hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the validated 2026-08-20 gallery spec: a `ProfileImage` model (12 max, captions), owner-only management, a "Work" section on profiles — and one hardened image pipeline (`accounts/images.py`) that both the gallery and the existing avatar upload go through.

**Architecture:** The pipeline is the security boundary and is a pure module (bytes in → validated re-encoded WebP out, no DB), so it gets pure unit tests. Everything else is thin: one model, two POST-only views, two template sections, and three integration points (avatar form, account deletion, JSON export).

**Tech Stack:** Django 6, Pillow (already a dependency), django-ratelimit (already a dependency), pytest-django. Prereq: the mobile-first surface plan has landed (`static/css/app.css` exists; Pico styles the templates).

**Spec:** `docs/superpowers/specs/2026-08-20-profile-gallery-design.md` — read it first; it is binding.

## Global Constraints

- **This is a security surface: tests first, always.** Every pipeline behavior lands red→green.
- Every user-facing string goes through i18n; every function fully typed. `ty` has no Django plugin — where a `FieldFile` confuses it, use the existing accommodation (`stored: Any = obj.image` bridge, as `AccountDeleteView` already does for the avatar), never a new pattern.
- `static/css/app.css` stays functional-only (spec 1's rule): the gallery grid is layout, nothing decorative.
- All commits DCO signed-off: `git commit -s`, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Gates before every commit: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`. Dev DB up: `docker compose up db -d`.
- Verified-user test idiom (house style): `User.objects.create_user(..., email_verified_at=timezone.now())`.

---

### Task 1: The pipeline — `accounts/images.py`

**Files:**
- Create: `accounts/images.py`
- Test: `accounts/tests/test_image_pipeline.py` (new)

**Interfaces:**
- Consumes: nothing (pure module).
- Produces: `process_image(uploaded: UploadedFile, *, max_side: int, thumbnail: bool = False) -> ProcessedImage` where `ProcessedImage` is a `NamedTuple` of `image: ContentFile` and `thumbnail: ContentFile | None`; module constants `MAX_UPLOAD_BYTES`, `ALLOWED_FORMATS`, `THUMBNAIL_SIDE`. Raises `django.core.exceptions.ValidationError`.

- [ ] **Step 1: Write the failing tests**

Create `accounts/tests/test_image_pipeline.py`:

```python
"""The hardened image intake (spec 2026-08-20-profile-gallery §2). Every byte
a user uploads goes through process_image — these tests are the security
gate's contract. Pure module: no database."""

from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts import images


def _upload(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 64),
    exif: bool = False,
    name: str = "t.jpg",
) -> SimpleUploadedFile:
    buffer = BytesIO()
    img = Image.new("RGB", size, "red")
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "TestCam"  # Make — the marker the strip test hunts for
        img.save(buffer, format=fmt, exif=tags)
    else:
        img.save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/octet-stream")


def test_valid_jpeg_reencodes_to_webp_with_a_thumbnail() -> None:
    processed = images.process_image(_upload(), max_side=2560, thumbnail=True)
    out = Image.open(BytesIO(processed.image.read()))
    assert out.format == "WEBP"
    assert processed.thumbnail is not None
    thumb = Image.open(BytesIO(processed.thumbnail.read()))
    assert thumb.format == "WEBP"


def test_the_clients_filename_never_survives() -> None:
    processed = images.process_image(_upload(name="../../evil<svg>.jpg"), max_side=2560)
    assert processed.image.name is not None
    assert processed.image.name.endswith(".webp")
    assert "evil" not in processed.image.name
    assert "/" not in processed.image.name


def test_svg_is_rejected_even_renamed_to_png() -> None:
    svg = SimpleUploadedFile(
        "art.png",
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        content_type="image/png",
    )
    with pytest.raises(ValidationError):
        images.process_image(svg, max_side=2560)


def test_gif_is_rejected() -> None:
    with pytest.raises(ValidationError):
        images.process_image(_upload(fmt="GIF", name="t.gif"), max_side=2560)


def test_oversize_upload_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(ValidationError):
        images.process_image(_upload(), max_side=2560)


def test_decompression_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real >40MP fixture would bloat the repo; shrinking the guard exercises
    # the identical code path (Pillow raises inside open() past 2x the limit).
    monkeypatch.setattr(images.Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(ValidationError):
        images.process_image(_upload(size=(64, 64)), max_side=2560)


def test_exif_is_destroyed() -> None:
    processed = images.process_image(_upload(exif=True), max_side=2560)
    data = processed.image.read()
    assert b"TestCam" not in data
    assert b"Exif" not in data and b"EXIF" not in data


def test_resize_caps_the_longest_side() -> None:
    processed = images.process_image(_upload(size=(300, 100)), max_side=200)
    out = Image.open(BytesIO(processed.image.read()))
    assert max(out.size) == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_image_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.images'` (or ImportError).

- [ ] **Step 3: Write the pipeline**

Create `accounts/images.py`:

```python
"""Hardened image intake — the ONLY path user image bytes take into storage
(spec docs/superpowers/specs/2026-08-20-profile-gallery-design.md §2).

Re-encoding is the core defense: decode fully, resize, write a fresh WebP.
A polyglot payload, appended archive or crafted metadata does not survive a
re-encode, and EXIF — GPS position included — is dropped because Pillow
writes none unless asked."""

from io import BytesIO
from typing import NamedTuple
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# SVG is script-capable XML and must stay impossible; GIF/animation is out of
# scope (spec). The check reads the *decoded* format, never name or headers.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
WEBP_QUALITY = 82
THUMBNAIL_SIDE = 400

# Parsing a header that promises a >40MP canvas must raise, not allocate.
Image.MAX_IMAGE_PIXELS = 40_000_000


class ProcessedImage(NamedTuple):
    image: ContentFile
    thumbnail: ContentFile | None


def _encode(source: Image.Image, max_side: int) -> ContentFile:
    out = source.copy()
    if out.mode not in ("RGB", "RGBA"):
        # P/LA can carry transparency; anything else flattens to RGB.
        out = out.convert("RGBA") if out.mode in ("P", "LA", "PA") else out.convert("RGB")
    out.thumbnail((max_side, max_side))  # no-op when already smaller
    buffer = BytesIO()
    out.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return ContentFile(buffer.getvalue(), name=f"{uuid4().hex}.webp")


def process_image(
    uploaded: UploadedFile, *, max_side: int, thumbnail: bool = False
) -> ProcessedImage:
    """Validate and re-encode one upload; ValidationError on anything that is
    not a plain JPEG/PNG/WebP within the caps."""
    if uploaded.size is not None and uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Images can be at most 10 MB."))
    try:
        source = Image.open(uploaded)
        source.load()
    except Image.DecompressionBombError as exc:
        raise ValidationError(_("This image's dimensions are too large.")) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(_("Upload a JPEG, PNG or WebP image.")) from exc
    if source.format not in ALLOWED_FORMATS:
        raise ValidationError(_("Upload a JPEG, PNG or WebP image."))
    if source.width * source.height > Image.MAX_IMAGE_PIXELS:
        raise ValidationError(_("This image's dimensions are too large."))
    return ProcessedImage(
        image=_encode(source, max_side),
        thumbnail=_encode(source, THUMBNAIL_SIDE) if thumbnail else None,
    )
```

If `ty` flags the PIL imports or `Image.Exif` in the test, use the house accommodation (`# ty: ignore[...]` on the specific line), not a stub file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest accounts/tests/test_image_pipeline.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add accounts/images.py accounts/tests/test_image_pipeline.py
git commit -s -m "feat(images): hardened intake pipeline — re-encode to WebP, strip EXIF, reject SVG/bombs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `ProfileImage` model + migration + admin

**Files:**
- Modify: `accounts/models.py` (model + `MAX_PORTFOLIO_IMAGES = 12`)
- Modify: `accounts/admin.py`
- Create: `accounts/migrations/0007_profileimage.py` (via makemigrations)
- Test: `accounts/tests/test_portfolio.py` (new — model half)

**Interfaces:**
- Consumes: nothing from Task 1 yet (files land via the views in Task 3).
- Produces: `ProfileImage` (fields `user`, `image`, `thumbnail`, `caption`, `created_at`; `Meta.ordering = ["-created_at"]`; `related_name="portfolio_images"`), constant `accounts.models.MAX_PORTFOLIO_IMAGES = 12`.

- [ ] **Step 1: Write the failing tests**

Create `accounts/tests/test_portfolio.py`:

```python
"""The profile gallery (spec 2026-08-20-profile-gallery) — model, management
views, display, and the file lifecycle."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import MAX_PORTFOLIO_IMAGES, ProfileImage, User

pytestmark = pytest.mark.django_db


def _user(email: str = "artist@example.com", verified: bool = True, **kwargs: object) -> User:
    return User.objects.create_user(
        email=email,
        password="x",
        display_name="Artist",
        email_verified_at=timezone.now() if verified else None,
        **kwargs,
    )


def _image(user: User, caption: str = "") -> ProfileImage:
    # Stored files are irrelevant to model tests — tiny stand-ins are enough.
    return ProfileImage.objects.create(
        user=user,
        image=ContentFile(b"webp-bytes", name="a.webp"),
        thumbnail=ContentFile(b"webp-bytes", name="t.webp"),
        caption=caption,
    )


def test_gallery_is_newest_first_and_capped_constant_is_twelve() -> None:
    user = _user()
    first = _image(user, "first")
    second = _image(user, "second")
    ProfileImage.objects.filter(pk=first.pk).update(
        created_at=timezone.now() - timedelta(days=1)
    )
    assert [i.pk for i in user.portfolio_images.all()] == [second.pk, first.pk]
    assert MAX_PORTFOLIO_IMAGES == 12


def test_rows_cascade_with_the_user() -> None:
    user = _user()
    _image(user)
    user.delete()
    assert ProfileImage.objects.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProfileImage'`.

- [ ] **Step 3: Model + migration + admin**

In `accounts/models.py`, below the `User` model:

```python
MAX_PORTFOLIO_IMAGES = 12


class ProfileImage(models.Model):
    """Portfolio piece (spec 2026-08-20-profile-gallery). Both files are
    pipeline outputs (accounts/images.py) — raw uploads never reach storage."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="portfolio_images",
        verbose_name=_("user"),
    )
    image = models.ImageField(_("image"), upload_to="portfolio/")
    thumbnail = models.ImageField(_("thumbnail"), upload_to="portfolio/thumbs/")
    caption = models.CharField(_("caption"), max_length=140, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("profile image")
        verbose_name_plural = _("profile images")

    def __str__(self) -> str:
        return f"{self.user.display_name}: {self.caption or self.image.name}"
```

Run: `uv run python manage.py makemigrations accounts`
Expected: `0007_profileimage.py` (name may include suffixes; keep whatever Django generates).

In `accounts/admin.py`, register it so a reported profile's images are one click away (spec §4) — follow the file's existing registration style:

```python
@admin.register(ProfileImage)
class ProfileImageAdmin(admin.ModelAdmin):
    list_display = ["user", "caption", "created_at"]
    list_select_related = ["user"]
    search_fields = ["user__display_name", "user__email", "caption"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: PASS.

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add accounts/models.py accounts/admin.py accounts/migrations/0007_profileimage.py accounts/tests/test_portfolio.py
git commit -s -m "feat(accounts): ProfileImage model — 12-image portfolio, newest first

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Upload + delete views, form, URLs, profile_edit section

**Files:**
- Modify: `accounts/forms.py` (`PortfolioImageForm`)
- Modify: `accounts/views.py` (`PortfolioAddView`, `PortfolioDeleteView`, `ProfileEditView.get_context_data`)
- Modify: `accounts/urls.py` (two paths)
- Modify: `templates/accounts/profile_edit.html` ("Work" section)
- Modify: `static/css/app.css` (`.portfolio-grid`)
- Test: `accounts/tests/test_portfolio.py` (append)

**Interfaces:**
- Consumes: `process_image` (Task 1), `ProfileImage` / `MAX_PORTFOLIO_IMAGES` (Task 2), `EmailVerifiedRequiredMixin` (`accounts/mixins.py`, existing — honors a `verification_message` class attribute).
- Produces: URL names `accounts:portfolio_add` (POST `profile/images/`), `accounts:portfolio_delete` (POST `profile/images/<int:pk>/delete/`); context keys `portfolio_images`, `portfolio_form` on profile_edit.

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests/test_portfolio.py`. The imports below go at the
**top of the file** with the existing ones (ruff enforces import placement);
only the functions append:

```python
from io import BytesIO
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def _png_upload(name: str = "work.png") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def test_upload_creates_reencoded_image_and_thumbnail(client: Client) -> None:
    user = _user()
    client.force_login(user)
    response = client.post(
        reverse("accounts:portfolio_add"), {"image": _png_upload(), "caption": "Boss fight"}
    )
    assert response.status_code == 302
    stored = user.portfolio_images.get()
    assert stored.caption == "Boss fight"
    assert stored.image.name.endswith(".webp")
    assert "work" not in stored.image.name  # client filename never survives
    assert stored.thumbnail.name.endswith(".webp")


def test_unverified_user_is_bounced_to_verification(client: Client) -> None:
    user = _user(verified=False)
    client.force_login(user)
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 302
    assert response.url == reverse("accounts:verification_sent")
    assert user.portfolio_images.count() == 0


def test_anonymous_is_sent_to_login(client: Client) -> None:
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_the_thirteenth_image_is_rejected(client: Client) -> None:
    user = _user()
    client.force_login(user)
    for _i in range(MAX_PORTFOLIO_IMAGES):
        _image(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert user.portfolio_images.count() == MAX_PORTFOLIO_IMAGES


def test_a_rejected_file_stores_nothing(client: Client) -> None:
    user = _user()
    client.force_login(user)
    svg = SimpleUploadedFile("a.png", b"<svg xmlns='x'/>", content_type="image/png")
    client.post(reverse("accounts:portfolio_add"), {"image": svg})
    assert user.portfolio_images.count() == 0


def test_upload_is_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    user = _user()
    client.force_login(user)
    for _i in range(10):
        client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 403


def test_delete_removes_row_and_both_files(client: Client) -> None:
    user = _user()
    client.force_login(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    stored = user.portfolio_images.get()
    image_storage, image_name = stored.image.storage, stored.image.name
    thumb_name = stored.thumbnail.name
    client.post(reverse("accounts:portfolio_delete", args=[stored.pk]))
    assert user.portfolio_images.count() == 0
    assert not image_storage.exists(image_name)
    assert not image_storage.exists(thumb_name)


def test_you_cannot_delete_someone_elses_image(client: Client) -> None:
    owner = _user()
    other = _user(email="other@example.com")
    stored = _image(owner)
    client.force_login(other)
    response = client.post(reverse("accounts:portfolio_delete", args=[stored.pk]))
    assert response.status_code == 404
    assert owner.portfolio_images.count() == 1
```

Note: if the rate-limit test interferes with the others (shared cache counters), mirror the cache-clearing idiom used in `accounts/tests/test_rate_limit.py` / `search/tests/test_people_search_view.py` (`cache.clear()` in a fixture).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: new tests FAIL — `NoReverseMatch: 'portfolio_add'`.

- [ ] **Step 3: Form, views, URLs, template**

`accounts/forms.py` — add (with `from accounts.images import ProcessedImage, process_image` at the imports):

```python
class PortfolioImageForm(forms.Form):
    """FileField, not ImageField: the pipeline does the validating, so its
    messages stay the single source of truth (accounts/images.py)."""

    image = forms.FileField(label=_("Image"))
    caption = forms.CharField(label=_("Caption"), max_length=140, required=False)

    def clean_image(self) -> ProcessedImage:
        return process_image(self.cleaned_data["image"], max_side=2560, thumbnail=True)
```

`accounts/views.py` — add (imports to ensure: `from django.views import View`, `from django_ratelimit.decorators import ratelimit`, `from accounts.forms import PortfolioImageForm`, `from accounts.mixins import EmailVerifiedRequiredMixin`, `from accounts.models import MAX_PORTFOLIO_IMAGES, ProfileImage`, plus the already-imported `messages`, `redirect`, `get_object_or_404`, `method_decorator`):

```python
# Named group, house rule: an unnamed decorator derives its group from the
# view's qualname, so a rename would silently move the counter.
@method_decorator(
    ratelimit(group="portfolio_add", key="user", rate="10/h", method="POST", block=True),
    name="post",
)
class PortfolioAddView(EmailVerifiedRequiredMixin, View):
    verification_message = _("Please verify your email before adding images.")

    def post(self, request: AuthedHttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if request.user.portfolio_images.count() >= MAX_PORTFOLIO_IMAGES:
            messages.error(request, _("You can show up to 12 images."))
            return redirect("accounts:profile_edit")
        form = PortfolioImageForm(request.POST, request.FILES)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("accounts:profile_edit")
        processed = form.cleaned_data["image"]
        ProfileImage.objects.create(
            user=request.user,
            image=processed.image,
            thumbnail=processed.thumbnail,
            caption=form.cleaned_data["caption"],
        )
        messages.success(request, _("Image added."))
        return redirect("accounts:profile_edit")


class PortfolioDeleteView(LoginRequiredMixin, View):
    def post(self, request: AuthedHttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        stored = get_object_or_404(ProfileImage, pk=pk, user=request.user)
        # FieldFile at runtime; ty sees the ImageField (same bridge as the
        # avatar in AccountDeleteView). Row deletion doesn't remove files.
        image: Any = stored.image
        image.delete(save=False)
        thumbnail: Any = stored.thumbnail
        thumbnail.delete(save=False)
        stored.delete()
        messages.success(request, _("Image removed."))
        return redirect("accounts:profile_edit")
```

`ProfileEditView` — add (or extend) `get_context_data`:

```python
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["portfolio_images"] = self.request.user.portfolio_images.all()  # ty: ignore[possibly-missing-attribute]
        context["portfolio_form"] = PortfolioImageForm()
        return context
```

(Drop the `# ty: ignore` if `ty` doesn't flag the `AnonymousUser` union — `LoginRequiredMixin` guarantees a `User` here.)

`accounts/urls.py` — after the `profile/edit/` path:

```python
    path("profile/images/", views.PortfolioAddView.as_view(), name="portfolio_add"),
    path(
        "profile/images/<int:pk>/delete/",
        views.PortfolioDeleteView.as_view(),
        name="portfolio_delete",
    ),
```

`templates/accounts/profile_edit.html` — append after the main profile form, matching the page's structure:

```html
  <section>
    <h2>{% translate "Work" %}</h2>
    <p class="muted">{% translate "Show your work — up to 12 images on your profile, newest first." %}</p>
    {% if portfolio_images %}
      <ul class="portfolio-grid">
        {% for pimg in portfolio_images %}
          <li>
            <a href="{{ pimg.image.url }}"><img src="{{ pimg.thumbnail.url }}" alt="{{ pimg.caption }}"></a>
            {% if pimg.caption %}<p class="muted">{{ pimg.caption }}</p>{% endif %}
            <form action="{% url 'accounts:portfolio_delete' pimg.pk %}" method="post">
              {% csrf_token %}
              <button type="submit" class="outline secondary">{% translate "Delete" %}</button>
            </form>
          </li>
        {% endfor %}
      </ul>
    {% endif %}
    <form action="{% url 'accounts:portfolio_add' %}" method="post" enctype="multipart/form-data">
      {% csrf_token %}
      <p>{{ portfolio_form.image.label_tag }} {{ portfolio_form.image }}</p>
      <p>{{ portfolio_form.caption.label_tag }} {{ portfolio_form.caption }}</p>
      <button type="submit">{% translate "Add image" %}</button>
    </form>
  </section>
```

`static/css/app.css` — append:

```css
/* Profile gallery (spec 2026-08-20-profile-gallery) — layout only. */
.portfolio-grid {
  list-style: none; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: .6rem;
}
.portfolio-grid img { width: 100%; height: auto; display: block; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: PASS (all).

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add accounts/forms.py accounts/views.py accounts/urls.py templates/accounts/profile_edit.html static/css/app.css accounts/tests/test_portfolio.py
git commit -s -m "feat(accounts): portfolio upload/delete — verified-only, 12 max, rate-limited

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: The "Work" section on the public profile

**Files:**
- Modify: `accounts/views.py` (`ProfileView.get_context_data`)
- Modify: `templates/accounts/profile.html`
- Test: `accounts/tests/test_portfolio.py` (append)

**Interfaces:**
- Consumes: `portfolio_images` related manager; the `.portfolio-grid` CSS from Task 3.
- Produces: context key `portfolio_images` on the profile page.

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests/test_portfolio.py`:

```python
def test_profile_shows_the_work_section(client: Client) -> None:
    user = _user()
    _image(user, caption="Boss fight concept")
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "Work" in body
    assert "Boss fight concept" in body


def test_profile_without_images_has_no_work_section(client: Client) -> None:
    user = _user()
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert "portfolio-grid" not in main
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: the two new tests FAIL.

- [ ] **Step 3: View + template**

`ProfileView.get_context_data` (exists at `accounts/views.py:157`) — add one line beside its existing context keys:

```python
        context["portfolio_images"] = self.object.portfolio_images.all()
```

`templates/accounts/profile.html` — between the Credits `</section>` and the GitHub block (credits stay the recruiter's first read, spec §3):

```html
  {% if portfolio_images %}
    <section>
      <h2>{% translate "Work" %}</h2>
      <ul class="portfolio-grid">
        {% for pimg in portfolio_images %}
          <li>
            <a href="{{ pimg.image.url }}"><img src="{{ pimg.thumbnail.url }}" alt="{{ pimg.caption }}" loading="lazy"></a>
            {% if pimg.caption %}<p class="muted">{{ pimg.caption }}</p>{% endif %}
          </li>
        {% endfor %}
      </ul>
    </section>
  {% endif %}
```

No new visibility rule: `profile_public=False` already 404s the whole page for others.

- [ ] **Step 4: Run, gates, commit**

Run: `uv run pytest accounts/tests/test_portfolio.py -v` → PASS
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add accounts/views.py templates/accounts/profile.html accounts/tests/test_portfolio.py
git commit -s -m "feat(profile): Work section — the gallery renders after credits

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: The avatar goes through the pipeline

**Files:**
- Modify: `accounts/forms.py` (`ProfileForm.clean_avatar`)
- Test: `accounts/tests/test_portfolio.py` (append)

**Interfaces:**
- Consumes: `process_image` (Task 1).
- Produces: every stored avatar is a re-encoded, EXIF-free, ≤512px WebP.

- [ ] **Step 1: Write the failing test**

Append to `accounts/tests/test_portfolio.py`:

```python
def _jpeg_with_exif(name: str = "face.jpg") -> SimpleUploadedFile:
    buffer = BytesIO()
    img = Image.new("RGB", (900, 900), "green")
    tags = Image.Exif()
    tags[0x010F] = "TestCam"
    img.save(buffer, format="JPEG", exif=tags)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def test_avatar_goes_through_the_pipeline(client: Client) -> None:
    """Same intake as the gallery (spec §2): re-encoded, EXIF gone, 512px cap.
    The old bare-ImageField path stored original bytes, GPS included."""
    user = _user()
    client.force_login(user)
    response = client.post(
        reverse("accounts:profile_edit"),
        {"display_name": "Artist", "avatar": _jpeg_with_exif()},
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.avatar.name.endswith(".webp")
    data = user.avatar.read()
    assert b"TestCam" not in data
    out = Image.open(BytesIO(data))
    assert max(out.size) <= 512
```

Note: the profile_edit POST must carry every required `ProfileForm` field — if `display_name` alone 302s today (check `accounts/tests/test_profile_edit.py` for the minimal-POST idiom), mirror that idiom here.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_portfolio.py::test_avatar_goes_through_the_pipeline -v`
Expected: FAIL — the stored name keeps `.jpg` / EXIF survives.

- [ ] **Step 3: Route the avatar through the pipeline**

In `accounts/forms.py`'s `ProfileForm`, add (import `UploadedFile` from `django.core.files.uploadedfile`):

```python
    def clean_avatar(self) -> Any:
        avatar = self.cleaned_data.get("avatar")
        # Only fresh uploads re-encode: an unchanged avatar arrives as the
        # stored FieldFile, and clearing arrives as False — pass both through.
        if isinstance(avatar, UploadedFile):
            return process_image(avatar, max_side=512).image
        return avatar
```

- [ ] **Step 4: Run, gates, commit**

Run: `uv run pytest accounts/tests/test_portfolio.py -v` → PASS
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
(If an existing profile-edit test uploaded a non-image or asserted the stored filename, align it with the pipeline's behavior.)

```bash
git add accounts/forms.py accounts/tests/test_portfolio.py
git commit -s -m "fix(accounts): avatar uploads go through the hardened pipeline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Account deletion cleans files; JSON export gains the portfolio

**Files:**
- Modify: `accounts/views.py` (`AccountDeleteView.post`, around line 211)
- Modify: `accounts/export.py` (`build_personal_data_export`)
- Test: `accounts/tests/test_portfolio.py` (append)

**Interfaces:**
- Consumes: `ProfileImage` rows and files from Task 3.
- Produces: export key `"portfolio"`: list of `{"caption", "created_at", "file"}`.

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests/test_portfolio.py`:

```python
def test_account_deletion_removes_portfolio_files(client: Client) -> None:
    """Non-negotiable zone: deletion must fully work (docs/00 #5). Cascade
    removes rows; this pins the files."""
    user = _user()
    client.force_login(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    stored = user.portfolio_images.get()
    storage, image_name, thumb_name = (
        stored.image.storage,
        stored.image.name,
        stored.thumbnail.name,
    )
    client.post(reverse("accounts:account_delete"))
    assert not User.objects.filter(pk=user.pk).exists()
    assert not storage.exists(image_name)
    assert not storage.exists(thumb_name)


def test_export_includes_the_portfolio(client: Client) -> None:
    user = _user()
    client.force_login(user)
    client.post(
        reverse("accounts:portfolio_add"), {"image": _png_upload(), "caption": "Boss fight"}
    )
    data = client.get(reverse("accounts:export_data")).json()
    assert len(data["portfolio"]) == 1
    assert data["portfolio"][0]["caption"] == "Boss fight"
    assert data["portfolio"][0]["file"].endswith(".webp")
```

Note: if `account_delete` requires a confirmation field in POST, mirror the idiom in `accounts/tests/test_deletion.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_portfolio.py -v`
Expected: FAIL — files survive deletion; `KeyError: 'portfolio'`.

- [ ] **Step 3: Deletion + export**

`AccountDeleteView.post` — next to the existing avatar cleanup (`accounts/views.py:213-216`):

```python
        for stored in user.portfolio_images.all():
            image: Any = stored.image
            image.delete(save=False)
            thumbnail: Any = stored.thumbnail
            thumbnail.delete(save=False)
```

`accounts/export.py` — in `build_personal_data_export`'s returned dict, alongside the existing sections (reuse the module's `_iso` helper):

```python
        "portfolio": [
            {
                "caption": image.caption,
                "created_at": _iso(image.created_at),
                "file": image.image.name,
            }
            for image in user.portfolio_images.all()
        ],
```

- [ ] **Step 4: Run, gates, commit**

Run: `uv run pytest accounts/tests/test_portfolio.py accounts/tests/test_deletion.py -v` → PASS
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add accounts/views.py accounts/export.py accounts/tests/test_portfolio.py
git commit -s -m "feat(accounts): portfolio in the GDPR surface — deletion removes files, export lists them

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Docs, final gates, browser verification

**Files:**
- Modify: `docs/01-DESIGN.md`, `docs/04-DATABASE-SCHEMA.md`, `ROADMAP.md`

**Interfaces:** consumes everything above, landed.

- [ ] **Step 1: docs/04-DATABASE-SCHEMA.md**

Add a `profile_image` section following the file's table-description format: the five fields with types/constraints, `CASCADE` on user, the note that both files are pipeline outputs and the 12-image cap is app-enforced. Reference migration 0007.

- [ ] **Step 2: docs/01-DESIGN.md**

In the profile section, add in the doc's own prose style:
- Profiles carry a "Work" gallery — up to 12 images with captions, newest first, shown after credits; managed from profile edit; verified accounts only.
- Every uploaded image (gallery **and** avatar) is re-encoded server-side: WebP, EXIF/GPS stripped, SVG impossible, 10 MB / 40 MP caps, random filenames (spec 2026-08-20-profile-gallery).
- Deletion removes image files; the JSON export lists the portfolio.

- [ ] **Step 3: ROADMAP.md**

Under the Phase 8 section added by the surface plan, append:

```markdown
## Phase 9 — Profile gallery & upload hardening ✅ (spec 2026-08-20)

Goal: artists can show work; every upload goes through one hardened pipeline.

- [x] `accounts/images.py`: re-encode to WebP, EXIF stripped, SVG/GIF impossible, 10 MB + 40 MP caps, UUID names
- [x] `ProfileImage` (migration 0007): 12 max, captions, newest first; admin registered
- [x] Upload/delete views — verified-only, rate-limited (10/h), owner-only delete
- [x] "Work" section on profiles (after credits); grid layout in app.css
- [x] Avatar routed through the same pipeline (512px)
- [x] GDPR: deletion removes files; JSON export lists the portfolio
```

- [ ] **Step 4: Final gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check && docker build -q .`
Expected: all pass.

- [ ] **Step 5: Browser verification (375px, light + dark)**

1. Log in as a fixture user, verify email state or use a fresh verified user; upload two images with captions from profile edit; delete one.
2. The profile page shows "Work" after Credits, grid wraps cleanly at 375px, thumbnails link to full images.
3. Upload an oversized/SVG file → the error message renders as a Django message, nothing stored.
4. Screenshot the profile (light + dark) for the session log.

- [ ] **Step 6: Commit**

```bash
git add docs/01-DESIGN.md docs/04-DATABASE-SCHEMA.md ROADMAP.md
git commit -s -m "docs: record the profile gallery and the hardened upload pipeline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
