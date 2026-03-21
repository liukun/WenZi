"""Claude Code Sessions — WenZi official example plugin.

Browse and view Claude Code session history through the launcher.

Installation:
    Copy this directory to ~/.config/WenZi/plugins/cc_sessions/

The plugin is auto-loaded by WenZi's ScriptEngine.
"""


def setup(wz):
    """Entry point called by the ScriptEngine plugin loader."""
    from .init_plugin import register

    register(wz)
