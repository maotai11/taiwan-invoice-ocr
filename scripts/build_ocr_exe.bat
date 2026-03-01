@echo off
:: ============================================================
:: Step 1 of 2: Build OCR Engine (standalone, no Python needed)
:: Output: <project_root>\ocr_pipeline\ocr_pipeline.exe
::
:: After this, run create_portable.bat (or npm run tauri -- build)
:: ============================================================

cd /d "%~dp0"
set PROJECT_ROOT=%~dp0..

echo [1/3] Checking PyInstaller...
python -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip failed. Make sure Python 3.x is installed and in PATH.
    pause & exit /b 1
)

echo [2/3] Building OCR engine - this takes 5-10 minutes...
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
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageOps ^
    --hidden-import numpy ^
    --hidden-import cv2 ^
    ocr_pipeline.py

if errorlevel 1 (
    echo ERROR: PyInstaller failed. See above for details.
    pause & exit /b 1
)

:: Move output to project_root\ocr_pipeline\
if exist "%PROJECT_ROOT%\ocr_pipeline" (
    rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline"
)
move "%PROJECT_ROOT%\ocr_pipeline_dist\ocr_pipeline" "%PROJECT_ROOT%\ocr_pipeline"
rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline_dist" 2>nul
rmdir /s /q "%PROJECT_ROOT%\ocr_pipeline_build_tmp" 2>nul

echo [3/3] Verifying output...
if exist "%PROJECT_ROOT%\ocr_pipeline\ocr_pipeline.exe" (
    echo.
    echo SUCCESS! OCR engine ready at:
    echo   %PROJECT_ROOT%\ocr_pipeline\ocr_pipeline.exe
    echo.
    echo Next: run create_portable.bat to package everything for offline use.
) else (
    echo ERROR: Expected EXE not found.
    pause & exit /b 1
)
pause
