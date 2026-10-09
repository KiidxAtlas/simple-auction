import asyncio
import threading
from types import SimpleNamespace as NS

import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import research
from simple_auction.ui.components.research_panel import _Job


@pytest.fixture(autouse=True)
def search_available():
    research.forget_search_check()
    yield
    research.forget_search_check()


class Stream:
    def __init__(self, events=(), stalled=False):
        self.events = iter(events)
        self.stalled = stalled
        self.waiting = asyncio.Event()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.events)
        except StopIteration:
            if self.stalled:
                self.waiting.set()
                await asyncio.Future()
            raise StopAsyncIteration from None

    async def close(self):
        self.closed = True


class Client:
    def __init__(self, create):
        self.closed = False
        self.async_closed = False
        self.aio = NS(interactions=NS(create=create), aclose=self.aclose)

    async def aclose(self):
        self.async_closed = True

    def close(self):
        self.closed = True


def _completed(id="turn-1"):
    return [
        NS(event_type="interaction.created", interaction=NS(id=id)),
        NS(event_type="step.delta", delta=NS(type="text", text="Answer")),
        NS(
            event_type="interaction.completed",
            interaction=NS(id=id, status="completed"),
        ),
    ]


def test_async_completion_and_followup_keep_conversation_contract():
    async def run():
        requests, streams = [], []

        async def create(**request):
            requests.append(request)
            stream = Stream(_completed(f"turn-{len(requests)}"))
            streams.append(stream)
            return stream

        chat = research.ResearchChat(Client(create))
        lot = Lot(lot_number=41001, make="Colt")
        first = [event async for event in chat.ask_async("Research", lot)]
        second = [event async for event in chat.ask_async("When?", lot)]
        assert [event.kind for event in first] == ["text", "done"]
        assert second[-1].kind == "done"
        assert "<lot_details>" in requests[0]["input"]
        assert requests[1]["input"] == "When?"
        assert requests[1]["previous_interaction_id"] == "turn-1"
        assert all(stream.closed for stream in streams)

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["headers", "stream"])
def test_cancellation_aborts_wait_closes_owned_client_and_preserves_history(
    monkeypatch, phase
):
    async def run():
        waiting = asyncio.Event()
        stream = Stream(_completed()[:2], stalled=True)

        async def create(**request):
            if phase == "headers":
                waiting.set()
                await asyncio.Future()
            return stream

        client = Client(create)
        monkeypatch.setattr(research, "make_client", lambda: client)
        chat = research.ResearchChat()
        chat._previous_id = "prior"
        chat._sent_context = "prior context"

        async def consume():
            return [
                event
                async for event in chat.ask_async("Research", Lot(lot_number=41001))
            ]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(
            (waiting if phase == "headers" else stream.waiting).wait(), 1
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert chat._previous_id == "prior"
        assert chat._sent_context == "prior context"
        assert client.closed and client.async_closed
        if phase == "stream":
            assert stream.closed

    asyncio.run(run())


def test_async_search_quota_retry_closes_stream_and_client(monkeypatch):
    async def run():
        requests = []
        stream = Stream(_completed())

        async def create(**request):
            requests.append(request)
            if len(requests) == 1:
                response = httpx.Response(
                    429, request=httpx.Request("POST", "https://example.invalid")
                )
                raise research.compat_errors.RateLimitError(
                    "quota", response=response, body=None
                )
            return stream

        client = Client(create)
        monkeypatch.setattr(research, "make_client", lambda: client)
        chat = research.ResearchChat()
        events = [
            event async for event in chat.ask_async("Research", Lot(lot_number=41001))
        ]
        assert "tools" in requests[0] and "tools" not in requests[1]
        assert [event.kind for event in events] == ["no_search", "text", "done"]
        assert stream.closed and client.closed and client.async_closed

    asyncio.run(run())


def test_job_stop_interrupts_a_stalled_request_and_emits_finished():
    app = QApplication.instance() or QApplication([])
    entered, cleaned, finished = (threading.Event() for _ in range(3))
    failures = []

    class Chat:
        async def ask_async(self, question, lot):
            try:
                entered.set()
                await asyncio.Future()
                yield research.Event("text", "unreachable")
            finally:
                cleaned.set()

    job = _Job(Chat(), "Research", Lot(lot_number=41001))
    job.finished.connect(finished.set, Qt.ConnectionType.DirectConnection)
    job.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    job.start()
    assert entered.wait(1)
    job.stop()
    job.stop()  # repeated Stop must not interrupt cleanup
    assert cleaned.wait(1)
    assert finished.wait(1)
    assert failures == []
    app.processEvents()


def test_job_stopped_before_start_never_makes_request():
    app = QApplication.instance() or QApplication([])
    finished = threading.Event()

    class Chat:
        async def ask_async(self, question, lot):
            raise AssertionError("must not start")
            yield

    job = _Job(Chat(), "Research", Lot(lot_number=41001))
    job.finished.connect(finished.set, Qt.ConnectionType.DirectConnection)
    job.stop()
    job.start()
    assert finished.wait(1)
    app.processEvents()


def test_actual_sdk_request_can_be_canceled_before_response_headers(monkeypatch):
    async def run():
        entered, aborted = asyncio.Event(), asyncio.Event()

        async def transport(request):
            try:
                entered.set()
                await asyncio.Future()
            finally:
                aborted.set()

        client = research.genai.Client(
            api_key="local-test-not-a-real-key",
            http_options={
                "base_url": "http://local-test.invalid",
                "async_client_args": {"transport": httpx.MockTransport(transport)},
            },
        )
        monkeypatch.setattr(research, "make_client", lambda: client)
        chat = research.ResearchChat()

        async def consume():
            return [
                event
                async for event in chat.ask_async("Research", Lot(lot_number=41001))
            ]

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            assert aborted.is_set()
            assert chat._previous_id is None and chat._sent_context is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await client.aio.aclose()
            client.close()

    asyncio.run(run())
