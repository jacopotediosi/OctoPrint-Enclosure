from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from octoprint.access import ADMIN_GROUP, READONLY_GROUP, USER_GROUP
from octoprint.access.permissions import Permissions

if TYPE_CHECKING:
    from octoprint.access.permissions import OctoPrintPermission


class PluginPermission(Enum):
    """A permission of the plugin."""

    STATUS = "STATUS"
    """See the inputs, outputs, actions and automations, with their state."""

    OUTPUTS_CONTROL = "OUTPUTS_CONTROL"
    """Control the outputs."""

    ACTIONS_RUN = "ACTIONS_RUN"
    """Run the actions."""

    AUTOMATIONS_ENABLE = "AUTOMATIONS_ENABLE"
    """Enable and disable the automations."""

    def to_octoprint(self) -> OctoPrintPermission:
        """Get the permission as OctoPrint registered it.

        Returns:
            OctoPrintPermission: The OctoPrint permission.

        """
        return getattr(Permissions, f"PLUGIN_ENCLOSURE_{self.value}")


def get_additional_permissions() -> list[dict]:
    """Describe the plugin permissions, in the format needed by the `octoprint.access.permissions` hook.

    Returns:
        list[dict]: The permissions, each with its key, name, description, roles, the permissions it includes, the
            groups that have it by default, and whether it is dangerous.

    """
    status = f"PLUGIN_ENCLOSURE_{PluginPermission.STATUS.value}"
    return [
        {
            "key": PluginPermission.STATUS.value,
            "name": "Status",
            "description": "Allows to see inputs, outputs, actions and automations, with their state.",
            "roles": ["status"],
            "default_groups": [ADMIN_GROUP, USER_GROUP, READONLY_GROUP],
        },
        {
            "key": PluginPermission.OUTPUTS_CONTROL.value,
            "name": "Control outputs",
            "description": "Allows to turn outputs on and off, and to set their duty cycle, color or target. "
            'Includes the "Status" permission.',
            "roles": ["outputs_control"],
            "permissions": [status],
            "dangerous": True,
            "default_groups": [ADMIN_GROUP, USER_GROUP],
        },
        {
            "key": PluginPermission.ACTIONS_RUN.value,
            "name": "Run actions",
            "description": 'Allows to run actions, e.g. G-code or shell scripts. Includes the "Status" permission.',
            "roles": ["actions_run"],
            "permissions": [status],
            "dangerous": True,
            "default_groups": [ADMIN_GROUP, USER_GROUP],
        },
        {
            "key": PluginPermission.AUTOMATIONS_ENABLE.value,
            "name": "Enable and disable automations",
            "description": 'Allows to enable and disable automations. Includes the "Status" permission.',
            "roles": ["automations_enable"],
            "permissions": [status],
            "dangerous": True,
            "default_groups": [ADMIN_GROUP, USER_GROUP],
        },
    ]
