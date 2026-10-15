"""Research a lot with Gemini (plus Google Search), as a running conversation.

Besides questions, a chat can suggest values for the lot's empty fields
("auto-fill"), and it can send the lot's photos so Gemini can see the item.
"""

import base64
import json
import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from google import genai

# The Interactions API raises these (not google.genai.errors); the SDK only
# exposes them from this module.
from google.genai._gaos.lib import compat_errors

from simple_auction.constants import RESEARCH_MODEL
from simple_auction.models import Lot
from simple_auction.services import api_key
from simple_auction.services.image import research_image
from simple_auction.services.title_layout import GUN_TYPES, CustomField

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a research assistant for staff at a firearms auction house who are \
cataloguing consigned items. Each conversation is about one lot. Its catalogue \
details are given in <lot_details> tags, and staff may update them during the \
conversation. Photos of the lot may be attached; use them to identify the \
item and read markings, and say when a photo is unclear.

When asked to research the lot, give a brief catalogue note, not a full report. \
Aim for 120–180 words, with at most three short sections: Identification, \
Key facts, and Verify next. Prioritize maker/model/variant, supported dating \
(including serial evidence when available), and the most useful checks for \
staff. Include only relevant history or collector features. Do not include \
comparable sales, prices, or a long history unless explicitly requested. \
Do not automatically appraise the lot. Distinguish sold results from asking \
prices whenever discussing sales.

Answer follow-up questions directly, usually in under 100 words. Give a longer \
answer when staff explicitly ask for detail or when needed to preserve \
important uncertainty, conflicting evidence, or safety caveats. Brevity must \
never turn an uncertain identification or date into a confident claim.

Use Google Search to check facts, preferring manufacturer records, collector \
references and auction results. Say plainly when something is uncertain or \
can't be confirmed, rather than guessing. Use short headings and bullets; \
don't repeat the lot details back."""

RESEARCH_REQUEST = (
    "Give a brief catalogue research note for this lot: identification, "
    "key facts, and what staff should verify next."
)

COMPARABLES_REQUEST = """\
Find comparable auction sales and listings using only the supplied item details.
Do not search for or infer a serial number. Clearly label each result Sold or
Asking (never treat an asking price as a completed sale). Include source URL,
sale date, price, currency, whether buyer premium is included, condition and
important differences. Say unknown when evidence is missing. Do not appraise
this lot, calculate a valuation, or change catalogue fields. Staff must verify
sources and manually record comparables before using them."""


def comparable_lot(lot: Lot) -> Lot:
    """Allowlisted search context, excluding serials, free text and photos."""
    return Lot(
        lot_number=lot.lot_number,
        make=lot.make,
        model=lot.model,
        caliber=lot.caliber,
        gun_type=lot.gun_type,
        year=lot.year,
        condition=lot.condition,
        barrel_length=lot.barrel_length,
    )


def safe_source_url(url: str) -> bool:
    """Only ordinary HTTP(S) source links may leave the research viewer."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme.lower() in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and "\\" not in url
            and parsed.port != 0
        )
    except ValueError:
        return False


AUTOFILL_REQUEST = """\
Suggest catalogue values for this lot's fields, as JSON matching the schema. \
Use the lot details, the photos and what you've found in this conversation. \
Fill a field only when the details, the photos or reliable sources support it; \
otherwise leave it as an empty string. Never invent serial numbers: give one \
only if it is legible in a photo. Never resolve ambiguous O/0, I/1 or S/5 \
markings by guessing: omit uncertain fields for human review. Give years as \
four digits and lengths with their units (e.g. 26 inches)."""

# Fields auto-fill may suggest: (Lot attribute, label, guidance for Gemini).
AUTOFILL_FIELDS = [
    ("make", "Make", "The manufacturer, e.g. Remington."),
    ("model", "Model", "The model and variant, e.g. SAM7SF or 870 Wingmaster."),
    ("caliber", "Caliber", "Caliber or gauge as marked, e.g. 7.62x39 or 12 GA."),
    ("gun_type", "Type", "One of Rifle, Shotgun or Handgun."),
    ("year", "Year", "Year of manufacture, four digits."),
    ("serial", "Serial number", "Only if legible in a photo."),
    ("barrel_length", "Barrel length", "With units, e.g. 28 inches."),
]
CUSTOM_KEY = "custom_{id}"  # schema property for a custom field

MAX_PHOTOS = 6  # sent per lot; the first ones in the lot's order

_TOOLS = [{"type": "google_search"}]

# Set once Google refuses search for this key (free tier), so later questions
# skip straight to answering without it. Reset when the app restarts.
_search_blocked = False


def forget_search_check() -> None:
    """Try Google Search again (e.g. after the API key changes)."""
    global _search_blocked
    _search_blocked = False


