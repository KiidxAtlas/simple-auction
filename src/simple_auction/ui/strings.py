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
SAVE_LOCKED_INLINE = "Not saved: close {file} in Excel"
SAVE_FAILED_INLINE = "Not saved: see the log"
UNSAVED_TITLE = "Unsaved changes"
UNSAVED_BODY = (
    "Lot {n} couldn't be saved. Close {file} in Excel and try again, "
    "or quit and lose the changes."
)
QUIT_ANYWAY = "Quit without saving"

ITEM_CARD = "Item"
CONSIGNMENT_CARD = "Consignment"
PHOTOS_CARD = "Photos"

SERIAL = "Serial #"
YEAR = "Year"
CONDITION = "Condition"
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
EXCEL_LOCKED_TITLE = "File is open"
EXCEL_LOCKED_BODY = "Close the Excel file and try again."
AUCTION_FULL_TITLE = "Auction full"


def count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
