# Simple Auction

Desktop app for cataloguing auction lots into Excel, with photos, serial
lookups and research.

## Run from source

```bash
uv run simple-auction
```

## Appearance

In **Settings**, turn **Dark mode** on or off and click **Save**. The change
applies immediately and is remembered after restarting. Until you save a
preference, the app follows your system's light/dark appearance.

## Saving and recovery

- Saving validates all photos and the lot-details JSON before changing files.
  Workbooks, details and photos are committed together, with rollback if a write
  fails. An interrupted save is recovered the next time the catalogue opens.
  Keep any hidden `.xlsx.transaction` directory with its auction files until
  recovery finishes; it contains the originals needed to roll back.
- Saving and catalogue loading run on a worker thread. Edits are briefly blocked
  while a consistent save/load finishes; longer operations show progress. Only
  auctions whose files changed are reloaded.
- Invalid details JSON is reported and is **not overwritten**. Repair the file
  or restore it from your backup before editing that auction.
- Settings are written atomically with a `.json.bak` backup. If settings cannot
  be read, startup offers **Retry**, **Restore backup**, or **Choose folders…**.
  Recovery preserves the damaged file as `config.json.invalid-<id>`; choosing
  folders never deletes existing auction data. Cancel leaves everything alone.
- Only one app instance using the same settings folder can run at a time, to
  prevent overlapping save/recovery operations. Do not have separate app copies
  write to the same catalogue simultaneously. Excel exports are not full backups:
  keep backups of the main folder **and** your configured photos folder.
- Research **Stop** cancels the HTTP request, including a wait for the first
  response or a stalled stream. Unfinished answers do not advance the chat history.

## Development

```bash
make install-dev   # uv sync, including the PyInstaller build extra
make test          # pytest
make lint          # ruff
make build-standalone   # dist/SimpleAuction/ (Windows build used by the installer)
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
(`SimpleAuction-Setup-<version>.exe`) and its `.sha256`, and publishes them
as a GitHub Release. There is no macOS release build; on a Mac, run from
source.

## Updates

**Installed (Windows) app:** checks GitHub for a newer release at startup
and from **Help → Check for Updates…**. Downloads are verified against the
release's `.sha256` before installing; the installer runs silently and
replaces the app.

**Running from source (e.g. on a Mac):** **Help → Check for Updates…** lists
the new commits on GitHub; **Update & Restart** runs a fast-forward-only
`git pull` and `uv sync`, then restarts. Local edits are never overwritten.
By hand: `git pull && uv sync`.
