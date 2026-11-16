"""Find, load, and check the plugins that installed packages declare.

A plugin is a class that a distribution declares as an entry point in a group
kamayoq.<group>. kamayoq imports only the plugins on the allowlist.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from typing_extensions import get_protocol_members, is_protocol

ENTRY_POINT_PREFIX = "kamayoq."


@dataclass(frozen=True)
class PluginGroup:
    """A kind of plugin and the Protocol that each of its classes must match."""

    name: str
    protocol: type

    @property
    def entry_point_group(self) -> str:
        """Return the entry point group that declares the plugins."""
        return ENTRY_POINT_PREFIX + self.name


PLUGIN_GROUPS: tuple[PluginGroup, ...] = ()
"""The plugin groups. Each Protocol issue adds its group here."""


def parameter_shape(function: Callable[..., object]) -> str:
    """Return the parameter names and kinds, with no annotations or defaults.

    Returns:
        A text such as "(self, *, person)", or "(?)" if the function has no
        signature.
    """
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return "(?)"
    bare_parameters = [
        parameter.replace(
            annotation=inspect.Parameter.empty, default=inspect.Parameter.empty
        )
        for parameter in signature.parameters.values()
    ]
    return str(
        signature.replace(
            parameters=bare_parameters, return_annotation=inspect.Signature.empty
        )
    )


def is_defined(cls: type, member: str, *, is_method: bool) -> bool:
    """Return True if a class of the MRO that is not a Protocol defines the member.

    An annotation defines a data member, but not a method member.
    """
    for owner in cls.__mro__:
        if is_protocol(owner):
            continue
        if member in vars(owner):
            return True
        if not is_method and member in inspect.get_annotations(owner):
            return True
    return False


def protocol_mismatches(cls: type, protocol: type) -> list[str]:
    """Return each problem that stops the class from matching the Protocol.

    The check compares the members, sync or async, and the parameter names and
    kinds. It does not compare annotations.
    """
    problems: list[str] = []
    for member in sorted(get_protocol_members(protocol)):
        expected = inspect.getattr_static(protocol, member, None)
        is_method = inspect.isfunction(expected)
        if not is_defined(cls, member, is_method=is_method):
            problems.append(f"missing {member}")
            continue
        if not is_method:
            continue
        actual = getattr(cls, member)
        expected_async = inspect.iscoroutinefunction(expected)
        actual_async = inspect.iscoroutinefunction(actual)
        if not callable(actual):
            problems.append(f"{member} is not callable")
        elif expected_async and not actual_async:
            problems.append(f"{member} must be async")
        elif actual_async and not expected_async:
            problems.append(f"{member} must not be async")
        elif (shape := parameter_shape(actual)) != parameter_shape(expected):
            problems.append(
                f"{member} parameters are {shape}, expected {parameter_shape(expected)}"
            )
    return problems
