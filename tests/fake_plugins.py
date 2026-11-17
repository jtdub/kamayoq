"""Fake installed distributions that declare kamayoq plugins."""

import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import pytest

from kamayoq.plugins import PluginGroup


class Greeter(Protocol):
    """Give the members that the plugins of the test group must have."""

    name: str

    @property
    def ready(self) -> bool:
        """Return True when the greeter can greet."""

    async def greet(self, person: str) -> str:
        """Return a greeting for the person."""

    def close(self) -> None:
        """Release the resources of the greeter."""


GREETER_GROUP = PluginGroup("greeters", Greeter)


def install_fake_distribution(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution: str,
    version: str,
    entry_points: Sequence[tuple[str, str, str]],
    module_source: str,
) -> str:
    """Write a distribution and its module in root, and put root on sys.path.

    Args:
        root: A new directory for this distribution only.
        monkeypatch: The fixture that removes root from sys.path after the test.
        distribution: The distribution name.
        version: The distribution version.
        entry_points: The (group, name, target) of each entry point. A target
            that starts with ":" names an attribute of the new module.
        module_source: The source of the new module.

    Returns:
        The unique name of the new module.
    """
    module = "kamayoq_fake_" + secrets.token_hex(8)
    dist_info = root / f"{distribution.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (root / f"{module}.py").write_text(module_source, encoding="utf-8")
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n",
        encoding="utf-8",
    )
    sections: dict[str, list[str]] = {}
    for group, name, target in entry_points:
        full_target = module + target if target.startswith(":") else target
        sections.setdefault(group, []).append(f"{name} = {full_target}\n")
    (dist_info / "entry_points.txt").write_text(
        "".join(f"[{group}]\n{''.join(lines)}\n" for group, lines in sections.items()),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(root)
    return module
