# Changelog

## Unreleased

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
