@echo off
setlocal
set "FDONPOSE_ROOT=%~dp0.."
set "CONDA_PREFIX=%FDONPOSE_ROOT%\.runtime\foundationpose"
set "FDONPOSE_TMP=%FDONPOSE_ROOT%\.cache\user-build-tmp"
if not exist "C:\BuildTools\Fdonpose\Common7\Tools\VsDevCmd.bat" (
  echo Missing approved VS 2022 toolchain. 1>&2
  exit /b 2
)
call "C:\BuildTools\Fdonpose\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 -vcvars_ver=14.38
if errorlevel 1 exit /b 2
if not exist "%CONDA_PREFIX%\python.exe" (
  echo Missing project Python environment. 1>&2
  exit /b 2
)
set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\Scripts;%CONDA_PREFIX%\Library\bin;%PATH%"
set "DISTUTILS_USE_SDK=1"
set "MSSdk=1"
set "MAX_JOBS=4"
set "TORCH_CUDA_ARCH_LIST=12.0"
set "PIP_CACHE_DIR=%FDONPOSE_ROOT%\.cache\pip"
set "TORCH_EXTENSIONS_DIR=%FDONPOSE_ROOT%\.cache\torch_extensions"
set "SAM2_BUILD_CUDA=0"
set "CUDA_HOME=%CONDA_PREFIX%\Library"
set "CUDA_PATH=%CUDA_HOME%"
set "CUB_HOME=%CUDA_HOME%\include"
set "TEMP=%FDONPOSE_TMP%"
set "TMP=%FDONPOSE_TMP%"
set "TMPDIR=%FDONPOSE_TMP%"
set "PIP_BUILD_TRACKER=%FDONPOSE_TMP%\tracker"
set "MPLCONFIGDIR=%FDONPOSE_ROOT%\.cache\matplotlib"
set "KMP_DUPLICATE_LIB_OK=TRUE"
set "WARP_CACHE_DIR=%FDONPOSE_ROOT%\.cache\warp"
set "FDONPOSE_WARP_FALLBACK=1"
if not exist "%FDONPOSE_TMP%" mkdir "%FDONPOSE_TMP%"
if not exist "%PIP_BUILD_TRACKER%" mkdir "%PIP_BUILD_TRACKER%"
if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"
if not exist "%WARP_CACHE_DIR%" mkdir "%WARP_CACHE_DIR%"
set "NVCC_PREPEND_FLAGS=-I%CUDA_HOME%\include\targets\x64"
set "CPATH=%CUDA_HOME%\include\targets\x64;%CPATH%"
set "CPLUS_INCLUDE_PATH=%CUDA_HOME%\include\targets\x64;%CPLUS_INCLUDE_PATH%"
set "LIB=%CUDA_HOME%\lib;%LIB%"
set "VSLANG=1033"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
%*
exit /b %ERRORLEVEL%
