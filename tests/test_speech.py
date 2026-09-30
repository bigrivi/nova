"""Tests for voice-to-text: service gating plus Groq Whisper client."""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from nova.server import create_app
from nova.settings import Settings
from nova.speech import recorder as recorder_module
from nova.speech.recorder import Recorder
from nova.speech.service import SpeechService, TranscriptionError


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    @property
    def recording(self) -> bool:
        return self.started and not self.stopped

    def start(self) -> None:
        if self.started and not self.stopped:
            raise RuntimeError("Recording already in progress")
        self.started = True
        self.stopped = False

    def stop(self) -> Path:
        if not self.recording:
            raise RuntimeError("No recording in progress")
        self.stopped = True
        path = Path("/tmp/nova-voice-test.m4a")
        path.write_bytes(b"fake-audio")
        return path


class _FakeTransport(httpx.AsyncBaseTransport):
    """Capture the request, then answer from a canned response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        self.bodies.append(request.content)
        return self.response


def _settings_with_key(monkeypatch, tmp_path, **overrides) -> Settings:
    home = tmp_path / "nova-voice"
    home.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "providers": {},
        "transcription": {
            "api_key": "gsk-test",
            "model": "whisper-large-v3-turbo",
            "language": "zh",
            **overrides,
        },
    }
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return Settings.load_config()


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _wait_until(predicate, timeout: float = 2.0) -> None:
    """Wait for a background thread to reach a state, or fail the test."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached within the timeout")


def test_status_disabled_without_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-off"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    service = SpeechService(Settings.load_config(), recorder=_FakeRecorder())
    assert service.status()["enabled"] is False


def test_status_enabled_with_key_reports_groq_model(monkeypatch, tmp_path) -> None:
    service = SpeechService(
        _settings_with_key(monkeypatch, tmp_path), recorder=_FakeRecorder()
    )
    status = service.status()
    assert status["enabled"] is True
    assert status["provider"] == "groq"
    assert status["model"] == "whisper-large-v3-turbo"
    assert status["recording_since_ms"] is None


def test_status_reports_take_start_for_a_reloaded_window(monkeypatch, tmp_path) -> None:
    """A view that mounts mid-take must be able to resume the clock."""
    import time

    service = SpeechService(
        _settings_with_key(monkeypatch, tmp_path), recorder=_FakeRecorder()
    )
    before = int(time.time() * 1000)
    service.start()
    since = service.status()["recording_since_ms"]
    assert since is not None and since >= before

    service.cancel()
    assert service.status()["recording_since_ms"] is None


def test_transcribe_posts_openai_compatible_multipart(monkeypatch, tmp_path) -> None:
    import nova.speech.client as client_module

    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings, recorder=_FakeRecorder())
    audio = tmp_path / "take.m4a"
    audio.write_bytes(b"fake-audio-bytes")

    transport = _FakeTransport(httpx.Response(200, json={"text": "你好"}))
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)
    result = _run(service.transcribe_file(audio))

    assert result == {"text": "你好"}
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.path == "/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer gsk-test"
    body = transport.bodies[0]
    assert b"whisper-large-v3-turbo" in body
    assert b"fake-audio-bytes" in body
    assert b'name="language"' in body


def test_transcribe_rejects_bad_key_as_transcription_error(
    monkeypatch, tmp_path
) -> None:
    import nova.speech.client as client_module

    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings, recorder=_FakeRecorder())
    audio = tmp_path / "take.m4a"
    audio.write_bytes(b"x")

    transport = _FakeTransport(
        httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)
    with pytest.raises(TranscriptionError, match="401"):
        _run(service.transcribe_file(audio))


def test_empty_audio_returns_empty_text(monkeypatch, tmp_path) -> None:
    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings, recorder=_FakeRecorder())
    audio = tmp_path / "empty.m4a"
    audio.write_bytes(b"")
    assert _run(service.transcribe_file(audio)) == {"text": ""}


def test_routes_registered(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-app"))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/speech/status").status_code == 200
    assert client.post("/api/speech/cancel").status_code == 409


def test_cancel_discards_audio_without_transcribing(monkeypatch, tmp_path) -> None:
    """Cancelling a take must not call the provider or leave the file behind."""
    import nova.speech.service as service_module

    def _boom(*_args, **_kwargs):
        raise AssertionError("cancel must not transcribe")

    monkeypatch.setattr(service_module.transcribe_client, "transcribe_file", _boom)
    recorder = _FakeRecorder()
    service = SpeechService(
        _settings_with_key(monkeypatch, tmp_path), recorder=recorder
    )
    recorder.start()

    assert service.cancel() == {"recording": False}
    assert not Path("/tmp/nova-voice-test.m4a").exists()

    with pytest.raises(RuntimeError, match="No recording in progress"):
        service.cancel()


