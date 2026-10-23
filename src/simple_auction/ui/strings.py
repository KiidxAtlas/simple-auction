APP_TITLE = "Simple Auction"

# Sidebar
CREATE_NEW = "New auction"
CREATE_NEW_TIP = "Start the next auction (+1000) with its first lot"
AUCTIONS_SECTION = "AUCTIONS"
AUCTION_ROW = "Auction {n}"
UNTITLED = "Untitled"
SETTINGS = "Settings"
SETTINGS_BTN = "Settings"
ADD_LOT_TIP = "Add a lot to this auction"
NEW_LOT = "New lot"
NEW_LOT_TIP = "Add the next lot to this auction (Ctrl+N)"
EXPORT_AUCTION = "Export to Excel…"
DELETE = "Delete"
DELETE_N = "Delete {n} items"
SIDEBAR_SEARCH = "Search lots"
SIDEBAR_NO_MATCH = "No lots match your search."
SIDEBAR_EMPTY = "No auctions yet. Create one to start cataloguing."
SIDEBAR_ATTENTION = "Needs attention ({n})"
SIDEBAR_ATTENTION_TIP = "Show only lots that still need a title or condition"
INCOMPLETE_TIP = "Still needs: {fields}"

# Lot editor
LOT_HEADING = "Lot #{n}"
LOT_SUBTITLE = "Auction {n}"
LOT_BREADCRUMB = "Auction {auction}  ›  Lot {lot}"
UNTITLED_LOT = "Untitled lot"
PREV_LOT_TIP = "Previous lot (Ctrl+Page Up)"
NEXT_LOT_TIP = "Next lot (Ctrl+Page Down)"
MORE_TIP = "More actions"
EXPORT = "Export"
EXPORT_TIP = "Save a copy of this auction's Excel file"
EXPORT_AUCTION_N = "Export auction {n} to Excel…"
DELETE_LOT = "Delete this lot…"
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

IDENTIFICATION_CARD = "Identification"
LISTING_CARD = "Listing"
CONSIGNMENT_CARD = "Consignment"
PHOTOS_CARD = "Photos"
CUSTOM_FIELDS_CARD = "More details"

SERIAL = "Serial #"
YEAR = "Year"
CONDITION = "Condition"
PICK_CONDITION = "Pick a condition"
TITLE = "Title"
DESC = "Description"
OWNER = "Owner"
BOOK_NO = "Book #"
BARREL_LENGTH = "Barrel length"
CA_LEGALITY = "CA legality"
C_AND_R = "C&&R"  # "&&" shows a literal "&" in a Qt label
C_AND_R_CHECK = "C&&R"
C_AND_R_TIP = 'Curio & Relic eligible. Adds "C&R" to the title.'

SERIAL_PLACEHOLDER = "Serial number"
MAKE = "Make"
MODEL = "Model"
MAKE_PLACEHOLDER = "e.g. Remington"
MODEL_PLACEHOLDER = "e.g. 870 Wingmaster"
YEAR_PLACEHOLDER = "e.g. 1965"
BARREL_PLACEHOLDER = "e.g. 18 inches"
CALIBER = "Caliber"
CALIBER_PLACEHOLDER = "e.g. 7.62x39"
GUN_TYPE = "Type"
GUN_TYPE_PLACEHOLDER = "Rifle, Shotgun or Handgun"
NONE_CHOICE = "None"  # the blank choice in a dropdown list
TITLE_PLACEHOLDER = "Short listing title"
TITLE_TRIMMED = "Too long: the end of the title will be cut to fit the condition."
AUTO_BADGE = "Auto-filled"
TITLE_AUTO_TIP = (
    "Built from the fields chosen in Settings → Listing fields. "
    "You can add your own wording too."
)
DESC_AUTO_TIP = (
    "The field lines chosen in Settings → Listing fields and the condition "
    "sentence are kept up to date automatically."
)
DESC_PLACEHOLDER = "Description shown to bidders"
OWNER_PLACEHOLDER = "Consignor name"
BOOK_PLACEHOLDER = "Book number"

