"""Find, load, and check the plugins that installed packages declare.

A plugin is a class that a distribution declares as an entry point in a group
kamayoq.<group>. kamayoq imports only the plugins on the allowlist.
"""

from dataclasses import dataclass

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
