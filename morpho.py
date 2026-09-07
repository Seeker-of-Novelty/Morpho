#!/usr/bin/env python3
"""
Morpho — a small, clean, all-in-one file converter powered by the tools already
on your system (ffmpeg, LibreOffice, Ghostscript, qpdf, poppler, calibre,
librsvg, bsdtar).

Single-file PySide6 (Qt 6) application.
Linux + Windows. No bundled binaries: every conversion shells out to a tool
you already have, and the app tells you plainly which one it needs.

Config lives in the platform config folder:
  Linux:   ~/.config/morpho/
  Windows: %LOCALAPPDATA%/morpho/

License: MIT
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageOps
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

from PySide6.QtCore import (
    QProcess,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
)

try:
    from PySide6.QtPdf import QPdfDocument
    HAVE_QTPDF = True
except ImportError:
    HAVE_QTPDF = False
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Morpho"
APP_ID = "morpho"
APP_VERSION = "2.0.0"

# ----------------------------------------------------------------------------
# Format model
# ----------------------------------------------------------------------------

# Output formats the user can pick, grouped by kind.
# ext -> (label, kind). `kind` decides which option controls apply (the media
# kinds drive ffmpeg's codec/quality knobs; everything else is a document-style
# conversion with no per-format knobs).
FORMATS = {
    # video containers
    "mp4":  ("MP4 video",        "video"),
    "mkv":  ("MKV video",        "video"),
    "webm": ("WebM video",       "video"),
    "mov":  ("MOV video",        "video"),
    "gif":  ("Animated GIF",     "video"),
    # audio
    "mp3":  ("MP3 audio",        "audio"),
    "m4a":  ("M4A (AAC) audio",  "audio"),
    "opus": ("Opus audio",       "audio"),
    "ogg":  ("OGG Vorbis audio", "audio"),
    "flac": ("FLAC (lossless)",  "audio"),
    "wav":  ("WAV (lossless)",   "audio"),
    # images
    "png":  ("PNG image",        "image"),
    "jpg":  ("JPEG image",       "image"),
    "webp": ("WebP image",       "image"),
    "avif": ("AVIF image",       "image"),
    "bmp":  ("BMP image",        "image"),
    "tiff": ("TIFF image",       "image"),
    # documents (LibreOffice)
    "pdf":  ("PDF document",                  "pdf"),
    "docx": ("Word document (DOCX)",          "doc"),
    "odt":  ("OpenDocument text (ODT)",       "doc"),
    "rtf":  ("Rich Text (RTF)",               "doc"),
    "txt":  ("Plain text (TXT)",              "doc"),
    "html": ("Web page (HTML)",               "doc"),
    "md":   ("Markdown (MD)",                 "doc"),
    # slides (LibreOffice Impress)
    "pptx": ("PowerPoint (PPTX)",             "slides"),
    "odp":  ("OpenDocument slides (ODP)",     "slides"),
    # spreadsheets (LibreOffice Calc)
    "xlsx": ("Excel workbook (XLSX)",         "sheet"),
    "ods":  ("OpenDocument sheet (ODS)",      "sheet"),
    "csv":  ("CSV (first sheet)",             "sheet"),
    # e-books (calibre)
    "epub": ("EPUB e-book",                   "ebook"),
    "mobi": ("Kindle MOBI e-book",            "ebook"),
    "azw3": ("Kindle AZW3 e-book",            "ebook"),
    # subtitles (ffmpeg)
    "srt":  ("SubRip subtitles (SRT)",        "subtitle"),
    "vtt":  ("WebVTT subtitles (VTT)",        "subtitle"),
    "ass":  ("ASS subtitles",                 "subtitle"),
    # archives (bsdtar)
    "zip":     ("ZIP archive",                "archive"),
    "7z":      ("7-Zip archive",              "archive"),
    "tar.gz":  ("tar.gz archive",             "archive"),
    "tar.xz":  ("tar.xz archive",             "archive"),
    "tar.zst": ("tar.zst archive",            "archive"),
}

# Display order of format groups in the "Convert to" picker.
KIND_ORDER = ["pdf", "doc", "slides", "sheet", "video", "audio", "image",
              "ebook", "subtitle", "archive"]
KIND_LABELS = {
    "video": "video", "audio": "audio", "image": "image", "svg": "SVG",
    "pdf": "PDF", "doc": "document", "slides": "slide deck",
    "sheet": "spreadsheet", "ebook": "e-book", "subtitle": "subtitle file",
    "archive": "archive",
}

# Input kinds by extension. Compound archive extensions (tar.gz …) are
# matched first by file_ext().
INPUT_KINDS: dict[str, str] = {}
for _e in ("mp4", "mkv", "webm", "mov", "avi", "m4v", "mpg", "mpeg", "ts",
           "m2ts", "wmv", "flv", "3gp", "ogv", "gif"):
    INPUT_KINDS[_e] = "video"
for _e in ("mp3", "m4a", "aac", "opus", "ogg", "oga", "flac", "wav", "wma",
           "aiff", "aif", "mka", "ac3", "dts", "amr"):
    INPUT_KINDS[_e] = "audio"
for _e in ("png", "jpg", "jpeg", "webp", "avif", "bmp", "tiff", "tif",
           "heic", "heif", "jxl", "ppm", "tga"):
    INPUT_KINDS[_e] = "image"
for _e in ("svg", "svgz"):
    INPUT_KINDS[_e] = "svg"
INPUT_KINDS["pdf"] = "pdf"
for _e in ("docx", "doc", "docm", "dot", "dotx", "odt", "ott", "fodt", "rtf",
           "txt", "html", "htm", "xhtml", "md", "markdown", "wpd", "pages"):
    INPUT_KINDS[_e] = "doc"
for _e in ("pptx", "ppt", "pptm", "pps", "ppsx", "potx", "odp", "otp", "fodp",
           "key"):
    INPUT_KINDS[_e] = "slides"
for _e in ("xlsx", "xls", "xlsm", "ods", "ots", "fods", "csv", "tsv",
           "numbers"):
    INPUT_KINDS[_e] = "sheet"
for _e in ("epub", "mobi", "azw", "azw3", "azw4", "fb2", "lit", "lrf",
           "kepub"):
    INPUT_KINDS[_e] = "ebook"
for _e in ("srt", "vtt", "ass", "ssa"):
    INPUT_KINDS[_e] = "subtitle"
for _e in ("zip", "7z", "tar", "tar.gz", "tgz", "tar.bz2", "tbz2", "tar.xz",
           "txz", "tar.zst", "tzst", "rar"):
    INPUT_KINDS[_e] = "archive"
del _e

COMPOUND_EXTS = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst")

_VIDEO_OUT = [e for e, (_, k) in FORMATS.items() if k == "video"]
_AUDIO_OUT = [e for e, (_, k) in FORMATS.items() if k == "audio"]
_IMAGE_OUT = [e for e, (_, k) in FORMATS.items() if k == "image"]

# Which outputs each input kind can be turned into, in preferred order (the
# first entry is the default when the current pick isn't reachable).
REACHABLE: dict[str, list[str]] = {
    "video":    _VIDEO_OUT + _AUDIO_OUT + _IMAGE_OUT,
    "audio":    _AUDIO_OUT,
    "image":    _IMAGE_OUT + ["pdf"],
    "svg":      ["png", "jpg", "webp", "avif", "bmp", "tiff", "pdf"],
    "pdf":      ["pdf", "png", "jpg", "tiff", "txt", "docx", "odt"],
    "doc":      ["pdf", "docx", "odt", "rtf", "txt", "html", "md",
                 "png", "jpg", "epub", "mobi", "azw3"],
    "slides":   ["pdf", "pptx", "odp", "png", "jpg"],
    "sheet":    ["pdf", "xlsx", "ods", "csv", "html"],
    "ebook":    ["epub", "mobi", "azw3", "pdf", "docx", "txt"],
    "subtitle": ["srt", "vtt", "ass"],
    "archive":  ["zip", "7z", "tar.gz", "tar.xz", "tar.zst"],
}

# Outputs that mean "one image per page/slide, saved in a folder".
PAGE_IMAGE_OUTS = {"png", "jpg", "tiff"}
PAGE_IMAGE_DPI = {"High quality": 300, "Balanced": 150, "Small file": 96}
PAGE_IMAGE_JPEG_Q = {"High quality": 92, "Balanced": 85, "Small file": 70}

# Inputs calibre's ebook-convert reads directly; other documents are first
# turned into DOCX by LibreOffice.
CALIBRE_INPUT_EXTS = {"docx", "odt", "rtf", "txt", "html", "htm", "epub",
                      "mobi", "azw", "azw3", "azw4", "fb2", "lit", "lrf",
                      "pdf", "kepub"}

# What LibreOffice must report having opened a file *as* for each input kind —
# it will happily load a corrupt .pptx as plain text and "convert" that, so
# the type it prints is checked before an output is accepted.
LO_DOC_TYPE = {"doc": "Writer", "slides": "Impress", "sheet": "Calc",
               "pdf": "Writer", "image": "Draw"}

# Raster formats Pillow can't open in a stock install; these are rasterised
# to PNG by ffmpeg before Pillow turns them into a PDF.
PIL_UNREADABLE = {"heic", "heif", "jxl"}

# ----------------------------------------------------------------------------
# External tools
# ----------------------------------------------------------------------------

# key -> description. `names` are tried on PATH (Windows variants first when
# they differ); `paths` are well-known install locations checked after PATH;
# `setting` is the QSettings key for a user-chosen binary.
TOOLS: dict[str, dict] = {
    "ffmpeg": {
        "label": "ffmpeg", "names": ("ffmpeg",), "setting": "ffmpeg_path",
        "purpose": "video, audio, images, subtitles",
        "arch": "ffmpeg", "winget": "Gyan.FFmpeg"},
    "soffice": {
        "label": "LibreOffice", "names": ("soffice", "libreoffice"),
        "setting": "soffice_path",
        "purpose": "documents, slides, spreadsheets",
        "arch": "libreoffice-fresh", "winget": "TheDocumentFoundation.LibreOffice",
        "paths": (r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                  "/usr/lib/libreoffice/program/soffice",
                  "/opt/libreoffice/program/soffice")},
    "gs": {
        "label": "Ghostscript", "names": ("gs",),
        "names_win": ("gswin64c", "gswin32c", "gs"), "setting": "gs_path",
        "purpose": "PDF size reduction",
        "arch": "ghostscript", "winget": "ArtifexSoftware.GhostScript"},
    "qpdf": {
        "label": "qpdf", "names": ("qpdf",), "setting": "qpdf_path",
        "purpose": "combining PDF pages",
        "arch": "qpdf", "winget": "qpdf.qpdf"},
    "pdftoppm": {
        "label": "pdftoppm (poppler)", "names": ("pdftoppm",),
        "setting": "pdftoppm_path",
        "purpose": "PDF pages to images (Qt is used if missing)",
        "arch": "poppler", "winget": None},
    "pdftotext": {
        "label": "pdftotext (poppler)", "names": ("pdftotext",),
        "setting": "pdftotext_path",
        "purpose": "PDF to plain text (LibreOffice is used if missing)",
        "arch": "poppler", "winget": None},
    "ebook-convert": {
        "label": "calibre (ebook-convert)", "names": ("ebook-convert",),
        "setting": "ebook_convert_path", "purpose": "e-books",
        "arch": "calibre", "winget": "calibre.calibre",
        "paths": (r"C:\Program Files\Calibre2\ebook-convert.exe",
                  "/Applications/calibre.app/Contents/MacOS/ebook-convert")},
    "rsvg-convert": {
        "label": "rsvg-convert (librsvg)", "names": ("rsvg-convert",),
        "setting": "rsvg_path",
        "purpose": "SVG rendering (ffmpeg is used if missing)",
        "arch": "librsvg", "winget": None},
    "bsdtar": {
        "label": "bsdtar (libarchive)", "names": ("bsdtar",),
        "names_win": ("bsdtar", "tar"), "setting": "bsdtar_path",
        "purpose": "archives",
        "arch": "libarchive", "winget": None},
}

# Video codec choices per container: label -> (ffmpeg encoder, extra args)
VIDEO_CODECS = {
    "mp4":  [("H.264 (compatible)", "libx264", []),
             ("H.265 / HEVC (smaller)", "libx265", ["-tag:v", "hvc1"]),
             ("AV1 (smallest, slow)", "libsvtav1", [])],
    "mov":  [("H.264 (compatible)", "libx264", []),
             ("H.265 / HEVC (smaller)", "libx265", ["-tag:v", "hvc1"])],
    "mkv":  [("H.264 (compatible)", "libx264", []),
             ("H.265 / HEVC (smaller)", "libx265", []),
             ("AV1 (smallest, slow)", "libsvtav1", []),
             ("VP9", "libvpx-vp9", [])],
    "webm": [("VP9", "libvpx-vp9", []),
             ("AV1 (smallest, slow)", "libsvtav1", [])],
}

# Audio codec per container when converting video (encoder, default args)
CONTAINER_AUDIO = {
    "mp4":  ("aac", []),
    "mov":  ("aac", []),
    "mkv":  ("aac", []),
    "webm": ("libopus", []),
}

# Audio-only outputs: ext -> (encoder, uses_bitrate)
AUDIO_ENCODERS = {
    "mp3":  ("libmp3lame", True),
    "m4a":  ("aac", True),
    "opus": ("libopus", True),
    "ogg":  ("libvorbis", True),
    "flac": ("flac", False),
    "wav":  ("pcm_s16le", False),
}

# Quality presets. Values chosen to match common professional defaults.
#   video: CRF per encoder family, speed preset
#   audio: bitrate kbps
#   image: quality knobs per format
PRESETS = {
    "High quality": {"crf_x264": 18, "crf_x265": 20, "crf_av1": 24, "crf_vp9": 24,
                     "speed": "slow", "abr": 320, "jpg_q": 2, "webp_q": 92, "gif_h": 720},
    "Balanced":     {"crf_x264": 23, "crf_x265": 26, "crf_av1": 32, "crf_vp9": 32,
                     "speed": "medium", "abr": 192, "jpg_q": 5, "webp_q": 80, "gif_h": 480},
    "Small file":   {"crf_x264": 28, "crf_x265": 30, "crf_av1": 40, "crf_vp9": 38,
                     "speed": "medium", "abr": 128, "jpg_q": 10, "webp_q": 65, "gif_h": 360},
}

SPEED_PRESETS = ["ultrafast", "veryfast", "fast", "medium", "slow", "veryslow"]
RESOLUTIONS = [("Original", 0), ("2160p (4K)", 2160), ("1440p", 1440),
               ("1080p", 1080), ("720p", 720), ("480p", 480)]
AUDIO_BITRATES = [320, 256, 192, 160, 128, 96, 64]

MEDIA_INPUT_EXTS = {e for e, k in INPUT_KINDS.items()
                    if k in ("video", "audio", "image")}

# Everything the Convert queue accepts.
CONVERT_INPUT_EXTS = set(INPUT_KINDS)

# Inputs accepted by the Combine-PDF mode. Images are converted to single-page
# PDFs with Pillow (if available) before merging.
MERGE_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"}

# Ghostscript image-downsample DPI used when compressing a PDF without an
# explicit size target — mapped from the quality preset.
PDF_PRESET_DPI = {"High quality": 288, "Balanced": 150, "Small file": 96}
PDF_MIN_DPI, PDF_MAX_DPI = 36, 300

STATUS_WAITING = "Waiting"
STATUS_DONE = "Done"
STATUS_ERROR = "Failed"
STATUS_CANCELLED = "Cancelled"
STATUS_SKIPPED = "Skipped"   # queued file can't become the chosen format
FINISHED_STATUSES = (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED,
                     STATUS_SKIPPED)

ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_STATUS = Qt.ItemDataRole.UserRole + 1
ROLE_LOG = Qt.ItemDataRole.UserRole + 2
ROLE_OUTPUT = Qt.ItemDataRole.UserRole + 3
ROLE_PAGE = Qt.ItemDataRole.UserRole + 5   # merge grid: 1-based source page
ROLE_KIND = Qt.ItemDataRole.UserRole + 6   # merge grid: "pdf" or "image"

# Thumbnail sizing for the page grid
THUMB_W, THUMB_H = 128, 166
GRID_W, GRID_H = 150, 210

IS_WINDOWS = os.name == "nt"
SUBPROC_FLAGS = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def config_dir() -> Path:
    d = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation))
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings() -> QSettings:
    return QSettings(str(config_dir() / "settings.ini"), QSettings.Format.IniFormat)


def find_tool(key: str) -> str:
    """Locate an external tool: the user's custom path from Settings first,
    then PATH (by each known name), then well-known install folders.
    Returns '' if not found."""
    spec = TOOLS[key]
    custom = settings().value(spec["setting"], "", str)
    if custom and Path(custom).is_file():
        return custom
    names = spec.get("names_win", spec["names"]) if IS_WINDOWS else spec["names"]
    for name in names:
        found = QStandardPaths.findExecutable(name)
        if found:
            return found
    for p in spec.get("paths", ()):
        if Path(p).is_file():
            return p
    return ""


def find_all_tools() -> dict[str, str]:
    return {key: find_tool(key) for key in TOOLS}


def install_hint(key: str) -> str:
    """Human-readable 'how to get it' text for a missing tool."""
    spec = TOOLS[key]
    if IS_WINDOWS:
        if spec.get("winget"):
            return (f"Install it with:\n\n    winget install {spec['winget']}"
                    "\n\nthen restart this app — or point to the binary in "
                    "Settings.")
        return ("Install it and point to the binary in Settings "
                "(see the README for download links).")
    return (f"Install it with your package manager, e.g.:\n\n"
            f"    sudo pacman -S {spec['arch']}\n\nthen restart this app — "
            "or point to the binary in Settings.")


def find_ffmpeg() -> str:
    """Custom path from settings first, then PATH. Returns '' if not found."""
    return find_tool("ffmpeg")


def file_ext(path: Path | str) -> str:
    """Lower-case extension without the dot, honouring compound archive
    extensions: 'a.tar.gz' -> 'tar.gz', 'B.PPTX' -> 'pptx'."""
    name = Path(path).name.lower()
    for comp in COMPOUND_EXTS:
        if name.endswith("." + comp):
            return comp
    return Path(name).suffix.lstrip(".")


def split_name(path: Path) -> tuple[str, str]:
    """(stem, ext) with compound extensions kept whole:
    'a.tar.gz' -> ('a', 'tar.gz'); 'x.y.pdf' -> ('x.y', 'pdf')."""
    ext = file_ext(path)
    stem = path.name[:-(len(ext) + 1)] if ext else path.name
    return stem, ext


def input_kind(path: Path | str) -> str | None:
    return INPUT_KINDS.get(file_ext(path))


def can_convert(src: Path, out: str) -> tuple[bool, str]:
    """Whether `src` can become format `out`. Returns (ok, reason)."""
    kind = input_kind(src)
    if kind is None:
        return False, "unsupported file type"
    if out not in REACHABLE.get(kind, []):
        return False, (f"a {KIND_LABELS.get(kind, kind)} can't become "
                       f"{out.upper()}")
    ext = file_ext(src)
    # Re-encoding media or recompressing a PDF to the same format is useful;
    # a document round-trip through LibreOffice is not.
    if ext == out and kind not in ("video", "audio", "image", "pdf"):
        return False, f"already {out.upper()}"
    return True, ""


def missing_tools(kind: str, src_ext: str, out: str, have: dict[str, str]
                  ) -> str | None:
    """Error text naming the tool a (kind → out) conversion needs but which
    isn't installed, or None if everything required is present. Fallbacks are
    honoured (e.g. pdftoppm missing is fine when QtPdf can render)."""
    def need(*keys: str) -> str | None:
        for k in keys:
            if have.get(k):
                return None
        spec = TOOLS[keys[0]]
        return (f"Needs {spec['label']} — not found. Install it or set its "
                "location in Settings.")

    if kind in ("video", "audio", "subtitle"):
        return need("ffmpeg")
    if kind == "image":
        if out == "pdf":
            if HAVE_PIL and src_ext not in PIL_UNREADABLE:
                return None
            if HAVE_PIL and have.get("ffmpeg"):
                return None
            return need("soffice")
        return need("ffmpeg")
    if kind == "svg":
        raster = (None if (have.get("rsvg-convert") or have.get("ffmpeg"))
                  else need("rsvg-convert"))
        if raster:
            return raster
        if out == "png":
            return None
        if out == "pdf":
            if have.get("rsvg-convert") or HAVE_PIL or have.get("soffice"):
                return None
            return need("rsvg-convert")
        return need("ffmpeg")
    if kind == "pdf":
        if out == "pdf":
            return need("gs")
        if out in PAGE_IMAGE_OUTS:
            return None if HAVE_QTPDF else need("pdftoppm")
        if out == "txt":
            return need("pdftotext", "soffice")
        return need("soffice")
    if kind in ("doc", "slides", "sheet"):
        if out in ("epub", "mobi", "azw3"):
            err = need("ebook-convert")
            if err:
                return err
            return None if src_ext in CALIBRE_INPUT_EXTS else need("soffice")
        err = need("soffice")
        if err:
            return err
        if out in PAGE_IMAGE_OUTS and not (HAVE_QTPDF or have.get("pdftoppm")):
            return need("pdftoppm")
        return None
    if kind == "ebook":
        return need("ebook-convert")
    if kind == "archive":
        return need("bsdtar")
    return None


def probe_encoders(ffmpeg: str) -> set[str]:
    """Ask ffmpeg which encoders this build actually has."""
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
            creationflags=SUBPROC_FLAGS,
        ).stdout
    except Exception:
        return set()
    encoders = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[VAS][F.][S.][X.][B.][D.]\s+(\S+)", line)
        if m:
            encoders.add(m.group(1))
    return encoders


def find_qpdf() -> str:
    """qpdf drives page-level PDF assembly. (pdfunite can only concatenate
    whole files, so it can't do page reordering and isn't used here.)"""
    return find_tool("qpdf")


def find_ffprobe(ffmpeg: str) -> str:
    """ffprobe is used to read a clip's duration up front (needed to compute a
    bitrate for size-targeted, two-pass encodes). It ships alongside ffmpeg, so
    look next to the chosen ffmpeg binary first, then fall back to PATH."""
    if ffmpeg:
        cand = Path(ffmpeg).with_name(
            "ffprobe.exe" if IS_WINDOWS else "ffprobe")
        if cand.is_file():
            return str(cand)
    return QStandardPaths.findExecutable("ffprobe") or ""


def find_ghostscript() -> str:
    """Ghostscript drives PDF size reduction (it downsamples embedded images,
    which qpdf cannot). On Windows the console binary is gswin64c/gswin32c;
    on Linux/mac it is `gs`."""
    return find_tool("gs")


# ----------------------------------------------------------------------------
# Document / archive / e-book command builders (pure, unit-testable)
# ----------------------------------------------------------------------------

def soffice_profile_dir() -> Path:
    """LibreOffice is run with its own user profile so a headless conversion
    never talks to (or gets swallowed by) a LibreOffice window the user has
    open. Kept under Morpho's config folder so start-up stays fast."""
    d = config_dir() / "libreoffice-profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_soffice_args(profile: Path, src: Path, out_ext: str, outdir: Path,
                       infilter: str | None = None,
                       export_filter: str | None = None) -> list[str]:
    """`soffice --headless --convert-to` for one file. Output lands in
    `outdir` as <src stem>.<out_ext> (LibreOffice picks the name and will
    overwrite, so callers point it at a private temp folder)."""
    args = [f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--norestore"]
    if infilter:
        args.append(f"--infilter={infilter}")
    target = f"{out_ext}:{export_filter}" if export_filter else out_ext
    args += ["--convert-to", target, "--outdir", str(outdir), str(src)]
    return args


def soffice_infilter(src_ext: str, kind: str) -> str | None:
    """Import filter override. PDFs must be opened by Writer's PDF importer to
    become editable text; HTML must be opened as a Writer document (not
    Writer/Web) or Word/RTF/Markdown export filters aren't available."""
    if kind == "pdf":
        return "writer_pdf_import"
    if src_ext in ("html", "htm", "xhtml"):
        return "HTML (StarWriter)"
    return None


def soffice_check(log: list[str], expected_type: str | None,
                  produced: Path) -> str | None:
    """Validate a LibreOffice run. soffice exits 0 even when it failed, and it
    will load a corrupt .pptx as plain text and 'convert' that — so we require
    (a) no Error line, (b) the document type it reports matches what the file
    is supposed to be, (c) a non-empty output file."""
    text = "\n".join(log)
    for line in log:
        s = line.strip()
        if s.startswith("Error") or s.startswith("Error:"):
            return f"LibreOffice: {s}"
    m = re.search(r" as a (\S+) document -> ", text)
    if expected_type and m and not m.group(1).startswith(expected_type):
        return (f"LibreOffice opened this as a {m.group(1)} document instead "
                f"of {expected_type} — the file is probably damaged or "
                "mislabelled, so it was not converted.")
    if not produced.is_file() or produced.stat().st_size == 0:
        return "LibreOffice produced no output."
    return None


def build_pdftoppm_args(src: Path, prefix: Path, fmt: str, dpi: int,
                        jpeg_q: int) -> list[str]:
    """Render every page of `src` to <prefix>-N.<fmt>."""
    args = ["-r", str(dpi)]
    if fmt == "jpg":
        args += ["-jpeg", "-jpegopt", f"quality={jpeg_q}"]
    elif fmt == "tiff":
        args += ["-tiff", "-tiffcompression", "lzw"]
    else:
        args += ["-png"]
    return args + [str(src), str(prefix)]


def render_pdf_pages_qt(src: Path, out_dir: Path, stem: str, fmt: str,
                        dpi: int, jpeg_q: int) -> str | None:
    """Fallback page rasteriser using Qt's own PDF module (no external tool).
    Returns error text or None."""
    if not HAVE_QTPDF:
        return "Neither pdftoppm nor Qt's PDF module is available."
    doc = QPdfDocument()
    if doc.load(str(src)) != QPdfDocument.Error.None_:
        return "Qt could not open this PDF."
    count = doc.pageCount()
    if count <= 0:
        doc.close()
        return "This PDF has no pages."
    width = len(str(count))
    ext = {"jpg": "jpg", "tiff": "tif"}.get(fmt, "png")
    for i in range(count):
        pt = doc.pagePointSize(i)   # points, 72 per inch
        size = QSize(max(1, round(pt.width() * dpi / 72.0)),
                     max(1, round(pt.height() * dpi / 72.0)))
        img = doc.render(i, size)
        if img.isNull():
            doc.close()
            return f"Qt failed to render page {i + 1}."
        if fmt == "jpg":
            img = img.convertToFormat(QImage.Format.Format_RGB32)
        target = out_dir / f"{stem}-{i + 1:0{width}d}.{ext}"
        ok = img.save(str(target), None, jpeg_q if fmt == "jpg" else -1)
        if not ok:
            doc.close()
            return f"Could not write {target.name}."
    doc.close()
    return None


def build_pdftotext_args(src: Path, dst: Path) -> list[str]:
    return ["-layout", str(src), str(dst)]


def build_ebook_convert_args(src: Path, dst: Path) -> list[str]:
    """calibre: `ebook-convert input output` — the output format is taken
    from the output file's extension."""
    return [str(src), str(dst)]


def build_rsvg_args(src: Path, dst: Path, fmt: str, height: int) -> list[str]:
    """rsvg-convert to PNG or PDF; a height alone keeps the aspect ratio."""
    args = ["-f", fmt]
    if height and fmt == "png":
        args += ["-h", str(height)]
    return args + ["-o", str(dst), str(src)]


def build_archive_extract_args(src: Path, into: Path) -> list[str]:
    """bsdtar auto-detects zip/7z/tar.*/rar on read."""
    return ["-xf", str(src), "-C", str(into)]


def build_archive_create_args(dst: Path, root: Path, entries: list[str]
                              ) -> list[str]:
    """bsdtar `-a` picks the container and compression from the output
    extension (.zip, .7z, .tar.gz, .tar.xz, .tar.zst)."""
    return ["-a", "-cf", str(dst), "-C", str(root)] + entries


def move_into_place(tmp_out: Path, dst: Path) -> str | None:
    """Move a finished temp output to its final, never-overwriting name."""
    try:
        if not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            return "The converter produced no output."
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_out), str(dst))
        return None
    except OSError as e:
        return f"Could not write the output: {e}"


