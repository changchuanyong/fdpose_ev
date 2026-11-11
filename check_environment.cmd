@echo off
setlocal
pushd "%~dp0"
if exist "%~dp0.runtime\foundationpose\python.exe" (
  "%~dp0.runtime\foundationpose\python.exe" scripts\check_windows.py %*
) else (
  python scripts\check_windows.py %*
)
set "FDONPOSE_EXIT=%ERRORLEVEL%"
popd
exit /b %FDONPOSE_EXIT%
