@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0run-gemma4-3060ti.ps1" -ModelPath "D:\AI\image-models\z-image-turbo\Qwen3-4B-Instruct-2507-Q4_K_M.gguf" %*
exit /b %ERRORLEVEL%
