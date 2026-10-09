APP_TITLE = "Simple Auction"

# Sidebar
CREATE_NEW = "+  New Auction"
CREATE_NEW_TIP = "Start the next auction (+1000) with its first lot"
AUCTIONS_SECTION = "AUCTIONS"
AUCTION_ROW = "Auction {n}"
UNTITLED = "Untitled"
SETTINGS = "Settings"
SETTINGS_BTN = "⚙   Settings"
ADD_LOT_TIP = "Add a lot to this auction"
NEW_LOT = "New lot"
EXPORT_AUCTION = "Export..."
DELETE = "Delete"
DELETE_N = "Delete {n} items"

# Lot editor
LOT_HEADING = "Lot #{n}"
LOT_SUBTITLE = "Auction {n}"
EXPORT = "Export"
EXPORT_TIP = "Save a copy of this auction's Excel file"
SAVE = "Save"
ALL_SAVED = "✓ All changes saved"
SAVING = "Saving…"
SAVE_LOCKED_INLINE = "Not saved: can't write {file}"
SAVE_FAILED_INLINE = "Not saved: see the log"
UNSAVED_TITLE = "Unsaved changes"
UNSAVED_BODY = (
    "Lot {n} couldn't be saved to {file}:\n\n{error}\n\n"
    "Fix the problem and try again, or quit and lose the unsaved edits."
)
QUIT_ANYWAY = "Quit without saving"

ITEM_CARD = "Item"
CONSIGNMENT_CARD = "Consignment"
PHOTOS_CARD = "Photos"

SERIAL = "Serial #"
YEAR = "Year"
CONDITION = "Condition"
PICK_CONDITION = "Pick a condition"
TITLE = "Title"
DESC = "Description"
OWNER = "Owner"
BOOK_NO = "Book #"

SERIAL_PLACEHOLDER = "Serial number"
MAKE = "Make"
MODEL = "Model"
MAKE_PLACEHOLDER = "e.g. Remington"
MODEL_PLACEHOLDER = "e.g. 870 Wingmaster"
YEAR_PLACEHOLDER = "e.g. 1965"
TITLE_PLACEHOLDER = "Short listing title"
TITLE_TRIMMED = "Too long: the end of the title will be cut to fit the condition."
DESC_PLACEHOLDER = "Description shown to bidders"
OWNER_PLACEHOLDER = "Consignor name"
BOOK_PLACEHOLDER = "Book number"

LOOKUP_FOUND = "✓ Serial table: {title}, made {year}"
LOOKUP_SEVERAL = "Several matches, pick the right year: {matches}"
LOOKUP_NONE = "No match in the serial table."
LOOKUP_TABLE_ERROR = "The serial table has an error: {error}"
SERIAL_LINK = "{name} ↗"
SERIAL_LINK_TIP = "Open {name} with this serial filled in"

ADD_PHOTOS = "Add photos"
PICK_PHOTOS = "Choose photos"
NO_PHOTOS = "No photos yet."
PHOTOS_HINT = "Select a photo and press Delete to remove it."

# Research panel
RESEARCH = "Research"
RESEARCH_TIP = "Research this gun with Gemini and Google Search"
RESEARCH_CLOSE_TIP = "Close research"
RESEARCH_SUBTITLE = "Lot #{n}"
RESEARCH_START = "Research this lot"
RESEARCH_START_HINT = (
    "Uses the title, serial, year, condition and description. "
    "Owner and book # are not sent."
)
RESEARCH_TURN_LABEL = "Research this lot"
RESEARCH_ASK_PLACEHOLDER = "Ask about this gun…"
RESEARCH_ASK = "Ask"
RESEARCH_STOP = "Stop"
RESEARCH_YOU = "You:"
RESEARCH_SOURCES = "Sources"
RESEARCH_THINKING = "Thinking…"
RESEARCH_SEARCHING = "Searching the web…"
RESEARCH_READING = "Reading results…"
RESEARCH_WRITING = "Writing…"
RESEARCH_STOPPING = "Stopping…"
RESEARCH_STOPPED = "Stopped."
RESEARCH_REFUSED = (
    "Gemini couldn't finish this answer (it may have been blocked by a safety "
    "filter). Try rephrasing the question."
)
RESEARCH_NO_KEY = "No Gemini API key found. Add one in Settings."
RESEARCH_BAD_KEY = "Gemini rejected the API key. Check it in Settings."
RESEARCH_BUSY = (
    "Gemini's free limit was reached (too many requests per minute or per day). "
    "Wait a bit and try again."
)
RESEARCH_NO_SEARCH = (
    "Answered without Google Search, so not checked against the web: your "
    "Gemini plan doesn't include Search. Enabling billing in Google AI Studio "
    "turns it on (the first 5,000 searches a month are free)."
)
RESEARCH_NO_CREDIT = (
    "Your Gemini prepaid credit is used up. Add credit for this project in "
    "Google AI Studio (ai.studio/projects), then try again."
)
RESEARCH_OFFLINE = "Couldn't reach Gemini. Check your internet connection."
RESEARCH_API_ERROR = "The research request failed: {error}"
RESEARCH_FAILED = "Research failed, see the log."

