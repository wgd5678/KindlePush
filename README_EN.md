# Kindle Push Assistant

[中文](README.md) | English

Windows desktop app that sends local PDF / EPUB / DOCX / TXT / RTF documents to your personal Kindle.
Supports converting PDF to EPUB locally (with built-in offline OCR for scanned books) before API push,
or using Amazon's email-based cloud conversion (→ KFX). Also supports local backup download before conversion.

## Features

- **File management**: add via button or drag-and-drop, list view (name/size/format/status), remove and clear
- **Three push methods**:
  - **Email push**: subject switches with the "Convert to Kindle reading format" toggle (`Convert` / filename); suitable for files < 50MB
  - **API push**: official Amazon Send to Kindle channel (stkclient / OAuth2), no 50MB limit
  - **USB transfer**: auto-detects Kindle drive letter, copies to the `documents` folder (no conversion)
- **Kindle reading format conversion (no email needed)**: when enabled, API push converts PDF to EPUB locally first — text-based PDFs are extracted directly (chapters split by bookmarks), scanned PDFs go through the built-in offline Chinese OCR (RapidOCR) page by page; the result is pushed via API and Amazon's cloud converts it to reflowable Kindle format. Email push still uses Amazon cloud conversion (subject `Convert`)
- **AZW3/AZW/MOBI/PRC support**: Amazon no longer accepts these formats, so API push always converts them to EPUB locally first (based on KindleUnpack, preserving TOC and styles — pure format conversion, no OCR needed); USB copies them as-is and they are readable directly; the email channel rejects them with a hint
- **Local download**: save a single file (right-click) or batch download selected files
- **Configuration**: JSON storage; email password encrypted with Fernet; SMTP connection test
- **Logs & history**: daily rotating logs, auto cleanup, one-click export; push history shows the latest 5 entries
- **Packaging**: PyInstaller single-file exe, portable, no installation required

## Quick Start (Development)

Requires Windows + Python 3.10+.

```bat
cd KindlePush
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Usage

### Email Push

1. Open "Settings → Email Push Config", fill in the sender email, SMTP server/port, password or app-specific token, and your Kindle email (SMTP settings for common providers are auto-filled).
2. Click "Test Connection", then save.
3. **Important**: first add your sender email to Amazon's "Manage Your Content and Devices → Preferences → Personal Document Settings → Approved Personal Document E-mail List", otherwise emails will be rejected.
4. Add files, choose "Email Push", click "Start Push".

### PDF Conversion to Kindle Reading Format

The **Convert to Kindle reading format** checkbox in "Push Options" (enabled by default) controls format conversion:

- **API push (no email needed)**: PDF is converted to EPUB locally first, then pushed via API as usual — Amazon's cloud converts the EPUB to reflowable Kindle format (adjustable fonts, screen-fitting). Text-based PDFs are extracted with pypdfium2 and split into chapters by bookmarks; scanned PDFs automatically go through the built-in RapidOCR page by page (~1–3 seconds per page). Converted files are stored in the app's temp folder and cleaned up after successful push if "auto-delete temp files" is enabled.
- **AZW3/AZW/MOBI/PRC (Kindle native formats)**: Amazon Send-to-Kindle (both email and API) no longer accepts these formats, so API push always converts them to EPUB locally first (based on KindleUnpack, preserving the book's TOC and styles — pure format conversion, no OCR). This happens regardless of the checkbox above. USB copies them as-is and they are readable directly; the email channel rejects them with a hint. DRM-protected purchased books cannot be converted and will raise an error.
- **Email push**: subject is `Convert`, using Amazon cloud conversion (email config required).
- **Unchecked**: files are pushed as-is; PDF keeps its original layout on Kindle; USB transfer never converts.
- **Fallback**: if local conversion fails, the original file is pushed instead and the history notes it — push never fails because of conversion.

### API Push

1. Click "Settings → API Push Config → Re-authorize" and sign in to your Amazon account in the browser as prompted.
2. After authorization, copy the full redirect URL from the browser address bar and paste it back into the dialog.
3. Choose a target device and push. The authorization persists — no repeated login needed.

### USB Transfer

1. Connect the Kindle with a data cable (the device enters disk mode).
2. Choose "USB Transfer"; the app auto-detects the drive letter (volumes labeled "Kindle" are preferred). Click "Refresh" if needed.
3. Files are copied to the Kindle's `documents` folder; safely eject and start reading.

## Packaging

```bat
.venv\Scripts\python build\make_icon.py
.venv\Scripts\pyinstaller build\kindle_push.spec --noconfirm
```

Output: `dist\KindlePushAssistant.exe` (single file, ready to distribute).

## Project Layout

```
KindlePush/
├── main.py                 # Entry point
├── app.py                  # Main application class / app context
├── requirements.txt
├── ui/                     # UI modules (main window / settings / auth / log + QSS)
├── core/                   # Core logic (file manager / push engine / email / API / USB / history)
├── models/                 # Data models (FileTask / config)
├── utils/                  # Logging / crypto / helpers
├── resources/              # Icon assets
├── build/                  # PyInstaller spec and icon generation script
├── logs/  temp/            # Created at runtime
└── config.json             # Auto-generated on first run (passwords stored encrypted)
```

## FAQ

- **Email push rejected**: the sender email is not on Amazon's approved list, or the subject is not `Convert` (the app sets it automatically when conversion is enabled).
- **Email push says file too large**: attachment exceeds the 50MB limit — use API push instead.
- **API authorization failed**: make sure you paste the complete redirect URL from the address bar after authorization completes.
- **Kindle not detected**: confirm the cable supports data transfer (some charging-only cables don't) and the device is mounted as a disk.
- **Scanned PDF conversion is slow**: local conversion runs OCR page by page (~1–3 s per page); a several-hundred-page book takes a few to a dozen minutes — this is normal.
- **Dependencies**: `pip install stkclient` works directly (`import stkclient`); local conversion depends on `pypdfium2` and `rapidocr-onnxruntime` (see requirements.txt; onnxruntime must stay on the 1.20 series).
