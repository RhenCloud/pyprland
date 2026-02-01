"""A plugin to auto-switch Fcitx5 input method status by window class/title."""

# from ..validation import ConfigField, ConfigItems
# from .interface import Plugin
import re
import contextlib

from pyprland.plugins.interface import Plugin
from pyprland.validation import ConfigField, ConfigItems


class Extension(Plugin):
    """A plugin to auto-switch Fcitx5 input method status by window class/title."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        # support loading as `external:fcitx5_switcher` while reading [fcitx5_switcher]
        self._conf_name = name.split(":", 1)[1] if ":" in name else name

    async def load_config(self, config: dict[str, Any]) -> None:  # type: ignore[override]
        """Load configuration using base section name (e.g. `fcitx5_switcher`)."""
        self.config.clear()
        with contextlib.suppress(KeyError):
            self.config.update(config[self._conf_name])
        if self.config_schema:
            self.config.set_schema(self.config_schema)

    environments = ["hyprland"]

    config_schema = ConfigItems(
        ConfigField("active_classes", list, default=[], description="Window classes that should activate Fcitx5"),
        ConfigField("active_titles", list, default=[], description="Window titles that should activate Fcitx5"),
        ConfigField("inactive_classes", list, default=[], description="Window classes that should deactivate Fcitx5"),
        ConfigField("inactive_titles", list, default=[], description="Window titles that should deactivate Fcitx5"),
    )

    async def event_activewindowv2(self, _addr: str) -> None:
        """A plugin to auto-switch Fcitx5 input method status by window class/title.

        Args:
            _addr: The address of the active window
        """
        _addr = "0x" + _addr

        active_classes = self.get_config_list("active_classes")
        active_titles = self.get_config_list("active_titles")
        inactive_classes = self.get_config_list("inactive_classes")
        inactive_titles = self.get_config_list("inactive_titles")

        clients = await self.get_clients()

        for client in clients:
            if client["address"] == _addr:
                # Hyprland client dict uses 'class_' key
                cls = client.get("class") or ""
                title = client.get("title") or ""
                self.log.debug("fcitx5_switcher: active client class=%s title=%s", cls, title)

                # Use regex matching for titles and classes (config may contain patterns)
                def matches_any(value: str, patterns: list[str]) -> bool:
                    for p in patterns:
                        try:
                            if re.search(str(p), value):
                                return True
                        except re.error:
                            # fallback to simple equality if invalid regex
                            if value == str(p):
                                return True
                    return False

                should_enable = matches_any(cls, active_classes) or matches_any(title, active_titles)
                should_disable = matches_any(cls, inactive_classes) or matches_any(title, inactive_titles)

                if should_enable:
                    self.log.debug("fcitx5_switcher: enabling fcitx for class=%s title=%s", cls, title)
                    ok = await self.backend.execute("execr fcitx5-remote -o")
                    self.log.debug("fcitx5_switcher: execute returned %s", ok)
                if should_disable:
                    self.log.debug("fcitx5_switcher: disabling fcitx for class=%s title=%s", cls, title)
                    ok = await self.backend.execute("execr fcitx5-remote -c")
                    self.log.debug("fcitx5_switcher: execute returned %s", ok)
