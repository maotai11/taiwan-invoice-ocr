@echo off
:: ============================================================
:: Taiwan Invoice OCR - Full Portable Build Script
::
:: What this does:
::   1. Build ocr_pipeline.exe (PyInstaller, no Python required)
::   2. Build Tauri release exe (cargo tauri build)
::   3. Assemble portable folder: dist_portable\
::   4. Zip to TaiwanInvoiceOCR_portable.zip
::
:: Requirements on THIS machine:
::   - Python 3.x  (pip, paddleocr, llama-cpp-python installed)
::   - Node.js + npm
::   - Rust + cargo
::   - cargo-tauri  (npm install -g @tauri-apps/cli)
::
:: The output ZIP can be transferred to any offline Windows PC.
:: ============================================================

setlocal enabledelayedexpansion
set PROJECT_ROOT=%~dp0
set PORTABLE_DIR=%PROJECT_ROOT%dist_portable
set ZIP_PATH=%PROJECT_ROOT%TaiwanInvoiceOCR_portable.zip
set TAURI_EXE=%PROJECT_ROOT%src-tauri\target\release\taiwan-invoice-ocr.exe

echo =====================================================
echo  Taiwan Invoice OCR - Portable Build
echo =====================================================
echo.

:: ----------------------------------------------------------
:: Step 1: PyInstaller - build ocr_pipeline.exe
:: ----------------------------------------------------------
echo [1/4] Building OCR engine (PyInstaller)...
call "%PROJECT_ROOT%scripts\build_ocr_exe.bat" nopause
if errorlevel 1 (
    echo ERROR: OCR engine build failed.
    goto :error
)
if not exist "%PROJECT_ROOT%ocr_pipeline\ocr_pipeline.exe" (
    echo ERROR: ocr_pipeline\ocr_pipeline.exe not found after build.
    goto :error
)
echo       OK - ocr_pipeline\ocr_pipeline.exe ready.
echo.

:: ----------------------------------------------------------
:: Step 2: Tauri - build release exe
:: ----------------------------------------------------------
echo [2/4] Building Tauri release app (npm run tauri build)...
cd /d "%PROJECT_ROOT%"
call npm run tauri build
if errorlevel 1 (
    echo ERROR: Tauri build failed.
    goto :error
)
if not exist "%TAURI_EXE%" (
    echo ERROR: Tauri release exe not found at:
    echo   %TAURI_EXE%
    goto :error
)
echo       OK - Tauri exe ready.
echo.

:: ----------------------------------------------------------
:: Step 3: Assemble portable folder
:: ----------------------------------------------------------
echo [3/4] Assembling portable folder at dist_portable\ ...

if exist "%PORTABLE_DIR%" rmdir /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%"

:: Main app exe
copy "%TAURI_EXE%" "%PORTABLE_DIR%\TaiwanInvoiceOCR.exe" >nul

:: OCR engine (PyInstaller bundle - entire directory)
echo       Copying ocr_pipeline\ ...
xcopy "%PROJECT_ROOT%ocr_pipeline" "%PORTABLE_DIR%\ocr_pipeline\" /E /I /Q /Y

:: Config files
echo       Copying config\ ...
xcopy "%PROJECT_ROOT%config" "%PORTABLE_DIR%\config\" /E /I /Q /Y

:: PaddleOCR models
echo       Copying ocr_models\ ...
xcopy "%PROJECT_ROOT%ocr_models" "%PORTABLE_DIR%\ocr_models\" /E /I /Q /Y

:: User data directory (templates, memory) - create empty if not yet seeded
if exist "%PROJECT_ROOT%data" (
    echo       Copying data\ ...
    xcopy "%PROJECT_ROOT%data" "%PORTABLE_DIR%\data\" /E /I /Q /Y
) else (
    mkdir "%PORTABLE_DIR%\data"
)

:: Qwen models (optional - large, ~1.5 GB)
if exist "%PROJECT_ROOT%models\qwen25vl3b" (
    echo       Copying models\qwen25vl3b\ (large - may take a while^) ...
    xcopy "%PROJECT_ROOT%models\qwen25vl3b" "%PORTABLE_DIR%\models\qwen25vl3b\" /E /I /Q /Y
) else (
    echo       (models\qwen25vl3b not found - Qwen disabled on target)
)

echo       Portable folder assembled.
echo.

:: ----------------------------------------------------------
:: Step 4: Create ZIP
:: ----------------------------------------------------------
echo [4/4] Creating ZIP archive...
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -Command "Compress-Archive -Path '%PORTABLE_DIR%\*' -DestinationPath '%ZIP_PATH%' -CompressionLevel Optimal"
if errorlevel 1 (
    echo WARNING: ZIP creation failed. Folder still available at dist_portable\
) else (
    echo       ZIP ready: TaiwanInvoiceOCR_portable.zip
)

echo.
echo =====================================================
echo  BUILD COMPLETE
echo =====================================================
echo.
echo  Portable folder : %PORTABLE_DIR%\
echo  ZIP archive     : %ZIP_PATH%
echo.
echo  Transfer the ZIP (or folder) to the target machine,
echo  extract, and run TaiwanInvoiceOCR.exe - done.
echo  No Python / Node / Rust required on target.
echo =====================================================
echo.
pause
exit /b 0

:error
echo.
echo =====================================================
echo  BUILD FAILED - see errors above
echo =====================================================
pause
exit /b 1
