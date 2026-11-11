@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0run-gemma4-3060ti.ps1" -ModelPath "D:\HYDRA-BASE\.hydra\gguf\qwen3.5-4b\qwen3.5-4b-Q4_K_M.gguf" %*
exit /b %ERRORLEVEL%