EMPTY_TITLE = "No lot selected"
EMPTY_BODY = "Pick a lot in the sidebar, or start a new auction."

# Settings
PICK_FOLDER = "Choose main folder"
AUCTIONS_FOLDER = "Main folder:"
BROWSE = "Browse..."
PHOTOS_FOLDER = "Photos folder:"
NEXT_AUCTION = "Next auction number:"
PICK_PHOTOS_FOLDER = "Choose photos folder"
SERIAL_TABLE = "Serial number table:"
SERIAL_LINKS = "Serial number links:"
LINK_NAME = "Name"
LINK_URL = "Link"
ADD_LINK = "Add"
REMOVE_LINK = "Remove"
API_KEY = "Gemini API key:"
API_KEY_PLACEHOLDER = "Paste your key from aistudio.google.com/apikey"
API_KEY_SAVED = "Saved securely. Paste a new key to replace it."
FORGET_KEY = "Remove key"
CONDITIONS = "Conditions:"
CONDITION_NAME = "Name"
CONDITION_NOTE = "Text added to the description"
CONDITIONS_HINT = "Order here is the order in the dropdown."
OPEN_CONDITIONS_FILE = "Open file…"
OPEN_CONDITIONS_FILE_TIP = "Edit data/conditions.yaml in a text editor"
CONDITIONS_RELOADED = "Conditions updated from conditions.yaml"
CONDITIONS_FILE_ERROR_TITLE = "Problem in conditions.yaml"
CONDITIONS_FILE_ERROR = (
    "{error}\n\nThe previous conditions are still in use. Fix the file and "
    "save it again."
)
MOVE_UP = "↑"
MOVE_DOWN = "↓"
LINKS_HINT = "Use {serial}, {make} and {title} in the link."
EDIT_SERIAL_TABLE = "Edit serial table..."

# Messages
SAVED = "Saved lot {n}"
DELETED = "Deleted {what}"
EXPORTED = "Exported to {path}"
CONFIRM_DELETE = "Delete {what}?\n\nFiles will be moved to the Trash."
EXPORT_FAILED = "Export failed, see the log."
SAVE_FAILED = "Saving failed, see the log."
TRASH_FAILED = "Couldn't move {name} to the Trash."
EXCEL_LOCKED_TITLE = "Workbook can't be written"
EXCEL_LOCKED_BODY = "The workbook couldn't be written. Close it in Excel if it's open, or check file and folder permissions, then try again."
AUCTION_FULL_TITLE = "Auction full"


