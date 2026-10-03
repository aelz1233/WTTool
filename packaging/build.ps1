$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$appVersion = & $python -c 'from wtflight import __version__; print(__version__)'
# Build against Windows and this environment only: unrelated tools can put
# incompatible ICU/UCRT/OpenSSL DLLs on PATH and contaminate dependency discovery.
$basePython = & $python -c 'import sys; print(sys.base_prefix)'
$env:PATH = "$(Split-Path $python);$basePython;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
& $python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name 'WT Flight' --icon wtflight\resources\wt-flight.ico --add-data 'wtflight\resources;wtflight\resources' --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick wtflight\__main__.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
foreach ($runtime in @('vcruntime140.dll', 'vcruntime140_1.dll')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".venv\Lib\site-packages\PySide6\$runtime") -Destination (Join-Path $projectRoot "dist\WT Flight\_internal\$runtime") -Force
}
Copy-Item -LiteralPath README.md -Destination 'dist\WT Flight\README.md'
Copy-Item -LiteralPath LICENSE -Destination 'dist\WT Flight\LICENSE'
$checkOutput = Join-Path $projectRoot 'audit_artifacts\build-check'
$binary = Join-Path $projectRoot 'dist\WT Flight\WT Flight.exe'
$check = Start-Process -FilePath $binary -ArgumentList "--self-check `"$checkOutput`"" -WindowStyle Hidden -PassThru
if (!$check.WaitForExit(30000)) {
    Stop-Process -Id $check.Id
    throw 'Packaged application check timed out'
}
if ($check.ExitCode -ne 0) { throw 'Packaged application check failed' }
$report = Get-Content -LiteralPath (Join-Path $checkOutput 'self-check.json') -Raw | ConvertFrom-Json
if (!$report.ok -or !$report.frozen) { throw 'Packaged application check failed' }
$compiler = Join-Path $projectRoot '.tools\inno\ISCC.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Install Inno Setup 6 in .tools\inno first' }
& $compiler "/DAppVersion=$appVersion" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
if ($env:WT_SIGNTOOL -and (Test-Path -LiteralPath $env:WT_SIGNTOOL) -and $env:WT_CERTIFICATE) {
    & $env:WT_SIGNTOOL sign /fd SHA256 /a /f $env:WT_CERTIFICATE /tr $env:WT_TIMESTAMP_URL `
        (Join-Path $projectRoot "release\WT-Flight-Setup-$appVersion.exe")
    if ($LASTEXITCODE -ne 0) { throw 'Installer signing failed' }
}
Get-FileHash (Join-Path $projectRoot "release\WT-Flight-Setup-$appVersion.exe") -Algorithm SHA256 | Format-List
