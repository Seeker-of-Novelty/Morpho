# Morpho

A small, clean, **all-in-one file converter** and PDF combiner GUI. One Python
file, Qt 6 (PySide6), powered by the tools already on your system. Dark,
uncluttered, drag-and-drop. Nothing is bundled.

| Drop in… | …get out |
|---|---|
| **Slides** PPTX / PPT / ODP / Keynote | PDF, PPTX, ODP, one PNG/JPEG per slide |
| **Documents** DOCX / DOC / ODT / RTF / TXT / HTML / Markdown / Pages | PDF, DOCX, ODT, RTF, TXT, HTML, Markdown, one PNG/JPEG per page, EPUB / MOBI / AZW3 |
| **Spreadsheets** XLSX / XLS / ODS / CSV / Numbers | PDF, XLSX, ODS, CSV, HTML |
| **PDF** | Smaller PDF, one PNG/JPEG/TIFF per page, TXT, DOCX / ODT (editable, layout may shift) |
| **Video** MP4 / MKV / WebM / MOV / AVI / … | MP4, MKV, WebM, MOV, GIF, any audio format, a PNG/JPEG frame |
| **Audio** MP3 / M4A / FLAC / WAV / OGG / Opus / … | MP3, M4A, Opus, OGG, FLAC, WAV |
| **Images** PNG / JPEG / WebP / AVIF / HEIC / TIFF / BMP / JXL | PNG, JPEG, WebP, AVIF, BMP, TIFF, PDF |
| **SVG** | PNG, JPEG, WebP, AVIF, BMP, TIFF, PDF |
| **E-books** EPUB / MOBI / AZW3 / FB2 / … | EPUB, MOBI, AZW3, PDF, DOCX, TXT |
| **Subtitles** SRT / VTT / ASS / SSA | SRT, VTT, ASS |
| **Archives** ZIP / 7z / tar.* / RAR | ZIP, 7z, tar.gz, tar.xz, tar.zst |

Two modes, switched with the segmented control at the top:

- **Convert** — the converter. The *Convert to* list adapts to what you've
  queued: drop a PPTX and it offers PDF / PPTX / ODP / PNG / JPEG; drop a mix
  and it offers the union, skipping (never failing) files that can't reach the
  format you picked.
- **Combine PDF** — drop PDFs (and images) and get a grid of every **page** as a
  thumbnail. Drag any page anywhere — pull page 2 out of one PDF and drop it
  between pages of another — then merge into a single PDF. Page-level, like
  Adobe's Combine.

## Run it (CachyOS / Arch)

```
sudo pacman -S --needed pyside6 python-pillow ffmpeg libreoffice-fresh ghostscript qpdf poppler librsvg libarchive calibre
python morpho.py
```

Only install what you'll use — every tool is optional and Morpho degrades
honestly, telling you exactly which tool a given conversion needs:

