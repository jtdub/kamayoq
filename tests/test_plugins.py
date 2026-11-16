"""Unit tests for the plugin registry."""

import importlib
import logging
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from fake_plugins import GREETER_GROUP, Greeter, install_fake_distribution
from typing_extensions import is_protocol

from kamayoq.plugins import (
    PLUGIN_GROUPS,
    PluginError,
    PluginGroup,
    load_plugins,
    protocol_mismatches,
)

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

KIND_POINT = ("kind", ":Kind")
NOT_VALID = "Plugins are not valid:\n"
RAISES_ON_GET = """\
class RaisesOnGet:
    def __get__(self, instance, owner):
        raise RuntimeError("bad descriptor")


Kind.greet = RaisesOnGet()
"""

FakeDistribution = tuple[str, str, Sequence[tuple[str, str]], str]
"""The distribution, its version, each (name, target) of a greeter, and the source."""


def install_greeters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distributions: Sequence[FakeDistribution],
) -> list[str]:
    """Install each fake distribution in its own directory, and return the modules."""
    return [
        install_fake_distribution(
            tmp_path / str(index),
            monkeypatch,
            distribution,
            version,
            [
                (GREETER_GROUP.entry_point_group, name, target)
                for name, target in points
            ],
            source,
        )
        for index, (distribution, version, points, source) in enumerate(distributions)
    ]


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


def test_allowed_plugin_loads_and_logs_its_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Return the allowed class, and log the package that declares it."""
    caplog.set_level(logging.INFO, logger="kamayoq.plugins")
    [module] = install_greeters(
        tmp_path, monkeypatch, [("fake-greeter", "1.0", [KIND_POINT], KIND)]
    )
    registry = load_plugins({"greeters:kind"}, (GREETER_GROUP,))
    assert registry == {("greeters", "kind"): importlib.import_module(module).Kind}
    assert (
        "kamayoq.plugins",
        logging.INFO,
        "Loaded plugin greeters:kind from fake-greeter 1.0.",
    ) in caplog.record_tuples


def test_plugin_not_on_allowlist_is_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Do not import a plugin that the allowlist does not name, and log it (AC-2)."""
    caplog.set_level(logging.INFO, logger="kamayoq.plugins")
    [module] = install_greeters(
        tmp_path,
        monkeypatch,
        [("fake-greeter", "1.0", [KIND_POINT], 'raise RuntimeError("imported")\n')],
    )
    assert load_plugins(frozenset(), (GREETER_GROUP,)) == {}
    assert module not in sys.modules
    assert (
        "kamayoq.plugins",
        logging.INFO,
        "Skipped plugin greeters:kind from fake-greeter 1.0. "
        "It is not on the plugin allowlist (KAMAYOQ_PLUGINS).",
    ) in caplog.record_tuples


@pytest.mark.parametrize(
    ("reference", "groups", "distributions", "expected"),
    [
        (
            "runtimes:x",
            (GREETER_GROUP,),
            [],
            "- runtimes:x: no plugin group runtimes. Known groups: greeters.",
        ),
        (
            "runtimes:x",
            (),
            [],
            "- runtimes:x: no plugin group runtimes. Known groups: none.",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [],
            "- greeters:kind: no installed package declares kind in kamayoq.greeters.",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [
                ("fake-a", "1.0", [KIND_POINT], KIND),
                ("fake-b", "2.0", [KIND_POINT], KIND),
            ],
            "- greeters:kind: more than one entry point declares it: "
            "fake-a 1.0 ({0}:Kind), fake-b 2.0 ({1}:Kind).",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [("kind", ":A"), ("kind", ":B")], "")],
            "- greeters:kind: more than one entry point declares it: "
            "fake-a 1.0 ({0}:A), fake-a 1.0 ({0}:B).",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [KIND_POINT], 'raise RuntimeError("boom")\n')],
            "- greeters:kind: cannot load {0}:Kind: RuntimeError: boom",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [KIND_POINT], "raise ValueError\n")],
            "- greeters:kind: cannot load {0}:Kind: ValueError",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [("kind", ":Missing")], KIND)],
            "- greeters:kind: cannot load {0}:Missing: "
            "AttributeError: module '{0}' has no attribute 'Missing'",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [("kind", ":instance")], KIND + "instance = Kind()\n")],
            "- greeters:kind: {0}:instance is not a class.",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [KIND_POINT], KIND + RAISES_ON_GET)],
            "- greeters:kind: cannot check {0}:Kind: RuntimeError: bad descriptor",
        ),
        (
            "greeters:kind",
            (GREETER_GROUP,),
            [("fake-a", "1.0", [KIND_POINT], KIND.replace("async def", "def"))],
            "- greeters:kind: {0}:Kind does not match Greeter: greet must be async.",
        ),
    ],
)
def test_load_errors_name_the_plugin_and_the_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
    groups: tuple[PluginGroup, ...],
    distributions: list[FakeDistribution],
    expected: str,
) -> None:
    """Stop the load with a line that names the plugin and the problem (AC-1, AC-3)."""
    modules = install_greeters(tmp_path, monkeypatch, distributions)
    with pytest.raises(PluginError) as error_info:
        load_plugins({reference}, groups)
    assert str(error_info.value) == NOT_VALID + expected.format(*modules)


def test_load_errors_list_each_plugin_in_sorted_order() -> None:
    """Give one error with one line for each bad plugin, sorted by reference."""
    with pytest.raises(PluginError) as error_info:
        load_plugins(["runtimes:x", "greeters:kind"], (GREETER_GROUP,))
    assert str(error_info.value) == (
        NOT_VALID
        + "- greeters:kind: no installed package declares kind in kamayoq.greeters.\n"
        + "- runtimes:x: no plugin group runtimes. Known groups: greeters."
    )
