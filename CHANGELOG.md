# Changelog

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