LOOKUP_FOUND = "✓ Serial table: {title}, made {year}"
LOOKUP_SEVERAL = "Several matches, pick the right year: {matches}"
LOOKUP_NONE = "No match in the serial table."
LOOKUP_TABLE_ERROR = "The serial table has an error: {error}"
SERIAL_LINK = "{name}"
SERIAL_LINK_TIP = "Open {name} with this serial filled in"
SERIAL_LINK_NEEDS_SERIAL = "Enter a serial number to look it up on {name}"
LOOK_UP_ON = "Look up on:"

ADD_PHOTOS = "Add photos…"
PICK_PHOTOS = "Choose photos"
NO_PHOTOS = "Drop photos here, or use Add photos."
PHOTOS_DROP_HINT = "JPEG, PNG, HEIC or WebP"
PHOTOS_HINT = "Drop more photos here. Select one and press Delete to remove it."
PHOTO_SIZE_BADGE = "{width}×{height} · {size} KB"
PHOTO_WILL_RESIZE = (
    "Will be resized to ProxiBid standards (1024×768, 145 KB) when saved."
)
PHOTO_PREVIEW = "View larger"
PHOTO_ROTATE_LEFT = "Rotate left"
PHOTO_ROTATE_RIGHT = "Rotate right"
PHOTO_MAKE_MAIN = "Make main photo"
PHOTO_MOVE_EARLIER = "Move earlier"
PHOTO_MOVE_LATER = "Move later"
PHOTO_REMOVE = "Remove"
PHOTO_ROTATE_FAILED_TITLE = "Rotate photos"
PHOTO_ROTATE_FAILED = "Could not rotate {name}."
PHOTO_PREVIEW_TITLE = "Photo"
PHOTO_CAPTION = "{n} of {total} · {name} · {width}×{height} · {size}"
PHOTO_UNREADABLE = "{name} could not be shown."
PREVIOUS = "Previous"
NEXT = "Next"
CLOSE = "Close"
PHOTOS_FIXED = "Resized {photos} to ProxiBid standards"

# Research panel
RESEARCH = "Research"
RESEARCH_TIP = "Research this gun with Gemini and Google Search"
RESEARCH_CLOSE_TIP = "Close research"
RESEARCH_SUBTITLE = "Lot #{n}"
RESEARCH_START = "Research this lot"
RESEARCH_EMPTY_TITLE = "Look up this gun"
RESEARCH_START_HINT = (
    "Get a short identification note and what to verify next. "
    "Details and enabled photos go to Google Gemini; owner and book # stay local. "
    "Ask a follow-up for more detail."
)
RESEARCH_TURN_LABEL = "Research this lot"
RESEARCH_INCLUDE_PHOTOS = "Include photos in research"
RESEARCH_INCLUDE_PHOTOS_TIP = (
    "Let Gemini see up to 6 of the lot's photos (sent again only when they change)"
)
RESEARCH_PHOTOS_SENT = "{n} photo(s) sent."
AUTOFILL = "Auto-fill fields"
AUTOFILL_TIP = (
    "Let Gemini suggest make, model, year, serial, barrel length and your own "
    "fields from the details, photos and research. You review them first."
)
AUTOFILL_TURN_LABEL = "Auto-fill this lot's fields"
AUTOFILL_WORKING = "Finding values for the fields…"
AUTOFILL_FOUND = (
    "Suggested values for: {fields}. Review them in the window that opened."
)
AUTOFILL_NOTHING = "No field values could be found for this lot."
AUTOFILL_TITLE = "Auto-fill fields"
AUTOFILL_INTRO = (
    "Ticked suggestions go into the lot when you click Fill. Check them "
    "against the item: they come from Gemini and may be wrong. You can edit "
    "a suggestion before filling it in."
)
AUTOFILL_REPLACES = "Replaces: {value}"
AUTOFILL_SAME = "Already filled in with this value."
AUTOFILL_APPLY = "Fill selected"
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
EMPTY_BODY = (
    "Pick a lot in the sidebar, start a new auction, or import an old spreadsheet."
)
EMPTY_IMPORT = "Import from Excel…"

