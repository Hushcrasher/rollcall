"""Shared test helpers used across more than one app's test suite. Fixtures
and factories that belong to a single app still live in that app's tests."""


def header(body: str) -> str:
    """The nav's own <header>, sliced out of a full page body.

    people_search.html (rendered in <main> on the home page) has its own
    search input, and other pages have their own headings — scoping to
    <header> is what makes assertions on the nav's markup specific to it.
    """
    return body[: body.index("</header>")]
