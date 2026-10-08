# Changelog

## Unreleased

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
