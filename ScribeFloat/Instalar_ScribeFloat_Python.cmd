@echo off
setlocal
chcp 65001 >nul
set "LOG=%USERPROFILE%\Desktop\ScribeFloat_instalacion.log"
echo Instalando ScribeFloat... > "%LOG%"
echo Carpeta del instalador: %~dp0 >> "%LOG%"
echo. >> "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalar_ScribeFloat_Python.ps1" >> "%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"
type "%LOG%"
echo.
if not "%INSTALL_EXIT%"=="0" (
    echo ERROR: No se pudo instalar ScribeFloat.
    echo Revise el log: "%LOG%"
    pause
    exit /b %INSTALL_EXIT%
)
echo OK: ScribeFloat quedo instalado.
echo Acceso directo: "%USERPROFILE%\Desktop\ScribeFloat.lnk"
echo Log: "%LOG%"
pause