def count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# Updates
MENU_HELP = "Help"
MENU_CHECK_UPDATES = "Check for Updates…"
UPDATES_TITLE = "Check for Updates"
UPDATES_CLOSE = "Close"
SOURCE_UPDATES_CURRENT = "Running version {version} from source."
SOURCE_UP_TO_DATE = "You have every change from GitHub."
SOURCE_AVAILABLE = "{changes} on GitHub"
SOURCE_AVAILABLE_BODY = "Update to get them; the app will restart."
SOURCE_LOCAL_CHANGES = (
    "You have unsaved code edits in this folder. They'll be kept; if one "
    "clashes with an update, the update stops and nothing is changed."
)
SOURCE_UPDATE_BUTTON = "Update && Restart"
SOURCE_UPDATING = "Updating…"
SOURCE_FAILED_TITLE = "Couldn't update"
SOURCE_FAILED = "Nothing was changed.\n\n{error}"
SOURCE_UPDATES_WAITING = "{changes} available: Help → Check for Updates"
UPDATES_CURRENT = "You're running version {version}."
UPDATES_CHECKING = "Checking for updates…"
UPDATES_FAILED_TITLE = "Couldn't check for updates"
UPDATES_FAILED = "Check your internet connection and try again."
UPDATES_UP_TO_DATE = "✓ You're up to date"
UPDATES_LATEST = "Version {version} is the latest available."
UPDATES_AVAILABLE = "Update available: version {version}"
UPDATES_AVAILABLE_BODY = "A new version is ready to download."
UPDATES_RELEASE_PAGE = "Release page"
UPDATES_INSTALL = "Download && Install"
UPDATES_DOWNLOADING_BTN = "Downloading…"
UPDATES_NO_CHECKSUM_TIP = (
    "Automatic install is off because this release has no SHA-256 checksum."
)
UPDATES_NOT_VERIFIED_TITLE = "Update not verified"
UPDATES_NOT_VERIFIED = (
    "This release doesn't publish a SHA-256 checksum. Open the release page "
    "and download it manually."
)
UPDATES_DOWNLOADING_TITLE = "Downloading Update"
UPDATES_DOWNLOADING = "Downloading Simple Auction {version}…"
UPDATES_PERCENT = "Downloading update… {percent}%"
UPDATES_DOWNLOAD_FAILED_TITLE = "Download failed"
UPDATES_DOWNLOAD_FAILED = (
    "The update couldn't be downloaded. Try again later or use the release page."
)
UPDATES_READY_TITLE = "Update ready"
UPDATES_READY = (
    "The verified update was downloaded to:\n{path}\n\nOpen it to finish installing."
)

# Import
IMPORT_BTN = "⤓   Import Excel…"
IMPORT_PICK = "Choose old auction spreadsheets"
IMPORT_TITLE = "Import Auction"
IMPORT_HEADING = "Import {name}"
IMPORT_ROWS = "{n} rows found."
IMPORT_AUCTION = "Auction number:"
IMPORT_MERGE_NOTE = (
    "Auction {n} already exists: only lots it doesn't have yet will be added."
)
IMPORT_RENUMBER = "Renumber lots starting at the auction number"
IMPORT_COLUMNS = "Columns"
IMPORT_PREVIEW = "Preview"
IMPORT_SKIP = "— not imported —"
IMPORT_UNNAMED = "Column {n}"
IMPORT_LOT = "Lot #"
IMPORT_BUTTON = "Import"
IMPORT_SUMMARY = "{lots} will be imported into auction {n}."
IMPORT_ALREADY = "{lots} already in that auction will be left as they are."
IMPORT_SKIPPED = "{rows} skipped (duplicate lot number or outside the auction)."
IMPORT_READ_FAILED_TITLE = "Couldn't read file"
IMPORT_READ_FAILED = "{name} couldn't be read as a spreadsheet: {error}"
IMPORT_EMPTY = "{name} has no rows to import."
IMPORTED = "Imported {lots} into auction {n}"
IMPORTED_NONE = "Nothing imported: auction {n} already has those lots."

# Errors
ERROR_TITLE = "Something went wrong"
ERROR_BODY = (
    "That didn't work because of an unexpected error:\n\n{error}\n\n"
    "Details were saved to {log}"
)

# Storage and explicit settings recovery
SAVE_FAILED_DETAIL = "Couldn't save lot {n}:\n\n{error}\n\nYour edits are still open. Fix the problem and try again."
SAVE_ERROR_INLINE = "Couldn't save: {error}"
IO_SAVING = "Saving lot…"
IO_LOADING = "Loading catalogue…"
IO_IMPORTING = "Importing lots…"
IO_DELETING = "Deleting lots…"
CATALOGUE_READ_FAILED = (
    "Couldn't load auction {n}:\n\n{error}\n\nThe files were not overwritten."
)
CONFIG_RECOVERY_TITLE = "Settings need recovery"
CONFIG_RECOVERY_BODY = (
    "{error}\n\nYou can repair the file and retry, restore the last saved settings, "
    "or choose your existing main and photos folders to create new settings. "
    "Recovery preserves a copy of the damaged file. Auction files are not deleted."
)
CONFIG_RESTORE = "Restore backup"
CONFIG_RESET = "Choose folders…"
CONFIG_PICK_BASE = "Choose your existing main folder (containing auctions and data)"
CONFIG_PICK_PHOTOS = "Choose your existing photos folder"
ALREADY_RUNNING = "Another Simple Auction instance is running, or the settings folder cannot be locked. Close the other instance or check folder permissions before trying again."

DARK_MODE = "Dark mode"
