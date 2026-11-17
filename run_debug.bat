@echo off
setlocal
cd /d "%~dp0"
rem 带控制台启动，出错时可以直接看到 Python 的报错信息
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
if not defined PY if exist "C:\Python39\python.exe" set "PY=C:\Python39\python.exe"
if not defined PY set "PY=python"
echo 使用解释器：%PY%
"%PY%" main.pyw
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul