# Simple Auction

Desktop app for cataloguing auction lots, with photos, CSV/Excel exports, shipping,
serial lookups and research. Optional local network sharing connects multiple computers.

## Run from source

```bash
uv sync
uv run python -m main
```

`uv run simple-auction` is equivalent. The `main.py` launcher prefers this
checkout's `src/` package over another installed copy. Plain `python -m main`
also uses the checkout, but its Python interpreter must have the dependencies
installed; `uv run` selects the project's managed environment.

## Appearance

The top bar switches between **Catalogue** and **Shipping**. **Settings** sits at
the top right, beside the sharing status when sharing is on. Short confirmations
(exports, imports, deletions) appear briefly at the bottom of the window.

In the catalogue, the sidebar has **New auction**, an import button for old Excel
files, and a search box that filters lots by number or title. An amber dot marks
lots still missing a title or condition; hover a lot to see its full title and
what it needs. New lots start with a blank Condition. All condition options have
empty description notes by default, so even explicitly selecting a condition adds
nothing to Description. Custom notes in Settings opt into description wording.
The **None** choice leaves Condition blank. Saved values and description text are
retained. The lot editor shows the lot's title as its heading, with
‹ › buttons (or Ctrl+Page Up/Down) for the previous and next lot. Details are grouped
into **Identification**, **Specs & compliance**, and **Listing**. Photos and
consignment appear beside them on wide windows and below them on narrow ones. Drag
photos onto the Photos area or use **Add photos…**. The serial lookup sites appear
as buttons under the Serial # field, whose entered text is bright red. Title sits
above Condition and CA legality. Title and description are marked **Auto-filled**:
generated text updates as you type, without waiting for a save, while manual edits
are preserved. The header holds previous/next
lot, **New lot** (Ctrl+N), **Research**, and **⋯** with the CSV/Excel export for the
lot's auction and Delete. Right-click a lot or auction in the sidebar for New lot,
Export and Delete; the sidebar list can also be used with the keyboard (arrows,
Return to open or close an auction). On narrow windows the editor reflows into one
column instead of cutting fields off.

Saved imported photos use their lot number and photo order: `41001.jpg`,
`41001-1.jpg`, `41001-2.jpg`, and so on. The sharing host also maintains these
copies in the configured Photos folder, under `auction 41000 photos`, for every
saved lot—not just lots opened on that computer. Opening the host rebuilds
missing or stale copies from existing shared records. Reordering, removing,
deleting and restoring photos update these copies; a failed folder write keeps
the shared originals and pending work for the next request or host restart.
Joining computers keep separate, lot-numbered cache copies when a lot is opened,
so a sync cannot replace an open draft's photos. Internal `.shared` files still
use content hashes; do not rename or delete them. Original import files are not renamed.

Press **Ctrl+D** (or **⋯ → Duplicate this lot**) to start a new lot from this lot's make,
model, condition and consignment; **Ctrl+G** jumps to the search box, and Enter there
opens the lot with that number. After deleting lots, **Undo** in the notice brings them
back (with their photos) for a few seconds. The **Needs attention (N)** chip under the
search box shows only lots missing a title or condition. **⋯ → Keyboard shortcuts…**
lists them all.

Photos are kept to ProxiBid standards: at most 1024×768 and 145 KB, saved as JPEG
under the usual lot-number names. Larger photos are resized when added, and photos
already saved are fixed automatically at startup (in shared mode, when the shared
database opens). The Photos area shows each photo's size, rotates (left/right),
previews at full size (double-click, arrow keys to move), and drag-to-reorder or
**Make main photo** sets which photo is first.

Auction workbooks use **Lot Number, Title, Description, Owner, Book Number,
Serial, Condition, Year**, in that order. Older app workbooks still load correctly
and are reordered when saved or exported. Both catalogue export formats include
only **Lot Number, Title, Description, Owner, Book Number**, in that order;
Serial, Condition, Year and all other columns are excluded. Neither export
rewrites the source workbook or includes its formatting and additional sheets.
Removing the Serial column does not remove serial text already saved inside a
Title or Description.

Use **Export to CSV or Excel…** and choose a file type:

- **Proxibid CSV (.csv)** is the upload format. Each lot occupies one physical
  line: line breaks inside fields become spaces. Empty cells remain empty fields
  with their commas and column positions preserved, including trailing empty
  fields; no placeholder text is inserted. The encoding is Windows-1252 without
  a BOM, preventing a garbled first header in Proxibid's legacy reader. Smart
  quotes and typographic hyphens/dashes in Title and Description use plain
  punctuation; saved catalogue text, owners and book identifiers are unchanged.
