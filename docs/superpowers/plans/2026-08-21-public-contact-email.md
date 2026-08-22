# Public contact email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An opt-in, separate `public_email` a member can publish on their public profile — while the account email stays private forever. Amends non-negotiable #1 and every text that states it.

**Architecture:** One column (`User.public_email`, migration 0008), one form field (settings), one profile block, one export key, and the policy texts (docs/00, CLAUDE.md, docs/01, docs/04, privacy, about). Negative tests prove the address appears on the public profile page and nowhere else.

**Spec:** `docs/superpowers/specs/2026-08-21-public-contact-email-design.md` — binding.

## Global Constraints

- The **account email** (`User.email`) is never rendered anywhere — every existing "no email" test stays and keeps asserting that. `public_email` renders on the public profile page ONLY: never in OG cards/meta, the home feed, search results, game/company pages, the contact relay mails, sitemaps, logs.
- Stored lowercased (every email write path case-folds — `SignupForm.clean_email` precedent); no uniqueness.
- i18n; typed Python; comments state constraints; TDD.
- Commits DCO (`git commit -s`) ending `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; gates before each: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`.

---

### Task 1: Model, migration, settings form

**Files:** Modify `accounts/models.py`, `accounts/forms.py` (`ProfileForm`), `accounts/admin.py` (fieldsets — `test_all_editable_user_fields_are_reachable_in_admin` enforces it); Create `accounts/migrations/0008_user_public_email.py` (makemigrations); Test `accounts/tests/test_public_email.py` (new).

- [ ] **Step 1: Failing tests**

```python
"""Opt-in public contact email (spec 2026-08-21-public-contact-email): a
SEPARATE address the member chooses to publish. The account email stays
private — every existing "no email" test keeps asserting that."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.models import User

pytestmark = pytest.mark.django_db


def _user(**kw) -> User:
    return User.objects.create_user(email=kw.pop("email", "login@example.com"), password="x", display_name="Member", **kw)


def test_settings_form_saves_the_address_lowercased() -> None:
    user = _user()
    form = ProfileForm(data={"display_name": "Member", "public_email": "Hello@Studio.GG"}, instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.public_email == "hello@studio.gg"


def test_public_email_is_optional_and_independent_from_the_login_email() -> None:
    user = _user()
    form = ProfileForm(data={"display_name": "Member"}, instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.public_email == ""
    assert user.email == "login@example.com"


def test_settings_page_renders_the_field_with_its_help(client: Client) -> None:
    user = _user()
    client.force_login(user)
    body = client.get(reverse("accounts:profile_edit")).content.decode()
    assert 'name="public_email"' in body
    assert "Shown on your public profile to anyone" in body
```

- [ ] **Step 2: Run** → FAIL (no field).

- [ ] **Step 3: Model + migration + form + admin**

`accounts/models.py`, after `contactable`:

```python
    # A SEPARATE, opt-in address the member chooses to publish. The account
    # `email` above is never rendered anywhere; this one renders on the public
    # profile page only (spec 2026-08-21-public-contact-email). Lowercased on
    # every write path, like `email`; deliberately not unique (a studio
    # address may be shared).
    public_email = models.EmailField(
        _("public contact email"),
        blank=True,
        default="",
        help_text=_("Shown on your public profile to anyone. Leave empty to be reachable only through Rollcall messages."),
    )
```

`uv run python manage.py makemigrations accounts -n user_public_email`.

`accounts/forms.py` `ProfileForm.Meta.fields`: insert `"public_email"` after `"contactable"`; add `labels = {"public_email": _("Public contact email (optional)")}` to `Meta`; add:

```python
    def clean_public_email(self) -> str:
        # Same case-folding rule as the account email (SignupForm.clean_email).
        return self.cleaned_data.get("public_email", "").strip().lower()
```

`accounts/admin.py`: add `"public_email"` to the `UserAdmin` fieldset that holds `contactable`.

- [ ] **Step 4: Run** `accounts/tests/test_public_email.py accounts/tests/test_admin.py accounts/tests/test_profile_edit.py -q` → green; full gates. **Step 5: Commit** `feat(accounts): opt-in public contact email (migration 0008) — settings field, lowercased`.

---

### Task 2: Profile display, export, and the "nowhere else" tests

**Files:** Modify `templates/accounts/profile.html`, `accounts/export.py`; Test `accounts/tests/test_public_email.py` (append).

- [ ] **Step 1: Failing tests** (append; imports: `date`, `Contribution`, `Discipline`, `Game`, `timezone`):

