"""The card renderer is a pure function: CardData in, PNG bytes out. These
tests pin the spec's §2 layout rules without pixel-matching a design."""

from io import BytesIO

from PIL import Image

from cards.render import HEIGHT, WIDTH, CardData, covered, fallback_card, render, title_size


def _png(data: CardData) -> Image.Image:
    return Image.open(BytesIO(render(data)))


def test_renders_a_1200x630_png() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    assert im.format == "PNG"
    assert im.size == (WIDTH, HEIGHT)


def test_title_shrinks_then_ellipsizes() -> None:
    # "Christelle Bayn-Delacroix de Montmorency" measures 1177px at 56px in
    # the real vendored Inter Bold — over the 1080px budget — so it would
    # fall straight to 44px rather than pinning the middle tier; this name
    # is verified (via font.getlength) to not fit at 72px but fit at 56px.
    assert title_size("Sasha Haddad") == 72
    assert title_size("Anne-Sophie Vasseur-Delacroix") == 56
    assert title_size("A" * 60) == 44  # still too long at 44 → the renderer ellipsizes


def test_text_block_is_vertically_centred() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    rows = [
        y
        for y in range(HEIGHT)
        if any(im.getpixel((x, y)) != (255, 255, 255) for x in range(0, WIDTH, 4))
    ]
    top, bottom = rows[0], HEIGHT - 1 - rows[-1]
    assert abs(top - bottom) <= 6


def test_empty_fields_collapse() -> None:
    full = _png(CardData(kind="profile", title="A", subtitle="B", stats="C", footer="D", badge="E"))
    bare = _png(CardData(kind="profile", title="A"))

    def ink(im: Image.Image) -> int:
        return sum(
            1
            for y in range(0, HEIGHT, 2)
            for x in range(0, WIDTH, 2)
            if im.getpixel((x, y)) != (255, 255, 255)
        )

    assert ink(full) > ink(bare)


def test_coverage_check() -> None:
    assert covered("Zoë Müller-Łukasz · Lyon — 2016–present…")
    assert covered("Ярослав Ковальчук")
    assert not covered("山田 太郎")
    assert not covered("أحمد")


def test_non_latin_name_renders_the_fallback_card() -> None:
    data = CardData(kind="profile", title="山田 太郎", subtitle="Tools Programmer")
    assert render(data) == render(fallback_card())


def test_wordmark_is_two_stacked_lines_in_the_mono_face() -> None:
    from cards.render import wordmark_lines

    assert [text for text, _font in wordmark_lines()] == ["ROLL", "CALL"]
    assert {font.getname()[0] for _text, font in wordmark_lines()} == {"JetBrains Mono"}


def test_card_still_renders_and_centres_with_the_stacked_wordmark() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    assert im.size == (WIDTH, HEIGHT)
    rows = [
        y
        for y in range(HEIGHT)
        if any(im.getpixel((x, y)) != (255, 255, 255) for x in range(0, WIDTH, 4))
    ]
    assert abs(rows[0] - (HEIGHT - 1 - rows[-1])) <= 6
