# Package (and optionally sign) the Firefox extension into a versioned .xpi
# on Windows. PowerShell equivalent of scripts/package-extension.sh.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\package-extension.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\package-extension.ps1 -Sign
#
# Signing uses Mozilla's web-ext (npm install -g web-ext) and an AMO API key
# in $env:AMO_JWT_ISSUER / $env:AMO_JWT_SECRET
# (https://addons.mozilla.org/developers/addon/api/key/).

param([switch]$Sign)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $RepoRoot "extension"
$Dist = Join-Path $RepoRoot "dist"

$manifest = Get-Content (Join-Path $Src "manifest.json") -Raw | ConvertFrom-Json
$Version = $manifest.version
$ExtId = $manifest.browser_specific_settings.gecko.id
$Xpi = Join-Path $Dist "claudecodebrowser-$Version.xpi"

$RepoSlug = if ($env:CCB_REPO_SLUG) { $env:CCB_REPO_SLUG } else { "nanogenomic/ClaudeCodeBrowser" }
$XpiUrl = "https://github.com/$RepoSlug/releases/download/v$Version/claudecodebrowser-$Version.xpi"

New-Item -ItemType Directory -Force -Path $Dist | Out-Null

Write-Host "Packaging ClaudeCodeBrowser extension v$Version ($ExtId)"

# Firefox update manifest, so installed copies can auto-update.
$updates = [ordered]@{
    addons = [ordered]@{
        "$ExtId" = [ordered]@{
            updates = @(
                [ordered]@{ version = $Version; update_link = $XpiUrl }
            )
        }
    }
}
$updatesPath = Join-Path $Dist "updates.json"
$updates | ConvertTo-Json -Depth 6 | Set-Content -Path $updatesPath -Encoding UTF8
Write-Host "Wrote update manifest: $updatesPath"

if ($Sign) {
    if (-not (Get-Command web-ext -ErrorAction SilentlyContinue)) {
        Write-Host "Error: web-ext not found. Install it with: npm install -g web-ext" -ForegroundColor Red
        exit 1
    }
    if (-not $env:AMO_JWT_ISSUER -or -not $env:AMO_JWT_SECRET) {
        Write-Host "Error: set `$env:AMO_JWT_ISSUER and `$env:AMO_JWT_SECRET (AMO API key page)." -ForegroundColor Red
        exit 1
    }
    Write-Host "Signing via AMO (channel: unlisted, self-distribution)..."
    web-ext sign --source-dir $Src --artifacts-dir $Dist --channel=unlisted `
        --api-key $env:AMO_JWT_ISSUER --api-secret $env:AMO_JWT_SECRET
    $signed = Get-ChildItem $Dist -Filter *.xpi | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($signed -and $signed.FullName -ne $Xpi) { Copy-Item $signed.FullName $Xpi -Force }
    Write-Host "Signed .xpi ready: $Xpi"
    Write-Host ""
    Write-Host "To publish as an auto-updating release:"
    Write-Host "  1. Create GitHub release tag v$Version"
    Write-Host "  2. Upload BOTH assets: $Xpi and $updatesPath"
} else {
    if (Test-Path $Xpi) { Remove-Item $Xpi }
    # Zip the extension contents with manifest.json at the archive root.
    # Not Compress-Archive: on Windows PowerShell 5.1 it stores entry names
    # with backslashes (popup\popup.html), which Firefox can't resolve.
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $srcFull = (Resolve-Path $Src).Path.TrimEnd('\') + '\'
    $zip = [System.IO.Compression.ZipFile]::Open($Xpi, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem $Src -Recurse -File | ForEach-Object {
            $entry = $_.FullName.Substring($srcFull.Length).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $_.FullName, $entry, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    } finally {
        $zip.Dispose()
    }
    Write-Host "Unsigned package: $Xpi"
    Write-Host ""
    Write-Host "To load it: Firefox -> about:debugging -> This Firefox ->"
    Write-Host "  Load Temporary Add-on -> select the .xpi (or extension\manifest.json)."
    Write-Host "For a permanent, auto-updating build, re-run with -Sign."
}