def unique_dir(path: Path) -> Path:
    """Sibling of unique_output for a folder: deck/, deck-1/, deck-2/ …"""
    if not path.exists():
        return path
    n = 1
    while True:
        cand = path.with_name(f"{path.name}-{n}")
        if not cand.exists():
            return cand
        n += 1


def null_sink() -> str:
    """The throwaway output for a two-pass analysis pass."""
    return "NUL" if IS_WINDOWS else "/dev/null"


def probe_duration(ffprobe: str, ffmpeg: str, src: Path) -> float | None:
    """Media duration in seconds, or None if it can't be determined.

    Prefers ffprobe (a clean machine-readable number); falls back to parsing
    ffmpeg's `-i` banner when only ffmpeg is available."""
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(src)],
                capture_output=True, text=True, timeout=30,
                creationflags=SUBPROC_FLAGS,
            )
            val = out.stdout.strip()
            if val and val.upper() != "N/A":
                d = float(val)
                return d if d > 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    if ffmpeg:
        try:
            out = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(src)],
                capture_output=True, text=True, timeout=30,
                creationflags=SUBPROC_FLAGS,
            )
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
                          out.stderr)
            if m:
                d = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                     + float(m.group(3)))
                return d if d > 0 else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def target_video_kbit(target_bytes: int, duration: float,
                      audio_kbit: int) -> int:
    """Video bitrate (kbit/s) so the muxed file lands near `target_bytes`.

    A small overhead margin is kept for container/muxing so we don't sail past
    the target, and the audio budget is subtracted off the top."""
    usable = target_bytes * 0.97 * 8.0 / max(duration, 0.001) / 1000.0
    return max(1, int(usable - max(0, audio_kbit)))


def target_audio_kbit(target_bytes: int, duration: float) -> int:
    """Audio bitrate (kbit/s) for a size-targeted audio-only export."""
    kbit = target_bytes * 0.98 * 8.0 / max(duration, 0.001) / 1000.0
    return max(8, int(kbit))


def dpi_for_pdf_target(current_bytes: int, target_bytes: int) -> int:
    """Pick a Ghostscript downsample DPI to bring a PDF near a target size.

    PDF bulk is embedded raster images, whose byte size scales roughly with the
    square of resolution, so from a 150-dpi baseline we scale by
    sqrt(target/current) and clamp to a sane range. Best-effort: a single pass
    may miss on unusual documents."""
    if current_bytes <= 0 or target_bytes <= 0:
        return PDF_MAX_DPI
    dpi = int(round(150 * (target_bytes / current_bytes) ** 0.5))
    return max(PDF_MIN_DPI, min(PDF_MAX_DPI, dpi))


def build_gs_args(src: Path, dst: Path, dpi: int) -> list[str]:
    """Ghostscript args to recompress `src` to `dst`, downsampling every image
    stream to `dpi`. `-dPDFSETTINGS=/ebook` sets sensible baseline defaults; the
    explicit resolution keys override its downsampling targets."""
    return [
        "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
        "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dBATCH", "-dQUIET",
        "-dDetectDuplicateImages=true",
        "-dDownsampleColorImages=true", "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={dpi}",
        "-dDownsampleGrayImages=true", "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={dpi}",
        "-dDownsampleMonoImages=true", "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={max(dpi, 300)}",
        f"-sOutputFile={dst}", str(src),
    ]


