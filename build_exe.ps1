param(
    [string]$Python = "py",
    [string]$Name = "FFmpegVideoCompressor",
    [string]$FfmpegPath = "",
    [switch]$OneFile,
    [string]$VenvPath = ".venv-build"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entryScript = Join-Path $projectRoot "kivy_ffmpeg_video_compressor.py"
$distMode = if ($OneFile) { "--onefile" } else { "--onedir" }
$venvRoot = Join-Path $projectRoot $VenvPath
$venvPython = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path $entryScript)) {
    throw "Entry script not found: $entryScript"
}

if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create build virtual environment."
    }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip in build virtual environment."
}

& $venvPython -m pip install -r (Join-Path $projectRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build dependencies."
}

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    $distMode,
    "--name", $Name,
    "--hidden-import", "kivy_deps.angle",
    "--hidden-import", "kivy_deps.sdl2",
    "--hidden-import", "kivy_deps.glew",
    "--hidden-import", "win32timezone",
    $entryScript
)

if ($FfmpegPath) {
    $resolvedFfmpeg = (Resolve-Path $FfmpegPath).Path
    $pyiArgs += @("--add-binary", "$resolvedFfmpeg;.")
}

& $venvPython @pyiArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$distPath = Join-Path $projectRoot "dist\$Name"
if ($OneFile) {
    $distPath = "$distPath.exe"
}

Write-Host ""
Write-Host "Build completed:"
Write-Host $distPath

if (-not $OneFile -and -not $FfmpegPath) {
    Write-Host ""
    Write-Host "Tip: copy ffmpeg.exe into the output folder if you want a fully portable build."
}