def test_cancel_without_a_recorder_is_a_conflict_not_a_crash(
    monkeypatch, tmp_path
) -> None:
    """No recorder means nothing to stop, and that is a 409, not a 500.

    Reproduces the unsupported-platform path on any host by handing the app a
    recorder-less service, which is what create_recorder leaves behind where
    native recording does not exist. macOS never hit this: there a real
    recorder refuses the cancel itself, so the route test passed for an
    unrelated reason.
    """
    from fastapi.testclient import TestClient

    import nova.speech.service as service_module

    def _boom() -> Recorder:
        raise RuntimeError("native recording is supported on macOS and Windows only")

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-unsupported"))
    monkeypatch.setattr(service_module, "create_recorder", _boom)
    app = create_app(settings=Settings.load_config())
    assert app.state.speech_service._recorder is None

    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/api/speech/cancel").status_code == 409


def test_service_reports_reason_when_no_recorder(monkeypatch, tmp_path) -> None:
    import nova.speech.service as service_module

    def _boom() -> Recorder:
        raise RuntimeError("native recording is supported on macOS and Windows only")

    monkeypatch.setattr(service_module, "create_recorder", _boom)
    service = SpeechService(_settings_with_key(monkeypatch, tmp_path))
    status = service.status()
    assert status["enabled"] is False
    assert "macOS and Windows only" in str(status["reason"])
    with pytest.raises(RuntimeError, match="macOS and Windows only"):
        service.start()


def test_main_thread_hop_runs_inline_on_the_main_thread() -> None:
    """Already on the main thread, so the hop is a direct call.

    Cross-platform on purpose: the fallback is what keeps the desktop server
    thread from deadlocking on waitUntilDone, and on Linux it is the only path
    there is.
    """
    calls: list[str] = []

    def _record(value: str) -> str:
        calls.append(value)
        return value

    assert recorder_module._call_on_main_thread(_record, "a") == "a"
    assert calls == ["a"]


@pytest.mark.skipif(
    sys.platform != "darwin", reason="the ObjC helper only exists where PyObjC does"
)
def test_main_thread_hop_defines_one_runner() -> None:
    """The ObjC helper class must be defined once, or the second take dies."""
    recorder_module._RUNNER_CLS = None
    first = recorder_module._runner_cls()
    assert recorder_module._runner_cls() is first


def test_main_thread_hop_propagates_errors() -> None:
    def _boom() -> None:
        raise ValueError("nope")

    recorder_module._RUNNER_CLS = None
    with pytest.raises(ValueError, match="nope"):
        recorder_module._call_on_main_thread(_boom)


def test_winmm_buffer_takes_recorded_samples_and_resets() -> None:
    buffer = recorder_module._WinmmBuffer()
    assert buffer.done() is False
    assert int(buffer.header.dwBufferLength) == recorder_module._BUFFER_BYTES

    buffer.data.raw = b"\x01\x02\x03\x04" + b"\x00" * (
        recorder_module._BUFFER_BYTES - 4
    )
    buffer.header.dwBytesRecorded = 4
    buffer.header.dwFlags = recorder_module._HEADER_DONE

    assert buffer.done() is True
    assert buffer.take() == b"\x01\x02\x03\x04"
    assert buffer.done() is False
    assert int(buffer.header.dwBytesRecorded) == 0
    assert buffer.take() == b""


