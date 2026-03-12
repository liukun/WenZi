"""py2app setup for building VoiceText.app."""

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from pathlib import Path
from setuptools import setup

# Read version from pyproject.toml (single source of truth)
with open(Path(__file__).parent / "pyproject.toml", "rb") as f:
    _pyproject = tomllib.load(f)
_version = _pyproject["project"]["version"]

APP = ["src/voicetext/app.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "VoiceText",
        "CFBundleDisplayName": "VoiceText",
        "CFBundleIdentifier": "com.voicetext.app",
        "CFBundleVersion": _version,
        "CFBundleShortVersionString": _version,
        "LSUIElement": True,  # Hide from Dock (menubar-only app)
        "NSMicrophoneUsageDescription": "VoiceText needs microphone access to record speech for transcription.",
        "NSAppleEventsUsageDescription": "VoiceText needs accessibility access to type transcribed text.",
    },
    "packages": ["voicetext", "funasr_onnx", "librosa", "sounddevice", "soundfile", "numpy"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