```python
def _with_public_email() -> User:
    return _user(public_email="hello@studio.gg")


def test_public_profile_shows_the_mailto_to_anonymous_and_members(client: Client) -> None:
    user = _with_public_email()
    url = reverse("accounts:profile", args=[user.slug])
    assert 'href="mailto:hello@studio.gg"' in client.get(url).content.decode()
    other = _user(email="o@example.com")
    client.force_login(other)
    assert 'href="mailto:hello@studio.gg"' in client.get(url).content.decode()


def test_owner_sees_the_address_flagged_as_public(client: Client) -> None:
    user = _with_public_email()
    client.force_login(user)
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "hello@studio.gg" in body and "Shown publicly" in body


def test_private_profile_still_404s_for_visitors(client: Client) -> None:
    user = _with_public_email()
    user.profile_public = False
    user.save(update_fields=["profile_public"])
    assert client.get(reverse("accounts:profile", args=[user.slug])).status_code == 404


def test_the_address_appears_nowhere_else(client: Client) -> None:
    """Spec §4: public profile page only."""
    user = _with_public_email()
    game = Game.objects.create(title="Game", source=Game.Source.MANUAL)
    Contribution.objects.create(user=user, game=game, discipline=Discipline.objects.get(name="Design"), job_title="Dev", start_date=date(2020, 1, 1))
    design = Discipline.objects.get(name="Design")
    pages = [
        reverse("home"),  # feed
        reverse("home") + f"?discipline={design.pk}",  # search results
        reverse("games:game", args=[game.slug]),
        reverse("cards:profile", args=[user.slug]),  # PNG bytes
    ]
    for url in pages:
        assert b"hello@studio.gg" not in client.get(url).content, url
    # The meta tags of the profile page itself.
    import re
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    for content in re.findall(r'<meta [^>]*content="([^"]*)"', body):
        assert "hello@studio.gg" not in content


def test_export_includes_the_public_email(client: Client) -> None:
    user = _with_public_email()
    client.force_login(user)
    assert client.get(reverse("accounts:export_data")).json()["identity"]["public_email"] == "hello@studio.gg"
```

(`cards` app and `reverse("cards:profile")` exist on `main` since PR #21 — confirm; if this branch predates it, drop that URL from the list and say so.)

- [ ] **Step 2: Run** → FAIL (no mailto; no export key).

- [ ] **Step 3: Template + export**

`templates/accounts/profile.html`, right after the `location_display` line:

```html
    {% if profile_user.public_email %}
      {# The member's own choice to publish this address (spec 2026-08-21-public-contact-email §3). The account email is never rendered. #}
      <p><a href="mailto:{{ profile_user.public_email }}">{{ profile_user.public_email }}</a>
        {% if is_owner %}<span class="muted">{% translate "Shown publicly" %}</span>{% endif %}</p>
    {% endif %}
```

`accounts/export.py` `identity`: add `"public_email": user.public_email,` after `"email"`.

- [ ] **Step 4: Run** the file + `accounts/ cards/ search/ games/ -q`; full gates. **Step 5: Commit** `feat(profile): show the member's public contact email on the public profile only`.

---

### Task 3: The policy texts, ROADMAP, gates

**Files:** Modify `docs/00-README.md`, `CLAUDE.md`, `docs/01-DESIGN.md`, `docs/04-DATABASE-SCHEMA.md`, `templates/legal/privacy.html`, `templates/about.html`, `ROADMAP.md`; Test `games/tests/test_legal_pages.py` (append), `config/tests/test_about_page.py` (append).

- [ ] **Step 1: Failing tests**

```python
def test_privacy_page_states_the_public_address_rule(client: Client) -> None:
    body = client.get(reverse("privacy")).content.decode()
    assert "account email is never shown" in body.lower()
    assert "public contact address" in body.lower()


def test_about_page_states_the_public_address_rule(client: Client) -> None:
    body = client.get(reverse("about")).content.decode()
    assert "choose to publish" in body.lower()
```

- [ ] **Step 2: Texts** (every user-facing string through `blocktranslate`; keep each doc's voice):
  - `docs/00-README.md` #1: `The **account** email is never displayed or exposed anywhere. A member may publish a *separate* contact address on their profile (opt-in, settings); it appears only on the public profile page — never in cards, feeds, search results, game pages, exports to third parties, or logs. Contact otherwise only via relay (Reply-To pattern). *(Amended 2026-08-21, spec 2026-08-21-public-contact-email.)*`
  - `CLAUDE.md` first hard rule: `**Never expose the account email** in any page, response, header, export-to-others or log. A member's opt-in `public_email` renders on their public profile page only — nowhere else (spec 2026-08-21-public-contact-email). Contact is relay-only (`contact/views.py`, Reply-To pattern). `User.__str__` returns `display_name` — keep it that way.`
  - `docs/01-DESIGN.md` §3.4 profile fields: the new field and where it shows; the contact section: relay stays the default channel.
  - `docs/04-DATABASE-SCHEMA.md` §1: the column (EmailField, blank, lowercased, not unique, user-owned).
  - `templates/legal/privacy.html` — "What we store": `…your settings, and — if you add one — a public contact address.` "How contact works": `Your account email is never shown to anyone. If you add a public contact address in your settings, it is shown on your public profile to anyone, and you can remove it at any time. When someone messages you through Rollcall, we email you on their behalf with their address as the reply-to, so you decide whether to reply.`
  - `templates/about.html` contact paragraph: `Account email addresses are never shown anywhere on Rollcall; members may choose to publish a separate contact address on their profile. Contact otherwise goes through a relay, and only reaches people who have allowed it. …` (keep the report sentence).
  - `ROADMAP.md`: Phase 14 — "Public contact email ✅ (spec 2026-08-21)": the field, the profile-only display, the policy texts amended (docs/00 #1, CLAUDE.md, privacy, about), negative tests.
- [ ] **Step 3: Run** the two test files; full gates incl. `docker build -q .`; `git grep -n -i "never shown to anyone\|never exposed\|never displayed"` to catch any remaining sentence that contradicts the amended rule (the model help text for `contactable` — "The email itself is never exposed." — is still true of the account email; leave or clarify as "The account email itself…").
- [ ] **Step 4: Commit** `docs,legal: the account email stays private; a member may publish a separate contact address`.
- [ ] Controller: browser check — settings field, profile rendering for a visitor, owner note; `migrate` on the dev DB.