def test_windows_recorder_writes_wav_from_frames(tmp_path) -> None:
    samples = b"\x10\x20" * 8000
    out = tmp_path / "take.wav"
    recorder_module.WindowsRecorder._write_wav(str(out), samples)

    with wave.open(str(out), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (
            1,
            2,
            recorder_module._SAMPLE_RATE,
        )
        assert wav.readframes(wav.getnframes()) == samples


def test_windows_recorder_requires_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows only"):
        recorder_module._winmm()


class _FakeWinmm:
    """Stand-in for winmm.dll: records calls, tracks the buffers it is given."""

    def __init__(self, open_error: int = 0) -> None:
        self.open_error = open_error
        self.calls: list[str] = []
        self.headers: list[Any] = []

    def waveInOpen(self, *args) -> int:
        self.calls.append("open")
        if self.open_error:
            return self.open_error
        args[0]._obj.value = 0x1234
        return 0

    def waveInClose(self, _handle) -> int:
        self.calls.append("close")
        return 0

    def waveInStart(self, _handle, _id) -> int:
        self.calls.append("start")
        return 0

    def waveInPrepareHeader(self, _handle, header, _flags) -> int:
        self.calls.append("prepare")
        self.headers.append(header._obj)
        return 0

    def waveInAddBuffer(self, _handle, header, _flags) -> int:
        self.calls.append("add")
        header._obj.dwFlags = 0
        return 0

    def waveInUnprepareHeader(self, _handle, _header, _flags) -> int:
        self.calls.append("unprepare")
        return 0

    def waveInReset(self, _handle) -> int:
        self.calls.append("reset")
        for header in self.headers:
            header.dwFlags = recorder_module._HEADER_DONE
        return 0


class _FakeKernel:
    """Stand-in for the kernel32 event functions, with manual signalling."""

    def __init__(self) -> None:
        self.signals = 0
        self.closed: list[int] = []

    def CreateEventW(self, *_args) -> int:
        return 0xBEEF

    def WaitForSingleObject(self, _handle, _ms) -> int:
        if self.signals > 0:
            self.signals -= 1
            return recorder_module._WAIT_OBJECT_0
        return 0x00000102

    def CloseHandle(self, handle) -> int:
        self.closed.append(int(handle))
        return 1


def _fake_winmm(monkeypatch, open_error: int = 0):
    """Patch ``_winmm`` so a WindowsRecorder can be driven on any platform."""
    fake = _FakeWinmm(open_error)
    kernel = _FakeKernel()
    monkeypatch.setattr(recorder_module, "_winmm", lambda: (fake, kernel))
    return fake, kernel


def test_windows_recorder_harvests_buffer_on_event(monkeypatch) -> None:
    fake, kernel = _fake_winmm(monkeypatch)
    recorder = recorder_module.WindowsRecorder()
    recorder.start()
    assert recorder.recording is True
    assert fake.calls[:3] == ["open", "prepare", "add"]
    assert fake.calls.count("add") == recorder_module._BUFFER_COUNT
    buffers = recorder._buffers
    assert len(buffers) == recorder_module._BUFFER_COUNT

    for buffer in buffers:
        buffer.data.raw = b"\x11\x22" * 100
        buffer.header.dwBytesRecorded = 200
        buffer.header.dwFlags = recorder_module._HEADER_DONE
    kernel.signals = 1
    _wait_until(lambda: len(recorder._frames) == len(buffers))

    path = recorder.stop()
    assert recorder.recording is False
    assert fake.calls[-6:-1] == [
        "reset",
        "unprepare",
        "unprepare",
        "unprepare",
        "unprepare",
    ]
    assert fake.calls[-1] == "close"
    assert kernel.closed == [0xBEEF]
    with wave.open(str(path), "rb") as wav:
        # 200 bytes per buffer, 2 bytes per 16-bit sample.
        assert wav.getnframes() == 100 * len(buffers)
    path.unlink()

    with pytest.raises(RuntimeError, match="No recording in progress"):
        recorder.stop()


def test_windows_recorder_stops_without_any_signal(monkeypatch) -> None:
    """Stopping early must still capture partial data, not an empty file."""
    _fake, _kernel = _fake_winmm(monkeypatch)
    recorder = recorder_module.WindowsRecorder()
    recorder.start()
    # Nothing was ever flagged done: waveInReset does that on the way out.
    path = recorder.stop()
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 0
    path.unlink()


def test_windows_recorder_reports_open_failure(monkeypatch) -> None:
    _fake, kernel = _fake_winmm(monkeypatch, open_error=5)
    recorder = recorder_module.WindowsRecorder()
    with pytest.raises(RuntimeError, match="winmm error 5"):
        recorder.start()
    assert recorder.recording is False
    assert kernel.closed == [0xBEEF]


def test_create_recorder_rejects_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="macOS and Windows only") as excinfo:
        recorder_module.create_recorder()
    assert str(excinfo.value) == recorder_module.UNSUPPORTED_PLATFORM


def test_create_recorder_picks_platform_implementation(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(
        recorder_module.create_recorder(), recorder_module.WindowsRecorder
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(recorder_module.create_recorder(), recorder_module.MacRecorder)
