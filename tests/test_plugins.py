"""Unit tests for the plugin registry."""

import importlib
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from fake_plugins import GREETER_GROUP, Greeter, install_fake_distribution
from typing_extensions import is_protocol

from kamayoq.api.app import create_app
from kamayoq.plugins import (
    PLUGIN_GROUPS,
    PluginError,
    PluginGroup,
    load_plugins,
    protocol_mismatches,
)
from kamayoq.settings import PLUGIN_REFERENCE, Settings

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
KIND_REF = "greeters:kind"
GREETERS = (GREETER_GROUP,)
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


def fake_a(*points: tuple[str, str], source: str = KIND) -> list[FakeDistribution]:
    """Return fake-a 1.0 with the entry points, or kind = :Kind if none."""
    return [("fake-a", "1.0", points or [KIND_POINT], source)]


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
        assert PLUGIN_REFERENCE.fullmatch(f"{group.name}:x")
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
        [("fake-greeter", "1.0", [KIND_POINT], KIND)],
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
            GREETERS,
            [],
            "no plugin group runtimes. Known groups: greeters.",
        ),
        ("runtimes:x", (), [], "no plugin group runtimes. Known groups: none."),
        (
            KIND_REF,
            GREETERS,
            [],
            "no installed package declares kind in kamayoq.greeters.",
        ),
        (
            KIND_REF,
            GREETERS,
            [*fake_a(), ("fake-b", "2.0", [KIND_POINT], KIND)],
            "more than one entry point declares it: "
            "fake-a 1.0 ({0}:Kind), fake-b 2.0 ({1}:Kind).",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(("kind", ":A"), ("kind", ":B")),
            "more than one entry point declares it: "
            "fake-a 1.0 ({0}:A), fake-a 1.0 ({0}:B).",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(source='raise RuntimeError("boom")'),
            "cannot load {0}:Kind: RuntimeError: boom",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(source="raise ValueError"),
            "cannot load {0}:Kind: ValueError",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(("kind", ":Missing")),
            "cannot load {0}:Missing: "
            "AttributeError: module '{0}' has no attribute 'Missing'",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(("kind", ":instance"), source=KIND + "instance = Kind()"),
            "{0}:instance is not a class.",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(source=KIND + RAISES_ON_GET),
            "cannot check {0}:Kind: RuntimeError: bad descriptor",
        ),
        (
            KIND_REF,
            GREETERS,
            fake_a(source=KIND.replace("async def", "def")),
            "{0}:Kind does not match Greeter: greet must be async.",
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
    assert str(error_info.value) == (
        f"{NOT_VALID}- {reference}: {expected.format(*modules)}"
    )


def test_load_errors_list_each_plugin_in_sorted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Give one error with one line for each bad plugin, sorted by reference."""
    [module] = install_greeters(
        tmp_path, monkeypatch, fake_a(source="raise ValueError")
    )
    with pytest.raises(PluginError) as error_info:
        load_plugins({KIND_REF, "greeters:absent"}, GREETERS)
    assert str(error_info.value) == (
        f"{NOT_VALID}- greeters:absent: no installed package declares absent in "
        f"kamayoq.greeters.\n- {KIND_REF}: cannot load {module}:Kind: ValueError"
    )


def test_create_app_puts_registry_in_app_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Load the allowed plugins when the app is created, and keep them in app.state."""
    monkeypatch.setattr("kamayoq.plugins.PLUGIN_GROUPS", GREETERS)
    [module] = install_greeters(tmp_path, monkeypatch, fake_a())
    url = "postgresql://u:p@h:5/d"
    app = create_app(Settings(database_url=url, plugins=frozenset({KIND_REF})))
    kind = importlib.import_module(module).Kind
    assert app.state.plugins == {("greeters", "kind"): kind}
    assert create_app(Settings(database_url=url)).state.plugins == {}
