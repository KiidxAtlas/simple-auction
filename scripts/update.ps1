param(
  [string]$RepoUrl = "https://github.com/KiidxAtlas/simple-auction.git"
)

$ErrorActionPreference = "Stop"
$AppName = "simple-auction"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
  $list = pipx list
  if ($list -match "package\s+$AppName") {
    pipx upgrade $AppName
  } else {
    pipx install "git+$RepoUrl" --force
  }
  Write-Host "Updated with pipx."
  exit 0
}

py -m pip install --user --upgrade "git+$RepoUrl"
Write-Host "Updated with pip --user."
