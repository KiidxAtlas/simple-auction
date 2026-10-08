# Simple Auction

Desktop app for cataloguing auction lots into Excel, with photos, serial
lookups and research.

## Run from source

```bash
uv run simple-auction
```

## Development

```bash
make install-dev   # uv sync, including the PyInstaller build extra
make test          # pytest
make lint          # ruff
make build-standalone   # dist/SimpleAuction.app (macOS) or dist/SimpleAuction/ (Windows)
```

## Releasing

Releases are built by GitHub Actions
(`.github/workflows/release-desktop.yml`) when a `vX.Y.Z` tag is pushed.

1. Bump the version in **both** `pyproject.toml` and
   `src/simple_auction/__init__.py` (`__version__`).
2. In `CHANGELOG.md`, move the `## Unreleased` notes under a dated heading:
   `## 0.2.0 — 2026-10-20` (the em dash and date are required; the section
   becomes the release notes).
3. Commit and push to `main`.
4. `make release VERSION=0.2.0`

`scripts/release.sh` checks the three version spots agree and that the
changelog entry exists, then tags and pushes. `make release` on a tag that
already exists re-pushes the tag to re-run the build.

The workflow builds the Windows installer
(`SimpleAuction-Setup-<version>.exe`) and a macOS DMG, writes a `.sha256` for
each, and publishes a GitHub Release with the Windows installer.

### macOS signing

The macOS job needs these repository secrets to build on a tag:
`MACOS_CERTIFICATE_BASE64`, `MACOS_CERTIFICATE_PASSWORD`,
`MACOS_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_APP_PASSWORD`, `APPLE_TEAM_ID`.

## Updates

Installed copies check GitHub for a newer release at startup and from
**Help → Check for Updates…**. Downloads are verified against the release's
`.sha256` before installing; on Windows the installer runs silently and
replaces the app.
