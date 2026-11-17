@echo off
setlocal
cd /d "%~dp0"

rem ---- 找一个装了 quickfix 的 Python（优先 3.9，其次 PATH 里的 python） ----
set "PYW="
set "PYEXE="

if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python39\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python39\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python39\pythonw.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"

if not defined PYW if exist "C:\Python39\pythonw.exe" set "PYW=C:\Python39\pythonw.exe"
if not defined PYW if exist "C:\Python39\pythonw.exe" set "PYEXE=C:\Python39\python.exe"

if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not defined PYW (
    where pythonw.exe >nul 2>nul
    if not errorlevel 1 set "PYW=pythonw"
)
if not defined PYEXE (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYW (
    echo.
    echo 没有找到 pythonw.exe，请先安装 Python 3.8 及以上版本。
    echo.
    pause
    exit /b 1
)

rem ---- 检查依赖 ----
if defined PYEXE (
    "%PYEXE%" -c "import quickfix" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo 当前 Python 缺少 QuickFIX 依赖：
        echo     %PYEXE%
        echo.
        echo 请执行下面这条命令安装：
        echo     "%PYEXE%" -m pip install quickfix
        echo.
        pause
        exit /b 1
    )
)

start "" "%PYW%" "main.pyw"
exit /b 0