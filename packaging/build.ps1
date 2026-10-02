$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
# Build against Windows and this environment only: unrelated tools can put
# incompatible ICU/UCRT/OpenSSL DLLs on PATH and contaminate dependency discovery.
$basePython = & $python -c 'import sys; print(sys.base_prefix)'
$env:PATH = "$(Split-Path $python);$basePython;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
& $python packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name 'WT Flight' --icon data\wt-flight.ico --add-data 'data;data' --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick wt_assistant.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
foreach ($runtime in @('vcruntime140.dll', 'vcruntime140_1.dll')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".venv\Lib\site-packages\PySide6\$runtime") -Destination (Join-Path $projectRoot "dist\WT Flight\_internal\$runtime") -Force
}
Copy-Item -LiteralPath README.md -Destination 'dist\WT Flight\README.md'
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
& $compiler packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Get-FileHash 'release\WT-Flight-Setup-1.0.6.exe' -Algorithm SHA256 | Format-List