| Tool | Used for |
|---|---|
| `ffmpeg` (+`ffprobe`) | video, audio, images, subtitles, HEIC/JXL decoding |
| `libreoffice` (`soffice`) | documents, slides, spreadsheets, PDF → DOCX/ODT |
| `ghostscript` (`gs`) | shrinking PDFs |
| `qpdf` | Combine-PDF mode |
| `poppler` (`pdftoppm`, `pdftotext`) | PDF pages → images (Qt's own PDF module is the fallback), PDF → text |
| `librsvg` (`rsvg-convert`) | SVG rendering (ffmpeg is the fallback) |
| `libarchive` (`bsdtar`) | archives |
| `calibre` (`ebook-convert`) | e-books, and documents → e-books |
| `python-pillow` | image → PDF (LibreOffice is the fallback), images in Combine-PDF |

All settings live in `~/.config/morpho/` (including a private LibreOffice
profile so conversions never interfere with a LibreOffice window you have
open). Point Morpho at any specific binary under *⋯ → Settings*.

## Install it properly (app menu entry + `morpho` command)

Per-user, no root, fish-safe (plain POSIX sh, no heredocs):

```
sh install.sh
```

This copies the app to `~/.local/share/morpho/`, creates `~/.local/bin/morpho`
and a desktop entry, and writes a manifest of every file it created.

## Uninstall

Two equivalent paths — both offer full config removal:

- **In the app:** menu (⋯) → *Uninstall Morpho…* → tick "Also delete all
  settings". Removes exactly the files in the install manifest, plus
  `~/.config/morpho/` if ticked.
- **From the shell:** `sh uninstall.sh` (keep settings) or
  `sh uninstall.sh --purge` (remove everything).

If you never ran `install.sh`, there is nothing installed: delete `morpho.py`
and (optionally) `~/.config/morpho/`.

## Using it

1. Drop files anywhere on the window (or click the drop zone / *Add files…*).
   Folders are accepted too — anything convertible inside is picked up.
2. Choose the output format. The list only shows formats your queued files can
   become. The note under it tells you what will happen — e.g. "every slide
   becomes a PNG", "PDF → PDF: recompressed" — and lists any files that will be
   skipped or need a tool you don't have.
3. Pick a quality preset (High / Balanced / Small). For media it sets codec
   quality; for PDF/page images it sets the render DPI (300 / 150 / 96) and
   JPEG quality; for shrinking PDFs it sets the downsample DPI. *Advanced*
   opens codec, CRF, encoder speed, resolution, and audio controls (media only;
   *Resolution* also caps the height when rendering an SVG).
4. Optionally tick **Limit output size** (video, lossy audio, and any PDF
   output — including PDFs made from documents). See below.
5. Choose *Same folder as each file* or a custom output folder.
6. **Convert.** Files run one at a time. Existing files are never overwritten
   — outputs get `-1`, `-2`… suffixes. Per-page images go into a folder named
   after the file (`deck.pptx` → `deck/deck-1.png`, `deck-2.png`, …).
   Double-click a finished item to open its folder; double-click a failed one
   to see the tool's log.

Codec lists are filtered at startup by what **your** ffmpeg build actually
supports (`ffmpeg -encoders`), so you can't pick an encoder you don't have.

### Targeting a file size (and shrinking PDFs)

Tick **Limit output size** and pick a target in MB. Morpho then aims for that
size instead of a fixed quality:

- **Video** is encoded **two-pass** at a bitrate computed from the clip's
  duration (so it takes two encoding passes — slower, but predictable size).
- **Audio** (MP3 / M4A / Opus / OGG) gets a bitrate computed the same way.
- **PDF** output — a queued PDF, or a PDF just made from a document — is
  recompressed with Ghostscript, downsampling embedded images toward the
  target. Even without the size limit on, a queued PDF converted "to PDF" is
  recompressed using the quality preset (High ≈ 288 dpi, Balanced ≈ 150 dpi,
  Small ≈ 96 dpi).

It's **best-effort**: if the result can't get under the target at a usable
quality, Morpho keeps the closest result and marks the item *"over N MB"*
rather than failing or mangling it. If Ghostscript would actually make a PDF
*bigger* (vector art, or scans already stored as JPEG 2000/JBIG2), the
recompressed copy is discarded and the original is left untouched.

### Combining PDFs, page by page

1. Switch to **Combine PDF** at the top.
2. Drop PDFs and/or images (or *Add files…*). Every page of every file becomes a
   thumbnail tile in the grid.
3. **Drag any page** to any position — freely interleave pages from different
   files. Select multiple tiles to move them together. *Move earlier* /
   *Move later* do the same from buttons; *Remove selected* drops pages you
   don't want. Pages combine left-to-right, top-to-bottom.
4. Name the output and pick a folder (defaults to the first page's source
   folder).
5. **Combine.** Existing files are never overwritten — you get `-1`, `-2`…
   suffixes, same as conversion. The result opens on request.

The final PDF is assembled by `qpdf` selecting exactly the pages you arranged.
Image pages are turned into single-page PDFs first (via Pillow, honouring EXIF
rotation)
