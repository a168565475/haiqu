@echo off
chcp 65001 >nul
title haiqu ERP Startup

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "E:\workspace\_project\project001_haiqu_ERP_CRM\start_haiqu_erp.ps1"
set "HAIQU_EXIT_CODE=%ERRORLEVEL%"

if not "%HAIQU_EXIT_CODE%"=="0" (
    echo.
    echo haiqu ERP startup failed. See the error above and the project logs folder.
    echo Press any key to close this window...
    pause >nul
)

exit /b %HAIQU_EXIT_CODE%
