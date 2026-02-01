"""Hdrop - Quick window dropdown/scratchpad functionality."""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, cast

from pyprland.plugins.interface import Plugin


@dataclass
class HdropOptions:
    """Options for handling hdrop window actions."""

    command: str | None
    focus: bool
    floating: bool
    height: int | None
    width: int | None
    center: bool
    skip: bool = False
    launch_on_missing: bool = False


class Extension(Plugin):
    """Hdrop - Quick window dropdown/scratchpad functionality."""

    def __init__(self, name: str) -> None:
        """Initialize hdrop extension."""
        super().__init__(name)
        # Normalize config section name so external:hdrop still reads [hdrop]
        self._conf_name = name.split(":", 1)[1] if ":" in name else name
        self.apps: dict[str, dict[str, Any]] = {}

    async def load_config(self, config: dict[str, Any]) -> None:
        """Load the plugin configuration using the base section name.

        This allows the plugin to be loaded as `external:hdrop` while still
        reading configuration from `[hdrop]` in the user's config file.
        """
        self.config.clear()
        with contextlib.suppress(KeyError):
            self.config.update(config[self._conf_name])
        if self.config_schema:
            self.config.set_schema(self.config_schema)

    async def on_reload(self) -> None:
        """Load apps configuration from config file."""
        self.apps = cast("dict[str, dict[str, Any]]", self.config.get("apps", {}))
        self.log.debug("Loaded %d hdrop apps from config", len(self.apps))

    def _get_app_config(self, app_name: str) -> dict[str, Any]:
        """Get config for an app (from file only)."""
        return self.apps.get(app_name, {})

    async def run_hdrop(self, args: str) -> str | None:
        """Main hdrop command entrypoint.

        New behavior: the command accepts a single token which must match an
        application configured under `hdrop.apps` in the config file. Example:

            pypr hdrop kitty

        This will use the configuration at `hdrop.apps.kitty` to decide
        whether to launch, toggle, focus, set floating, center and resize the
        window. The older subcommand-based CLI (`toggle|show|hide|focus`)
        is deprecated and no longer used.
        """
        app_name = args.strip().split(None, 1)[0] if args and args.strip() else ""
        if not app_name:
            return "Error: app name required (defined under hdrop.apps)"

        return await self.run_app(app_name)

    async def run_app(self, app_name: str) -> str | None:
        """Toggle/launch an app defined in configuration by name.

        Behaviour is driven entirely from `hdrop.apps.<app_name>` config.
        """
        app_conf = self._get_app_config(app_name)
        if not app_conf:
            return f"Error: app '{app_name}' not configured"

        # Determine class identifier (used to find/manage windows)
        class_name = cast("str", app_conf.get("class", app_name))
        command = app_conf.get("command")
        focus_flag = bool(app_conf.get("focus", False))
        floating_flag = bool(app_conf.get("floating", False))
        center_flag = bool(app_conf.get("center", False))
        height = app_conf.get("height")
        width = app_conf.get("width")
        launch_on_missing = bool(app_conf.get("launch_on_missing", False))

        await self._handle_window(
            class_name,
            HdropOptions(
                command=command,
                focus=focus_flag,
                floating=floating_flag,
                height=height,
                width=width,
                center=center_flag,
                launch_on_missing=launch_on_missing,
            ),
        )
        return None

    async def run_toggle(self, args: str) -> str | None:
        """Toggle a window between workspace and hdrop scratchpad.

        Usage: pypr hdrop:toggle CLASS [ARGS]
        where CLASS is the window class to toggle
        ARGS can include: --focus, --floating, --height, --width, --center
        """
        parts = args.split(None, 1)
        if not parts:
            return "Error: CLASS name required"

        class_name = parts[0]
        # Use configuration from hdrop.apps for all options; ignore CLI args
        app_conf = self._get_app_config(class_name)
        await self._handle_window(
            class_name,
            HdropOptions(
                command=app_conf.get("command"),
                focus=bool(app_conf.get("focus", False)),
                floating=bool(app_conf.get("floating", False)),
                height=app_conf.get("height"),
                width=app_conf.get("width"),
                center=bool(app_conf.get("center", False)),
                launch_on_missing=bool(app_conf.get("launch_on_missing", False)),
            ),
        )
        return None

    async def run_focus(self, args: str) -> str | None:
        """Focus a window or bring it from hdrop.

        Usage: pypr hdrop:focus CLASS
        """
        class_name = args.strip()
        if not class_name:
            return "Error: CLASS name required"

        if await self._is_window_in_hdrop(class_name):
            await self._move_window_to_active_workspace(class_name)
        else:
            await self.backend.execute(f"focuswindow class:{class_name}")
        return None

    async def run_show(self, args: str) -> str | None:
        """Show a window from hdrop to active workspace.

        Usage: pypr hdrop:show CLASS [OPTIONS]
        """
        parts = args.split(None, 1)
        if not parts:
            return "Error: CLASS name required"

        class_name = parts[0]
        # Use configuration from hdrop.apps for options; ignore CLI args
        app_conf = self._get_app_config(class_name)
        await self._handle_window(
            class_name,
            HdropOptions(
                command=app_conf.get("command"),
                focus=True,
                floating=bool(app_conf.get("floating", False)),
                height=app_conf.get("height"),
                width=app_conf.get("width"),
                center=bool(app_conf.get("center", False)),
                launch_on_missing=bool(app_conf.get("launch_on_missing", False)),
            ),
        )
        return None

    async def run_hide(self, args: str) -> str | None:
        """Hide a window to hdrop scratchpad.

        Usage: pypr hdrop:hide CLASS
        """
        class_name = args.strip()
        if not class_name:
            return "Error: CLASS name required"

        if await self._is_window_exists(class_name):
            await self._move_window_to_hdrop(class_name)
        return None

    # Note: explicit `hdrop:launch` subcommand removed; launching via
    # configuration-driven `hdrop` or the other subcommands remains supported.

    # Helper methods

    async def _is_window_exists(self, class_name: str) -> bool:
        """Check if a window with the given class exists."""
        clients = await self.get_clients()
        return any(cast("str", c["class"]) == class_name for c in clients)

    async def _is_window_in_hdrop(self, class_name: str) -> bool:
        """Check if a window is in the hdrop workspace."""
        clients = await self.get_clients()
        return any(cast("str", c["class"]) == class_name and cast("str", c["workspace"]["name"]) == "special:hdrop" for c in clients)

    async def _move_window_to_hdrop(self, class_name: str) -> None:
        """Move a window to the hdrop scratchpad."""
        await self.backend.execute(f"movetoworkspacesilent special:hdrop,class:{class_name}")

    async def _move_window_to_active_workspace(self, class_name: str) -> None:
        """Move a window to the active workspace."""
        workspace = cast("dict[str, Any]", await self.backend.execute_json("activeworkspace"))
        workspace_id = cast("int", workspace["id"])
        await self.backend.execute(f"movetoworkspace {workspace_id},class:{class_name}")

    async def _handle_window(self, class_name: str, opts: HdropOptions) -> None:
        """Handle window display/hide logic.

        Parameters are grouped in `HdropOptions` to reduce function arity.
        """
        command = opts.command
        focus_flag = opts.focus
        floating_flag = opts.floating
        height = opts.height
        width = opts.width
        center_flag = opts.center
        skip_flag = opts.skip
        launch_on_missing = opts.launch_on_missing

        # Launch command if needed and window doesn't exist and allowed by config
        if not skip_flag and command is not None and not await self._is_window_exists(class_name) and launch_on_missing:
            await self.backend.execute(f"exec {command}")
            await asyncio.sleep(0.5)
            # Recursively call with skip=True
            new_opts = HdropOptions(
                command=command,
                focus=focus_flag,
                floating=floating_flag,
                height=height,
                width=width,
                center=center_flag,
                skip=True,
                launch_on_missing=opts.launch_on_missing,
            )
            await self._handle_window(class_name, new_opts)
            return

        # Window exists: act according to flags
        if await self._is_window_exists(class_name):
            if await self._is_window_in_hdrop(class_name):
                # Window is in hdrop, bring it to active workspace
                await self._move_window_to_active_workspace(class_name)
                if floating_flag:
                    await self._configure_floating_window(class_name, height, width, center_flag)
            elif focus_flag:
                # Just focus the window
                await self.backend.execute(f"focuswindow class:{class_name}")
            else:
                # Hide window to hdrop
                await self._move_window_to_hdrop(class_name)

    async def _configure_floating_window(
        self,
        class_name: str,
        height: int | None,
        width: int | None,
        center_flag: bool,
    ) -> None:
        """Configure a floating window."""
        # Ensure floating mode for the window(s)
        clients = await self.get_clients()
        target_clients = [
            c for c in clients if cast("str", c["class"]) == class_name and cast("str", c["workspace"]["name"]) != "special:hdrop"
        ]

        if target_clients:
            for client in target_clients:
                if not cast("bool", client["floating"]):
                    await self.backend.execute(f"togglefloating address:{client['address']}")
        else:
            await self.backend.execute(f"togglefloating class:{class_name}")

        # Resize if dimensions provided
        if height is not None and width is not None:
            await self.backend.execute(f"resizewindowpixel exact {width} {height},class:{class_name}")

        # Center the window if requested
        if center_flag:
            await self.backend.execute(f"centerwindow class:{class_name}")
