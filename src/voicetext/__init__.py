"""VoiceText - macOS menubar speech-to-text app."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("voicetext")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
