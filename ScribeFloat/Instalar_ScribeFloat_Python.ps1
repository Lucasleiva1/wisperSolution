param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\ScribeFloat"
)

$ErrorActionPreference = "Stop"

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $InstallRoot "app"
$VenvDir = Join-Path $InstallRoot "venv"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ScribeFloat"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "ScribeFloat.lnk"
$StartMenuShortcut = Join-Path $StartMenuDir "ScribeFloat.lnk"
$LauncherCmd = Join-Path $InstallRoot "Abrir_ScribeFloat.cmd"

function Test-PythonExe($Path) {
    try {
        & $Path --version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-PythonLauncher {
    $expectedPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-PythonExe $expectedPython) {
        return $expectedPython
    }

    foreach ($candidate in @("python", "py")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            if (Test-PythonExe $candidate) {
                return $candidate
            }
        }
    }

    throw "No se encontro Python 3.11 funcional. Instala Python 3.11 y vuelve a ejecutar este instalador."
}

function Copy-AppFiles {
    New-Item -ItemType Directory -Force -Path $InstallRoot, $AppDir | Out-Null

    foreach ($folder in @("src", "assets")) {
        $from = Join-Path $SourceRoot $folder
        $to = Join-Path $AppDir $folder
        if (Test-Path $to) {
            Remove-Item -LiteralPath $to -Recurse -Force
        }
        Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
    }

    foreach ($file in @("requirements.txt", "config.json")) {
        $from = Join-Path $SourceRoot $file
        if (Test-Path $from) {
            Copy-Item -LiteralPath $from -Destination (Join-Path $AppDir $file) -Force
        }
    }
}

function Remove-OldCompiledInstall {
    $oldFolders = @(
        "av", "av.libs", "certifi", "ctranslate2", "customtkinter", "faster_whisper",
        "hf_xet", "markupsafe", "numpy", "numpy.libs", "onnxruntime", "PIL", "pygame",
        "tcl", "tcl8", "tk", "tokenizers", "torch", "yaml", "_sounddevice_data"
    )

    $oldFiles = @(
        "main.exe", "unins000.dat", "unins000.exe", "ctranslate2.dll",
        "libcrypto-3.dll", "libffi-8.dll", "libiomp5md.dll", "libssl-3.dll",
        "msvcp140.dll", "msvcp140_1.dll", "python3.dll", "python311.dll",
        "select.pyd", "sqlite3.dll", "tcl86t.dll", "tk86t.dll", "unicodedata.pyd",
        "vcruntime140.dll", "vcruntime140_1.dll", "_asyncio.pyd", "_bz2.pyd",
        "_cffi_backend.pyd", "_ctypes.pyd", "_decimal.pyd", "_elementtree.pyd",
        "_hashlib.pyd", "_lzma.pyd", "_multiprocessing.pyd", "_overlapped.pyd",
        "_queue.pyd", "_socket.pyd", "_sqlite3.pyd", "_ssl.pyd", "_tkinter.pyd",
        "_uuid.pyd", "pyexpat.pyd"
    )

    foreach ($name in $oldFolders + $oldFiles) {
        $path = Join-Path $InstallRoot $name
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

function Ensure-Venv {
    $pythonLauncher = Get-PythonLauncher
    $venvPython = Join-Path $VenvDir "Scripts\python.exe"

    if (-not (Test-PythonExe $venvPython)) {
        if (Test-Path $VenvDir) {
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        }
        & $pythonLauncher -m venv $VenvDir
    }

    if (-not (Test-PythonExe $venvPython)) {
        throw "No se pudo crear un entorno Python funcional en $VenvDir."
    }

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $AppDir "requirements.txt")

    return $venvPython
}

function New-Shortcut($Path, $Target, $Arguments, $WorkingDirectory) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = "ScribeFloat"
    $shortcut.Save()
}

Write-Host "=========================================="
Write-Host " Instalando ScribeFloat Python + GPU"
Write-Host "=========================================="
Write-Host "Instalacion por usuario: no requiere permisos de administrador."

Remove-OldCompiledInstall
Copy-AppFiles
$venvPython = Ensure-Venv
$venvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
$mainPy = Join-Path $AppDir "src\main.py"

Set-Content -Path $LauncherCmd -Value "@echo off`r`nstart `"`" `"$venvPythonw`" `"$mainPy`"`r`n" -Encoding ASCII

New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
New-Shortcut -Path $DesktopShortcut -Target $venvPythonw -Arguments "`"$mainPy`"" -WorkingDirectory $AppDir
New-Shortcut -Path $StartMenuShortcut -Target $venvPythonw -Arguments "`"$mainPy`"" -WorkingDirectory $AppDir

Write-Host ""
Write-Host "Instalacion terminada."
Write-Host "App: $AppDir"
Write-Host "Venv: $VenvDir"
Write-Host "Acceso directo: $DesktopShortcut"
Write-Host ""
