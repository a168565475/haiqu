@echo off
chcp 65001 >nul
title haiqu ERP Startup

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_haiqu_erp.ps1"
set "HAIQU_EXIT_CODE=%ERRORLEVEL%"

if not "%HAIQU_EXIT_CODE%"=="0" pause

exit /b %HAIQU_EXIT_CODE%
