@echo off
setlocal
chcp 65001 >nul
set "SCRIPT=C:\Users\jaell\Desktop\wisperSolution\ScribeFloat\Instalar_ScribeFloat_Python.ps1"
set "LOG=%USERPROFILE%\Desktop\ScribeFloat_instalacion.log"
echo Instalando ScribeFloat... > "%LOG%"
echo Script: %SCRIPT% >> "%LOG%"
echo. >> "%LOG%"
if not exist "%SCRIPT%" (
    echo ERROR: No se encontro el script de instalacion: "%SCRIPT%"
    echo ERROR: No se encontro el script de instalacion: "%SCRIPT%" >> "%LOG%"
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" >> "%LOG%" 2>&1
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
