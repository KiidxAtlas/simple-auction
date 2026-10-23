# Changelog

## 0.1.16 — 2026-10-23

### Fixed

- Synced photos now use lot-based filenames, matching local imports:
  `41001.jpg`, `41001-1.jpg`, and so on, in saved photo order.
- Previously cached shared photos receive properly named copies when loaded.
  Reordering or removing photos updates the numbering without replacing photo
  copies still referenced by an open form or unsaved draft.
- Original import files and internal hash-based transfer files remain untouched.

## 0.1.15 — 2026-10-23

### Added

- Offline auction-wide spelling review for titles and descriptions, with explicit
  replacement, skip, and personal-dictionary controls.
- Persistent recovery for deleted lots and auctions, including photos, in local
  and shared catalogues via Tools → Recover deleted items.
- Previous saved lot revisions can be exported with photos for manual recovery.
  Recovery starts with this update; separate full backups are still recommended.

### Changed

- Serial-number text is bright red; Title appears above Condition and CA legality.
- Generated titles and descriptions update while typing, preserving manual edits.
- The C&R checkbox and generated qualifier now read simply C&R.

### Fixed

- Host reload preserves unsaved drafts and independent photo copies before
  replacing the form, and stops if preservation or downloads fail.
- Save completion no longer replaces photo edits made while the save was running.
- Spell-check saves reject conflicting edits instead of overwriting newer work.

## 0.1.14 — 2026-10-16

### Added

- Photos: rotate left/right, full-size preview (double-click, arrow keys),
  drag-to-reorder or "Make main photo", and a size badge on each thumbnail.
- Duplicate this lot (Ctrl+D), Undo after deleting lots, Ctrl+G to jump to the
  search box (Enter opens the lot with that number), and a "Keyboard
  shortcuts…" list in the ⋯ menu.
- A "Needs attention (N)" chip in the sidebar that shows only incomplete lots.
- The shared-database opening message says that photo sizes are being checked.
- README describes the photo standard (1024×768, 145 KB).

### Changed

- Unlocking Output now needs a private passphrase. The app only contains a
  salted hash of it, so the plain word can no longer be read from the source.
- Photos shared from a host that break the ProxiBid standard are fixed when
  the shared database opens, and the lots that use them are updated.
- The startup photo check reads only each file's size and header instead of the
  whole file, so it is much lighter on large or network photo folders.

## 0.1.13 — 2026-10-16

### Changed

- Photos now follow the ProxiBid standard: at most 1024×768 (768×1024 for
  portrait) and 145 KB, never enlarged, upright, and without camera metadata.
  Photo naming is unchanged.
- Photos saved earlier that break the standard are fixed automatically in the
  background when the app starts and when the photos folder changes; photos that
  already comply, and any that cannot be read, are left untouched.

## 0.1.12 — 2026-10-16

### Changed

- The Settings button that hides Output again is now labelled **Remove elevated
  privileges**; it takes effect on Save.

### Fixed

- Typing the Output access word into the Gemini API key field no longer shows
  that it was accepted before Save; the elevated-access status and removal
  button reflect only access that is already saved.

## 0.1.11 — 2026-10-16

### Added

- Daily output distinguishes lots with meaningful saved information from lots
  with their information filled out; photos and publication approval are separate.
  Blank, unchanged lots and deleted lots are excluded, and repeated saves do not
  inflate output. The header shows both daily counts.
- Output stays hidden until unlocked privately from the Gemini API key field in
  Settings → Research; the access word is never saved as an API key.
- Output history synchronizes through local network sharing so connected
  computers show the same KPIs.
- Output shows daily/weekly/monthly totals, in-progress work, streaks, pace,
  a 30-day trend, weekday/hour charts, daily history and auction progress.

### Fixed

- The test suite explicitly disposes of remaining Qt widgets and shuts down its
  shared application before interpreter finalization, preventing the Linux
  segmentation fault after all tests passed.

## 0.1.10 — 2026-10-15

### Fixed

- Explicitly reselecting a condition restores deleted generated wording without
  restoring other deleted fields during saving or passive editing.
- Serial lookup links appear only when a serial is entered, and remain directly
  clickable without a disclosure button.

## 0.1.9 — 2026-10-15

### Added

- App-wide OpenDyslexic reading-font toggle and Small/Medium/Large text sizes in
  Appearance, with a preview, persistent preferences and bundled licensed fonts.
- Offline English spelling with red underlines, right-click suggestions,
  undoable replacements, session ignore and a persistent personal dictionary.
- Always-visible official serial links alongside configurable lookup links,
  including automatic serial prefill for Ruger.
- Portable identification evidence, supporting photo/PDF attachments, research
  packets, staff questions, sold/asking comparables and publication review.
- Actionable readiness queue and non-blocking duplicate/relisting review with
  explicit research reuse and approval invalidation after material edits.
- Expiring, private-network QR phone photo intake with guided shots and desktop
  review, plus explicit photo-identification disclosure and reviewed suggestions.
- Consistent full backup, validated non-destructive restore, visible backup
  status, and owner-filtered consignor PDF review sheets.

### Changed

- CA legality now displays LEGAL FOR CA / NOT LEGAL FOR CA, including generated
  titles; older title wording is recognised without duplicating qualifiers.
- Identification and Listing align as equal-sized cards on wide windows, with
  Photos below Identification and Consignment expanded by default.
- Research photo sharing starts off for each lot, labelled "Include photos in
  research" above Research tools; Identify from photos is beside Research tools.
- Removed the secondary photo-sharing hint beneath the research photo checkbox;
  explicit photo identification still asks for consent.
- Moved C&R into Identification and CA legality beside Condition in Listing,
  removing the separate Listing options disclosure without changing saved values.
- Long titles now have a horizontal scrollbar, sideways trackpad scrolling and
  Shift+wheel support, without changing text, selection or normal page scrolling.
- Spell checking now covers editable lot text fields, including make, model,
  caliber, serial and custom fields, not only listing prose.
- Removed Cody and Colt Archives, the lookup disclosure and More lookup sources
  menu, and the separate Copy serial button.
- Auction workbooks and exports use Lot Number, Title, Description, Owner,
  Book Number, Serial, Condition and Year order; older workbooks still load.
- All serial lookup sites are managed in Settings, including the official defaults;
  edits, reordering and removals persist without hard-coded links reappearing.

### Fixed

- Description edits after the condition sentence are preserved, including text
  on the same line. Reopening a lot or finishing a title edit no longer rebuilds
  an unchanged condition sentence; condition/template changes retain user notes.
- Deleted or partially edited description fields stay user-owned even when the
  corresponding make, model, caliber or condition changes.
- Make and model entries capitalize each word's initial letter on finishing an
  edit and on save, while retaining existing model-code capitalization.
- Scrolling over a closed dropdown no longer changes its selection, even when
  it has focus. Page scrolling, keyboard selection and open popup lists still work.

## 0.1.8 — 2026-10-14

### Changed

