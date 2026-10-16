APP_NAME = "Simple Auction"

# Autosave waits this long after the last edit, and retries this often if
# the Excel file is open elsewhere.
AUTOSAVE_MS = 2000
AUTOSAVE_RETRY_MS = 3000

# Lot titles, including the " - Excellent" condition suffix.
TITLE_MAX_LENGTH = 100

AUCTION_STEP = 1000
FIRST_AUCTION = 40000

# ProxiBid photo standard: at most 1024x768 (768x1024 for portrait) and 145 KB.
# The size limit is decimal (145,000 bytes), the stricter reading of "145k".
PHOTO_MAX_WIDTH = 1024
PHOTO_MAX_HEIGHT = 768
PHOTO_MAX_BYTES = 145_000
IMAGE_MIN_QUALITY = 20
IMAGE_MAX_QUALITY = 95

# Research panel (Gemini with Google Search). The cheapest current model with
# Search ($0.25 / $1.50 per 1M tokens in/out, Oct 2026); gemini-2.5-flash-lite
# is cheaper but closed to new accounts. On the free tier Google blocks Search
# and research answers without it; with billing, the first 5,000 searches a
# month are free. If Google retires this model, gemini-3.5-flash-lite is next.
RESEARCH_MODEL = "gemini-3.1-flash-lite"

# Each auction's photos go in <photos folder>/auction 41000 photos/, named
# 41001.jpg, 41001-1.jpg, 41001-2.jpg ...
PHOTO_FOLDER_NAME = "auction {auction} photos"
