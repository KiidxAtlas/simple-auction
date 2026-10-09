"""Research a lot with Gemini (plus Google Search), as a running conversation."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

from google import genai

# The Interactions API raises these (not google.genai.errors); the SDK only
# exposes them from this module.
from google.genai._gaos.lib import compat_errors

from simple_auction.constants import RESEARCH_MODEL
from simple_auction.models import Lot
from simple_auction.services import api_key

SYSTEM_PROMPT = """\
You are a research assistant for staff at a firearms auction house who are \
cataloguing consigned items. Each conversation is about one lot. Its catalogue \
details are given in <lot_details> tags, and staff may update them during the \
conversation.

When asked to research the lot, give a briefing a cataloguer can use: what the \
item is (maker, model, variant), when and where it was made, including what \
the serial number indicates about the date of manufacture if that can be \
determined, notable history or variants, the features that drive collector \
value, a realistic auction value range with recent comparable sales where you \
can find them, and what to verify in person (markings, matching numbers, \
originality). Answer follow-up questions directly.

Use Google Search to check facts, preferring manufacturer records, collector \
references and auction results. Say plainly when something is uncertain or \
can't be confirmed, rather than guessing. Keep answers skimmable with short \
headings or bullet points, and don't repeat the lot details back."""

RESEARCH_REQUEST = "Research this lot for the catalogue."

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
    "no_search" (answering without Google Search), "done" (with sources)
    or "refused".
    """

    kind: str
    text: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)  # (title, url)


class MissingApiKeyError(Exception):
    """GEMINI_API_KEY isn't set (normally it comes from .env)."""


class ResearchFailedError(Exception):
    """Gemini reported an error part-way through an answer."""


def describe_lot(lot: Lot) -> str:
    """The lot fields sent for research. Owner and book # stay local."""
    fields = [
        ("Lot number", str(lot.lot_number)),
        ("Make", lot.make),
        ("Model", lot.model),
        ("Title", lot.title),
        ("Serial number", lot.serial),
        ("Year of manufacture (as catalogued)", str(lot.year or "")),
        ("Condition", lot.condition),
        ("Description", lot.desc),
    ]
    return "\n".join(f"{name}: {value}" for name, value in fields if value)


def make_client() -> genai.Client:
    key = api_key.current()  # Settings (Keychain), else .env
    if not key:
        raise MissingApiKeyError
    return genai.Client(api_key=key)


class ResearchChat:
    """A conversation about one lot. Not thread-safe: one question at a time.

    Gemini keeps the history server-side; each turn points at the previous one
    with previous_interaction_id.
    """

    def __init__(self, client: genai.Client | None = None) -> None:
        self._client = client
        self._previous_id: str | None = None
        self._sent_context: str | None = None

    def ask(self, question: str, lot: Lot) -> Iterator[Event]:
        """Stream the answer to `question`.

        Lot details go along with the first question, and again whenever
        they've changed. The conversation only moves on once an answer
        completes, so a failed or stopped question can simply be asked again.
        """
        context, request = self._request(question, lot)
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
        yield response.finish(self, context)

    def _request(self, question: str, lot: Lot) -> tuple[str, dict]:
        context = describe_lot(lot)
        content = question
        if context != self._sent_context:
            content = f"<lot_details>\n{context}\n</lot_details>\n\n{question}"
        request = {
            "model": RESEARCH_MODEL,
            "input": content,
            "system_instruction": SYSTEM_PROMPT,
            "stream": True,
        }
        if not _search_blocked:
            request["tools"] = _TOOLS
        if self._previous_id:
            request["previous_interaction_id"] = self._previous_id
        return context, request

    async def ask_async(self, question: str, lot: Lot) -> AsyncIterator[Event]:
        """Cancelable request, including waits for headers and stalled streams.

        Own clients are scoped to one event loop/turn, while conversation IDs
        remain on this chat. Cancellation never advances an unfinished turn.
        """
        context, request = self._request(question, lot)
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
            if "tools" not in request:
                yield Event("no_search")
            response = _Response()
            async for raw in stream:
                event = response.consume(raw)
                if event is not None:
                    yield event
            yield response.finish(self, context)
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
                        if getattr(a, "type", None) == "url_citation" and a.url:
                            self.sources.setdefault(a.url, a.title or a.url)
            case "interaction.completed":
                self.status = event.interaction.status
                self.interaction_id = self.interaction_id or event.interaction.id
            case "error":
                message = getattr(event.error, "message", None)
                raise ResearchFailedError(message or "unknown error")
        return None

    def finish(self, chat: ResearchChat, context: str) -> Event:
        if self.status != "completed":
            return Event("refused")
        chat._previous_id = self.interaction_id
        chat._sent_context = context
        return Event("done", sources=[(t, u) for u, t in self.sources.items()])
