"""Unit tests for the plugin registry."""

import re
from collections.abc import Callable

import pytest
from fake_plugins import Greeter
from typing_extensions import is_protocol

from kamayoq.plugins import PLUGIN_GROUPS, PluginGroup, protocol_mismatches

GROUP_NAME = re.compile(r"[a-z][a-z0-9_]*")
KIND = """\
class Kind:
    name = "kind"
    ready = True

    async def greet(self, person):
        return "Hello"

    def close(self):
        return None
"""
ASYNC_GREET = "    async def greet(self, person):"
CLOSE = "    def close(self):\n        return None\n"


def kind_source(old: str, new: str) -> str:
    """Return the source of the correct class Kind with one change."""
    assert old in KIND
    return KIND.replace(old, new)


def define_kind(source: str) -> type:
    """Run the source, and return the class Kind that it defines."""
    namespace: dict[str, object] = {"Greeter": Greeter, "Callable": Callable}
    exec(source, namespace)
    kind = namespace["Kind"]
    assert isinstance(kind, type)
    return kind


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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (KIND, []),
        (kind_source('name = "kind"', "name: str"), []),
        (
            kind_source(
                "ready = True", "@property\n    def ready(self):\n        return True"
            ),
            [],
        ),
        (
            KIND.replace("class Kind:", "class Base:")
            + "class Kind(Base):\n    pass\n",
            [],
        ),
        (kind_source(ASYNC_GREET, '    async def greet(self, person="x"):'), []),
        (
            "class Kind(Greeter):\n    pass\n",
            ["missing close", "missing greet", "missing name", "missing ready"],
        ),
        (kind_source(CLOSE, ""), ["missing close"]),
        (kind_source("    ready = True\n", ""), ["missing ready"]),
        (kind_source(CLOSE, "    close: Callable[[], None]\n"), ["missing close"]),
        (kind_source(CLOSE, "    close = 3\n"), ["close is not callable"]),
        (
            kind_source(ASYNC_GREET, "    def greet(self, person):"),
            ["greet must be async"],
        ),
        (
            kind_source("    def close(self):", "    async def close(self):"),
            ["close must not be async"],
        ),
        (
            kind_source(ASYNC_GREET, "    async def greet(self, who):"),
            ["greet parameters are (self, who), expected (self, person)"],
        ),
        (
            kind_source(ASYNC_GREET, "    async def greet(self, *, person):"),
            ["greet parameters are (self, *, person), expected (self, person)"],
        ),
        (
            kind_source(ASYNC_GREET, "    async def greet(self, person, /):"),
            ["greet parameters are (self, person, /), expected (self, person)"],
        ),
        (
            kind_source(
                "    def close(self):", "    def close(self, *args, **kwargs):"
            ),
            ["close parameters are (self, *args, **kwargs), expected (self)"],
        ),
        (
            kind_source('    name = "kind"\n', "").replace(
                ASYNC_GREET, "    def greet(self, person):"
            ),
            ["greet must be async", "missing name"],
        ),
    ],
)
def test_protocol_mismatches_report_each_problem(
    source: str, expected: list[str]
) -> None:
    """Report each missing member, sync or async mismatch, and other parameters."""
    assert protocol_mismatches(define_kind(source), Greeter) == expected
