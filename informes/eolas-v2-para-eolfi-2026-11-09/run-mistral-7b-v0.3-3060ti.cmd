@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0run-gemma4-3060ti.ps1" -ModelPath "D:\AI\Hydra\gguf\Mistral-7B-Instruct-v0.3-Q4_K_M.gguf" %*
exit /b %ERRORLEVEL%
