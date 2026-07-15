"""extract_login — parse a GitHub login from a pasted URL or bare handle."""

import pytest

from accounts.github import extract_login


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/torvalds", "torvalds"),
        ("github.com/torvalds", "torvalds"),
        ("https://github.com/torvalds/", "torvalds"),
        ("torvalds", "torvalds"),
        ("  https://github.com/torvalds  ", "torvalds"),
        ("https://www.github.com/torvalds", "torvalds"),
        ("github.com/torvalds/linux", "torvalds"),  # repo URL -> first segment
        ("https://github.com/a-b-c", "a-b-c"),
        ("torvalds?tab=repositories", "torvalds"),
        ("", None),
        ("   ", None),
        ("https://github.com/", None),
        ("-badstart", None),  # login cannot start with a hyphen
        ("bad--double", None),  # consecutive hyphens are invalid
        ("this-name-is-way-too-long-to-be-a-valid-github-login-x", None),  # >39 chars
        ("https://gitlab.com/torvalds", None),  # foreign URL — rejected, not a github handle
    ],
)
def test_extract_login(raw: str, expected: str | None) -> None:
    assert extract_login(raw) == expected
