"""Unit tests for the map from IdP groups to kamayoq roles."""

import pytest

from kamayoq.roles import RoleMap, roles_for_groups

ROLE_MAP: RoleMap = {
    "/admins": frozenset({"admin"}),
    "/authors": frozenset({"agent-author", "viewer"}),
    "/readers": frozenset({"viewer"}),
}


@pytest.mark.parametrize(
    ("groups", "roles"),
    [
        ({"/admins"}, {"admin"}),
        ({"/admins", "/authors"}, {"admin", "agent-author", "viewer"}),
        ({"/authors", "/readers"}, {"agent-author", "viewer"}),
        ({"/other"}, set()),
        (set(), set()),
    ],
)
def test_roles_are_the_union_of_the_roles_of_each_mapped_group(
    groups: set[str], roles: set[str]
) -> None:
    """Give the union of the mapped roles, with no duplicates (AC-4, E15)."""
    assert roles_for_groups(frozenset(groups), ROLE_MAP) == roles