def build_two_pass_args(src: Path, dst: Path, ext: str, opts: dict,
                        passlog: str) -> tuple[list[str], list[str], str | None]:
    """Return (pass1_args, pass2_args, error) for a size-targeted video encode.

    Mirrors the video branch of `build_args` but drives the encoder by target
    bitrate (`-b:v`) over two passes instead of by CRF, which is how ffmpeg
    hits a predictable file size."""
    encoder = opts["vcodec"]
    kbit = opts["target_vkbit"]
    extra = list(opts.get("vcodec_extra", []))
    scale = (["-vf", f"scale=-2:min({opts['height']}\\,ih)"]
             if opts["height"] else [])

    def codec_args() -> list[str]:
        a = ["-c:v", encoder] + extra + ["-b:v", f"{kbit}k"]
        if encoder == "libx264":
            a += ["-preset", opts["speed"], "-pix_fmt", "yuv420p"]
        elif encoder == "libx265":
            a += ["-preset", opts["speed"]]
        elif encoder == "libsvtav1":
            a += ["-preset", "6"]
        elif encoder == "libvpx-vp9":
            a += ["-row-mt", "1"]
        return a

    common = ["-hide_banner", "-y", "-i", str(src)]
    # ffmpeg's generic -pass/-passlogfile drives two-pass for x264, x265, VP9
    # and SVT-AV1 alike (it translates to each encoder's own stats mechanism).
    p1 = (common + codec_args() + scale
          + ["-pass", "1", "-passlogfile", passlog, "-an",
             "-f", "null", "-progress", "pipe:1", "-nostats", null_sink()])
    p2 = (common + codec_args() + scale
          + ["-pass", "2", "-passlogfile", passlog])

    acodec = opts["acodec"]
    if acodec == "copy":
        p2 += ["-c:a", "copy"]
    else:
        p2 += ["-c:a", acodec, "-b:a", f"{opts['abr']}k"]
    if ext == "mp4":
        p2 += ["-movflags", "+faststart"]
    p2 += ["-progress", "pipe:1", "-nostats", str(dst)]
    return p1, p2, None


def qpdf_npages(qpdf: str, path: Path) -> int | None:
    """Page count via `qpdf --show-npages`. Used only when QtPdf is
    unavailable (QtPdf otherwise supplies both count and thumbnails)."""
    if not qpdf:
        return None
    try:
        out = subprocess.run(
            [qpdf, "--show-npages", str(path)],
            capture_output=True, text=True, timeout=15,
            creationflags=SUBPROC_FLAGS,
        )
        if out.returncode in (0, 3):  # 3 = ok with warnings
            return int(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def build_page_args(entries: list[tuple[str, int]], dst: Path) -> list[str]:
    """Build `qpdf --empty --pages ...` args for an ordered page list.

    `entries` is [(pdf_path, page_number_1based), ...] in final output order.
    Consecutive ascending pages from the same file are coalesced into an
    "a-b" range purely to keep the command line short; the resulting page
    order is identical either way.
    """
    args = ["--empty", "--pages"]
    i, n = 0, len(entries)
    while i < n:
        path, page = entries[i]
        last = page
        j = i + 1
        while j < n and entries[j][0] == path and entries[j][1] == last + 1:
            last += 1
            j += 1
        args += [path, str(page) if last == page else f"{page}-{last}"]
        i = j
    args += ["--", str(dst)]
    return args


def unique_output(path: Path) -> Path:
    """Never overwrite: file.mp4 -> file-1.mp4, file-2.mp4, ...
    (compound extensions stay whole: a.tar.gz -> a-1.tar.gz)."""
    if not path.exists():
        return path
    stem, ext = split_name(path)
    suffix = f".{ext}" if ext else ""
    n = 1
    while True:
        candidate = path.parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


# ----------------------------------------------------------------------------
# Command builder
# ----------------------------------------------------------------------------

def build_args(src: Path, dst: Path, ext: str, opts: dict,
               available: set[str]) -> tuple[list[str], str | None]:
    """Return (ffmpeg args, error message or None)."""
    kind = FORMATS[ext][1]
    args: list[str] = ["-hide_banner", "-y", "-i", str(src)]

    def need(encoder: str) -> str | None:
        if available and encoder not in available:
            return (f"This ffmpeg build has no '{encoder}' encoder. "
                    f"Pick a different codec in Advanced.")
        return None

    if kind == "video" and ext != "gif":
        encoder = opts["vcodec"]
        err = need(encoder)
        if err:
            return [], err
        args += ["-c:v", encoder] + list(opts.get("vcodec_extra", []))
        crf = opts["crf"]
        if encoder == "libx264":
            args += ["-crf", str(crf), "-preset", opts["speed"],
                     "-pix_fmt", "yuv420p"]
        elif encoder == "libx265":
            args += ["-crf", str(crf), "-preset", opts["speed"]]
        elif encoder == "libsvtav1":
            args += ["-crf", str(crf), "-preset", "6"]
        elif encoder == "libvpx-vp9":
            args += ["-crf", str(crf), "-b:v", "0", "-row-mt", "1"]
        if opts["height"]:
            args += ["-vf", f"scale=-2:min({opts['height']}\\,ih)"]
        acodec = opts["acodec"]
        if acodec == "copy":
            args += ["-c:a", "copy"]
        else:
            err = need(acodec)
            if err:
                return [], err
            args += ["-c:a", acodec, "-b:a", f"{opts['abr']}k"]
        if ext == "mp4":
            args += ["-movflags", "+faststart"]

    elif ext == "gif":
        h = opts["height"] or opts["gif_h"]
        args += ["-vf",
                 f"fps=12,scale=-2:min({h}\\,ih):flags=lanczos",
                 "-loop", "0", "-an"]

    elif kind == "audio":
        encoder, uses_bitrate = AUDIO_ENCODERS[ext]
        err = need(encoder)
        if err:
            return [], err
        args += ["-vn", "-c:a", encoder]
        if uses_bitrate:
            args += ["-b:a", f"{opts['abr']}k"]

    elif kind == "image":
        args += ["-frames:v", "1", "-update", "1"]
        if ext == "jpg":
            args += ["-q:v", str(opts["jpg_q"])]
        elif ext == "webp":
            err = need("libwebp")
            if err:
                return [], err
            args += ["-c:v", "libwebp", "-quality", str(opts["webp_q"])]
        elif ext == "avif":
            err = need("libaom-av1")
            if err:
                return [], err
            args += ["-c:v", "libaom-av1", "-still-picture", "1",
                     "-crf", str(opts["crf_av1_img"])]
        # png / bmp / tiff: ffmpeg defaults are correct and lossless

    args += ["-progress", "pipe:1", "-nostats", str(dst)]
    return args, None


# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------

QSS = """
* { font-family: "Inter", "Segoe UI", "Noto Sans", "Cantarell", sans-serif; }

QWidget { background: #101114; color: #E8E6E1; font-size: 13px; }

#Card {
    background: #191B1F;
    border: 1px solid #26292F;
    border-radius: 10px;
}

#DropZone {
    background: #16181C;
    border: 2px dashed #33373F;
    border-radius: 12px;
    color: #9BA0A8;
}
#DropZone[dragActive="true"] {
    border-color: #E8A33D;
    background: #1D1A14;
    color: #E8A33D;
}

#Hint  { color: #9BA0A8; font-size: 12px; }
#Title { font-size: 17px; font-weight: 600; letter-spacing: 0.3px; }
#Accent { color: #E8A33D; }
#Ok    { color: #6FBF73; font-size: 12px; }
#Bad   { color: #E0655A; font-size: 12px; }

QPushButton {
    background: #22252B;
    border: 1px solid #2E323A;
    border-radius: 8px;
    padding: 7px 16px;
}
QPushButton:hover  { background: #282C33; border-color: #3A3F49; }
QPushButton:pressed { background: #1D2025; }
QPushButton:disabled { color: #5C616A; background: #1A1C20; border-color: #24272D; }

QPushButton#Primary {
    background: #E8A33D;
    border: 1px solid #E8A33D;
    color: #17130A;
    font-weight: 600;
}
QPushButton#Primary:hover  { background: #F2B45C; border-color: #F2B45C; }
QPushButton#Primary:pressed { background: #D29131; }
QPushButton#Primary:disabled { background: #4A3D22; border-color: #4A3D22; color: #8A7A55; }

QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    color: #E8E6E1;
}
QToolButton:hover { background: #22252B; border-color: #2E323A; }
QToolButton::menu-indicator { image: none; }

QComboBox, QSpinBox, QLineEdit {
    background: #16181C;
    border: 1px solid #2E323A;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #E8A33D;
    selection-color: #17130A;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #3A3F49; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #E8A33D; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #9BA0A8;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background: #191B1F;
    border: 1px solid #2E323A;
    border-radius: 8px;
    selection-background-color: #E8A33D;
    selection-color: #17130A;
    outline: none;
}
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; background: transparent; }
QSpinBox::up-arrow {
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid #9BA0A8;
}
QSpinBox::down-arrow {
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid #9BA0A8;
}

#SegBar {
    background: #16181C;
    border: 1px solid #26292F;
    border-radius: 9px;
}
QPushButton#Seg {
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 5px 16px;
    color: #9BA0A8;
}
QPushButton#Seg:hover { color: #E8E6E1; background: #1D2025; }
QPushButton#Seg:checked {
    background: #E8A33D;
    color: #17130A;
    font-weight: 600;
}

QListWidget {
    background: #16181C;
    border: 1px solid #26292F;
    border-radius: 10px;
    padding: 4px;
}
QListWidget::item {
    padding: 9px 10px;
    border-radius: 6px;
    margin: 1px 0;
}
QListWidget::item:hover { background: #191B1F; }
QListWidget::item:selected { background: #2A2415; color: #E8E6E1; }

QTreeWidget {
    background: #16181C;
    border: 1px solid #26292F;
    border-radius: 10px;
    padding: 4px;
    alternate-background-color: #191B1F;
}
QTreeWidget::item { padding: 6px 4px; border-radius: 6px; }
QTreeWidget::item:selected { background: #2A2415; color: #E8E6E1; }
QHeaderView::section {
    background: transparent;
    color: #9BA0A8;
    border: none;
    border-bottom: 1px solid #26292F;
    padding: 6px 4px;
    font-size: 12px;
}

QProgressBar {
    background: #16181C;
    border: 1px solid #26292F;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: #9BA0A8;
    font-size: 11px;
}
QProgressBar::chunk { background: #E8A33D; border-radius: 6px; }

QSlider::groove:horizontal {
    height: 5px; background: #16181C;
    border: 1px solid #26292F; border-radius: 3px;
}
QSlider::sub-page:horizontal { background: #E8A33D; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #E8A33D; border: 2px solid #17130A;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: #F2B45C; }
QSlider:disabled::sub-page:horizontal { background: #4A3D22; }
QSlider:disabled::handle:horizontal { background: #4A3D22; }

QMenu {
    background: #191B1F;
    border: 1px solid #2E323A;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item { padding: 7px 24px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: #E8A33D; color: #17130A; }
QMenu::separator { height: 1px; background: #26292F; margin: 6px 8px; }

QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #3A3F49; border-radius: 5px; background: #16181C;
}
QCheckBox::indicator:checked { background: #E8A33D; border-color: #E8A33D; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2E323A; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3A3F49; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip {
    background: #22252B; color: #E8E6E1;
    border: 1px solid #3A3F49; border-radius: 6px; padding: 6px;
}
"""


# ----------------------------------------------------------------------------
# Dialogs
# ----------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """One row per external tool: a path box (blank = auto-detect), a Browse
    button and what was found on this machine."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        intro = QLabel(
            "Morpho converts with tools already on your system. Leave a box "
            "blank to auto-detect from PATH, or point at a specific binary.")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.edits: dict[str, QLineEdit] = {}
        for key, spec in TOOLS.items():
            lay.addSpacing(4)
            lay.addWidget(QLabel(f"{spec['label']}  —  {spec['purpose']}"))
            row = QHBoxLayout()
            edit = QLineEdit(settings().value(spec["setting"], "", str))
            edit.setPlaceholderText("Auto-detect from PATH")
            browse = QPushButton("Browse…")
            names = (spec.get("names_win", spec["names"]) if IS_WINDOWS
                     else spec["names"])
            browse.clicked.connect(
                lambda _=False, e=edit, n=names[0]: self._browse(e, n))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            lay.addLayout(row)
            found = find_tool(key)
            hint = QLabel(f"Detected: {found}" if found
                          else "Not found — install it or set a location above.")
            hint.setObjectName("Hint" if found else "Bad")
            hint.setWordWrap(True)
            lay.addWidget(hint)
            self.edits[key] = edit

        cfg = QLabel(f"Settings are stored in:\n{config_dir()}")
        cfg.setObjectName("Hint")
        cfg.setWordWrap(True)
        lay.addSpacing(6)
        lay.addWidget(cfg)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browse(self, target: QLineEdit, tool: str):
        name = f"{tool}.exe" if IS_WINDOWS else tool
        path, _ = QFileDialog.getOpenFileName(
            self, f"Locate {name}", str(Path.home()))
        if path:
            target.setText(path)

    def _save(self):
        values = {key: e.text().strip() for key, e in self.edits.items()}
        for p in values.values():
            if p and not Path(p).is_file():
                QMessageBox.warning(self, "Settings",
                                    f"This path does not point to a file:\n{p}")
                return
        s = settings()
        for key, p in values.items():
            s.setValue(TOOLS[key]["setting"], p)
        s.sync()
        self.accept()


class UninstallDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(f"Uninstall {APP_NAME}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        manifest = Path.home() / ".local" / "share" / APP_ID / "manifest.txt"
        self.manifest = manifest if manifest.is_file() else None

        if self.manifest:
            what = ("This removes the installed application files "
                    "(listed in the install manifest) from your home directory.")
        else:
            what = (f"{APP_NAME} was run directly, not installed — to remove the "
                    "app itself, just delete this file:\n"
                    f"{Path(sys.argv[0]).resolve()}")
        label = QLabel(what)
        label.setWordWrap(True)
        lay.addWidget(label)

        self.purge = QCheckBox(f"Also delete all settings  ({config_dir()})")
        self.purge.setChecked(True)
        lay.addWidget(self.purge)

        buttons = QDialogButtonBox()
        remove = buttons.addButton(
            "Uninstall", QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        remove.clicked.connect(self._uninstall)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _uninstall(self):
        errors = []
        if self.manifest:
            try:
                for line in self.manifest.read_text().splitlines():
                    p = Path(line.strip())
                    if line.strip() and p.exists():
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)
                share_dir = self.manifest.parent
                self.manifest.unlink(missing_ok=True)
                if share_dir.exists() and not any(share_dir.iterdir()):
                    share_dir.rmdir()
            except OSError as e:
                errors.append(str(e))
        if self.purge.isChecked():
            shutil.rmtree(config_dir(), ignore_errors=True)
        if errors:
            QMessageBox.warning(self, "Uninstall",
                                "Some files could not be removed:\n"
                                + "\n".join(errors))
        else:
            QMessageBox.information(
                self, "Uninstall",
                f"{APP_NAME} has been removed. Goodbye.")
        QApplication.quit()


# ----------------------------------------------------------------------------
# Page grid
# ----------------------------------------------------------------------------

class PageGrid(QListWidget):
    """Icon-mode grid of page thumbnails with deterministic drag reordering.

    Rather than rely on Qt's built-in internal-move (whose behaviour varies
    across view modes/platforms), the drop is handled explicitly: the target
    index is computed from the cursor, and the selected tiles are moved with
    takeItem/insertItem. External file drops are forwarded to `on_external`
    so dropping onto a full grid still adds files.
    """

    def __init__(self, on_reordered, on_external):
        super().__init__()
        self._on_reordered = on_reordered
        self._on_external = on_external
        self.setAcceptDrops(True)
        self.setDragEnabled(True)

    def _is_internal(self, event) -> bool:
        return event.source() is self

    def dragEnterEvent(self, event):
        if self._is_internal(event) or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._is_internal(event) or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self._is_internal(event):
            self._internal_drop(event)
        elif event.mimeData().hasUrls():
            paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                     if u.isLocalFile()]
            event.acceptProposedAction()
            self._on_external(paths)
        else:
            event.ignore()

    def _internal_drop(self, event):
        rows = sorted(self.row(i) for i in self.selectedItems())
        if not rows:
            event.ignore()
            return
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid():
            target = idx.row()
            rect = self.visualRect(idx)
            # Insert after the tile if dropped past its horizontal midpoint.
            if pos.x() > rect.center().x():
                target += 1
        else:
            target = self.count()
        # Pull selected items out (highest row first keeps indices valid).
        taken = [self.takeItem(r) for r in sorted(rows, reverse=True)][::-1]
        target -= sum(1 for r in rows if r < target)
        target = max(0, min(target, self.count()))
        for k, it in enumerate(taken):
            self.insertItem(target + k, it)
            it.setSelected(True)
        event.accept()
        self._on_reordered()


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(680, 560)
        self.setAcceptDrops(True)

        self.tools: dict[str, str] = {}
        self.encoders: set[str] = set()
        self._refresh_tools()

        self.proc: QProcess | None = None
        self.current_item: QTreeWidgetItem | None = None
        self.current_duration: float = 0.0
        self.current_log: list[str] = []
        self.converting = False
        self._loading_preset = False
        self._rebuilding_formats = False

        # Per-item job: a list of sequential stages (a plain conversion is one
        # ffmpeg run; a size-targeted video is two passes; a slide deck → PNG
        # is LibreOffice → PDF then pdftoppm; …) plus a finalize step. A stage
        # is either a process ("program"/"args") or a Python callable ("func").
        # See _build_job / _run_stage / _stage_finished.
        self.current_job: dict = {}
        self.current_stages: list[dict] = []
        self.current_stage_idx: int = 0
        self._cur_span: tuple[int, int] = (0, 100)
        self._passlog_dir: tempfile.TemporaryDirectory | None = None
        self._job_tmp: tempfile.TemporaryDirectory | None = None
        self.current_target_bytes: int = 0
        self.current_targeted: bool = False

        # Combine-PDF mode state
        self.mode = "convert"           # "convert" or "merge"
        self.merging = False
        self._merge_tmpdir: tempfile.TemporaryDirectory | None = None
        self._merge_log: list[str] = []
        self._merge_output: Path | None = None

        self._build_ui()
        self._apply_preset(self.preset_combo.currentText())
        self._refresh_badge()
        if not self.ffmpeg and not self.tools.get("soffice"):
            QTimer.singleShot(300, self._prompt_ffmpeg_missing)

    def _refresh_tools(self):
        """(Re)locate every external tool. ffmpeg's encoder list is probed
        only when its path changed, since that spawns a process."""
        old_ffmpeg = self.tools.get("ffmpeg")
        self.tools = find_all_tools()
        self.ffmpeg = self.tools["ffmpeg"]
        self.qpdf = self.tools["qpdf"]
        self.gs = self.tools["gs"]
        self.ffprobe = find_ffprobe(self.ffmpeg)
        if self.ffmpeg != old_ffmpeg or not self.encoders:
            self.encoders = probe_encoders(self.ffmpeg) if self.ffmpeg else set()

    # ---------------- UI construction ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"{APP_NAME}")
        title.setObjectName("Title")
        arrow = QLabel("→")
        arrow.setObjectName("Accent")
        arrow.setStyleSheet("font-size: 17px; font-weight: 700;")
        header.addWidget(title)
        header.addWidget(arrow)
        header.addSpacing(14)

        # Mode switch (segmented control)
        seg = QFrame()
        seg.setObjectName("SegBar")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(3)
        self.mode_group = QButtonGroup(self)
        self.btn_mode_convert = QPushButton("Convert")
        self.btn_mode_merge = QPushButton("Combine PDF")
        for i, b in enumerate((self.btn_mode_convert, self.btn_mode_merge)):
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode_group.addButton(b, i)
            seg_lay.addWidget(b)
        self.btn_mode_convert.setChecked(True)
        self.btn_mode_convert.clicked.connect(lambda: self._set_mode("convert"))
        self.btn_mode_merge.clicked.connect(lambda: self._set_mode("merge"))
        header.addWidget(seg)

        header.addStretch(1)

        self.ffmpeg_badge = QLabel()
        header.addWidget(self.ffmpeg_badge)

        menu_btn = QToolButton()
        menu_btn.setText("⋯")
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_btn)
        act_settings = QAction("Settings…", self)
        act_settings.triggered.connect(self._open_settings)
        act_uninstall = QAction(f"Uninstall {APP_NAME}…", self)
        act_uninstall.triggered.connect(lambda: UninstallDialog(self).exec())
        act_about = QAction("About", self)
        act_about.triggered.connect(self._about)
        menu.addAction(act_settings)
        menu.addSeparator()
        menu.addAction(act_uninstall)
        menu.addAction(act_about)
        menu_btn.setMenu(menu)
        header.addWidget(menu_btn)
        root.addLayout(header)

        # Stacked body: page 0 = Convert, page 1 = Combine PDF
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_convert_page())
        self.stack.addWidget(self._build_merge_page())
        root.addWidget(self.stack, 1)

        # Shared bottom action row
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setValue(0)
        bottom.addWidget(self.progress, 1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.hide()
        bottom.addWidget(self.btn_cancel)
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setObjectName("Primary")
        self.btn_convert.clicked.connect(self._on_primary_clicked)
        self.btn_convert.setEnabled(False)
        bottom.addWidget(self.btn_convert)
        root.addLayout(bottom)

        self._on_format_changed()

    def _build_convert_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Drop zone (shown while queue is empty)
        self.drop_zone = QLabel(
            "Drop files here\n\nor click to browse\n\n"
            "video · audio · images · PDF · Word · PowerPoint · Excel · "
            "e-books · subtitles · archives")
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setMinimumHeight(150)
        self.drop_zone.mousePressEvent = lambda e: self._browse_files()
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.drop_zone)

        # Queue
        self.queue = QTreeWidget()
        self.queue.setHeaderLabels(["File", "Size", "Status"])
        self.queue.setRootIsDecorated(False)
        self.queue.setAlternatingRowColors(True)
        self.queue.setColumnWidth(0, 340)
        self.queue.setColumnWidth(1, 80)
        self.queue.itemDoubleClicked.connect(self._show_item_details)
        self.queue.hide()
        root.addWidget(self.queue, 1)

        queue_btns = QHBoxLayout()
        self.btn_add = QPushButton("Add files…")
        self.btn_add.clicked.connect(self._browse_files)
        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._clear_queue)
        queue_btns.addWidget(self.btn_add)
        queue_btns.addWidget(self.btn_remove)
        queue_btns.addWidget(self.btn_clear)
        queue_btns.addStretch(1)
        self.queue_btns_widget = QWidget()
        self.queue_btns_widget.setLayout(queue_btns)
        self.queue_btns_widget.hide()
        root.addWidget(self.queue_btns_widget)

        # Options card
        card = QFrame()
        card.setObjectName("Card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Convert to"))
        self.format_combo = QComboBox()
        for ext, (label, _) in FORMATS.items():
            self.format_combo.addItem(label, ext)
        saved_fmt = self.format_combo.findData(
            settings().value("last_format", "mp4", str))
        self.format_combo.setCurrentIndex(max(0, saved_fmt))
        self.format_combo.setToolTip(
            "Lists the formats the queued files can become. With a mixed "
            "queue, files that can't reach the chosen format are skipped.")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        row1.addWidget(self.format_combo, 1)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Quality"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.setCurrentText("Balanced")
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        row1.addWidget(self.preset_combo, 1)
        card_lay.addLayout(row1)

        # Target output size. When on, video is encoded two-pass to a computed
        # bitrate, audio to a computed bitrate, and PDFs are downsampled — all
        # aiming at the MB figure below. Quality preset then only breaks ties.
        size_row = QHBoxLayout()
        self.size_check = QCheckBox("Limit output size")
        self.size_check.setToolTip(
            "Encode to a target file size instead of a fixed quality.\n"
            "Video uses two passes (slower); PDFs are downsampled with "
            "Ghostscript.")
        self.size_check.setChecked(settings().value("target_on", False, bool))
        self.size_check.toggled.connect(self._on_size_limit_toggled)
        size_row.addWidget(self.size_check)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 4000)          # 1 MB … 4 GB
        self.size_slider.setValue(int(settings().value("target_mb", 200, int)))
        self.size_slider.valueChanged.connect(self._on_size_slider)
        size_row.addWidget(self.size_slider, 1)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 4000)
        self.size_spin.setSuffix(" MB")
        self.size_spin.setValue(self.size_slider.value())
        self.size_spin.valueChanged.connect(self._on_size_spin)
        size_row.addWidget(self.size_spin)
        card_lay.addLayout(size_row)

        # Explains the plan for the current queue + format (PDF recompression,
        # per-page images, skipped files, missing tools).
        self.pdf_note = QLabel()
        self.pdf_note.setObjectName("Hint")
        self.pdf_note.setWordWrap(True)
        self.pdf_note.hide()
        card_lay.addWidget(self.pdf_note)

        # Advanced (collapsible)
        self.adv_toggle = QToolButton()
        self.adv_toggle.setText("Advanced")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.adv_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        card_lay.addWidget(self.adv_toggle)

        self.adv_panel = QWidget()
        adv = QVBoxLayout(self.adv_panel)
        adv.setContentsMargins(4, 0, 0, 0)
        adv.setSpacing(8)

        adv_row1 = QHBoxLayout()
        adv_row1.addWidget(QLabel("Video codec"))
        self.vcodec_combo = QComboBox()
        self.vcodec_combo.currentIndexChanged.connect(self._mark_custom)
        adv_row1.addWidget(self.vcodec_combo, 1)
        adv_row1.addSpacing(10)
        adv_row1.addWidget(QLabel("CRF"))
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 63)
        self.crf_spin.setToolTip("Lower = better quality, bigger file")
        self.crf_spin.valueChanged.connect(self._mark_custom)
        adv_row1.addWidget(self.crf_spin)
        adv.addLayout(adv_row1)

        adv_row2 = QHBoxLayout()
        adv_row2.addWidget(QLabel("Encoder speed"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(SPEED_PRESETS)
        self.speed_combo.setToolTip(
            "Slower = better compression for the same quality")
        self.speed_combo.currentIndexChanged.connect(self._mark_custom)
        adv_row2.addWidget(self.speed_combo, 1)
        adv_row2.addSpacing(10)
        adv_row2.addWidget(QLabel("Resolution"))
        self.res_combo = QComboBox()
        for label, h in RESOLUTIONS:
            self.res_combo.addItem(label, h)
        self.res_combo.currentIndexChanged.connect(self._mark_custom)
        adv_row2.addWidget(self.res_combo, 1)
        adv.addLayout(adv_row2)

        adv_row3 = QHBoxLayout()
        adv_row3.addWidget(QLabel("Audio"))
        self.acodec_combo = QComboBox()
        self.acodec_combo.addItem("Re-encode (default)", "encode")
        self.acodec_combo.addItem("Copy without re-encoding", "copy")
        self.acodec_combo.currentIndexChanged.connect(self._mark_custom)
        adv_row3.addWidget(self.acodec_combo, 1)
        adv_row3.addSpacing(10)
        adv_row3.addWidget(QLabel("Audio bitrate"))
        self.abr_combo = QComboBox()
        for b in AUDIO_BITRATES:
            self.abr_combo.addItem(f"{b} kbps", b)
        self.abr_combo.currentIndexChanged.connect(self._mark_custom)
        adv_row3.addWidget(self.abr_combo, 1)
        adv.addLayout(adv_row3)

        self.adv_panel.hide()
        card_lay.addWidget(self.adv_panel)

        # Output folder
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to"))
        self.out_combo = QComboBox()
        self.out_combo.addItem("Same folder as each file", "same")
        self.out_combo.addItem("Choose a folder…", "custom")
        self.out_combo.activated.connect(self._on_out_choice)
        out_row.addWidget(self.out_combo, 1)
        self.out_label = QLabel("")
        self.out_label.setObjectName("Hint")
        out_row.addWidget(self.out_label, 1)
        card_lay.addLayout(out_row)

        root.addWidget(card)

        saved_out = settings().value("out_dir", "", str)
        if saved_out and Path(saved_out).is_dir():
            self.out_combo.setCurrentIndex(1)
            self.out_label.setText(saved_out)

        return page

    # ---------------- Combine-PDF page ----------------

    def _build_merge_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Drop zone (shown while the grid is empty)
        self.merge_drop = QLabel(
            "Drop PDFs or images here\n\nor click to browse")
        self.merge_drop.setObjectName("DropZone")
        self.merge_drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.merge_drop.setMinimumHeight(150)
        self.merge_drop.mousePressEvent = lambda e: self._browse_merge_files()
        self.merge_drop.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.merge_drop)

        # Page thumbnail grid — every page is one draggable tile, with its
        # caption underneath (IconMode). Static movement keeps tiles snapped to
        # the reflowing grid; InternalMove handles drag reordering. The
        # Move earlier/later buttons are an always-available equivalent.
        self.merge_list = PageGrid(on_reordered=self._renumber_merge,
                                   on_external=self._add_merge_files)
        self.merge_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.merge_list.setFlow(QListView.Flow.LeftToRight)
        self.merge_list.setWrapping(True)
        self.merge_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.merge_list.setMovement(QListWidget.Movement.Static)
        self.merge_list.setUniformItemSizes(True)
        self.merge_list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.merge_list.setGridSize(QSize(GRID_W, GRID_H))
        self.merge_list.setSpacing(8)
        self.merge_list.setWordWrap(True)
        self.merge_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.merge_list.setDragDropMode(
            QAbstractItemView.DragDropMode.DragDrop)
        self.merge_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.merge_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        # Renumber captions whenever rows are added/removed (reorder is handled
        # by PageGrid's on_reordered callback).
        model = self.merge_list.model()
        model.rowsInserted.connect(self._renumber_merge)
        model.rowsRemoved.connect(self._renumber_merge)
        self.merge_list.hide()
        root.addWidget(self.merge_list, 1)

        hint = QLabel(
            "Drag any page to reorder — mix pages from different files freely. "
            "Pages are combined left to right, top to bottom.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.merge_hint = hint
        hint.hide()
        root.addWidget(hint)

        merge_btns = QHBoxLayout()
        self.mbtn_add = QPushButton("Add files…")
        self.mbtn_add.clicked.connect(self._browse_merge_files)
        self.mbtn_up = QPushButton("Move earlier")
        self.mbtn_up.clicked.connect(lambda: self._merge_move(-1))
        self.mbtn_down = QPushButton("Move later")
        self.mbtn_down.clicked.connect(lambda: self._merge_move(1))
        self.mbtn_remove = QPushButton("Remove selected")
        self.mbtn_remove.clicked.connect(self._remove_merge_selected)
        self.mbtn_clear = QPushButton("Clear")
        self.mbtn_clear.clicked.connect(self._clear_merge)
        for b in (self.mbtn_add, self.mbtn_up, self.mbtn_down,
                  self.mbtn_remove, self.mbtn_clear):
            merge_btns.addWidget(b)
        merge_btns.addStretch(1)
        self.merge_btns_widget = QWidget()
        self.merge_btns_widget.setLayout(merge_btns)
        self.merge_btns_widget.hide()
        root.addWidget(self.merge_btns_widget)

        # Output card
        card = QFrame()
        card.setObjectName("Card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Output name"))
        self.merge_name = QLineEdit("combined")
        self.merge_name.setPlaceholderText("combined")
        name_row.addWidget(self.merge_name, 1)
        name_row.addWidget(QLabel(".pdf"))
        card_lay.addLayout(name_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to"))
        self.merge_out_combo = QComboBox()
        self.merge_out_combo.addItem("Same folder as the first file", "same")
        self.merge_out_combo.addItem("Choose a folder…", "custom")
        self.merge_out_combo.activated.connect(self._on_merge_out_choice)
        out_row.addWidget(self.merge_out_combo, 1)
        self.merge_out_label = QLabel("")
        self.merge_out_label.setObjectName("Hint")
        out_row.addWidget(self.merge_out_label, 1)
        card_lay.addLayout(out_row)

        root.addWidget(card)

        saved_out = settings().value("merge_out_dir", "", str)
        if saved_out and Path(saved_out).is_dir():
            self.merge_out_combo.setCurrentIndex(1)
            self.merge_out_label.setText(saved_out)

        return page

    # ---------------- ffmpeg presence ----------------

    def _refresh_badge(self):
        lines = []
        for key, spec in TOOLS.items():
            path = self.tools.get(key, "")
            lines.append(f"{'✓' if path else '✗'} {spec['label']}: "
                         f"{path or 'not found'}")
        self.ffmpeg_badge.setToolTip("\n".join(lines))
        if self.mode == "merge":
            ready = bool(self.qpdf)
            self.ffmpeg_badge.setText("qpdf ready" if ready
                                      else "qpdf not found")
        else:
            missing = [TOOLS[k]["label"].split(" (")[0]
                       for k in TOOLS if not self.tools.get(k)]
            ready = not missing
            if ready:
                self.ffmpeg_badge.setText("all tools ready")
            elif len(missing) <= 2:
                self.ffmpeg_badge.setText(f"{', '.join(missing)} not found")
            else:
                self.ffmpeg_badge.setText(f"{len(missing)} tools not found")
        self.ffmpeg_badge.setObjectName("Ok" if ready else "Bad")
        # re-polish so the objectName style applies
        self.ffmpeg_badge.style().unpolish(self.ffmpeg_badge)
        self.ffmpeg_badge.style().polish(self.ffmpeg_badge)

    def _prompt_ffmpeg_missing(self):
        box = QMessageBox(self)
        box.setWindowTitle("ffmpeg is required")
        box.setText(
            f"{APP_NAME} converts media with the ffmpeg already on your "
            "system, and none was found.")
        box.setInformativeText(install_hint("ffmpeg"))
        locate = box.addButton("Locate ffmpeg…",
                               QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is locate:
            self._open_settings()

    def _prompt_tool_missing(self, key: str, why: str):
        spec = TOOLS[key]
        box = QMessageBox(self)
        box.setWindowTitle(f"{spec['label']} is required")
        box.setText(f"{APP_NAME} {why} with {spec['label']}, which wasn't "
                    "found.")
        box.setInformativeText(install_hint(key))
        locate = box.addButton("Open Settings…",
                               QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is locate:
            self._open_settings()

    def _open_settings(self):
        if SettingsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._refresh_tools()
            self._refresh_badge()
            if self.mode == "merge":
                self._sync_merge_state()
            else:
                self._sync_empty_state()

    def _about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME} {APP_VERSION}</b><br>"
            "An all-in-one file converter — video, audio, images, PDFs, "
            "documents, slides, spreadsheets, e-books, subtitles and "
            "archives — powered by the tools already on your system "
            "(ffmpeg, LibreOffice, Ghostscript, qpdf, poppler, calibre, "
            "librsvg, bsdtar).<br><br>"
            f"Settings folder: {config_dir()}<br>"
            "License: MIT")

    # ---------------- mode switch ----------------

    def _set_mode(self, mode: str):
        if mode == self.mode:
            return
        # Don't switch away mid-run; restore the button and bail.
        if self.converting or self.merging:
            (self.btn_mode_convert if self.mode == "convert"
             else self.btn_mode_merge).setChecked(True)
            return
        self.mode = mode
        self.stack.setCurrentIndex(0 if mode == "convert" else 1)
        self.btn_mode_convert.setChecked(mode == "convert")
        self.btn_mode_merge.setChecked(mode == "merge")
        self.progress.setValue(0)
        self._refresh_badge()
        if mode == "convert":
            self._sync_empty_state()
        else:
            self._sync_merge_state()

    def _on_primary_clicked(self):
        if self.mode == "merge":
            self._start_merge()
        else:
            self._start_queue()

    # ---------------- drag & drop ----------------

    def _active_drop_zone(self) -> QLabel:
        return self.merge_drop if self.mode == "merge" else self.drop_zone

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            dz = self._active_drop_zone()
            dz.setProperty("dragActive", True)
            self._repolish(dz)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        dz = self._active_drop_zone()
        dz.setProperty("dragActive", False)
        self._repolish(dz)

    def dropEvent(self, event: QDropEvent):
        dz = self._active_drop_zone()
        dz.setProperty("dragActive", False)
        self._repolish(dz)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if self.mode == "merge":
            self._add_merge_files(paths)
        else:
            self._add_files(paths)
        event.acceptProposedAction()

    @staticmethod
    def _repolish(w: QWidget):
        w.style().unpolish(w)
        w.style().polish(w)

    # ---------------- queue management ----------------

    def _browse_files(self):
        exts = " ".join(f"*.{e}" for e in sorted(CONVERT_INPUT_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add files", str(Path.home()),
            f"Convertible files ({exts});;All files (*)")
        self._add_files([Path(f) for f in files])

    def _add_files(self, paths: list[Path]):
        added = 0
        skipped = 0
        for p in paths:
            if p.is_dir():
                children = [c for c in sorted(p.iterdir())
                            if c.is_file() and input_kind(c)]
                self._add_files(children)
                continue
            if not p.is_file():
                continue
            if input_kind(p) is None:
                skipped += 1
                continue
            if self._find_item(p):
                continue
            item = QTreeWidgetItem(
                [p.name, human_size(p.stat().st_size), STATUS_WAITING])
            item.setData(0, ROLE_PATH, str(p))
            item.setData(0, ROLE_STATUS, STATUS_WAITING)
            item.setToolTip(0, str(p))
            self.queue.addTopLevelItem(item)
            added += 1
        if skipped and not added:
            QMessageBox.information(
                self, APP_NAME,
                "Those files aren't a type Morpho knows how to convert, so "
                "they were skipped.")
        self._sync_empty_state()

    def _find_item(self, path: Path) -> QTreeWidgetItem | None:
        for i in range(self.queue.topLevelItemCount()):
            item = self.queue.topLevelItem(i)
            if item.data(0, ROLE_PATH) == str(path):
                return item
        return None

    def _remove_selected(self):
        if self.converting:
            return
        for item in self.queue.selectedItems():
            self.queue.takeTopLevelItem(
                self.queue.indexOfTopLevelItem(item))
        self._sync_empty_state()

    def _clear_queue(self):
        if self.converting:
            return
        self.queue.clear()
        self.progress.setValue(0)
        self._sync_empty_state()

    def _sync_empty_state(self):
        has_items = self.queue.topLevelItemCount() > 0
        self.drop_zone.setVisible(not has_items)
        self.queue.setVisible(has_items)
        self.queue_btns_widget.setVisible(has_items)
        self._rebuild_format_combo()
        self._update_size_controls()
        n_ok = len(self._convertible_waiting())
        self.btn_convert.setEnabled(has_items and not self.converting
                                    and n_ok > 0)
        if n_ok:
            self.btn_convert.setText(
                f"Convert {n_ok} file{'s' if n_ok != 1 else ''}")
        else:
            self.btn_convert.setText("Convert")

    def _waiting_items(self) -> list[QTreeWidgetItem]:
        return [self.queue.topLevelItem(i)
                for i in range(self.queue.topLevelItemCount())
                if self.queue.topLevelItem(i).data(0, ROLE_STATUS)
                == STATUS_WAITING]

    def _item_problem(self, item: QTreeWidgetItem, out: str) -> str | None:
        """Why this queued file can't be converted to `out` right now (not
        reachable, or a needed tool is missing) — None when it can."""
        src = Path(item.data(0, ROLE_PATH))
        ok, why = can_convert(src, out)
        if not ok:
            return why
        kind = input_kind(src) or ""
        return missing_tools(kind, file_ext(src), out, self.tools)

    def _convertible_waiting(self) -> list[QTreeWidgetItem]:
        out = self._current_ext()
        if not out:
            return []
        return [it for it in self._waiting_items()
                if self._item_problem(it, out) is None]

    def _show_item_details(self, item: QTreeWidgetItem, _col: int):
        log = item.data(0, ROLE_LOG)
        out = item.data(0, ROLE_OUTPUT)
        status = item.data(0, ROLE_STATUS)
        if status == STATUS_DONE and out:
            folder = Path(out) if Path(out).is_dir() else Path(out).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif log:
            QMessageBox.warning(
                self, "Conversion log",
                f"{item.text(0)}\n\n{log}")

    # ---------------- options logic ----------------

    def _current_ext(self) -> str:
        return self.format_combo.currentData() or ""

    def _rebuild_format_combo(self):
        """Adaptive picker: list only the formats the queued files can become
        (all formats when the queue is empty). Keeps the current pick when it
        is still reachable; otherwise falls back to the most sensible default
        for what's queued (PDF for documents, the first reachable otherwise)."""
        kinds: list[str] = []
        for i in range(self.queue.topLevelItemCount()):
            k = input_kind(self.queue.topLevelItem(i).data(0, ROLE_PATH))
            if k and k not in kinds:
                kinds.append(k)
        if kinds:
            reachable: list[str] = []
            for k in kinds:
                for e in REACHABLE.get(k, []):
                    if e not in reachable:
                        reachable.append(e)
        else:
            reachable = list(FORMATS)

        before = self._current_ext()
        current = before or settings().value("last_format", "mp4", str)
        if current not in reachable:
            current = "pdf" if "pdf" in reachable else reachable[0]

        self._rebuilding_formats = True
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        first = True
        for kind in KIND_ORDER:
            exts = [e for e in reachable if FORMATS[e][1] == kind]
            if not exts:
                continue
            if not first:
                self.format_combo.insertSeparator(self.format_combo.count())
            first = False
            for e in exts:
                self.format_combo.addItem(FORMATS[e][0], e)
        idx = self.format_combo.findData(current)
        self.format_combo.setCurrentIndex(max(0, idx))
        self.format_combo.blockSignals(False)
        self._rebuilding_formats = False
        if self._current_ext() != before:
            # Only a real change re-applies codec defaults (so adding files
            # never resets a hand-tuned CRF); the note is refreshed either way.
            self._on_format_changed()
        else:
            self._update_size_controls()

    def _on_format_changed(self):
        ext = self._current_ext()
        if not ext:
            return
        kind = FORMATS[ext][1]
        settings().setValue("last_format", ext)
        self._loading_preset = True
        self.vcodec_combo.clear()
        for label, encoder, extra in VIDEO_CODECS.get(ext, []):
            if not self.encoders or encoder in self.encoders:
                self.vcodec_combo.addItem(label, (encoder, extra))
        is_video = kind == "video" and ext != "gif"
        self.vcodec_combo.setEnabled(is_video and self.vcodec_combo.count() > 0)
        self.crf_spin.setEnabled(is_video)
        self.speed_combo.setEnabled(is_video)
        # Resolution also caps the height when an SVG is rasterised.
        self.res_combo.setEnabled(kind in ("video", "image"))
        self.acodec_combo.setEnabled(is_video)
        self.abr_combo.setEnabled(is_video or kind == "audio")
        self._loading_preset = False
        self._apply_preset(self.preset_combo.currentText())
        if not self._rebuilding_formats:
            self._update_size_controls()
            self._sync_convert_button()

    def _sync_convert_button(self):
        if self.converting:
            return
        n_ok = len(self._convertible_waiting())
        self.btn_convert.setEnabled(n_ok > 0)
        self.btn_convert.setText(
            f"Convert {n_ok} file{'s' if n_ok != 1 else ''}" if n_ok
            else "Convert")

    def _apply_preset(self, name: str):
        if name not in PRESETS or self._loading_preset:
            return
        p = PRESETS[name]
        self._loading_preset = True
        encoder = self._selected_encoder()
        self.crf_spin.setValue(self._crf_for(encoder, p))
        self.speed_combo.setCurrentText(p["speed"])
        idx = self.abr_combo.findData(p["abr"])
        if idx >= 0:
            self.abr_combo.setCurrentIndex(idx)
        self._loading_preset = False

    @staticmethod
    def _crf_for(encoder: str, p: dict) -> int:
        return {"libx264": p["crf_x264"], "libx265": p["crf_x265"],
                "libsvtav1": p["crf_av1"], "libvpx-vp9": p["crf_vp9"],
                }.get(encoder, p["crf_x264"])

    def _selected_encoder(self) -> str:
        data = self.vcodec_combo.currentData()
        return data[0] if data else "libx264"

    def _mark_custom(self):
        if self._loading_preset:
            return
        # Codec change re-baselines CRF to the preset value for that codec
        sender = self.sender()
        if sender is self.vcodec_combo:
            name = self.preset_combo.currentText()
            if name in PRESETS:
                self._loading_preset = True
                self.crf_spin.setValue(
                    self._crf_for(self._selected_encoder(), PRESETS[name]))
                self._loading_preset = False

    def _on_out_choice(self, index: int):
        if self.out_combo.itemData(index) == "custom":
            d = QFileDialog.getExistingDirectory(
                self, "Choose output folder",
                self.out_label.text() or str(Path.home()))
            if d:
                self.out_label.setText(d)
                settings().setValue("out_dir", d)
            else:
                self.out_combo.setCurrentIndex(0)
                self.out_label.setText("")
        else:
            self.out_label.setText("")
            settings().setValue("out_dir", "")
        settings().sync()

    # ---------------- output-size targeting ----------------

    def _on_size_slider(self, v: int):
        if self.size_spin.value() != v:
            self.size_spin.blockSignals(True)
            self.size_spin.setValue(v)
            self.size_spin.blockSignals(False)
        settings().setValue("target_mb", v)

    def _on_size_spin(self, v: int):
        if self.size_slider.value() != v:
            self.size_slider.blockSignals(True)
            self.size_slider.setValue(v)
            self.size_slider.blockSignals(False)
        settings().setValue("target_mb", v)

    def _on_size_limit_toggled(self, on: bool):
        settings().setValue("target_on", on)
        self._update_size_controls()

    def _target_mb(self) -> int:
        return self.size_spin.value()

    def _size_limit_on(self) -> bool:
        # Intent only — whether a target applies to a given file is decided per
        # file in _build_job. (Deliberately independent of isEnabled(), since
        # the control is disabled during a run.)
        return self.size_check.isChecked()

    def _queue_kinds(self) -> set[str]:
        kinds = set()
        for i in range(self.queue.topLevelItemCount()):
            k = input_kind(self.queue.topLevelItem(i).data(0, ROLE_PATH))
            if k:
                kinds.add(k)
        return kinds

    @staticmethod
    def _ext_supports_target(ext: str) -> bool:
        """True when an output can be driven to a target size — video
        (two-pass), a lossy audio codec (computed bitrate), or PDF (Ghostscript
        downsampling). Lossless audio, images, GIF and documents can't be
        size-targeted this way."""
        if not ext:
            return False
        kind = FORMATS[ext][1]
        if kind == "video":
            return ext != "gif"
        if kind == "audio":
            return AUDIO_ENCODERS[ext][1]  # uses_bitrate
        return ext == "pdf"

    def _update_size_controls(self):
        """Enable the size row when the chosen output can be size-targeted,
        then refresh the note under the picker that explains the plan (and
        any files that will be skipped or need a missing tool)."""
        out = self._current_ext()
        supported = self._ext_supports_target(out)
        self.size_check.setEnabled(supported)
        active = supported and self.size_check.isChecked()
        for w in (self.size_slider, self.size_spin):
            w.setEnabled(active)
        if not supported:
            self.size_check.setToolTip(
                "This output can't be size-targeted (lossless, image or "
                "document format). Pick PDF, video or lossy audio.")
        else:
            self.size_check.setToolTip(
                "Encode to a target file size instead of a fixed quality.\n"
                "Video uses two passes (slower); PDFs are downsampled with "
                "Ghostscript.")
        self._update_plan_note(active)

    def _update_plan_note(self, size_active: bool):
        out = self._current_ext()
        kinds = self._queue_kinds()
        if not out or not kinds:
            self.pdf_note.hide()
            return
        lines: list[str] = []
        bad = False

        if out == "pdf" and "pdf" in kinds:
            if not self.gs:
                lines.append("PDFs need Ghostscript to be recompressed — not "
                             "found. Set it in Settings.")
                bad = True
            else:
                verb = (f"shrunk toward {self._target_mb()} MB"
                        if size_active else "recompressed with Ghostscript")
                lines.append(f"PDF → PDF: {verb}.")
        elif out == "pdf" and size_active and self.gs:
            lines.append(f"Output PDFs are then shrunk toward "
                         f"{self._target_mb()} MB with Ghostscript.")
        if out in PAGE_IMAGE_OUTS and kinds & {"pdf", "doc", "slides"}:
            preset = self.preset_combo.currentText()
            lines.append(
                f"Every page/slide becomes a separate {out.upper()} at "
                f"{PAGE_IMAGE_DPI.get(preset, 150)} dpi, in a folder named "
                "after the file.")
        if out in ("docx", "odt") and "pdf" in kinds:
            lines.append("PDF → editable text: LibreOffice rebuilds the layout "
                         "from the PDF; text is kept but formatting may shift.")
        if out in ("epub", "mobi", "azw3") and kinds & {"doc", "sheet"}:
            lines.append("Documents are converted to e-books by calibre.")

        # Files that will be skipped or need a tool that isn't installed.
        skipped: list[str] = []
        missing: dict[str, list[str]] = {}
        for it in self._waiting_items():
            problem = self._item_problem(it, out)
            if problem is None:
                continue
            name = Path(it.data(0, ROLE_PATH)).name
            if problem.startswith("Needs "):
                missing.setdefault(problem, []).append(name)
            else:
                skipped.append(f"{name} ({problem})")
        if skipped:
            shown = ", ".join(skipped[:3])
            more = f" and {len(skipped) - 3} more" if len(skipped) > 3 else ""
            lines.append(f"Will be skipped: {shown}{more}.")
        for problem, names in missing.items():
            n = len(names)
            lines.append(f"{n} file{'s' if n != 1 else ''} — {problem}")
            bad = True

        if not lines:
            self.pdf_note.hide()
            return
        self.pdf_note.setObjectName("Bad" if bad else "Hint")
        self.pdf_note.setText("\n".join(lines))
        self._repolish(self.pdf_note)
        self.pdf_note.show()

    def _gather_opts(self) -> dict:
        preset = PRESETS.get(self.preset_combo.currentText(),
                             PRESETS["Balanced"])
        data = self.vcodec_combo.currentData()
        encoder, extra = data if data else ("libx264", [])
        return {
            "vcodec": encoder,
            "vcodec_extra": extra,
            "crf": self.crf_spin.value(),
            "speed": self.speed_combo.currentText(),
            "height": self.res_combo.currentData() or 0,
            "acodec": ("copy" if self.acodec_combo.currentData() == "copy"
                       else CONTAINER_AUDIO.get(self._current_ext(),
                                                ("aac", []))[0]),
            "abr": self.abr_combo.currentData() or 192,
            "jpg_q": preset["jpg_q"],
            "webp_q": preset["webp_q"],
            "gif_h": preset["gif_h"],
            "crf_av1_img": {"High quality": 18, "Balanced": 28,
                            "Small file": 38}.get(
                self.preset_combo.currentText(), 28),
        }

    # ---------------- conversion pipeline ----------------

    def _start_queue(self):
        out = self._current_ext()
        ok_items = self._convertible_waiting()
        if not ok_items:
            # Nothing can run: if a single missing tool is the reason, say so.
            problems = {self._item_problem(it, out) for it in self._waiting_items()}
            problems.discard(None)
            needs = [p for p in problems if p and p.startswith("Needs ")]
            if len(needs) == 1 and len(problems) == 1:
                for key, spec in TOOLS.items():
                    if spec["label"] in needs[0]:
                        self._prompt_tool_missing(
                            key, f"converts these files to {out.upper()}")
                        return
            return
        self.converting = True
        self.btn_convert.hide()
        self.btn_cancel.show()
        for w in (self.format_combo, self.preset_combo, self.adv_panel,
                  self.out_combo, self.btn_add, self.btn_remove,
                  self.btn_clear, self.size_check, self.size_slider,
                  self.size_spin):
            w.setEnabled(False)
        self._start_next()

    def _next_waiting(self) -> QTreeWidgetItem | None:
        for i in range(self.queue.topLevelItemCount()):
            item = self.queue.topLevelItem(i)
            if item.data(0, ROLE_STATUS) == STATUS_WAITING:
                return item
        return None

    def _start_next(self):
        self._cleanup_job()
        item = self._next_waiting()
        if item is None:
            self._finish_queue()
            return
        self.current_item = item
        self.current_duration = 0.0
        self.current_log = []
        self.current_job = {}
        self.current_stages = []
        self.current_stage_idx = 0
        self.current_targeted = False
        self.current_target_bytes = 0

        src = Path(item.data(0, ROLE_PATH))
        out = self._current_ext()

        # Files that can't become the chosen format are skipped, not failed.
        ok, why = can_convert(src, out)
        if not ok:
            self.current_item = None
            item.setData(0, ROLE_STATUS, STATUS_SKIPPED)
            item.setData(0, ROLE_LOG, f"Skipped: {why}.")
            item.setText(2, f"Skipped  ·  {why}")
            item.setToolTip(2, f"Skipped — {why}.")
            self._update_total_progress(0)
            QTimer.singleShot(0, self._start_next)
            return

        out_dir = (Path(self.out_label.text())
                   if self.out_combo.currentData() == "custom"
                   and self.out_label.text() else src.parent)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._item_failed(item, f"Cannot create output folder: {e}")
            QTimer.singleShot(0, self._start_next)
            return

        try:
            job, err = self._build_job(src, out_dir, out)
        except Exception as e:  # a planner bug must never hang the queue
            job, err = None, f"Could not plan this conversion: {e!r}"
        if err or not job:
            self._item_failed(item, err or "Could not plan this conversion.")
            QTimer.singleShot(0, self._start_next)
            return

        self.current_job = job
        self.current_targeted = bool(job.get("targeted"))
        self.current_target_bytes = int(job.get("target_bytes", 0))
        item.setData(0, ROLE_OUTPUT, str(job["dst"]))
        item.setText(2, "Starting…")
        self.current_stages = job["stages"]
        self._run_stage()

    # ---- job planning -----------------------------------------------------

    def _new_job_tmp(self) -> Path:
        if self._job_tmp is None:
            self._job_tmp = tempfile.TemporaryDirectory(prefix="morpho-job-")
        return Path(self._job_tmp.name)

    def _cleanup_job(self):
        self._cleanup_passlog()
        if self._job_tmp is not None:
            try:
                self._job_tmp.cleanup()
            except OSError:
                pass
            self._job_tmp = None

    @staticmethod
    def _stage(program: str, args: list[str], label: str, **extra) -> dict:
        d = {"program": program, "args": args, "label": label,
             "span": (0, 100), "ok": (0,), "duration": 0.0}
        d.update(extra)
        return d

    @staticmethod
    def _func_stage(func, label: str, **extra) -> dict:
        d = {"func": func, "label": label, "span": (0, 100), "ok": (0,),
             "duration": 0.0}
        d.update(extra)
        return d

    @staticmethod
    def _spread(stages: list[dict]) -> list[dict]:
        """Give sequential stages equal slices of the 0–100 progress span."""
        n = len(stages)
        for i, st in enumerate(stages):
            st["span"] = (int(100 * i / n), int(100 * (i + 1) / n))
        return stages

    def _build_job(self, src: Path, out_dir: Path, out: str
                   ) -> tuple[dict | None, str | None]:
        """Plan the stages for one queued file. Returns (job, error).

        job = {"stages": [...], "dst": Path, "finalize": callable | None,
               "targeted": bool, "target_bytes": int, "is_dir": bool}
        `finalize(result)` runs after the last stage succeeds; it may return an
        error string or fill `result` with status/log/tooltip overrides."""
        kind = input_kind(src) or ""
        ext = file_ext(src)
        err = missing_tools(kind, ext, out, self.tools)
        if err:
            return None, err
        stem, _ = split_name(src)
        limit_on = self._size_limit_on()
        target_bytes = self._target_mb() * 1024 * 1024 if limit_on else 0

        if kind in ("video", "audio"):
            return self._media_job(src, out_dir, stem, out, target_bytes)
        if kind == "image":
            if out == "pdf":
                return self._image_to_pdf_job(src, out_dir, stem, ext)
            return self._media_job(src, out_dir, stem, out, 0)
        if kind == "svg":
            return self._svg_job(src, out_dir, stem, out)
        if kind == "subtitle":
            dst = unique_output(out_dir / f"{stem}.{out}")
            args = ["-hide_banner", "-y", "-i", str(src), str(dst)]
            return {"stages": [self._stage(self.ffmpeg, args, "Converting")],
                    "dst": dst}, None
        if kind == "pdf":
            return self._pdf_job(src, out_dir, stem, out, target_bytes)
        if kind in ("doc", "slides", "sheet"):
            return self._office_job(src, out_dir, stem, kind, ext, out,
                                    target_bytes)
        if kind == "ebook":
            return self._ebook_job(src, out_dir, stem, out)
        if kind == "archive":
            return self._archive_job(src, out_dir, stem, out)
        return None, "Unsupported file type."

    def _media_job(self, src: Path, out_dir: Path, stem: str, ext: str,
                   target_bytes: int) -> tuple[dict | None, str | None]:
        """ffmpeg: a single CRF/quality pass or, when size-limited, a computed
        bitrate (two passes for video, one for audio)."""
        kind = FORMATS[ext][1]
        dst = unique_output(out_dir / f"{stem}.{ext}")
        opts = self._gather_opts()

        if target_bytes and self._ext_supports_target(ext):
            duration = probe_duration(self.ffprobe, self.ffmpeg, src)
            if not duration:
                args, err = build_args(src, dst, ext, opts, self.encoders)
                if err:
                    return None, err
                st = self._stage(self.ffmpeg, args, "Converting",
                                 note="size target skipped: unknown duration")
                return {"stages": [st], "dst": dst}, None

            if kind == "video":
                audio_kbit = 0 if opts["acodec"] == "copy" else opts["abr"]
                opts = dict(opts, target_vkbit=target_video_kbit(
                    target_bytes, duration, audio_kbit))
                passlog = self._new_passlog()
                p1, p2, err = build_two_pass_args(src, dst, ext, opts, passlog)
                if err:
                    return None, err
                return {"stages": [
                    self._stage(self.ffmpeg, p1, "Analyzing", span=(0, 50),
                                duration=duration),
                    self._stage(self.ffmpeg, p2, "Encoding", span=(50, 100),
                                duration=duration)],
                    "dst": dst, "targeted": True,
                    "target_bytes": target_bytes}, None

            # audio: one pass at the computed bitrate
            opts = dict(opts, abr=target_audio_kbit(target_bytes, duration))
            args, err = build_args(src, dst, ext, opts, self.encoders)
            if err:
                return None, err
            st = self._stage(self.ffmpeg, args, "Converting", duration=duration)
            return {"stages": [st], "dst": dst, "targeted": True,
                    "target_bytes": target_bytes}, None

        args, err = build_args(src, dst, ext, opts, self.encoders)
        if err:
            return None, err
        return {"stages": [self._stage(self.ffmpeg, args, "Converting")],
                "dst": dst}, None

    def _image_to_pdf_job(self, src: Path, out_dir: Path, stem: str,
                          ext: str) -> tuple[dict | None, str | None]:
        dst = unique_output(out_dir / f"{stem}.pdf")
        tmp = self._new_job_tmp()
        stages: list[dict] = []
        if HAVE_PIL:
            source = src
            if ext in PIL_UNREADABLE and self.ffmpeg:
                # Pillow can't read HEIC/JXL: rasterise to PNG with ffmpeg first.
                source = tmp / f"{stem}.png"
                stages.append(self._stage(
                    self.ffmpeg, ["-hide_banner", "-y", "-i", str(src),
                                  "-frames:v", "1", "-update", "1",
                                  str(source)], "Decoding"))
            stages.append(self._func_stage(
                lambda s=source: MainWindow._image_to_pdf(s, dst), "Writing PDF"))
            return {"stages": self._spread(stages), "dst": dst}, None
        # No Pillow: LibreOffice Draw opens images and exports PDF.
        lo_out = tmp / f"{src.stem}.pdf"
        stages.append(self._soffice_stage(src, "pdf", tmp, "image", ext))
        stages.append(self._func_stage(
            lambda: move_into_place(lo_out, dst), "Saving"))
        return {"stages": self._spread(stages), "dst": dst}, None

    def _svg_job(self, src: Path, out_dir: Path, stem: str, out: str
                 ) -> tuple[dict | None, str | None]:
        """Rasterise with rsvg-convert (or ffmpeg's SVG decoder), then hand
        the PNG to ffmpeg/Pillow for any other target."""
        dst = unique_output(out_dir / f"{stem}.{out}")
        tmp = self._new_job_tmp()
        rsvg = self.tools.get("rsvg-convert")
        height = self.res_combo.currentData() or 0
        stages: list[dict] = []
        if out == "pdf" and rsvg:
            stages.append(self._stage(
                rsvg, build_rsvg_args(src, dst, "pdf", 0), "Rendering"))
            return {"stages": stages, "dst": dst}, None
        png = dst if out == "png" else tmp / f"{stem}.png"
        if rsvg:
            stages.append(self._stage(
                rsvg, build_rsvg_args(src, png, "png", height), "Rendering"))
        else:
            args = ["-hide_banner", "-y", "-i", str(src), "-frames:v", "1",
                    "-update", "1"]
            if height:
                args += ["-vf", f"scale=-2:min({height}\\,ih)"]
            stages.append(self._stage(self.ffmpeg, args + [str(png)],
                                      "Rendering"))
        if out == "png":
            return {"stages": stages, "dst": dst}, None
        if out == "pdf":
            if HAVE_PIL:
                stages.append(self._func_stage(
                    lambda: MainWindow._image_to_pdf(png, dst), "Writing PDF"))
            else:
                lo_out = tmp / f"{stem}.pdf"
                stages.append(self._soffice_stage(png, "pdf", tmp, "image",
                                                  "png"))
                stages.append(self._func_stage(
                    lambda: move_into_place(lo_out, dst), "Saving"))
            return {"stages": self._spread(stages), "dst": dst}, None
        opts = dict(self._gather_opts(), height=0)
        args, err = build_args(png, dst, out, opts, self.encoders)
        if err:
            return None, err
        stages.append(self._stage(self.ffmpeg, args, "Converting"))
        return {"stages": self._spread(stages), "dst": dst}, None

    def _soffice_stage(self, src: Path, out_ext: str, outdir: Path,
                       kind: str, src_ext: str,
                       export_filter: str | None = None) -> dict:
        """One LibreOffice run, validated by soffice_check afterwards."""
        soffice = self.tools["soffice"]
        args = build_soffice_args(soffice_profile_dir(), src, out_ext, outdir,
                                  soffice_infilter(src_ext, kind),
                                  export_filter)
        produced = outdir / f"{src.stem}.{out_ext}"
        expected = LO_DOC_TYPE.get(kind)
        return self._stage(
            soffice, args, "Converting", log_stdout=True,
            check=lambda log, p=produced, e=expected: soffice_check(log, e, p))

    def _pages_stages(self, pdf: Path, dst_dir: Path, stem: str, out: str
                      ) -> list[dict]:
        """PDF → one image per page into dst_dir (created when this runs).
        pdftoppm when present, Qt's PDF module otherwise."""
        preset = self.preset_combo.currentText()
        dpi = PAGE_IMAGE_DPI.get(preset, 150)
        q = PAGE_IMAGE_JPEG_Q.get(preset, 85)
        pdftoppm = self.tools.get("pdftoppm")

        def prepare() -> str | None:
            try:
                dst_dir.mkdir(parents=True, exist_ok=False)
            except OSError as e:
                return f"Cannot create {dst_dir.name}: {e}"
            return None

        if pdftoppm:
            return [self._stage(
                pdftoppm, build_pdftoppm_args(pdf, dst_dir / stem, out, dpi, q),
                "Rendering pages", prepare=prepare, log_stdout=True)]

        def render() -> str | None:
            err = prepare()
            return err or render_pdf_pages_qt(pdf, dst_dir, stem, out, dpi, q)
        return [self._func_stage(render, "Rendering pages")]

    @staticmethod
    def _count_pages_finalize(dst_dir: Path):
        def finalize(result: dict) -> str | None:
            files = sorted(p for p in dst_dir.iterdir() if p.is_file())
            if not files:
                return "No pages were rendered."
            total = sum(p.stat().st_size for p in files)
            n = len(files)
            result["status"] = (f"Done  ·  {n} page{'s' if n != 1 else ''}  ·  "
                                f"{human_size(total)}")
            result["tooltip"] = (f"Saved {n} images to {dst_dir}\n"
                                 "Double-click to open the folder")
            return None
        return finalize

    def _gs_compress_stages(self, src_pdf: Path, dst: Path, target_bytes: int,
                            keep_if_bigger: Path | None
                            ) -> tuple[list[dict], callable]:
        """Ghostscript recompression of src_pdf → dst, plus a finalize that
        refuses to hand back a file no smaller than the input. For a PDF the
        user queued, `keep_if_bigger` is None and the original is simply left
        alone; for a PDF we just produced (doc → PDF with a size limit), it is
        that intermediate, which is moved into place instead."""
        preset_dpi = PDF_PRESET_DPI.get(self.preset_combo.currentText(), 150)

        stage = self._stage(self.gs, [], "Compressing")

        def prepare() -> str | None:
            try:
                cur = src_pdf.stat().st_size
            except OSError:
                cur = 0
            dpi = (dpi_for_pdf_target(cur, target_bytes) if target_bytes
                   else preset_dpi)
            stage["args"] = build_gs_args(src_pdf, dst, dpi)
            return None
        stage["prepare"] = prepare

        def finalize(result: dict) -> str | None:
            try:
                src_size = src_pdf.stat().st_size
                out_size = dst.stat().st_size
            except OSError:
                return None
            if not src_size or out_size < src_size:
                return None
            # Ghostscript inflated it (vector art, or JPEG2000/JBIG2 scans it
            # had to re-encode). Never return something bigger than we had.
            dst.unlink(missing_ok=True)
            if keep_if_bigger is None:
                result["status"] = "Unchanged  ·  couldn't shrink"
                result["output"] = str(src_pdf)
                result["log"] = (
                    "This PDF couldn't be made smaller — its content (vector "
                    "art, or already-compressed image scans) doesn't shrink by "
                    f"downsampling. Left the original unchanged "
                    f"({human_size(src_size)}).")
                result["tooltip"] = (result["log"]
                                     + "\nDouble-click to open its folder.")
                result["skip_target_check"] = True
            else:
                err = move_into_place(keep_if_bigger, dst)
                if err:
                    return err
                result["note"] = "couldn't shrink further"
                result["skip_target_check"] = True
            return None
        return [stage], finalize

    def _pdf_job(self, src: Path, out_dir: Path, stem: str, out: str,
                 target_bytes: int) -> tuple[dict | None, str | None]:
        tmp = self._new_job_tmp()
        if out == "pdf":
            dst = unique_output(out_dir / f"{stem}.pdf")
            stages, fin = self._gs_compress_stages(src, dst, target_bytes, None)
            return {"stages": stages, "dst": dst, "finalize": fin,
                    "targeted": bool(target_bytes),
                    "target_bytes": target_bytes}, None
        if out in PAGE_IMAGE_OUTS:
            dst_dir = unique_dir(out_dir / stem)
            return {"stages": self._pages_stages(src, dst_dir, stem, out),
                    "dst": dst_dir, "is_dir": True,
                    "finalize": self._count_pages_finalize(dst_dir)}, None
        if out == "txt":
            dst = unique_output(out_dir / f"{stem}.txt")
            pdftotext = self.tools.get("pdftotext")
            if pdftotext:
                st = self._stage(pdftotext, build_pdftotext_args(src, dst),
                                 "Extracting text")
                return {"stages": [st], "dst": dst}, None
            lo_out = tmp / f"{src.stem}.txt"
            stages = [self._soffice_stage(src, "txt", tmp, "pdf", "pdf"),
                      self._func_stage(lambda: move_into_place(lo_out, dst),
                                       "Saving")]
            return {"stages": self._spread(stages), "dst": dst}, None
        # docx / odt: LibreOffice's PDF importer, with a layout caveat.
        dst = unique_output(out_dir / f"{stem}.{out}")
        lo_out = tmp / f"{src.stem}.{out}"
        stages = [self._soffice_stage(src, out, tmp, "pdf", "pdf"),
                  self._func_stage(lambda: move_into_place(lo_out, dst),
                                   "Saving", note="layout may have shifted")]
        return {"stages": self._spread(stages), "dst": dst}, None

    def _office_job(self, src: Path, out_dir: Path, stem: str, kind: str,
                    ext: str, out: str, target_bytes: int
                    ) -> tuple[dict | None, str | None]:
        """Documents, slide decks and spreadsheets via LibreOffice."""
        tmp = self._new_job_tmp()

        if out in PAGE_IMAGE_OUTS:
            pdf = tmp / f"{src.stem}.pdf"
            dst_dir = unique_dir(out_dir / stem)
            stages = ([self._soffice_stage(src, "pdf", tmp, kind, ext)]
                      + self._pages_stages(pdf, dst_dir, stem, out))
            return {"stages": self._spread(stages), "dst": dst_dir,
                    "is_dir": True,
                    "finalize": self._count_pages_finalize(dst_dir)}, None

        if out in ("epub", "mobi", "azw3"):
            dst = unique_output(out_dir / f"{stem}.{out}")
            ebook = self.tools["ebook-convert"]
            stages: list[dict] = []
            source = src
            if ext not in CALIBRE_INPUT_EXTS:
                source = tmp / f"{src.stem}.docx"
                stages.append(self._soffice_stage(src, "docx", tmp, kind, ext))
            stages.append(self._stage(
                ebook, build_ebook_convert_args(source, dst), "Building e-book",
                log_stdout=True,
                check=lambda log, d=dst: (None if d.is_file() and d.stat().st_size
                                          else "calibre produced no output.")))
            return {"stages": self._spread(stages), "dst": dst}, None

        dst = unique_output(out_dir / f"{stem}.{out}")
        lo_out = tmp / f"{src.stem}.{out}"
        stages = [self._soffice_stage(src, out, tmp, kind, ext)]
        if out == "pdf" and target_bytes and self.gs:
            gs_stages, fin = self._gs_compress_stages(lo_out, dst, target_bytes,
                                                      keep_if_bigger=lo_out)
            stages += gs_stages
            return {"stages": self._spread(stages), "dst": dst,
                    "finalize": fin, "targeted": True,
                    "target_bytes": target_bytes}, None
        stages.append(self._func_stage(lambda: move_into_place(lo_out, dst),
                                       "Saving"))
        return {"stages": self._spread(stages), "dst": dst}, None

    def _ebook_job(self, src: Path, out_dir: Path, stem: str, out: str
                   ) -> tuple[dict | None, str | None]:
        dst = unique_output(out_dir / f"{stem}.{out}")
        st = self._stage(
            self.tools["ebook-convert"], build_ebook_convert_args(src, dst),
            "Converting e-book", log_stdout=True,
            check=lambda log, d=dst: (None if d.is_file() and d.stat().st_size
                                      else "calibre produced no output."))
        return {"stages": [st], "dst": dst}, None

    def _archive_job(self, src: Path, out_dir: Path, stem: str, out: str
                     ) -> tuple[dict | None, str | None]:
        """Repack: extract everything to a temp folder, then create the new
        archive from its top-level entries (so paths inside are unchanged)."""
        dst = unique_output(out_dir / f"{stem}.{out}")
        tmp = self._new_job_tmp() / "extract"
        tmp.mkdir(parents=True, exist_ok=True)
        bsdtar = self.tools["bsdtar"]
        extract = self._stage(bsdtar, build_archive_extract_args(src, tmp),
                              "Extracting")
        create = self._stage(bsdtar, [], "Packing")

        def prepare() -> str | None:
            entries = sorted(os.listdir(tmp))
            if not entries:
                return "The archive is empty or could not be read."
            create["args"] = build_archive_create_args(dst, tmp, entries)
            return None
        create["prepare"] = prepare
        return {"stages": self._spread([extract, create]), "dst": dst}, None

    # ---- stage runner ------------------------------------------------------

    def _run_stage(self):
        stage = self.current_stages[self.current_stage_idx]
        self._cur_span = stage["span"]
        self.current_duration = stage.get("duration", 0.0) or 0.0
        if self.current_item:
            self.current_item.setText(2, f"{stage.get('label', 'Converting')}…")

        prepare = stage.get("prepare")
        if prepare:
            try:
                err = prepare()
            except Exception as e:
                err = f"{stage.get('label', 'Stage')} failed: {e}"
            if err:
                self.current_log.append(err)
                self._stage_finished(1, None)
                return

        if "func" in stage:
            # Python stage (Pillow, Qt rendering, moving files): run on the
            # next event-loop turn so the status text paints first.
            def run():
                try:
                    err = stage["func"]()
                except Exception as e:
                    err = f"{stage.get('label', 'Stage')} failed: {e}"
                if err:
                    self.current_log.append(err)
                self._stage_finished(0 if not err else 1, None)
            QTimer.singleShot(0, run)
            return

        self.proc = QProcess(self)
        self.proc.setProgram(stage["program"])
        self.proc.setArguments(stage["args"])
        if stage.get("cwd"):
            self.proc.setWorkingDirectory(stage["cwd"])
        self.proc.readyReadStandardOutput.connect(self._read_progress)
        self.proc.readyReadStandardError.connect(self._read_stderr)
        self.proc.finished.connect(self._stage_finished)
        self.proc.errorOccurred.connect(self._proc_error)
        self.proc.start()

    def _new_passlog(self) -> str:
        self._cleanup_passlog()
        self._passlog_dir = tempfile.TemporaryDirectory(prefix="morpho-2pass-")
        return str(Path(self._passlog_dir.name) / "ffpass")

    def _cleanup_passlog(self):
        if self._passlog_dir is not None:
            self._passlog_dir.cleanup()
            self._passlog_dir = None

    def _read_stderr(self):
        if not self.proc:
            return
        text = bytes(self.proc.readAllStandardError()).decode(
            "utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self.current_log.append(line)
        self.current_log = self.current_log[-60:]
        if self.current_duration == 0.0:
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
            if m:
                h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                self.current_duration = h * 3600 + mnt * 60 + s

    def _read_progress(self):
        if not self.proc or not self.current_item:
            return
        text = bytes(self.proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        stage = (self.current_stages[self.current_stage_idx]
                 if self.current_stage_idx < len(self.current_stages) else {})
        if stage.get("log_stdout"):
            # LibreOffice / calibre report on stdout; keep it for the log and
            # for soffice_check.
            for line in text.splitlines():
                if line.strip():
                    self.current_log.append(line)
            self.current_log = self.current_log[-60:]
            return
        for line in text.splitlines():
            if line.startswith("out_time=") and self.current_duration > 0:
                m = re.match(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                if m:
                    t = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                         + float(m.group(3)))
                    frac = max(0.0, min(1.0, t / self.current_duration))
                    lo, hi = self._cur_span
                    pct = int(lo + (hi - lo) * frac)
                    label = stage.get("label", "Converting")
                    self.current_item.setText(2, f"{label}  {pct}%")
                    self._update_total_progress(pct)

    def _update_total_progress(self, current_pct: int):
        total = self.queue.topLevelItemCount()
        if not total:
            return
        done = sum(1 for i in range(total)
                   if self.queue.topLevelItem(i).data(0, ROLE_STATUS)
                   in FINISHED_STATUSES)
        self.progress.setValue(
            int((done * 100 + current_pct) / total))

    def _discard_output(self, out: str | None):
        """Remove a partial output — a file, or a page-image folder this job
        created (never a folder we didn't make)."""
        if not out:
            return
        p = Path(out)
        try:
            if p.is_dir():
                if self.current_job.get("is_dir"):
                    shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    def _stage_finished(self, exit_code: int, _status):
        item = self.current_item
        stage = (self.current_stages[self.current_stage_idx]
                 if self.current_stages
                 and self.current_stage_idx < len(self.current_stages)
                 else None)
        if self.proc is not None:
            # Drain anything still buffered (LibreOffice prints its one status
            # line right before exiting).
            self._read_progress()
            self._read_stderr()
        self.proc = None
        if item is None:
            return

        # Cancelled mid-run: drop any partial output and move on.
        if item.data(0, ROLE_STATUS) == STATUS_CANCELLED:
            self.current_item = None
            self._discard_output(item.data(0, ROLE_OUTPUT))
            self._cleanup_job()
            self._update_total_progress(0)
            QTimer.singleShot(0, self._start_next)
            return

        ok_codes = stage.get("ok", (0,)) if stage else (0,)
        err: str | None = None
        if exit_code not in ok_codes:
            prog = Path(stage["program"]).name if stage and "program" in stage \
                else "converter"
            tail = "\n".join(self.current_log[-12:])
            err = tail or f"{prog} exited with code {exit_code}"
        elif stage and stage.get("check"):
            try:
                err = stage["check"](list(self.current_log))
            except Exception as e:
                err = f"Could not verify the output: {e}"
            if err:
                tail = "\n".join(self.current_log[-6:])
                if tail and tail not in err:
                    err = f"{err}\n\n{tail}"
        if err:
            self.current_item = None
            self._item_failed(item, err)
            self._discard_output(item.data(0, ROLE_OUTPUT))
            self._cleanup_job()
            self._update_total_progress(0)
            QTimer.singleShot(0, self._start_next)
            return

        # Stage succeeded — run the next one if this job has more.
        self.current_stage_idx += 1
        if self.current_stage_idx < len(self.current_stages):
            self._run_stage()
            return

        # Job complete: finalize, then report.
        self.current_item = None
        result: dict = {}
        finalize = self.current_job.get("finalize")
        if finalize:
            try:
                err = finalize(result)
            except Exception as e:
                err = f"Finishing failed: {e}"
            if err:
                self._item_failed(item, err)
                self._discard_output(item.data(0, ROLE_OUTPUT))
                self._cleanup_job()
                self._update_total_progress(0)
                QTimer.singleShot(0, self._start_next)
                return

        item.setData(0, ROLE_STATUS, STATUS_DONE)
        if result.get("output"):
            item.setData(0, ROLE_OUTPUT, result["output"])
        out = item.data(0, ROLE_OUTPUT)
        if result.get("log"):
            item.setData(0, ROLE_LOG, result["log"])

        if result.get("status"):
            item.setText(2, result["status"])
            item.setToolTip(2, result.get("tooltip", ""))
        else:
            try:
                size_bytes = Path(out).stat().st_size
                size = human_size(size_bytes)
            except OSError:
                size_bytes, size = 0, ""
            over = (self.current_targeted and self.current_target_bytes
                    and not result.get("skip_target_check")
                    and size_bytes > self.current_target_bytes)
            notes = [n for n in (
                result.get("note"),
                *(s.get("note") for s in self.current_stages)) if n]
            if over:
                mb = self._target_mb()
                item.setText(2, f"Done  ·  {size}  ·  over {mb} MB")
                item.setData(0, ROLE_LOG,
                             f"Couldn't get under {mb} MB at a usable quality — "
                             f"kept the best result: {size}.")
                item.setToolTip(2, f"Saved to {out}\n{size} — above the "
                                f"{mb} MB target.\nDouble-click to open folder.")
            else:
                extra = f"  ·  {notes[0]}" if notes else ""
                item.setText(2, f"Done  ·  {size}{extra}")
                item.setToolTip(2, f"Saved to {out}\nDouble-click to open folder")
        self._cleanup_job()
        self._update_total_progress(0)
        QTimer.singleShot(0, self._start_next)

    def _proc_error(self, _err):
        # Only act on a genuine start failure (Crashed-on-kill also fires here,
        # but by then _stage_finished has already nulled self.proc).
        if not (self.proc
                and self.proc.state() == QProcess.ProcessState.NotRunning):
            return
        item = self.current_item
        prog = "The converter"
        if self.current_stages and self.current_stage_idx < len(
                self.current_stages):
            prog = Path(self.current_stages[self.current_stage_idx].get(
                "program", prog)).name
        self.proc = None
        self.current_item = None
        if item is not None and item.data(0, ROLE_STATUS) != STATUS_CANCELLED:
            self._item_failed(item, f"{prog} could not be started. "
                              "Check the path in Settings.")
            self._discard_output(item.data(0, ROLE_OUTPUT))
        self._cleanup_job()
        QTimer.singleShot(0, self._start_next)

    def _item_failed(self, item: QTreeWidgetItem, log: str):
        item.setData(0, ROLE_STATUS, STATUS_ERROR)
        item.setData(0, ROLE_LOG, log)
        item.setText(2, "Failed  ·  double-click for details")

    def _cancel(self):
        if self.mode == "merge":
            if self.proc:
                self.proc.kill()
            return
        if self.current_item is not None:
            self.current_item.setData(0, ROLE_STATUS, STATUS_CANCELLED)
            self.current_item.setText(2, STATUS_CANCELLED)
            out = self.current_item.data(0, ROLE_OUTPUT)
            if out:
                # remove the partial output after the process dies
                QTimer.singleShot(500, lambda p=out: self._discard_output(p))
        if self.proc:
            self.proc.kill()
        # Mark everything still waiting as cancelled so the run stops
        for i in range(self.queue.topLevelItemCount()):
            it = self.queue.topLevelItem(i)
            if it.data(0, ROLE_STATUS) == STATUS_WAITING:
                it.setData(0, ROLE_STATUS, STATUS_CANCELLED)
                it.setText(2, STATUS_CANCELLED)

    def _finish_queue(self):
        self.converting = False
        self._cleanup_job()
        self.btn_cancel.hide()
        self.btn_convert.show()
        for w in (self.format_combo, self.preset_combo, self.adv_panel,
                  self.out_combo, self.btn_add, self.btn_remove,
                  self.btn_clear, self.size_check):
            w.setEnabled(True)
        # size_slider/spin enabled state is derived by _update_size_controls
        done = sum(1 for i in range(self.queue.topLevelItemCount())
                   if self.queue.topLevelItem(i).data(0, ROLE_STATUS)
                   in (STATUS_DONE, STATUS_SKIPPED))
        total = self.queue.topLevelItemCount()
        if done == total and total > 0:
            self.progress.setValue(100)
        self._sync_empty_state()

    # ---------------- Combine-PDF pipeline ----------------

    def _browse_merge_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add PDFs or images", str(Path.home()),
            "PDF & images (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tiff "
            "*.tif *.gif);;All files (*)")
        self._add_merge_files([Path(f) for f in files])

    def _merge_accepts(self, path: Path) -> bool:
        ext = path.suffix.lower().lstrip(".")
        return ext == "pdf" or ext in MERGE_IMAGE_EXTS

    def _add_merge_files(self, paths: list[Path]):
        # Flatten folders, keep only PDFs/images, preserving order.
        accepted: list[Path] = []
        skipped = 0

        def collect(ps: list[Path]):
            nonlocal skipped
            for p in ps:
                if p.is_dir():
                    collect(sorted(c for c in p.iterdir() if c.is_file()))
                elif p.is_file():
                    if self._merge_accepts(p):
                        accepted.append(p)
                    else:
                        skipped += 1

        collect(paths)
        if not accepted:
            if skipped:
                QMessageBox.information(
                    self, APP_NAME,
                    "Those files aren't PDFs or images, so they were skipped.")
            return

        failed: list[str] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in accepted:
                ext = p.suffix.lower().lstrip(".")
                if ext == "pdf":
                    count, thumbs = self._render_pdf(p)
                    if count <= 0:
                        failed.append(p.name)
                        continue
                    for page in range(1, count + 1):
                        self._add_page_item(p, page, "pdf", thumbs.get(page))
                    QApplication.processEvents()  # keep UI alive on big PDFs
                else:
                    self._add_page_item(p, 1, "image", self._image_thumb(p))
        finally:
            QApplication.restoreOverrideCursor()

        if failed:
            QMessageBox.warning(
                self, APP_NAME,
                "These files couldn't be read as PDFs and were skipped:\n\n"
                + "\n".join(failed))
        self._renumber_merge()
        self._sync_merge_state()

    def _add_page_item(self, path: Path, page: int, kind: str,
                       pixmap: QPixmap | None):
        item = QListWidgetItem()
        item.setData(ROLE_PATH, str(path))
        item.setData(ROLE_PAGE, page)
        item.setData(ROLE_KIND, kind)
        if pixmap is None or pixmap.isNull():
            pixmap = self._placeholder_pixmap(path.name, page)
        item.setIcon(QIcon(pixmap))
        item.setToolTip(f"{path}\nPage {page}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter
                              | Qt.AlignmentFlag.AlignBottom)
        item.setSizeHint(QSize(GRID_W, GRID_H))
        self.merge_list.addItem(item)

    def _render_pdf(self, path: Path) -> tuple[int, dict[int, QPixmap]]:
        """Return (page_count, {page_1based: QPixmap}). Thumbnails come from
        Qt's QtPdf; without it we still get a page count from qpdf and fall
        back to placeholder tiles."""
        thumbs: dict[int, QPixmap] = {}
        if HAVE_QTPDF:
            doc = QPdfDocument()
            if doc.load(str(path)) != QPdfDocument.Error.None_:
                return 0, {}
            count = doc.pageCount()
            for i in range(count):
                pt = doc.pagePointSize(i)
                if pt.width() > 0 and pt.height() > 0:
                    scale = min(THUMB_W / pt.width(), THUMB_H / pt.height())
                    size = QSize(max(1, round(pt.width() * scale)),
                                 max(1, round(pt.height() * scale)))
                else:
                    size = QSize(THUMB_W, THUMB_H)
                img = doc.render(i, size)
                if not img.isNull():
                    thumbs[i + 1] = QPixmap.fromImage(img)
            doc.close()
            return count, thumbs
        return (qpdf_npages(self.qpdf, path) or 0), {}

    def _image_thumb(self, path: Path) -> QPixmap | None:
        pm = QPixmap(str(path))
        if pm.isNull() and HAVE_PIL:
            try:  # formats Qt can't load (some webp/tiff builds) via Pillow
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGBA")
                    data = im.tobytes("raw", "RGBA")
                    qi = QImage(data, im.width, im.height,
                                QImage.Format.Format_RGBA8888)
                    pm = QPixmap.fromImage(qi.copy())
            except Exception:
                return None
        if pm.isNull():
            return None
        return pm.scaled(THUMB_W, THUMB_H,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)

    def _placeholder_pixmap(self, name: str, page: int) -> QPixmap:
        pm = QPixmap(THUMB_W, THUMB_H)
        pm.fill(QColor("#22252B"))
        painter = QPainter(pm)
        painter.setPen(QColor("#9BA0A8"))
        f = QFont()
        f.setPointSize(9)
        painter.setFont(f)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
                         f"{name}\npage {page}")
        painter.end()
        return pm

    def _renumber_merge(self, *args):
        """Refresh the "N.  name · pP" caption after add or reorder."""
        for i in range(self.merge_list.count()):
            item = self.merge_list.item(i)
            name = Path(item.data(ROLE_PATH)).name
            short = name if len(name) <= 20 else name[:18] + "…"
            page = item.data(ROLE_PAGE)
            item.setText(f"{i + 1}.  {short}  ·  p{page}")

    def _merge_move(self, delta: int):
        if self.merging:
            return
        rows = sorted(self.merge_list.row(i)
                      for i in self.merge_list.selectedItems())
        if not rows:
            return
        # Move in the direction that keeps items in bounds without collisions.
        order = rows if delta < 0 else list(reversed(rows))
        for row in order:
            new_row = row + delta
            if new_row < 0 or new_row >= self.merge_list.count():
                continue
            item = self.merge_list.takeItem(row)
            self.merge_list.insertItem(new_row, item)
            item.setSelected(True)
        self._renumber_merge()

    def _remove_merge_selected(self):
        if self.merging:
            return
        for item in self.merge_list.selectedItems():
            self.merge_list.takeItem(self.merge_list.row(item))
        self._renumber_merge()
        self._sync_merge_state()

    def _clear_merge(self):
        if self.merging:
            return
        self.merge_list.clear()
        self.progress.setValue(0)
        self._sync_merge_state()

    def _sync_merge_state(self):
        if self.mode != "merge":
            return
        count = self.merge_list.count()
        has = count > 0
        self.merge_drop.setVisible(not has)
        self.merge_list.setVisible(has)
        self.merge_btns_widget.setVisible(has)
        self.merge_hint.setVisible(has)
        self.btn_convert.setEnabled(
            count >= 2 and not self.merging and bool(self.qpdf))
        self.btn_convert.setText(
            f"Combine {count} page{'s' if count != 1 else ''}"
            if has else "Combine PDF")

    def _on_merge_out_choice(self, index: int):
        if self.merge_out_combo.itemData(index) == "custom":
            d = QFileDialog.getExistingDirectory(
                self, "Choose output folder",
                self.merge_out_label.text() or str(Path.home()))
            if d:
                self.merge_out_label.setText(d)
                settings().setValue("merge_out_dir", d)
            else:
                self.merge_out_combo.setCurrentIndex(0)
                self.merge_out_label.setText("")
        else:
            self.merge_out_label.setText("")
            settings().setValue("merge_out_dir", "")
        settings().sync()

    def _start_merge(self):
        if not self.qpdf:
            self._prompt_pdf_missing()
            return
        n = self.merge_list.count()
        if n < 2:
            QMessageBox.information(
                self, APP_NAME, "Add at least two pages to combine.")
            return

        # Ordered page entries straight from the grid.
        entries = [(Path(self.merge_list.item(i).data(ROLE_PATH)),
                    int(self.merge_list.item(i).data(ROLE_PAGE)),
                    self.merge_list.item(i).data(ROLE_KIND))
                   for i in range(n)]

        missing = sorted({p for p, _, _ in entries if not p.is_file()})
        if missing:
            QMessageBox.warning(
                self, APP_NAME,
                "These files are no longer available:\n\n"
                + "\n".join(str(p) for p in missing))
            return

        image_paths = {p for p, _, k in entries if k == "image"}
        if image_paths and not HAVE_PIL:
            QMessageBox.warning(
                self, APP_NAME,
                "Combining image pages needs the Pillow library, which isn't "
                "installed.\n\nInstall it with:  pip install Pillow\n(or "
                "sudo pacman -S python-pillow), then try again — or remove "
                "the image pages and combine PDF pages only.")
            return

        # Output path (folder defaults to the first page's source file).
        first = entries[0][0]
        out_dir = (Path(self.merge_out_label.text())
                   if self.merge_out_combo.currentData() == "custom"
                   and self.merge_out_label.text() else first.parent)
        name = Path(self.merge_name.text().strip() or "combined").name
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        name = name or "combined"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME,
                                f"Cannot create output folder:\n{e}")
            return
        dst = unique_output(out_dir / f"{name}.pdf")

        # Each image becomes one temp single-page PDF, shared across any of its
        # pages in the sequence (an image only ever contributes one page).
        self._cleanup_merge_tmp()
        img_map: dict[Path, Path] = {}
        if image_paths:
            self._merge_tmpdir = tempfile.TemporaryDirectory(prefix="morpho-")
            tmp = Path(self._merge_tmpdir.name)
            for idx, p in enumerate(sorted(image_paths)):
                pdf_path = tmp / f"{idx:04d}.pdf"
                err = self._image_to_pdf(p, pdf_path)
                if err:
                    self._cleanup_merge_tmp()
                    QMessageBox.warning(
                        self, APP_NAME,
                        f"Could not read image:\n{p.name}\n\n{err}")
                    return
                img_map[p] = pdf_path

        resolved = [(str(img_map[p]), 1) if k == "image" else (str(p), page)
                    for p, page, k in entries]
        args = build_page_args(resolved, dst)

        self._merge_output = dst
        self._merge_log = []
        self._enter_merge_running()

        self.proc = QProcess(self)
        self.proc.setProgram(self.qpdf)
        self.proc.setArguments(args)
        self.proc.readyReadStandardError.connect(self._read_merge_stderr)
        self.proc.finished.connect(self._merge_finished)
        self.proc.errorOccurred.connect(self._merge_error)
        self.proc.start()

    @staticmethod
    def _image_to_pdf(src: Path, dst: Path) -> str | None:
        """Render one image to a single-page PDF. Returns error text or None."""
        try:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)  # honour camera rotation
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGB")
                elif im.mode not in ("RGB", "L", "CMYK"):
                    im = im.convert("RGB")
                im.save(dst, "PDF", resolution=150.0)
            return None
        except Exception as e:  # Pillow raises many types; report cleanly
            return str(e)

    def _read_merge_stderr(self):
        if not self.proc:
            return
        text = bytes(self.proc.readAllStandardError()).decode(
            "utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self._merge_log.append(line)
        self._merge_log = self._merge_log[-60:]

    def _enter_merge_running(self):
        self.merging = True
        self.progress.setRange(0, 0)  # busy indicator
        self.btn_convert.hide()
        self.btn_cancel.show()
        for w in (self.merge_name, self.merge_out_combo, self.mbtn_add,
                  self.mbtn_up, self.mbtn_down, self.mbtn_remove,
                  self.mbtn_clear, self.merge_list,
                  self.btn_mode_convert, self.btn_mode_merge):
            w.setEnabled(False)

    def _exit_merge_running(self):
        self.merging = False
        self.progress.setRange(0, 100)
        self.btn_cancel.hide()
        self.btn_convert.show()
        for w in (self.merge_name, self.merge_out_combo, self.mbtn_add,
                  self.mbtn_up, self.mbtn_down, self.mbtn_remove,
                  self.mbtn_clear, self.merge_list,
                  self.btn_mode_convert, self.btn_mode_merge):
            w.setEnabled(True)
        self._sync_merge_state()

    def _merge_finished(self, exit_code: int, _status):
        self.proc = None
        dst = self._merge_output
        self._exit_merge_running()
        # qpdf: 0 = ok, 3 = ok with warnings.
        ok = exit_code in (0, 3)
        if ok and dst and dst.is_file():
            self.progress.setValue(100)
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"Combined PDF saved:\n{dst.name}")
            box.setInformativeText(str(dst))
            open_btn = box.addButton("Open folder",
                                     QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(dst.parent)))
        else:
            self.progress.setValue(0)
            if dst:
                Path(dst).unlink(missing_ok=True)
            tail = "\n".join(self._merge_log[-14:])
            QMessageBox.warning(
                self, APP_NAME,
                "Combining failed.\n\n"
                + (tail or f"qpdf exited with code {exit_code}"))
        self._merge_output = None
        self._cleanup_merge_tmp()

    def _merge_error(self, _err):
        if self.proc and self.proc.state() == QProcess.ProcessState.NotRunning:
            self.proc = None
            self._exit_merge_running()
            self.progress.setValue(0)
            if self._merge_output:
                Path(self._merge_output).unlink(missing_ok=True)
                self._merge_output = None
            self._cleanup_merge_tmp()
            QMessageBox.warning(
                self, APP_NAME,
                "qpdf could not be started. Check the path in Settings.")

    def _cleanup_merge_tmp(self):
        if self._merge_tmpdir is not None:
            self._merge_tmpdir.cleanup()
            self._merge_tmpdir = None

    def _prompt_pdf_missing(self):
        self._prompt_tool_missing("qpdf", "combines PDF pages")

    # ---------------- advanced toggle ----------------

    def _toggle_advanced(self, checked: bool):
        self.adv_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.adv_panel.setVisible(checked)

    def closeEvent(self, event):
        if (self.converting or self.merging) and self.proc:
            what = "A conversion" if self.converting else "A PDF combine"
            reply = QMessageBox.question(
                self, APP_NAME,
                f"{what} is running. Stop it and quit?")
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.proc.kill()
        self._cleanup_merge_tmp()
        self._cleanup_job()
        event.accept()


def main():
    QApplication.setApplicationName(APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.resize(760, 620)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
