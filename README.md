# Taiwan Invoice OCR

Offline desktop OCR app for Taiwan invoices. This release is packaged for **direct use on offline Windows PCs** with **no Python / Node.js / Rust pre-install required**.

## Download And Run (No Prerequisites)

Use one of the release assets:

1. `Taiwan Invoice OCR_0.2.0_x64-setup.exe`
2. `TaiwanInvoiceOCR_portable_20260302_fix.zip`

### Option A: Setup EXE (recommended)

1. Download `Taiwan Invoice OCR_0.2.0_x64-setup.exe`
2. Run installer
3. Launch `Taiwan Invoice OCR`

### Option B: Portable ZIP

1. Download `TaiwanInvoiceOCR_portable_20260302_fix.zip`
2. Extract to any folder
3. Run `TaiwanInvoiceOCR.exe`

## What Is Fixed In This Build

- Fixed: uploading PDF may fail to show preview image
- Fixed: uploading PDF may fail OCR recognition directly
- Fixed: local image path rendering in Tauri app (`convertFileSrc`)
- Fixed: offline OCR pipeline can handle PDF input by rendering first page to PNG before OCR
- Fixed: packaged resources lookup for installer/portable runtime paths

## Supported Input

- PDF
- JPG / JPEG
- PNG
- WEBP
- TIFF / TIF
- HEIC

## Output

- Table view for manual review/edit
- Excel export (`.xlsx`)

## Offline Runtime Contents

Both setup and portable packages include required runtime assets:

- Tauri desktop app executable
- OCR engine executable (`ocr_pipeline.exe`)
- PaddleOCR model folders (`ocr_models/det`, `ocr_models/rec`, `ocr_models/cls`)
- App config (`config/ocr_config.json`, `config/keyword_weights.json`)

## Qwen Model (Optional)

Qwen multimodal model is optional. If model files are not present, app still runs with PaddleOCR pipeline.

## Build Notes (for maintainers)

- Frontend build: `npm run build`
- Desktop build: `npm run tauri build`
- OCR engine packaging: `scripts/build_ocr_exe.bat`
- Portable assembly script: `create_portable.bat`

## Repository

- GitHub: https://github.com/maotai11/taiwan-invoice-ocr
- Latest release: https://github.com/maotai11/taiwan-invoice-ocr/releases/latest