@dataclass
class Event:
    """One step of a streamed answer.

    kind is "text" (a piece of the answer), "searching", "reading",
    "no_search" (answering without Google Search), "photos" (text says how
    many were sent), "done" (with sources), "filled" (auto-fill `values`)
    or "refused".
    """

    kind: str
    text: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)  # (title, url)
    values: dict[str, str] = field(default_factory=dict)


class MissingApiKeyError(Exception):
    """GEMINI_API_KEY isn't set (normally it comes from .env)."""


class ResearchFailedError(Exception):
    """Gemini reported an error part-way through an answer."""


def describe_lot(lot: Lot, custom_fields: list[CustomField] = ()) -> str:
    """The lot fields sent for research. Owner and book # stay local."""
    fields = [
        ("Lot number", str(lot.lot_number)),
        ("Make", lot.make),
        ("Model", lot.model),
        ("Caliber", lot.caliber),
        ("Type", lot.gun_type),
        ("Title", lot.title),
        ("Serial number", lot.serial),
        ("Year of manufacture (as catalogued)", str(lot.year or "")),
        ("Barrel length", lot.barrel_length),
        ("Condition", lot.condition),
        ("C&R eligible", "Yes" if lot.c_and_r else ""),
        *((f.label, lot.custom.get(f.id, "")) for f in custom_fields),
        ("Description", lot.desc),
    ]
    return "\n".join(f"{name}: {value}" for name, value in fields if value)


def photo_key(lot: Lot) -> tuple:
    """Identifies the photos that would be sent, to resend only on change."""
    key = []
    for path in lot.photos[:MAX_PHOTOS]:
        try:
            stat = Path(path).stat()
        except OSError:
            continue
        key.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(key)


def _image_parts(paths: list[Path]) -> list[dict]:
    parts = []
    for path in paths:
        prepared = research_image(Path(path))
        if prepared is None:
            log.warning("Couldn't prepare %s for research", path)
            continue
        data, mime = prepared
        parts.append(
            {
                "type": "image",
                "data": base64.b64encode(data).decode("ascii"),
                "mime_type": mime,
            }
        )
    return parts


def autofill_schema(custom_fields: list[CustomField]) -> dict:
    properties = {
        key: {"type": "string", "description": f"{label}. {hint}"}
        for key, label, hint in AUTOFILL_FIELDS
    }
    for custom in custom_fields:
        properties[CUSTOM_KEY.format(id=custom.id)] = {
            "type": "string",
            "description": custom.label,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
    }


