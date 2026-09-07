#!/bin/sh
# Morpho uninstaller (Linux). POSIX sh — run from fish as:  sh uninstall.sh
# Add --purge to also delete all settings in ~/.config/morpho
set -eu

APP_ID="morpho"
SHARE="$HOME/.local/share/$APP_ID"
MANIFEST="$SHARE/manifest.txt"
CONFIG="$HOME/.config/$APP_ID"

if [ -f "$MANIFEST" ]; then
    while IFS= read -r f; do
        [ -n "$f" ] && rm -rf -- "$f"
    done < "$MANIFEST"
    rm -f -- "$MANIFEST"
    rmdir -- "$SHARE" 2>/dev/null || true
    echo "Application files removed."
else
    echo "No install manifest found — nothing was installed via install.sh."
fi

if [ "${1:-}" = "--purge" ]; then
    rm -rf -- "$CONFIG"
    echo "Settings removed ($CONFIG)."
else
    echo "Settings kept in $CONFIG  (run with --purge to remove them too)."
fi