# Settings
SETTINGS_FOOTER_HINT = "Changes take effect when you click Save."
SETTINGS_AUCTION_ABOUT = (
    "How new auctions are numbered and where serial numbers are looked up."
)
SETTINGS_CONDITIONS_ABOUT = "The choices in each lot's Condition dropdown and the sentence each one adds to the description."
SETTINGS_LISTING_ABOUT = (
    "Choose which details go into each lot's title and description, put them "
    "in order, and add fields of your own."
)
SETTINGS_APPEARANCE_ABOUT = "How Simple Auction looks."
SETTINGS_SHARING_ABOUT = "Work on the same auctions from two computers on your network."
SETTINGS_FOLDERS_ABOUT = "Where auctions, data and photos are stored."
SETTINGS_RESEARCH_ABOUT = "Lot research with Google Gemini."
PICK_FOLDER = "Choose main folder"
AUCTIONS_FOLDER = "Main folder"
MAIN_FOLDER_HINT = "Auction workbooks, conditions and shipping files are kept here."
BROWSE = "Browse…"
SHOW_FOLDER = "Open"
SHOW_FOLDER_TIP = "Show this folder in Explorer / Finder"
PHOTOS_FOLDER = "Photos folder"
PHOTOS_FOLDER_HINT = "Each auction's photos go in a subfolder named after it."
FOLDERS_SECTION = "Storage locations"
NUMBERING_SECTION = "Auction numbering"
NEXT_AUCTION = "Next auction number:"
NEXT_AUCTION_HINT = (
    "New auction creates this auction next; the following ones count up from it."
)
PICK_PHOTOS_FOLDER = "Choose photos folder"
SERIAL_TABLE = "Serial number table:"
SERIAL_LINKS = "Serial number links:"
SERIAL_LOOKUP_SECTION = "Serial number lookup sites"
SERIAL_LOOKUP_ABOUT = "Each site becomes a button under a lot's Serial # field that opens the site with the serial filled in."
SERIAL_TABLE_ABOUT = (
    "Serials are also checked against your own serial table to fill in the year."
)
LINK_NAME = "Name"
LINK_NAME_PLACEHOLDER = "e.g. Lindcott Armory"
LINK_URL = "Link"
LINKS_EMPTY = "Select a site to edit it, or click Add site."
ADD_LINK = "Add site"
REMOVE_LINK = "Remove"
RESEARCH_SECTION = "Gemini API key"
RESEARCH_ABOUT = "Research needs your own free Gemini API key. It is stored in the system keychain, never in a file."
API_KEY = "API key"
API_KEY_PLACEHOLDER = "Paste your key here"
API_KEY_SAVED_PLACEHOLDER = "Paste a new key to replace the saved one"
API_KEY_SAVED = "✓ A key is saved."
API_KEY_NONE = "No key saved yet."
SHOW_KEY = "Show"
HIDE_KEY = "Hide"
GET_API_KEY = "Get a free key at aistudio.google.com"
GET_API_KEY_URL = "https://aistudio.google.com/apikey"
FORGET_KEY = "Remove key"
CONDITIONS = "Conditions:"
CONDITIONS_SECTION = "Condition choices"
CONDITION_NAME = "Name"
CONDITION_NAME_HINT = "e.g. Very good"
CONDITION_NOTE = "Text added to the description"
CONDITION_NOTE_PLACEHOLDER = (
    "The sentence added to a lot's description when this condition is picked."
)
CONDITIONS_EMPTY = "Select a condition to edit it, or click Add condition."
ADD_CONDITION = "Add condition"
CONDITIONS_HINT = "The order here is the order in the dropdown. Drag a condition or use the arrows to move it."
CONDITIONS_FILE_ABOUT = "Conditions are stored in conditions.yaml, which you can also edit in a text editor."
OPEN_CONDITIONS_FILE = "Open conditions.yaml"
OPEN_CONDITIONS_FILE_TIP = "Edit data/conditions.yaml in a text editor"
CONDITIONS_RELOADED = "Conditions updated from conditions.yaml"
CONDITIONS_FILE_ERROR_TITLE = "Problem in conditions.yaml"
CONDITIONS_FILE_ERROR = (
    "{error}\n\nThe previous conditions are still in use. Fix the file and "
    "save it again."
)
LISTING_PREVIEW_SECTION = "Example"
LISTING_PREVIEW_HINT = (
    "How a lot's title and description come out with these settings. Empty "
    "fields and N/A are always left out. Changes apply to the open lot and "
    "future edits, not to lots already saved."
)
LISTING_PREVIEW_TITLE = "Title"
LISTING_PREVIEW_DESC = "Description"
LISTING_PREVIEW_DESC_TEXT = "Your own description text stays here."
LISTING_PREVIEW_CONDITION = "The condition sentence is added at the end."
LISTING_PREVIEW_VALUE = "your {label}"
LISTING_ARRANGE_SECTION = "What goes where"
LISTING_ARRANGE_HINT = (
    "Tick a field to include it. Drag fields, or select one and use the "
    "arrows, to set the order. A field can go in the title, the description, "
    "both or neither."
)
LISTING_TITLE_COLUMN = "Title"
LISTING_TITLE_HINT = (
    "Fields above “Your own wording” go before it; fields below go after it, "
    "after a dash."
)
LISTING_DESC_COLUMN = "Description"
LISTING_DESC_HINT = "Each ticked field becomes a line like “Make: Colt” at the top."
LISTING_OWN_WORDING = "Your own wording"
TITLE_FIELDS_CUSTOM_TIP = "Where the words you type in the Title box go"
FIELD_ORDER_HINT = "Drag, or select a field and use the arrows."
FIELD_MOVE_UP = "Move field up"
FIELD_MOVE_DOWN = "Move field down"
CUSTOM_FIELDS_SECTION = "Your own fields"
CUSTOM_FIELDS_HINT = (
    "Add details such as Caliber or Finish. Each one gets a box in the lot "
    "editor's More details card, and appears in the lists above so you can "
    "place it in the title or description."
)
CUSTOM_FIELDS_EMPTY = "Select a field to edit it, or click Add field."
ADD_CUSTOM_FIELD = "Add field"
CUSTOM_FIELD_NAME = "Name"
CUSTOM_FIELD_NAME_PLACEHOLDER = "e.g. Caliber"
CUSTOM_FIELD_NAME_HINT = (
    "Shown above its box in the lot editor and as the label in the description."
)
CUSTOM_FIELD_PREFIX = "Text before the value in the title (optional)"
CUSTOM_FIELD_PREFIX_PLACEHOLDER = "e.g. Cal:"
CUSTOM_FIELD_PREFIX_HINT = (
    "With “Cal:”, a lot with .45 ACP gets “Cal: .45 ACP” in its title. "
    "Leave empty to add just the value."
)
CUSTOM_FIELD_IN_LIST = "{label}  ·  your field"
THEME_SECTION = "Theme"
THEME_SYSTEM = "Match system"
THEME_LIGHT = "Light"
THEME_DARK = "Dark"
THEME_HINT = "Match system switches between light and dark along with your computer."
LINKS_HINT = "Use {serial}, {make} and {title} where the lot's values go."
EDIT_SERIAL_TABLE = "Edit serial table…"
EDIT_SERIAL_TABLE_TIP = "Open the serial number table (CSV) in your spreadsheet app"
# Messages
SAVED = "Saved lot {n}"
DELETED = "Deleted {what}"
UNDO = "Undo"
UNDO_RESTORED = "Restored {what}"
DUPLICATE_LOT = "Duplicate this lot"
SHORTCUTS_MENU = "Keyboard shortcuts…"
SHORTCUTS_TITLE = "Keyboard shortcuts"
SHORTCUTS_BODY = (
    "Ctrl+S\tSave now\n"
    "Ctrl+N\tNew lot in this auction\n"
    "Ctrl+D\tDuplicate this lot\n"
    "Ctrl+PgUp / Ctrl+PgDown\tPrevious / next lot\n"
    "Ctrl+G\tGo to a lot (type its number, press Enter)\n"
    "Delete\tDelete the selected lots in the list"
)
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
SOURCE_UPDATES_WAITING = "{changes} available"
SOURCE_UPDATES_WAITING_TIP = "Open Check for Updates"
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
IMPORT_BTN = "Import from Excel…"
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
IO_OPENING_SHARED = (
    "Opening the shared catalogue and checking photo sizes…\n"
    "The first start after an update can take a while."
)
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
SHIPPING_NAV = "Shipping"
CATALOGUE_NAV = "Catalogue"
OUTPUT_NAV = "Output"
COMPLETED_TODAY = "{lots} completed today"
COMPLETED_TODAY_TIP = (
    "Lots that became ready to publish today (every check in the work queue passed)."
)
HISTORY_UNLOCKED = "Elevated access is on. Output appears in the header."
LOCK_HISTORY = "Remove elevated privileges"
RELOAD_SHARED = "Reload from host"
