"""Fail on purpose to prove that each CI check fails."""

import pytest

# This prose comment breaks the no-comments check
COUNT: int = "one"


def test_red_run_proof() -> None:
    """Fail on purpose."""
    pytest.fail("Red-run proof. Revert this commit.")
