"""Unit tests for the plugin registry."""

import re

from fake_plugins import Greeter
from typing_extensions import is_protocol

from kamayoq.plugins import PLUGIN_GROUPS, PluginGroup

GROUP_NAME = re.compile(r"[a-z][a-z0-9_]*")


def test_entry_point_group_has_kamayoq_prefix() -> None:
    """Put kamayoq. before the group name."""
    assert PluginGroup("greeters", Greeter).entry_point_group == "kamayoq.greeters"


def test_plugin_groups_have_unique_valid_names_and_protocols() -> None:
    """Give each group a unique lower-case name and a Protocol."""
    names = [group.name for group in PLUGIN_GROUPS]
    assert len(names) == len(set(names))
    for group in PLUGIN_GROUPS:
        assert GROUP_NAME.fullmatch(group.name)
        assert is_protocol(group.protocol)
