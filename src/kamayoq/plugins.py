"""Find, load, and check the plugins that installed packages declare.

A plugin is a class that a distribution declares as an entry point in a group
kamayoq.<group>. kamayoq imports only the plugins on the allowlist.
"""

import inspect
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from typing_extensions import get_protocol_members, is_protocol

ENTRY_POINT_PREFIX = "kamayoq."

logger = logging.getLogger(__name__)


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

PluginRegistry = Mapping[tuple[str, str], type]
"""The class of each loaded plugin, by (group, name)."""


class PluginError(Exception):
    """A plugin cannot load. The message is safe to print."""


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
        else:
            shape, expected_shape = parameter_shape(actual), parameter_shape(expected)
            if shape != expected_shape:
                problems.append(
                    f"{member} parameters are {shape}, expected {expected_shape}"
                )
    return problems


def package_of(point: EntryPoint) -> str:
    """Return the name and version of the distribution that declares the entry point."""
    if point.dist is None:
        return "an unknown package"
    return f"{point.dist.name} {point.dist.version}"


def describe(error: Exception) -> str:
    """Return the exception type and its message, with no traceback."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def load_allowed(
    reference: str,
    known: Mapping[str, PluginGroup],
    declared: Mapping[str, Sequence[EntryPoint]],
) -> type:
    """Load one plugin of the allowlist, and check it.

    Raises:
        PluginError: With the first problem of the plugin.
    """
    group_name, _, name = reference.partition(":")
    if group_name not in known:
        names = ", ".join(sorted(known)) or "none"
        raise PluginError(f"no plugin group {group_name}. Known groups: {names}.")
    group = known[group_name]
    matches = [point for point in declared[group_name] if point.name == name]
    if not matches:
        raise PluginError(
            f"no installed package declares {name} in {group.entry_point_group}."
        )
    if len(matches) > 1:
        parts = ", ".join(
            sorted(f"{package_of(point)} ({point.value})" for point in matches)
        )
        raise PluginError(f"more than one entry point declares it: {parts}.")
    [point] = matches
    try:
        plugin = point.load()
    except Exception as error:
        raise PluginError(f"cannot load {point.value}: {describe(error)}") from error
    if not inspect.isclass(plugin):
        raise PluginError(f"{point.value} is not a class.")
    try:
        problems = protocol_mismatches(plugin, group.protocol)
    except Exception as error:
        raise PluginError(f"cannot check {point.value}: {describe(error)}") from error
    if problems:
        raise PluginError(
            f"{point.value} does not match {group.protocol.__name__}: "
            f"{'; '.join(problems)}."
        )
    logger.info("Loaded plugin %s from %s.", reference, package_of(point))
    return plugin


def load_plugins(
    allowlist: Collection[str], groups: Sequence[PluginGroup]
) -> PluginRegistry:
    """Load and check each plugin on the allowlist.

    An installed plugin that the allowlist does not name is not imported.

    Args:
        allowlist: The plugin references, each one group:name.
        groups: The known plugin groups.

    Raises:
        PluginError: With one line for each plugin that cannot load.
    """
    known = {group.name: group for group in groups}
    declared = {
        group.name: tuple(entry_points(group=group.entry_point_group))
        for group in groups
    }
    for group_name, points in declared.items():
        for point in points:
            reference = f"{group_name}:{point.name}"
            if reference not in allowlist:
                logger.info(
                    "Skipped plugin %s from %s. It is not on the plugin allowlist "
                    "(KAMAYOQ_PLUGINS).",
                    reference,
                    package_of(point),
                )
    registry: dict[tuple[str, str], type] = {}
    lines: list[str] = []
    for reference in sorted(allowlist):
        group_name, _, name = reference.partition(":")
        try:
            registry[(group_name, name)] = load_allowed(reference, known, declared)
        except PluginError as error:
            lines.append(f"- {reference}: {error}")
    if lines:
        raise PluginError("Plugins are not valid:\n" + "\n".join(lines))
    return registry