- The description now starts with Caliber, Type and Barrel length; Make and
  Model are no longer added there (they're still in the title). If you
  never changed the description fields in Settings → Listing fields, you
  get the new layout automatically; a layout you chose yourself is kept.

### Fixed

- Settings → Listing fields no longer gets wider than the window with wide
  system fonts; long field labels wrap.
- The title no longer sometimes gets make/model (or other field) text added
  a second time. Autosaving while you were still typing in a field could
  save that field without its text in the title, so it was added again the
  next time the lot was opened.
- Edits that arrive while a save is running (e.g. a serial lookup result)
  are no longer marked as saved before they are.
- Autosave waits 2 seconds after you stop typing (was 0.7) and no longer
  greys out the window for a moment while it saves.
- Text the app fills in for you — the make, model, condition and other
  fields in the title, the "Make: …" lines at the top of the description,
  and the condition sentence — no longer comes back after you delete it,
  including after saving and reopening the lot. It's written again only
  when you change the value it comes from.

## 0.1.7 — 2026-10-14

### Added

- C&R eligible checkbox in the Listing card. When ticked, "C&R ELIGIBLE"
  is added to the end of the title, and it's removed again when unticked.
  It's part of the default title layout and can be moved or switched off
  in Settings → Listing fields. A saved layout that matches the previous
  default picks it up automatically.
- The blank choice in the Type list now reads "None". Picking it still
  leaves the field empty.

### Changed

- Lot editor: Identification and Specs are one card, with up to three short
  fields to a row. CA legality sits next to Condition above the title. The
  description grows to fill the window, so a whole lot fits on one screen at
  1280×800 without scrolling.
- Refreshed look: an app mark in the top bar, softer palette and borders,
  raised cards, and an accent marker on the open lot in the sidebar.
- Research panel: a clearer empty state with a single Auto-fill button.

## 0.1.6 — 2026-10-13

### Fixed

- Autosave no longer takes focus away from the field you're typing in.

## 0.1.5 — 2026-10-09

### Added

- Six-digit pairing codes, with existing saved pairings preserved during updates.
  Saved host/join modes resume when the app reopens. Clients retry while the host
  is offline and rediscover the same host after a network-address change, remembering
  the recovered address. Repeated incorrect pairing attempts are rate limited.
- Settings opens on Auction setup, followed by General. The wider dialog gives
  links and conditions expandable tables, wrapped descriptions, and clearer
  selection and reorder controls. Save/Cancel stay visible on small screens.
- Local network sharing in Settings: host on one computer, find it from another,
  pair with a code, and share auctions, lot details, photos, and shipping progress.
  The host imports existing data into a local SQLite database; photos remain
  files and Excel/Pirate Ship exports remain available on either computer.
- Shared saves check for conflicting edits, assign new numbers on the server,
  merge changes to different buyers, and preserve unsaved drafts while disconnected.
  Shipping exports have a shared transactional ledger and recoverable downloads.
- Turning hosting off continues using the latest local database. Original import
  sources remain intact, and hosted databases survive application restarts.
- A header Shipping button switches the full workspace to a Proxibid-to-Pirate
  Ship page. Drop in a Winning Bidders CSV, review automatically mapped buyer
  addresses, correct mistakes or exclude local pickups, then weigh and measure
  every box before exporting. Package measurements are required for export.
- Package measurements use plain text inputs: weight in pounds, dimensions in
  inches, with Tab navigation and Enter to mark ready. A buyer queue, central
  package form, and separate address/items cards replace the long stacked form.
  Mark ready & next moves through packing; search and status filters
  help find buyers. After export, open the CSV folder and Pirate Ship directly
  from the page.
- New measured exports use Weight (Pounds); existing stored weights retain their
  original values.
- Shipping progress is saved per auction. Exports record shipment history to
  exclude previously exported shipments. CSV and progress writes commit together.

### Fixed

- Completed loading dialogs no longer reappear over the shipping column
  confirmation window and block importing buyers.

## 0.1.4 — 2026-10-09

### Fixed

- The old, unmodified four-condition starter list now upgrades to the nine-step
  grading scale when migrating settings or loading an existing conditions YAML.
  Custom condition names, notes and ordering are preserved.
- Condition descriptions starting with `%` load as literal text; generated
  descriptions are quoted safely. Editing a YAML file by deleting and replacing
  it no longer leaves the dropdown stuck on its previous condition choices.

## 0.1.3 — 2026-10-09

### Changed

- Titles are built in this order: make, model, serial number (as
  `S/N: A123456M`), then anything typed, then the condition — e.g.
  "Remington 870 Wingmaster S/N: A123456M 12ga Pump - Excellent". Editing
  make, model or serial updates the start of the title in place.
- New lots start with no condition ("Pick a condition"), like imported lots:
  nothing is added to the title or description, even when saving, until
  someone picks one.
- Settings now has a **Dark mode** toggle. Saving applies the choice immediately
  and remembers it across restarts, independently of the system appearance.

### Fixed

- Failed photo replacements and workbook/details writes preserve the previous
  lot state. Saves use atomic file replacement and a recovery journal; startup
  rolls back interrupted saves. Imports and lot deletions also coordinate their
  workbook and details updates.
- Damaged lot-details files are reported instead of silently overwritten.
- Damaged settings have explicit startup recovery, preserving the original
  file and offering backup restore or selection of existing data folders.
- Photo processing, saving and catalogue reads no longer run on the GUI thread.
  Longer operations show progress, and unchanged auctions are cached.
- Save errors report the actual problem rather than always blaming Excel.
- Stopping research interrupts pending HTTP requests and closes their resources,
  without advancing unfinished conversation history.
- Check for Updates said "check your internet connection" on some Windows
  PCs that were online. The app now checks secure connections the same way
  Windows and browsers do (Python's stricter checks rejected certificates
  added by antivirus web protection), and if a check does fail, the window
  says why.

## 0.1.2 — 2026-10-09

### Changed

- The default conditions are now a nine-step grading scale: Factory New,
  New, Perfect, Excellent, Fine, Very Good, Good, Fair and Poor.
- Importing a condition column understands usual auction wording for these
  ("NIB" → New, "LNIB" → Perfect, "VG" → Very Good, "parts gun" → Poor).
- Conditions now live in `data/conditions.yaml` in the main folder, one
  `Name: text` per line, so they're easy to edit in any text editor. Saved
  changes show up in the app right away; a mistake in the file is reported
  (with its line number) and the previous conditions stay in use. Settings
  has an **Open file…** button, and the table there still works. Conditions
  saved by 0.1.1 move to the file automatically.
- Imported lots start with no condition ("Pick a condition"), and their
  title and description are left exactly as imported until someone picks
  one. A spreadsheet's condition column is only used if you choose it in
  the import window.

## 0.1.1 — 2026-10-09

### Added

- Import old auctions from Excel (.xlsx) or CSV files with **Import Excel…**
  in the sidebar. Columns are matched by their names (Lot #, Serial No.,
  Consignor, Cond., …) and can be changed before importing; a preview shows
  the lots first. Importing into an existing auction only adds lots it
  doesn't already have.
- Conditions are editable in Settings: add, remove, rename and reorder them,
  and change the text each one adds to the description. The first condition
  is the default for new lots. Lots keep their condition if it's later
  renamed or removed.
- Help → Check for Updates when running from source (e.g. on a Mac): lists
  the new changes on GitHub and updates and restarts in one click. A quiet
  check at startup notes waiting updates in the status bar. Local code edits
  are never overwritten; if one clashes, the update stops and changes nothing.
- Unexpected errors now show a message instead of failing silently, and are
  logged to `simple-auction.log` in the settings folder.

### Fixed

- Help → Check for Updates did nothing: the update window failed to open.

## 0.1.0 — 2026-10-08

First release.

### Added

- Auctions as Excel files, one per auction series (41000, 42000, …), with lots
  numbered automatically; set the next auction number in Settings.
- Sidebar with auctions and lots: multi-select, right-click to export or
  delete, and a "+" on each auction to add a lot.
- Lot editor with serial, year, condition, make, model, title, description,
  owner, book # and photos. Everything saves automatically.
- Condition, make and model fill in the title and description; titles are
  limited to 100 characters.
- Photos are renamed by lot (41001, 41001-1, …) and compressed to half their
  file size, in an "auction 41000 photos" folder.
- Serial number links (Lindcott Armory by default) and an optional serial
  table for year lookups.
- Research panel: ask Gemini about a lot, with Google Search when your plan
  includes it. The API key is stored in the system keychain.
- Light and dark themes, resizable panels, and in-app update checks.
