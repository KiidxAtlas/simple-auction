# Simple Auction

Desktop app for cataloguing auction lots, with photos, Excel exports, shipping,
serial lookups and research. Optional local network sharing connects multiple computers.

## Run from source

```bash
uv run simple-auction
```

## Appearance

Settings opens on **Auction setup**, with the next auction number and spacious
editable lists for serial-number links and conditions. Double-click a cell to
edit it; use Move up / Move down to reorder conditions. **General** contains appearance, local
network sharing, folders, the serial lookup table, and the research API key.
**Save** applies changes from both tabs; **Cancel** closes the dialog.

In **Settings → General**, turn **Dark mode** on or off and click **Save**. The change
applies immediately and is remembered after restarting. Until you save a
preference, the app follows your system's light/dark appearance.

## Local network sharing

Install the same app version on both computers. No Docker, Supabase, cloud
account, or internet connection is needed for sharing.

1. On the computer holding your existing data, open **Settings → General → Local network
   sharing**. Enable **Share with another computer** and **This computer is the
   host**, then click **Save**. Copy its six-digit pairing code.
2. On the second computer, enable **Share with another computer**, leave **This
   computer is the host** off, and click **Find host**. Select the host, paste its
   pairing code, click **Test connection**, and **Save**. The second computer's
   existing standalone files are preserved; they are not automatically merged.
3. Keep the host awake with the app open. Both computers show connection status
   and refresh shared records approximately every two seconds. If discovery is
   blocked, enter the host's private IPv4 address and port manually. Settings
   shows the host's addresses; the default TCP port is `8765`, discovery uses UDP
   `8766`. Allow the app through the private-network firewall. Guest networks may
   block connections between computers.

Save the connection once on each computer. The code, host identity, and sharing
mode are kept in your user settings outside the installation folder, so app
updates and restarts keep the pairing. After a power cycle, reopen Simple Auction
on both computers: hosting resumes and the other computer reconnects automatically,
including if the host's local address changed. If the host opens later, the other
computer keeps retrying without asking you to pair again. Existing pairings remain
valid when upgrading; their host code is displayed as six digits. UDP discovery
must be allowed for automatic recovery after an address change.

The host imports existing auctions, lot details, photos, and shipping progress
once into `<main folder>/data/shared.sqlite3`, without deleting the source files.
After migration the database is the source of current records, including when
hosting is turned off. The original spreadsheets and shipping JSON are snapshots;
to bring in subsequent spreadsheet changes, use Import. Turning hosting back on
shares the latest database again. A second computer needs the host for shared
work; its downloaded photos are a cache, not a complete offline workspace.

Photos remain JPEG files in the configured photos folder. Shared originals are
kept in `.shared/<host identity>/`; immutable image files prevent a failed or
conflicting edit from replacing another person's photos. Clients download photos
when opening a lot, cache them under `data/shared-cache/`, and upload newly added
photos through the existing compression pipeline. Both computers can export the
current auction to Excel and export ready shipments to Pirate Ship CSV.

The server assigns new auction/lot numbers and checks edits before saving.
Changes to different buyers merge; competing edits to the same lot or buyer are
reported while retaining the unsaved draft. **Reload from host** explicitly
loads the latest version and asks before discarding unsaved edits. Settings
remains available while disconnected; changing connections preserves drafts in
`data/shared-drafts/`. Retry saving after reconnecting.

Shipping CSV generation and export history commit in one database transaction.
A failed download offers **Recover CSV download…**, including after restarting.
**Download CSV again** downloads the latest export without creating shipments
again. Exports made before sharing remain on the computer that created them.

Sharing uses authenticated HTTP restricted to private IPv4 networks. The pairing
code grants access to all shared auction, photo, and buyer data. Use a trusted
private network; traffic is not encrypted and this server is not designed for
internet exposure. Keep backups of the host's main folder **and** photos folder,
with the app closed, including the database and hidden shared-photo directory.

## Proxibid → Pirate Ship shipping

Click **Shipping** in the top header to switch the entire workspace; **Back to
Catalogue** returns to lot editing, preserving your selection and saving edits.

`examples/proxibid-winning-bidders-example.csv` is a fictional import demo.
Its headers and column order have not been verified against an actual Proxibid
export; use your own Winning Bidders Report and confirm its column mapping.

1. Export the **Winning Bidders Report** from Proxibid as CSV. Drop it on the
   shipping page or click **Import Proxibid CSV…**. Review the buyer preview and
   click **Import buyers**. Recognized columns are mapped automatically; use
   **Adjust CSV columns** if the preview needs correcting. Choose the country
   to use for rows that do not specify one.
2. Select a buyer from the queue. Their shipping address and lots appear on the
   right; the center contains the package form. Use **Edit** to correct an address
   or **Local pickup** to leave that buyer out of shipping. Search or filter the
   queue to find buyers needing attention.
3. Type the weight in **pounds** (for example `2.5`) and the box dimensions in
   **inches**. Tab moves through length, width, and height. Click **Mark ready &
   next**, or press Enter in the height field. For multiple boxes, use **+ Box**,
   select it, and check the lots that belong in it. Each lot belongs to one box.
4. Click **Export to Pirate Ship…** to save ready shipments. The export panel
   shows the file and buttons to open its folder and Pirate Ship. In Pirate Ship,
   choose **Upload a Spreadsheet** and select the CSV. Map **Weight (Pounds)** to
   pounds and the dimensions to inches, review the shipments, then buy labels.
   Local pickups, incomplete shipments, and shipments already exported stay out
   of the file. Pirate Ship handles services, insurance, customs, and printing.

Every shipment must be weighed and measured before it can be exported; there is
no addresses-only export. Each buyer starts with one box containing all their
lots. Saved weights from earlier versions are displayed and exported in pounds
without changing the stored measurement.

In standalone file mode, packing progress is saved automatically under
`<main folder>/data/shipping/`. With sharing enabled or after host migration, it
is saved in the host database instead.
Saved auctions can be reopened from the shipping page's auction list. Include
this folder in backups: it contains buyer addresses and export history.
Re-importing an existing auction reference is blocked to preserve packing and
export history. **Exported** means the CSV was created, not that a label was
purchased or the package shipped. Exported boxes are locked and excluded from
subsequent exports in both modes; keep the exported CSV until labels have been purchased.
An export commits its CSV and progress together, with rollback on write failure.

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
  write directly to the same catalogue simultaneously. Use local network sharing
  for simultaneous work. Excel exports are not full backups:
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
