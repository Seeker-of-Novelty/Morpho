#!/bin/sh
# Morpho installer (Linux, per-user, no root needed).
# POSIX sh — run from fish as:  sh install.sh
set -eu

APP_ID="morpho"
SHARE="$HOME/.local/share/$APP_ID"
BIN="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# Sanity checks
command -v python3 >/dev/null 2>&1 || {
    echo "python3 not found. Install it first (sudo pacman -S python)."; exit 1; }
python3 -c "import PySide6" 2>/dev/null || {
    echo "PySide6 not found. Install it first (sudo pacman -S pyside6)."; exit 1; }
# Optional tools — each unlocks a category; Morpho says which one it needs.
note() { command -v "$1" >/dev/null 2>&1 || echo "Note: $1 not found — $2 (sudo pacman -S $3)."; }
note ffmpeg      "video, audio, images, subtitles"          ffmpeg
note soffice     "documents, slides, spreadsheets"          libreoffice-fresh
note gs          "shrinking PDFs"                            ghostscript
note qpdf        "Combine-PDF mode"                          qpdf
note pdftoppm    "PDF pages to images (Qt fallback exists)"  poppler
note rsvg-convert "SVG rendering (ffmpeg fallback exists)"   librsvg
note bsdtar      "archives"                                  libarchive
note ebook-convert "e-books"                                 calibre
if ! python3 -c "import PIL" 2>/dev/null; then
    echo "Note: Pillow not found — image to PDF and images in Combine-PDF need it"
    echo "      (sudo pacman -S python-pillow)."
fi

mkdir -p "$SHARE" "$BIN" "$DESKTOP_DIR"

cp "$SRC_DIR/morpho.py" "$SHARE/morpho.py"

# Launcher
LAUNCHER="$BIN/morpho"
printf '#!/bin/sh\nexec python3 "%s" "$@"\n' "$SHARE/morpho.py" > "$LAUNCHER"
chmod +x "$LAUNCHER"

# Desktop entry
DESKTOP="$DESKTOP_DIR/morpho.desktop"
printf '%s\n' \
    "[Desktop Entry]" \
    "Type=Application" \
    "Name=Morpho" \
    "Comment=All-in-one file converter (video, audio, images, PDF, Office documents, e-books, archives)" \
    "Exec=$LAUNCHER" \
    "Terminal=false" \
    "Categories=Utility;AudioVideo;Office;" \
    > "$DESKTOP"

# Manifest: everything the in-app uninstaller (and uninstall.sh) will remove
printf '%s\n' \
    "$SHARE/morpho.py" \
    "$LAUNCHER" \
    "$DESKTOP" \
    > "$SHARE/manifest.txt"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "Installed. Launch 'Morpho' from your app menu, or run: morpho"
echo "Config will live in: $HOME/.config/morpho/"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Note: $BIN is not on your PATH (app menu launch still works)." ;;
esac