- **Excel workbook (.xlsx)** is for opening and editing in Excel. Book Number is
  stored as literal Text, preserving leading zeros, long identifiers and
  punctuation without formulas or apostrophe prefixes. Like CSV, Excel exports
  replace embedded line breaks with spaces so saving the workbook as CSV does
  not recreate multiline lot records. This affects the exported copy only.

If a CSV contains characters Windows-1252 cannot represent, export stops with an
explanation and leaves any existing destination file untouched. Choose XLSX to
preserve those characters, or edit them before making a Proxibid CSV. Catalogue
imports accept both UTF-8 and Windows-1252 CSV files.

CSV has no cell-type information. Even quoted numbers can lose leading zeros or
precision when Excel opens and resaves them, so use the XLSX choice for Excel
work rather than opening the Proxibid CSV. Exports cannot infer missing zeros
from values that were already changed in an older file.

Worksheet rows without lot numbers are not exported in either format. Empty
cells remain empty, and saved catalogue descriptions keep their original line
breaks.

For Proxibid **Bulk Loader**, indicate that the first row contains column headings.
Map **Lot Number → Lot Number**, **Title → Lot Title**, and
**Description → Lot Description**. If Proxibid defaults Title or Description to
**Column ignored**, select their destination fields manually before finishing.
Leave Owner and Book Number unmapped unless you intentionally use a corresponding
supported field; neither is a unique lot identity. Never map Description, Owner
or Book Number to Lot Number or Import ID.
Review the scan preview before importing: the lot-number column must contain
the actual lot numbers, not headings or description fragments. Proxibid's
[catalogue upload guide, page 16](https://www.proxibid.com/AnnouncementFiles/File/The_Complete_Proxibid_Welcome_Packet.pdf#page=16)
requires carriage returns removed from descriptions, no duplicate lot numbers,
and no rows without lot information. Always generate a new CSV after updating;
an older exported file is not rewritten by an app update.

Settings lists its sections on the left. **Auction setup** has the next auction
number, the serial-number lookup sites and the serial table. **Conditions** lists
the dropdown choices; select one to edit its name and description sentence on the
right, and use the arrows (or drag) to reorder. Serial lookup sites are edited the
same way. **Listing fields** decides what goes where: two side-by-side lists,
**Title** and **Description**, each with a checkbox per field. Tick a field to
include it and drag it (or select it and use the arrows) to set the order; a field
can go in the title, the description, both or neither. In the title, fields above
**Your own wording** go before the words you type and fields below go after a dash.
In the description, each ticked field becomes a line such as `Make: Colt` at the top,
above your own text; condition wording is added at the end only when its note is
configured in Settings. An **Example** box shows the resulting title and description.
Existing unmodified starter condition lists are upgraded to empty notes; custom
names, ordering and notes are kept. This does not rewrite saved lot descriptions.
Under **Your own fields** click **Add field** to create fields such as Caliber or
Finish: each gets a box in the lot editor's **More details** card and appears in
both lists (ticked for the description), optionally with text before the value in
the title (e.g. "Cal:" gives "Cal: .45 ACP"). Values are saved per lot with
make/model (not as Excel columns); removing a field keeps lots' existing values.
Empty values and CA legality **N/A** are omitted. Changes apply to the open lot and
future edits, rather than rewriting every saved lot. **Appearance**, **Sharing**,
**Folders** and **Research** (the Gemini API key) follow. **Save** applies all
sections; **Cancel** discards pending changes.

### Output and daily work

Output is unlocked privately: type the access word into the Gemini API key field
in **Settings → Research** and save. The word is never stored as an API key, so
your saved Gemini key is kept. Once unlocked, **Remove elevated privileges** appears
in the same section; save afterwards to hide Output again.

Output distinguishes lots with information started from lots whose information
is filled out. Photos can be added later; publication readiness is a separate
measure. Blank, untouched lots and deleted lots do not contribute to output.
Repeated saves of the same lot do not create additional daily output.

Use **Settings → Sharing** to connect your computers. Output history travels
through that connection alongside the catalogue, rather than requiring a
cloud-synced folder. Both computers must run the same app version.

The lot editor includes **Caliber**, **Type** (Rifle, Shotgun or Handgun, or type
your own), optional **Barrel length** (enter the units with the value) and **CA
legality**: **LEGAL FOR CA**, **NOT LEGAL FOR CA**, or **N/A** (the default). These are
saved with make/model in the lot-details file (or shared database), not as
additional Excel columns, and can be imported from spreadsheet columns such as
"Caliber"/"Gauge" and "Type".

Titles follow the house style by default:
`Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition LEGAL FOR CA`
(make, model, caliber, type, your own wording, `SN:` serial, condition followed by
"Condition", then `LEGAL FOR CA` / `NOT LEGAL FOR CA`; N/A adds nothing). The description
starts with Make, Model, Caliber and Type lines. Settings saved with the previous
built-in title layout switch to this one automatically; a layout you changed is
kept. Titles written in the older style ("S/N:", " - Good") are recognised and
rewritten in the new style when the lot is opened.

When a title is wider than its field, a horizontal scrollbar appears underneath.
Drag it, scroll sideways on a trackpad, or hold **Shift** while using the mouse
wheel to see the hidden words. Panning does not move the caret or change the
text or selection. Normal vertical scrolling still scrolls the page; keyboard
navigation and Undo continue to work, and the existing title-length limit stays
the same.

You can add your own description text after the condition sentence, either on
the same line or in following paragraphs. It stays in place when saving and
reopening the lot. Changing the condition replaces only recognised generated
wording; unfamiliar or manually edited text is retained rather than discarded.
Deleted or partially edited generated description lines are not rebuilt when
their source fields change. Intact generated lines can still update normally.
Explicitly selecting a condition restores its generated title wording and, only
when its note is non-empty, its description sentence. Empty notes leave existing
description text unchanged. Saving, reopening, or finishing an unrelated edit does
not restore deletions.
Make and model entries capitalize word initials: `remington` becomes `Remington`
and `sig sauer` becomes `Sig Sauer`. Existing capitalization in model codes such
as `AR-15` and `M&P` is kept, and serial numbers are not reformatted.

The lot editor aligns Identification and Listing in equal-sized cards on wide
windows, with Photos below Identification, and stacks the cards on narrow ones.
**Consignment** is expanded by default for owner and book number. **C&R** is
always visible in Identification, and **CA legality** sits beside Condition in
Listing. Collapsing Consignment never clears its fields. Serial lookup
sources appear below the serial field once a serial is entered. **Photo tools**
beside Add photos includes phone intake; evidence and publication review remain
in the lot's **⋯** menu. Duplicate warnings still appear when relevant.
Scrolling over a closed dropdown scrolls the page rather than changing the
selected value. Click to open the dropdown when you want to choose an option;
normal keyboard navigation and scrolling inside an open list remain available.

In **Settings → Appearance**, choose **Match system**, **Light** or **Dark** and click
**Save**. The change applies immediately and is remembered after restarting.
The same section includes **Use OpenDyslexic** and **Text size → Small / Medium /
Large**, with a sample of your pending choice. Click **Save** to apply the font
and size throughout the desktop UI; **Cancel** leaves the current appearance
unchanged. Both choices are remembered after restart, including when the app
follows the system's light/dark theme. OpenDyslexic is bundled (regular, bold,
italic, and bold italic); no download or system font installation is needed.
The font and its SIL Open Font License are included in the app's `ui/fonts`
resources. Choosing a reading font is a personal preference, not a treatment.

