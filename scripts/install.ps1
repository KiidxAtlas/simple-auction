param(
  [string]$RepoUrl = "https://github.com/KiidxAtlas/simple-auction.git"
)

$ErrorActionPreference = "Stop"
$AppName = "simple-auction"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
  pipx install "git+$RepoUrl" --force
  Write-Host "Installed with pipx. Run: $AppName"
  exit 0
}

py -m pip install --user --upgrade "git+$RepoUrl"
Write-Host "Installed with pip --user. Ensure Scripts path is on PATH, then run: $AppName"
