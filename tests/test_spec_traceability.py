"""The spec's traceability matrix has to stay true.

`docs/specs/conversations.md` maps every verification criterion to the tests
that cover it. That matrix is only worth having if it is accurate, and it drifts
silently the moment a test is renamed — which is exactly what happened twice
while implementing model fallback.

Three AI reviewers of this project all found the same class of defect:
documentation asserting behaviour the code did not have. This is the one place
that class can be caught automatically, so it is.
"""

import re
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs" / "specs" / "conversations.md"
TESTS = Path(__file__).resolve().parent


def _referenced_test_names() -> set[str]:
    return set(re.findall(r"`(test_[a-z0-9_]+)`", SPEC.read_text()))


def _defined_test_names() -> set[str]:
    source = "\n".join(p.read_text() for p in TESTS.rglob("test_*.py"))
    return set(re.findall(r"^(?:async )?def (test_[a-z0-9_]+)", source, re.M))


def test_every_test_named_in_the_spec_exists() -> None:
    missing = sorted(_referenced_test_names() - _defined_test_names())

    assert not missing, (
        "docs/specs/conversations.md names tests that do not exist: "
        f"{missing}. Either the test was renamed or the criterion is unverified."
    )


def test_every_verification_criterion_names_at_least_one_test() -> None:
    rows = re.findall(r"^\| \d+ \| (.+?) \| (.+?) \|$", SPEC.read_text(), re.M)

    assert rows, "the verification matrix could not be parsed"
    uncovered = [criterion for criterion, tests in rows if "test_" not in tests]
    assert not uncovered, f"criteria with no test named: {uncovered}"