### Spell checking

Editable lot fields (including make, model, caliber, serial, title, description,
and custom fields), research questions, and notes have offline English spell
checking. Suspected misspellings get a red
wavy underline. Right-click a word for suggestions and click one to replace it;
normal Undo, Cut, Copy, and Paste remain available. **Ignore** skips a word for
this app session; **Add to dictionary** remembers it on this computer in
`~/.config/simple-auction/spelling.json`. Custom names and specialist vocabulary
can be added there through the menu. No text is sent to a spelling service.
Numeric-only fields, passwords, URLs, API keys, and shipping identifiers are excluded.
This is spelling assistance, not grammar checking or automatic rewriting.

## Identification, research and publication review

- Once a serial is entered, lookup links appear directly below its field and are
  clickable without a menu or disclosure button. Clearing the serial hides them.
  **Colt**, **Ruger**, **Browning**, and Lindcott are defaults;
  every link can be edited, reordered or removed in Settings → Auction setup →
  Serial number lookup sites. Older settings receive the formerly hard-coded
  sites once; saved removals are respected. Cody and Colt Archives are not included.
  Ruger and Lindcott prefill the serial through their supported URL parameters,
  as do custom URL templates containing `{serial}`. Colt does not support URL
  prefill: its link copies the serial for pasting. Browning is a dating guide,
  not a serial-entry form.
