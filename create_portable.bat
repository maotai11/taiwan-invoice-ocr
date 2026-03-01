@echo off
:: ============================================================
:: Step 2 of 2: Package everything into a portable folder
::
:: Prerequisites:
::   1. scripts\build_ocr_exe.bat was already run
::   2. npm run tauri -- build was already run (or use existing EXE)
::
:: Output: portable\Taiwan-Invoice-OCR\
::   taiwan-invoice-ocr.exe   <- Tauri app
::   ocr_pipeline\            <- bundled Python + paddleocr + llama_cpp
::   config\                  <- ocr_config.json
::   ocr_models\              <- PaddleOCR local models (det/rec/cls)
::   models\                  <- Qwen GGUF (copy manually if large)
:: ============================================================

set ROOT=%~dp0
set OUT=%ROOT%portable\Taiwan-Invoice-OCR
set TAURI_EXE=%ROOT%src-tauri\target\release\taiwan-invoice-ocr.exe

echo Creating portable package at: %OUT%
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

:: --- Tauri app EXE ---
if exist "%TAURI_EXE%" (
    copy "%TAURI_EXE%" "%OUT%\taiwan-invoice-ocr.exe" >nul
    echo [OK] App EXE copied
) else (
    echo [WARN] Tauri EXE not found at: %TAURI_EXE%
    echo        Run: PATH=%%PATH%%;%%USERPROFILE%%\.cargo\bin && npm run tauri -- build
)

:: --- OCR engine (PyInstaller output) ---
if exist "%ROOT%ocr_pipeline" (
    xcopy /e /q /y "%ROOT%ocr_pipeline\*" "%OUT%\ocr_pipeline\" >nul
    echo [OK] OCR engine copied
) else (
    echo [WARN] ocr_pipeline\ not found. Run scripts\build_ocr_exe.bat first.
)

:: --- Config ---
xcopy /e /q /y "%ROOT%config\*" "%OUT%\config\" >nul
echo [OK] Config copied

:: --- OCR models (PaddleOCR) ---
if exist "%ROOT%ocr_models" (
    xcopy /e /q /y "%ROOT%ocr_models\*" "%OUT%\ocr_models\" >nul
    echo [OK] OCR models copied
) else (
    echo [WARN] ocr_models\ not found. Copy det/rec/cls folders manually.
)

:: --- Qwen models (large, copy if present) ---
if exist "%ROOT%models" (
    xcopy /e /q /y "%ROOT%models\*" "%OUT%\models\" >nul
    echo [OK] Qwen models copied
) else (
    echo [WARN] models\ not found. Copy models\qwen25vl3b\ manually to: %OUT%\models\
)

echo.
echo ============================================================
echo Portable package ready: %OUT%
echo.
echo To deploy on offline Computer B:
echo   1. Copy the entire Taiwan-Invoice-OCR\ folder to Computer B
echo   2. Double-click taiwan-invoice-ocr.exe
echo   (No Python, no installation needed)
echo ============================================================
pause
