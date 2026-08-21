# Profile gallery & upload hardening — design

> Status: validated 2026-08-20. Adds one model (`ProfileImage`, migration
> 0007), owner-only management views, a profile "Work" section, and — the
> security half — a single image-processing pipeline that the existing avatar
> upload is moved onto. Complements
> [2026-08-20-mobile-first-surface-design.md](2026-08-20-mobile-first-surface-design.md)
> (which provides the style layer this renders under).

## Problem

Artists have no way to show work. The product bet is that people declare
credits because the profile is worth having; for roughly half the industry
(art, animation, UI, audio) a profile without images isn't. Developers got the
GitHub block (spec 2026-07-15); artists get nothing.

Meanwhile the one upload we do have — the avatar — is a bare `ImageField`:
Pillow confirms the bytes decode as an image, and nothing else. No size cap,
no dimension cap, original bytes stored as-is (EXIF included, so a photo
uploads its GPS position), original filename kept. Adding a second, bigger
upload surface without fixing that would double down on the weakness.

## Decision (validated with the product owner, 2026-08-20)

**Profile-level gallery** — not per-credit images. Up to **12 images** per
user, each with an optional caption, newest first. Per-credit attachment was
considered (better recruiter context) and rejected for this iteration: more
model surface, more UI, and the gallery ships value now. Revisit later; the
model below doesn't preclude adding a nullable `contribution` FK one day.

## 1. Model — `accounts.ProfileImage`

| Field | Type | Notes |
|---|---|---|
| `user` | FK `User`, `CASCADE`, `related_name="portfolio_images"` | |
| `image` | `ImageField(upload_to="portfolio/")` | pipeline output, never raw upload |
| `thumbnail` | `ImageField(upload_to="portfolio/thumbs/")` | pipeline output |
| `caption` | `CharField(max_length=140, blank=True)` | plain text, rendered escaped |
| `created_at` | `DateTimeField(auto_now_add=True)` | |

`Meta.ordering = ["-created_at"]`. The 12-image cap is enforced in the upload
view (count check inside the POST handler), not the schema — same pragmatism
as other app-level invariants, and the cap may move.

Docs: new section in `docs/04-DATABASE-SCHEMA.md`; profile behavior in
`docs/01-DESIGN.md`; `ROADMAP.md` entry.

## 2. The pipeline — `accounts/images.py`

One module, one entry point, used by **both** the gallery and the avatar:

```
process_image(uploaded_file, *, max_side: int) -> ProcessedImage
# ProcessedImage: named tuple of (image: ContentFile, thumbnail: ContentFile | None)
```

Ordered checks, each failing with an i18n `ValidationError`:

1. **Upload size ≤ 10 MB** — checked before any decode.
2. **Decompression-bomb guard** — module sets `Image.MAX_IMAGE_PIXELS` to
   40 MP so oversized canvases raise instead of exhausting memory; the
   resulting `DecompressionBombError` is caught and translated to a user
   error.
3. **Format allow-list from decoded bytes** — `{JPEG, PNG, WEBP}` read off
   the parsed image, never the filename or `Content-Type`. **SVG is
   deliberately impossible** (script-capable XML), as is GIF (animation is
   out of scope) and everything exotic.
4. **Re-encode, always** — decode fully, convert mode as needed (alpha
   preserved), resize to `max_side` (gallery 2560px, avatar 512px, thumbnail
   400px), save as **WebP q≈82** to a fresh buffer. Re-encoding is the core
   defense: any polyglot payload, appended archive, or crafted metadata does
   not survive it, and **EXIF is dropped** (Pillow writes none unless asked)
   — which also strips GPS, a privacy obligation in the spirit of
   docs/00 #1.
5. **Random names** — `uuid4().hex + ".webp"`; the client's filename never
   reaches storage.

Storage stays Django's default (local `media/` in dev, R2 via django-storages
in prod — separate origin, so a hostile file that somehow survived would still
not execute in the site's context). No `<img>` ever points at raw user input.

The avatar form path switches to `process_image(..., max_side=512)` (no
thumbnail). Existing stored avatars are left as-is — dev-fixture data only;
prod hasn't launched.

## 3. Views & templates

- **Manage** (owner only): a "Work" section on `profile_edit.html` — current
  images as thumbnails with delete buttons, plus an upload form (file +
  caption, one image per submit; multi-upload is out of scope). Two endpoints
  in `accounts/urls.py`:
  - `POST /profile/images/` (`portfolio_add`) — `EmailVerifiedRequiredMixin`
    (existing, `accounts/mixins.py`) with `verification_message` "Please
    verify your email before adding images."; rejects the 13th image with
    "You can show up to 12 images."
  - `POST /profile/images/<pk>/delete/` (`portfolio_delete`) — owner check by
    filtering on `request.user`, deletes the DB row **and both files** — the
    files via a `post_delete` receiver on `ProfileImage`, not in the view, so
    the cascade and admin deletion paths clean up on the same code.
  - Both POST-only with CSRF, redirecting back to `profile_edit`; no htmx
    needed.
- **Rate limit**: `10/h` per user on `portfolio_add`, django-ratelimit with
  an explicitly named group (house pattern — see the note on
  `_RATELIMIT_GROUP` in `contributions/views.py`). Counting every POST is
  fine — no need to count only accepted uploads.
- **Display**: a `Work` section on `profile.html`, after Credits and before
  the GitHub block (credits stay the recruiter's first read). A thumbnail
  grid (`app.css`, functional layout only: CSS grid `auto-fill/minmax`);
  each thumbnail links to the full `image` URL. Captions render under the
  thumbnail, escaped as all output is. The section is absent when the user
  has no images. Visibility needs no new rule: the gallery renders inside the
  profile page, and `profile_public=False` already 404s the whole page.

## 4. Abuse, moderation, GDPR

- **Moderation**: the existing report flow covers profiles
  (`/report?type=user`), and the gallery is profile content — no new report
  type. The admin gets `ProfileImage` registered with thumbnails listed, so
  a reported profile's images are one click away.
- **Account deletion** (non-negotiable test zone): deletion already removes
  the avatar file; extend the same step to every `ProfileImage` row's two
  files. Cascade removes the rows.
- **JSON export**: add a `portfolio` list (caption, `created_at`, stored
  filename) alongside the existing sections.

## Out of scope

- Per-credit image attachment, manual reordering, cropping UI, multi-file
  upload, animated formats, NSFW auto-detection (report flow + admin is the
  POC answer), migrating previously stored avatar files.

## Tests (TDD — this is a security surface, write these first)

1. A valid JPEG/PNG/WebP upload lands re-encoded as WebP with a UUID name;
   dimensions capped; thumbnail written.
2. An SVG — including one renamed `.png` — is rejected; so is a >10 MB file
   and a decompression bomb (tiny file, huge canvas).
3. Output of a JPEG-with-EXIF upload contains **no EXIF** (assert on bytes,
   not on Pillow's politeness).
4. The 13th image is rejected; the 12th isn't.
5. Anonymous → login redirect; logged-in-unverified → verification bounce.
6. Rate limit: the 11th upload within an hour is rejected.
7. Deleting an image removes both files from storage; deleting the account
   removes all of them (extends the existing deletion tests).
8. Export contains the portfolio section.
9. Another user's `portfolio_delete` on my image 404s.
10. Avatar path: the same pipeline runs (one asserting test, e.g. EXIF gone).