- **Evidence & publication review…** (beside consignment or in the lot's **⋯**
  menu) stores identification status, dated source links, year/range estimates,
  uncertainty notes, and supporting photos or PDFs. Attachments are embedded in
  the lot's packet, so they travel with standalone saves, sharing and backups.
  Each attachment is limited to 2 MiB and the complete packet to 12 MiB.
  Different date estimates remain separate and are flagged for review; recording
  evidence does not change the lot's year or claim legal eligibility.
- **Research** requests a brief identification note, key facts, and what to verify
  next, rather than a full history or price report. Ask a follow-up for more
  detail. The latest answer is shown in full; **Show earlier answers** and
  **Show sources** reveal conversation history and references on demand.
  **Include photos in research** sits above **Research tools** and starts off
  for each lot. **Identify from photos…** is directly beside Research tools;
  that separate action still asks for permission before sending photos.
  **Research tools** expands auto-fill and comparable searches. The photo-sharing
  checkbox stays visible, without an additional disclosure line beneath it.
  **Save to packet** appears for a completed answer and retains its full text and
  sources, even when references or earlier answers are collapsed. Partial,
  stopped and failed answers cannot be captured. The packet's Research tab also
  records staff notes and unanswered consignor questions.
- **Find comparables** starts a separate search without serials, photos, free-text
  descriptions or prior chat history. Verify results, then record them in the
  packet's **Comparable sales** tab. Sold results and asking prices are separate;
  record currency, sale date, buyer's-premium treatment and condition differences.
  This workflow does not automatically appraise the lot.
- **Identify photos** explicitly asks before sending catalogue details and photos
  to Google Gemini (requires a configured API key and internet access). Review the
  suggested fields against the reference photos before applying them. Existing
  values are not selected for replacement by default. Ambiguous serial characters
  must be checked by a person, not guessed.
- **Tools → Ready to publish — work queue…** lists missing identification, photos,
  unfinished research, unanswered questions, date conflicts and pending listing
  approval. Double-click an issue to open its lot at the relevant field or review
  dialog. The photo checklist is an explicit staff review, including categories
  that are not applicable; it is not an automatic image-quality judgment.
- Matching make/serial entries show a duplicate/relisting review button. Open the
  earlier lot, keep the entries separate with an explanation, or mark a relisting
  and reuse its research. Reused evidence is unverified until reviewed again.
  This is a warning, never a hard block: serials are not globally unique.
- Editing listing text clears listing approval. Changing identification clears
  identification/research approval; changing photos resets their review checklist.

## Phone photo intake

Open **Phone photo intake…** on a saved lot. Select the computer's private LAN
address and click **Start phone session**. Connect the phone to the same trusted
Wi-Fi and scan the QR code. The ten-minute link is restricted to that lot and
expires automatically; keep it private. The page guides overall, opposite-side,
markings, serial and defect shots. On the phone, choose the view, then use
**Take picture** to open the camera or **Choose file** to select an existing
photo. The exact picker depends on your phone/browser. Review the preview
(or **Remove** it to choose again), then press
**Send photo**. Upload status confirms receipt; keep the page open while sending.
Photo tips and network/privacy details expand when needed.
On the desktop, uncheck unwanted photos and choose **Add photos** to save them
through the normal photo pipeline. Cancel removes the received temporary files.

Intake uses unencrypted local HTTP, not a public upload service. Allow the app
through the private-network firewall; guest Wi-Fi isolation can prevent access.
JPEG, PNG and WebP are supported (not HEIC): 12 MiB and 30 megapixels per image,
24 images and 100 MiB per session. Camera metadata is stripped. Nothing is sent
to AI until a separate research/identification request is explicitly made.

## Guided auction spell check

Open any lot in the auction, then click **Spell check auction…** in the top bar.
The current lot must save successfully before review starts. The review checks
saved **titles and descriptions** across that auction using the same offline
English and personal dictionaries as the editor. Serial tokens are excluded even
when embedded in titles/descriptions, including alphabetic serials. Identifier
fields, photos, and research packets are not rewritten. Replacements that would
exceed the title's 100-character limit are refused, not silently shortened.

Each finding shows its lot, field, highlighted word and surrounding text. Choose
a suggested word (or type your own), then **Replace** to save just that occurrence.
**Skip** leaves only that occurrence alone; **Add to dictionary** saves the word
to this computer's personal dictionary and leaves the lot unchanged. There is no
automatic correction or Replace all. **Close** ends the review; replacements
already saved remain saved. A changed or deleted lot is rejected rather than
overwritten: close and reopen spell check to review fresh data. Shared saves use
the host's existing conflict checks and do not fall back to writing a local copy.

## Full backups and consignor review sheets

