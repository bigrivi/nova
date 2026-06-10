import pytest

from nova.cli.chat_app import ChatApp, _split_history_window
from nova.db.database import Message


def _message(index: int, role: str = "user") -> Message:
    return Message(
        id=f"msg-{index}",
        session_id="session-1",
        role=role,
        content=f"message {index}",
        time_created=index,
    )


def test_split_history_window_keeps_tail_visible_without_marker():
    history = [_message(index) for index in range(10)]

    older, visible = _split_history_window(history, initial_size=4)

    assert [message.id for message in older] == [
        "msg-0",
        "msg-1",
        "msg-2",
        "msg-3",
        "msg-4",
        "msg-5",
    ]
    assert [message.id for message in visible] == [
        "msg-6",
        "msg-7",
        "msg-8",
        "msg-9",
    ]


@pytest.mark.asyncio
async def test_handle_message_forces_scroll_and_evicts_top(monkeypatch):
    app = ChatApp.__new__(ChatApp)
    calls: list[tuple[str, bool]] = []

    class FakeContainer:
        async def mount(self, widget):
            calls.append(("mount", False))

        def call_after_refresh(self, callback):
            callback()

        def scroll_end(self, **kwargs):
            pass

    async def fake_run_stream(text: str) -> None:
        calls.append(("stream", False))

    async def fake_evict(container, *, force: bool = False) -> None:
        calls.append(("evict", force))

    def fake_request_scroll_end(*, force: bool = False) -> None:
        calls.append(("scroll", force))

    monkeypatch.setattr(app, "query_one", lambda *args, **kwargs: FakeContainer())
    monkeypatch.setattr(app, "_run_stream", fake_run_stream)
    monkeypatch.setattr(app, "_evict_top_if_needed", fake_evict, raising=False)
    monkeypatch.setattr(app, "_request_scroll_end", fake_request_scroll_end, raising=False)

    await app._handle_message("hello")

    assert ("scroll", True) in calls
    assert ("evict", True) in calls
    assert calls[-1] == ("stream", False)
