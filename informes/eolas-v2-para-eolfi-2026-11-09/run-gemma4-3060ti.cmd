@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0run-gemma4-3060ti.ps1" %*
exit /b %ERRORLEVEL%
