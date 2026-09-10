#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/media2mqtt"
PLIST_NAME="com.media2mqtt"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "==> Stopping media2mqtt"
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true

if [ -f "$PLIST_DST" ]; then
    echo "==> Removing plist"
    rm "$PLIST_DST"
fi

if [ -d "$INSTALL_DIR" ]; then
    read -rp "Remove $INSTALL_DIR and all data? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
        echo "==> Removed $INSTALL_DIR"
    else
        echo "==> Kept $INSTALL_DIR"
    fi
fi

echo "==> Uninstalled"
