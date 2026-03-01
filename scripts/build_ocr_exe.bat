@echo off
:: ============================================================
:: Build OCR Engine as standalone EXE (no Python needed)
:: Output: <project_root>\ocr_pipeline\ocr_pipeline.exe
::
:: Usage:
::   build_ocr_exe.bat          - interactive (pauses on exit)
::   build_ocr_exe.bat nopause  - called from create_portable.bat
:: ============================================================

cd /d "%~dp0"
set PROJECT_ROOT=%~dp0..
set NOPAUSE=%1

echo [1/3] Checking PyInstaller...
python -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip failed. Make sure Python 3.x is in PATH.
    goto :error
)

echo [2/3] Building OCR engine - this may take 5-15 minutes...
python -m PyInstaller ^
    --onedir ^
    --name ocr_pipeline ^
    --distpath "%PROJECT_ROOT%\ocr_pipeline_dist" ^
    --workpath "%PROJECT_ROOT%\ocr_pipeline_build_tmp" ^
    --noconfirm ^
    --collect-all paddleocr ^
    --collect-all paddle ^
    --collect-submodules paddle ^
    --collect-all llama_cpp ^
    --hidden-import llama_cpp.llama ^
    --hidden-import llama_cpp.llama_chat_format ^
    --hidden-import llama_cpp.llama_types ^
    --hidden-import invoice_classifier ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageOps ^
    --hidden-import numpy ^
    --hidden-import cv2 ^
    --paths "%~dp0" ^
    ocr_pipeline.py

if errorlevel 1 (
    echo ERROR: PyInstaller failed. See output above.
    goto :error
)

:: Replace previous build
echo [3/3] Installing to ocr_pipeline\...
if exist "%PROJECT_ROOT%\ocr_pipeline" rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline"
move "%PROJECT_ROOT%\ocr_pipeline_dist\ocr_pipeline" "%PROJECT_ROOT%\ocr_pipeline"
rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline_dist"  2>nul
rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline_build_tmp" 2>nul

if not exist "%PROJECT_ROOT%\ocr_pipeline\ocr_pipeline.exe" (
    echo ERROR: Expected EXE not found after move.
    goto :error
)

echo.
echo SUCCESS - OCR engine ready:
echo   %PROJECT_ROOT%\ocr_pipeline\ocr_pipeline.exe
echo.
echo Next: run create_portable.bat to package the full app.
if /i "%NOPAUSE%" neq "nopause" pause
exit /b 0

:error
if /i "%NOPAUSE%" neq "nopause" pause
exit /b 1
