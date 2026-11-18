"""The kamayoq roles, and the map from IdP groups to roles."""

from collections.abc import Mapping
from typing import Literal

Role = Literal["admin", "agent-author", "tool-granter", "approver", "auditor", "viewer"]
RoleMap = Mapping[str, frozenset[Role]]


def roles_for_groups(groups: frozenset[str], role_map: RoleMap) -> frozenset[Role]:
    """Return the union of the roles of each group in the map."""
    return frozenset().union(*(role_map.get(group, frozenset()) for group in groups))
