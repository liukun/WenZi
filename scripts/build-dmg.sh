#!/usr/bin/env bash
# Package an already-built WenZi .app into a DMG installer.
# Usage:
#   ./scripts/build-dmg.sh              # Standard (expects dist/WenZi.app)
#   ./scripts/build-dmg.sh --lite       # Lite     (expects dist/WenZi-Lite.app)
#   ./scripts/build-dmg.sh [version]    # Standard with explicit version
#   ./scripts/build-dmg.sh --lite [version]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_DIR/dist"

# Parse --lite flag
APP_NAME="WenZi"
VOL_NAME="WenZi"
for arg in "$@"; do
    if [ "$arg" = "--lite" ]; then
        APP_NAME="WenZi-Lite"
        VOL_NAME="WenZi Lite"
    fi
done

APP_PATH="$DIST_DIR/$APP_NAME.app"

# Check that the .app exists
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: $APP_PATH not found."
    echo "Run 'make build' (or 'make build-lite') first."
    exit 1
fi

# Read version from pyproject.toml
PYPROJECT_VERSION=$(python3 -c "
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
with open('$PROJECT_DIR/pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")

# Version: explicit arg > git tag > pyproject.toml
VERSION=""
for arg in "$@"; do
    if [ "$arg" != "--lite" ]; then
        VERSION="$arg"
    fi
done
if [ -z "$VERSION" ]; then
    VERSION=$(git -C "$PROJECT_DIR" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || echo "")
fi
if [ -z "$VERSION" ]; then
    VERSION="$PYPROJECT_VERSION"
fi

# Validate version matches pyproject.toml
if [ "$VERSION" != "$PYPROJECT_VERSION" ]; then
    echo "ERROR: Version mismatch!"
    echo "  Requested: $VERSION"
    echo "  pyproject.toml: $PYPROJECT_VERSION"
    echo "Update pyproject.toml or use matching version."
    exit 1
fi

DMG_PATH="$DIST_DIR/${APP_NAME}-${VERSION}-arm64.dmg"

cd "$PROJECT_DIR"

echo "==> Creating DMG for $APP_NAME v${VERSION}..."

# Remove previous DMG if exists (create-dmg won't overwrite)
rm -f "$DMG_PATH"
create-dmg \
    --volname "$VOL_NAME" \
    --volicon "$PROJECT_DIR/resources/dmg-volume.icns" \
    --background "$PROJECT_DIR/resources/dmg-background.png" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 128 \
    --icon "$APP_NAME.app" 175 190 \
    --app-drop-link 425 190 \
    --hide-extension "$APP_NAME.app" \
    --no-internet-enable \
    "$DMG_PATH" \
    "$APP_PATH"

APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo ""
echo "==> DMG complete!"
echo "    App: $APP_PATH ($APP_SIZE)"
echo "    DMG: $DMG_PATH ($DMG_SIZE)"