**Tools → Back up / restore…** creates a new full backup of the main folder,
separate photos folder, shipping records and sanitized app settings. A live
shared database is captured consistently, including committed WAL data. API keys
and pairing codes are excluded. The dialog shows the last successful backup on
this computer. A remote client cannot claim its cache is a full backup: back up
on the host instead. Keep backups away from the working folders.

Restore validates paths and checksums and writes only into a new/empty folder;
it never overwrites the current catalogue. The restored copy includes remapped
settings with sharing off. Where activation is safe, **Use restored settings
after restart…** explicitly switches the next launch to that copy and closes the
current app. With a live database/sharing, stop using that catalogue and reopen
the restored configuration separately rather than replacing it underneath clients.
Excel exports are still not backups.

**Tools → Consignor review sheets…** selects an auction, groups its lots by owner,
and previews printable review sheets with photos, descriptions, unresolved
questions, and room for corrections/approval. Filter to one owner before exporting
a PDF for that consignor. Exporting does not change catalogue approval state.
Use a new filename for backups and review PDFs; existing outputs are not replaced.

## Local network sharing

Install the same app version on both computers. No Docker, Supabase, cloud
account, or internet connection is needed for sharing.

1. On the computer holding your existing data, open **Settings → Sharing**.
   Enable **Share with another computer** and **This computer is the
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

Click **Shipping** in the top bar to switch the entire workspace; **Catalogue**
returns to lot editing, preserving your selection and saving edits.

`examples/proxibid-winning-bidders-example.csv` is a fictional import demo.
Its headers and column order have not been verified against an actual Proxibid
export; use your own Winning Bidders Report and confirm its column mapping.

1. Export the **Winning Bidders Report** from Proxibid as CSV. Drop it on the
   shipping page or click **Choose CSV file…** (later imports use the import
   button next to the auction list). Review the buyer preview and click
   **Import buyers**. Recognized columns are mapped automatically; use
   **Adjust CSV columns** if the preview needs correcting. Choose the country
   to use for rows that do not specify one.
2. Select a buyer from the queue. Their shipping address and lots appear on the
   right; the center contains the package form. The queue names what needs fixing
   (for example **No street address**). Use **Edit** to correct an address
   or **Local pickup** to leave that buyer out of shipping. Search or filter the
   queue to find buyers needing attention.
3. Type the weight in **pounds** (for example `2.5`) and the box dimensions in
   **inches**. Tab moves through length, width, and height. Click **Mark ready &
   next**, or press Enter in the height field. For multiple boxes, use **Add box**,
   select it, and check the lots that belong in it. Each lot belongs to one box.
4. Click **Export to Pirate Ship…** under the buyer queue to save ready shipments. The export panel
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

**Tools → Recover deleted items…** retains deleted catalogue lots and auctions,
including saved lot details, evidence packets and photos, across app restarts.
Choose the shared host history or this computer's standalone history. **Restore
deleted items** restores an entire deletion only if none of its lot numbers (or
the deleted auction number) has been reused; it never overwrites current work.
Restore a deleted auction before restoring separately deleted lots within it.
The short-lived **Undo** notice is still available, but is no longer your only
recovery route.

Changed lot saves also retain the previous saved text/details and photos as a
**Previous saved revision**. Use **Export snapshot…** to write `snapshot.json`
and JPEGs into a new `recovered-…` folder. Copy wanted text or add recovered photos
back manually; revision export never replaces the current lot or photo order.
Removed/replaced saved photos are included in these revisions. New unsaved edits
that were never saved are not catalogue history. Before **Reload from host**
replaces dirty drafts, the app preserves lot/shipping JSON and independent photo
copies in `data/shared-drafts`; recovery offers **Open unsaved drafts folder**.
Reload stops if preservation or photo downloads fail. An earlier save completing
also no longer replaces photo edits made while it was running.

Archives are written before local deletion; if writing the archive fails, deletion
stops. Shared deletion and its archive commit in the same SQLite transaction.
Local history is `data/recovery.sqlite3`; shared history is inside the host's
`data/shared.sqlite3`, available to paired clients while the host is reachable.
History is retained (not automatically purged) and the existing full-backup tool
includes it. Keep full backups on a separate disk: recovery history is not protection
against losing the working disk. History starts with this feature; earlier deletions
require an existing full backup or the operating system's Trash/Recycle Bin.
This covers catalogue deletion and previous saved lot revisions, not arbitrary
external file deletion, unsaved typing, or shipping-history rollback.

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
  for simultaneous work. CSV exports are not full backups:
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