def parse_autofill(text: str, custom_fields: list[CustomField]) -> dict[str, str]:
    """Suggestions from Gemini's JSON: {Lot attribute, or a custom field's
    title key ("custom:<id>"): value}.
    Empty, malformed and unexpected values are dropped."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ResearchFailedError("auto-fill answer wasn't valid JSON") from e
    if not isinstance(data, dict):
        raise ResearchFailedError("auto-fill answer wasn't a JSON object")
    keys = {key: key for key, _label, _hint in AUTOFILL_FIELDS}
    keys |= {CUSTOM_KEY.format(id=f.id): f.key for f in custom_fields}
    values = {}
    for key, target in keys.items():
        value = data.get(key)
        if not isinstance(value, str) or not (value := " ".join(value.split())):
            continue
        if target == "year" and not (value.isdigit() and len(value) == 4):
            continue
        if target == "gun_type":
            value = next(
                (t for t in GUN_TYPES if t.casefold() == value.casefold()), value
            )
        values[target] = value[:200]
    return values


def make_client() -> genai.Client:
    key = api_key.current()  # Settings (Keychain), else .env
    if not key:
        raise MissingApiKeyError
    return genai.Client(api_key=key)


@dataclass
class _Sent:
    """What a request includes, recorded once Gemini has answered it."""

    context: str
    photos: tuple
    photo_count: int = 0


class ResearchChat:
    """A conversation about one lot. Not thread-safe: one question at a time.

    Gemini keeps the history server-side; each turn points at the previous one
    with previous_interaction_id.
    """

    def __init__(
        self,
        client: genai.Client | None = None,
        *,
        custom_fields: list[CustomField] = (),
        include_photos: bool = True,
    ) -> None:
        self._client = client
        self._previous_id: str | None = None
        self._sent_context: str | None = None
        self._sent_photos: tuple = ()
        self.custom_fields = list(custom_fields)
        self.include_photos = include_photos

    def ask(self, question: str, lot: Lot) -> Iterator[Event]:
        """Stream the answer to `question`.

        Lot details go along with the first question, and again whenever
        they've changed; the same for photos. The conversation only moves on
        once an answer completes, so a failed or stopped question can simply
        be asked again.
        """
        sent, request = self._request(question, lot)
        if self._client is None:
            self._client = make_client()
        global _search_blocked
        try:
            stream = self._client.interactions.create(**request)
        except compat_errors.RateLimitError:
            if "tools" not in request:
                raise
            del request["tools"]
            stream = self._client.interactions.create(**request)
            _search_blocked = True
        if sent.photo_count:
            yield Event("photos", str(sent.photo_count))
        if "tools" not in request:
            yield Event("no_search")
        response = _Response()
        try:
            for raw in stream:
                event = response.consume(raw)
                if event is not None:
                    yield event
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()
        yield response.finish(self, sent)

    def _request(
        self, question: str, lot: Lot, *, schema: dict | None = None
    ) -> tuple[_Sent, dict]:
        context = describe_lot(lot, self.custom_fields)
        photos = photo_key(lot) if self.include_photos else ()
        text = question
        if context != self._sent_context:
            text = f"<lot_details>\n{context}\n</lot_details>\n\n{question}"
        content: str | list[dict] = text
        sent = _Sent(context, photos)
        if photos and photos != self._sent_photos:
            images = _image_parts([Path(p) for p, _mtime, _size in photos])
            if images:
                note = f"\n\n({len(images)} photo(s) of the lot attached.)"
                content = [{"type": "text", "text": text + note}, *images]
                sent.photo_count = len(images)
        request = {
            "model": RESEARCH_MODEL,
            "input": content,
            "system_instruction": SYSTEM_PROMPT,
            "stream": True,
        }
        if schema is not None:
            request["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            }
        if not _search_blocked:
            request["tools"] = _TOOLS
        if self._previous_id:
            request["previous_interaction_id"] = self._previous_id
        return sent, request

    async def ask_async(self, question: str, lot: Lot) -> AsyncIterator[Event]:
        """Cancelable request, including waits for headers and stalled streams.

        Own clients are scoped to one event loop/turn, while conversation IDs
        remain on this chat. Cancellation never advances an unfinished turn.
        """
        sent, request = self._request(question, lot)
        async for event in self._stream_async(sent, request):
            yield event

    async def autofill_async(self, lot: Lot) -> AsyncIterator[Event]:
        """Suggest values for the lot's fields: progress events, then one
        "filled" event (or "refused"). It is a turn of the conversation, so
        Gemini can use what was researched and the photos already sent."""
        sent, request = self._request(
            AUTOFILL_REQUEST, lot, schema=autofill_schema(self.custom_fields)
        )
        answer = []
        async for event in self._stream_async(sent, request):
            if event.kind == "text":
                answer.append(event.text)
            elif event.kind == "done":
                yield Event(
                    "filled", values=parse_autofill("".join(answer), self.custom_fields)
                )
            else:
                yield event

    async def _stream_async(self, sent: _Sent, request: dict) -> AsyncIterator[Event]:
        client = self._client or make_client()
        owned = self._client is None
        stream = None
        global _search_blocked
        try:
            try:
                stream = await client.aio.interactions.create(**request)
            except compat_errors.RateLimitError:
                if "tools" not in request:
                    raise
                del request["tools"]
                stream = await client.aio.interactions.create(**request)
                _search_blocked = True
            if sent.photo_count:
                yield Event("photos", str(sent.photo_count))
            if "tools" not in request:
                yield Event("no_search")
            response = _Response()
            async for raw in stream:
                event = response.consume(raw)
                if event is not None:
                    yield event
            yield response.finish(self, sent)
        finally:
            try:
                if stream is not None:
                    await stream.close()
            finally:
                if owned:
                    try:
                        await client.aio.aclose()
                    finally:
                        client.close()


@dataclass
class _Response:
    interaction_id: str | None = None
    status: str | None = None
    sources: dict[str, str] = field(default_factory=dict)

    def consume(self, event) -> Event | None:
        match event.event_type:
            case "interaction.created":
                self.interaction_id = event.interaction.id
            case "step.start":
                if event.step.type == "google_search_call":
                    return Event("searching")
                if event.step.type == "google_search_result":
                    return Event("reading")
            case "step.delta":
                delta = event.delta
                if delta.type == "text" and delta.text:
                    return Event("text", delta.text)
                if delta.type == "text_annotation_delta":
                    for a in delta.annotations or []:
                        if getattr(
                            a, "type", None
                        ) == "url_citation" and safe_source_url(a.url):
                            self.sources.setdefault(a.url, a.title or a.url)
            case "interaction.completed":
                self.status = event.interaction.status
                self.interaction_id = self.interaction_id or event.interaction.id
            case "error":
                message = getattr(event.error, "message", None)
                raise ResearchFailedError(message or "unknown error")
        return None

    def finish(self, chat: ResearchChat, sent: _Sent) -> Event:
        if self.status != "completed":
            return Event("refused")
        chat._previous_id = self.interaction_id
        chat._sent_context = sent.context
        chat._sent_photos = sent.photos
        return Event("done", sources=[(t, u) for u, t in self.sources.items()])
