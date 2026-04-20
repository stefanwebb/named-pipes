"""Unit tests for STTServer.

stream_transcribe is stubbed so tests do not require a mic or model. We verify
that the three broadcast callbacks produce the correct JSON messages and that
_close() cleanly stops the worker thread.
"""

import json
import threading
import time

import pytest

pytest.importorskip("mlx")

import named_pipes.stt.server as stt_mod
from named_pipes.stt import STTConfig, STTServer
from named_pipes.text_named_pipe import Role, TextNamedPipe


class _StubStreamTranscribe:
    """Stand-in for voxtral.stream.stream_transcribe.

    Captures the callbacks passed by STTServer and blocks until
    stop_event is set. Tests invoke the captured callbacks directly.
    """

    def __init__(self):
        self.on_token = None
        self.on_start = None
        self.on_end = None
        self.stop_event = None
        self.entered = threading.Event()

    def __call__(self, **kwargs):
        self.on_token = kwargs["on_token"]
        self.on_start = kwargs["on_speaking_started"]
        self.on_end = kwargs["on_speaking_finished"]
        self.stop_event = kwargs["stop_event"]
        self.entered.set()
        self.stop_event.wait()


@pytest.fixture
def stub(monkeypatch):
    stub = _StubStreamTranscribe()
    monkeypatch.setattr(stt_mod, "stream_transcribe", stub)
    return stub


class _TestClient(TextNamedPipe):
    """Minimal concrete TextNamedPipe client for tests."""

    def msg_handler_fn(self, msg: dict, pid: int | None):  # noqa: D401
        pass


def _collect_messages(path: str, count: int, timeout: float = 2.0) -> list[dict]:
    """Subscribe a client-side reader and collect `count` broadcast messages."""
    client = _TestClient(path, Role.CLIENT)
    client.send_message(json.dumps({"pid": client._pid, "cmd": "subscribe"}))

    collected: list[dict] = []
    deadline = time.monotonic() + timeout

    def reader():
        while len(collected) < count and time.monotonic() < deadline:
            try:
                msg = client.recv_message()
            except Exception:
                return
            if msg.get("event") == "subscribed":
                continue
            collected.append(msg)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=timeout + 0.5)
    client._close()
    return collected


def test_construct_starts_worker_with_callbacks(stub):
    pipe = STTServer(STTConfig(name="stt-test"))
    try:
        assert stub.entered.wait(timeout=2.0), "worker thread never started"
        assert callable(stub.on_token)
        assert callable(stub.on_start)
        assert callable(stub.on_end)
        assert isinstance(stub.stop_event, threading.Event)
    finally:
        pipe._close()


def test_on_token_broadcasts_result_json(stub):
    with STTServer(STTConfig(name="stt-test")) as pipe:
        pipe.listen()
        assert stub.entered.wait(timeout=2.0)

        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages("/tmp/tool-stt-test", count=1))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)
        stub.on_token("hello")
        done.wait(timeout=2.0)

        assert collected == [{"event": "token", "text": "hello"}]


def test_on_speaking_events_broadcast_speech_start_end(stub):
    with STTServer(STTConfig(name="stt-test")) as pipe:
        pipe.listen()
        assert stub.entered.wait(timeout=2.0)

        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages("/tmp/tool-stt-test", count=4))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)
        stub.on_start()
        stub.on_end()
        done.wait(timeout=2.0)

        speech_events = [
            m for m in collected if m.get("event") in ("speech_start", "speech_end")
        ]
        assert speech_events == [
            {"event": "speech_start"},
            {"event": "speech_end"},
        ]


def test_close_sets_stop_event_and_joins_worker(stub):
    pipe = STTServer(STTConfig(name="stt-test"))
    assert stub.entered.wait(timeout=2.0)
    pipe._close()
    assert stub.stop_event.is_set()
    assert not pipe._worker.is_alive()
