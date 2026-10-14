from types import SimpleNamespace as NS

import httpx
import pytest
from google.genai._gaos.lib import compat_errors

from simple_auction.constants import RESEARCH_MODEL
from simple_auction.models import Lot
from simple_auction.services import research
from simple_auction.services.research import (
    MissingApiKeyError,
    ResearchChat,
    ResearchFailedError,
    describe_lot,
)


class FakeStream:
    def __init__(self, events, fail_after=None):
        self.events, self.fail_after = events, fail_after
        self.closed = False

    def __iter__(self):
        for i, event in enumerate(self.events):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("connection dropped")
            yield event

    def close(self):
        self.closed = True


class FakeClient:
    """Plays back one FakeStream per request and records the requests."""

    def __init__(self, *streams):
        self.streams = list(streams)
        self.requests = []
        self.interactions = NS(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        return self.streams.pop(0)


def created(i):
    return NS(event_type="interaction.created", interaction=NS(id=i))


def step(kind):
    return NS(event_type="step.start", step=NS(type=kind))


def text(t):
    return NS(event_type="step.delta", delta=NS(type="text", text=t))


def cite(url, title):
    ann = NS(type="url_citation", url=url, title=title)
    return NS(
        event_type="step.delta",
        delta=NS(type="text_annotation_delta", annotations=[ann]),
    )


def completed(status="completed"):
    return NS(
        event_type="interaction.completed", interaction=NS(id=None, status=status)
    )


def answer(t, interaction_id="i1", status="completed"):
    return FakeStream([created(interaction_id), text(t), completed(status)])


LOT = Lot(41002, title="Remington 870", serial="A123", owner="J. Miller", book_no="7")


def run(chat, question, lot=LOT):
    return list(chat.ask(question, lot))


def test_describe_lot_leaves_out_owner_and_book():
    d = describe_lot(LOT)
    assert "Remington 870" in d and "A123" in d
    assert "Miller" not in d and "Book" not in d


def test_condition_included():
    assert "Condition: Fair" in describe_lot(Lot(1, title="Colt", condition="Fair"))


def test_request_uses_model_search_and_system_prompt():
    client = FakeClient(answer("a"))
    run(ResearchChat(client), "Q")
    req = client.requests[0]
    assert req["model"] == RESEARCH_MODEL == "gemini-3.1-flash-lite"
    assert req["tools"] == [{"type": "google_search"}]
    assert req["stream"] is True
    assert "auction house" in req["system_instruction"]
    assert "previous_interaction_id" not in req


def test_follow_ups_chain_and_resend_details_only_when_changed():
    client = FakeClient(answer("a", "i1"), answer("b", "i2"), answer("c", "i3"))
    chat = ResearchChat(client)
    run(chat, "Q1")
    run(chat, "Q2")
    run(chat, "Q3", Lot(41002, title="Remington 870 Wingmaster", serial="A123"))
    first, second, third = client.requests
    assert first["input"].startswith("<lot_details>") and first["input"].endswith("Q1")
    assert second["input"] == "Q2" and second["previous_interaction_id"] == "i1"
    assert "Wingmaster" in third["input"] and third["previous_interaction_id"] == "i2"


def test_streams_text_status_and_sources():
    events = [
        created("i1"),
        step("google_search_call"),
        step("google_search_result"),
        step("model_output"),
        text("Made in "),
        text("1972."),
        cite("https://example.com/870", "870 history"),
        cite("https://example.com/870", "870 history"),  # duplicates collapse
        completed(),
    ]
    stream = FakeStream(events)
    got = run(ResearchChat(FakeClient(stream)), "Q")
    assert [e.kind for e in got] == ["searching", "reading", "text", "text", "done"]
    assert got[-1].sources == [("870 history", "https://example.com/870")]
    assert stream.closed


def test_incomplete_answer_reported_and_not_built_on():
    client = FakeClient(answer("", "i1", status="failed"), answer("ok", "i2"))
    chat = ResearchChat(client)
    assert run(chat, "Q")[-1].kind == "refused"
    run(chat, "Q again")
    retry = client.requests[1]
    assert "previous_interaction_id" not in retry
    assert retry["input"].startswith("<lot_details>")


def test_error_event_raises():
    err = NS(event_type="error", error=NS(message="quota exceeded"))
    with pytest.raises(ResearchFailedError, match="quota"):
        run(ResearchChat(FakeClient(FakeStream([created("i1"), err]))), "Q")


def test_dropped_connection_leaves_conversation_unchanged():
    failing = FakeStream([created("i1"), text("a"), completed()], fail_after=2)
    client = FakeClient(answer("first", "i0"), failing, answer("ok", "i2"))
    chat = ResearchChat(client)
    run(chat, "Q1")
    with pytest.raises(RuntimeError):
        run(chat, "Q2")
    assert failing.closed
    run(chat, "Q2")  # retry continues from the last good answer
    assert client.requests[2]["previous_interaction_id"] == "i0"


def test_stopped_answer_leaves_conversation_unchanged():
    client = FakeClient(answer("long answer", "i1"), answer("ok", "i2"))
    chat = ResearchChat(client)
    events = chat.ask("Q", LOT)
    next(events)
    events.close()  # user pressed Stop
    run(chat, "Q")
    assert "previous_interaction_id" not in client.requests[1]


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(research.api_key, "saved", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        run(ResearchChat(), "Q")


def test_settings_key_used_before_env(monkeypatch):
    monkeypatch.setattr(research.api_key, "saved", lambda: "from-keychain")
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert research.api_key.current() == "from-keychain"


def _quota_error():
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(429, request=request)
    return compat_errors.RateLimitError("quota", response=response, body=None)


class SearchBlockedClient(FakeClient):
    """Like the free tier: requests with Google Search get a quota error."""

    def _create(self, **request):
        self.requests.append(request)
        if "tools" in request:
            raise _quota_error()
        return self.streams.pop(0)


def test_free_tier_answers_without_search_and_remembers(monkeypatch):
    monkeypatch.setattr(research, "_search_blocked", False)
    client = SearchBlockedClient(answer("a", "i1"), answer("b", "i2"))
    chat = ResearchChat(client)
    first = run(chat, "Q1")
    assert first[0].kind == "no_search" and first[-1].kind == "done"
    run(chat, "Q2")
    # Q1 tried search then retried without; Q2 skipped search straight away.
    assert ["tools" in r for r in client.requests] == [True, False, False]
    research.forget_search_check()
    assert research._search_blocked is False


def test_real_rate_limit_without_search_still_raises(monkeypatch):
    monkeypatch.setattr(research, "_search_blocked", True)

    class Busy(FakeClient):
        def _create(self, **request):
            raise _quota_error()

    with pytest.raises(compat_errors.RateLimitError):
        run(ResearchChat(Busy()), "Q")


def test_photos_are_sent_once_and_autofill_parses_suggestions(tmp_path):
    import asyncio
    import json

    from PIL import Image

    from simple_auction.services.title_layout import CustomField

    photo = tmp_path / "front.jpg"
    Image.new("RGB", (3000, 2000)).save(photo)
    caliber = CustomField("cal1", "Caliber")
    requests = []

    class Stream:
        def __init__(self, events):
            self.events = iter(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration:
                raise StopAsyncIteration from None

        async def close(self):
            pass

    answers = [
        json.dumps(
            {
                "make": "Colt",
                "model": "Python",
                "year": "about 1965",
                "serial": "",
                "barrel_length": "6 inches",
                "custom_cal1": ".357 Magnum",
            }
        ),
        "Answer",
    ]

    async def create(**request):
        requests.append(request)
        return Stream([created(f"i{len(requests)}"), text(answers.pop(0)), completed()])

    client = NS(aio=NS(interactions=NS(create=create)))
    chat = ResearchChat(client, custom_fields=[caliber])
    lot = Lot(1, make="Colt", photos=[photo], custom={"cal1": ""})

    async def run():
        filled = [e async for e in chat.autofill_async(lot)]
        followup = [e async for e in chat.ask_async("When?", lot)]
        return filled, followup

    filled, followup = asyncio.run(run())
    assert ("photos", "1") in [(e.kind, e.text) for e in filled]
    (result,) = [e for e in filled if e.kind == "filled"]
    # Bad years are dropped; custom fields come back under their title key.
    assert result.values == {
        "make": "Colt",
        "model": "Python",
        "barrel_length": "6 inches",
        caliber.key: ".357 Magnum",
    }
    first = requests[0]
    assert first["response_format"]["schema"]["properties"]["custom_cal1"]
    parts = first["input"]
    assert parts[0]["type"] == "text" and "Caliber" not in parts[0]["text"]
    assert parts[1]["type"] == "image" and parts[1]["mime_type"] == "image/jpeg"
    # The follow-up continues the conversation without re-sending the photo.
    assert isinstance(requests[1]["input"], str)
    assert requests[1]["previous_interaction_id"] == "i1"
    assert "response_format" not in requests[1]
    assert not any(e.kind == "photos" for e in followup)


def test_photos_can_be_switched_off(tmp_path):
    from PIL import Image

    photo = tmp_path / "front.jpg"
    Image.new("RGB", (10, 10)).save(photo)
    chat = ResearchChat(FakeClient(answer("Hi")), include_photos=False)
    run(chat, "Q", Lot(1, photos=[photo]))
    assert isinstance(chat._client.requests[0]["input"], str)
