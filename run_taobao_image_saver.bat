@echo off
setlocal
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m taobao_image_saver
) else (
  python -m taobao_image_saver
)
