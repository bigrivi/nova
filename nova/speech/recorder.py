"""Platform microphone recording for voice-to-text.

The desktop webview exposes no microphone API (no getUserMedia, and the
bare MediaRecorder object has no audio source), so recording happens here
in Python behind a small interface, each platform using its own OS audio
API with no third-party dependency:

- macOS: AVAudioRecorder (AAC/m4a), with main-thread hops via Foundation.
- Windows: winmm waveIn (16 kHz mono WAV), driven through ctypes.

Platform frameworks are imported lazily so this module imports cleanly
everywhere; missing pieces raise RuntimeError with an actionable message
instead of breaking server startup.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import tempfile
import threading
import wave
from ctypes import (
    POINTER,
    Structure,
    c_int,
    c_size_t,
    c_uint16,
    c_uint32,
    c_void_p,
)
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_SAMPLE_WIDTH_BYTES = 2
_CHANNELS = 1


class Recorder(Protocol):
    """Single-flight microphone recorder writing to a temp audio file."""

    @property
    def recording(self) -> bool:
        """True while a take is in progress."""
        ...

    def start(self) -> None:
        """Begin recording. Raises RuntimeError when already recording."""
        ...

    def stop(self) -> Path:
        """Stop recording and return the audio file path.

        Raises RuntimeError when nothing is recording.
        """
        ...


#: Reported to the composer when the platform has no native recorder.
UNSUPPORTED_PLATFORM = "native recording is supported on macOS and Windows only"


def create_recorder() -> Recorder:
    """Build the recorder for this platform.

    Raises RuntimeError on platforms without a native recorder.
    """
    if sys.platform == "darwin":
        return MacRecorder()
    if sys.platform == "win32":
        return WindowsRecorder()
    raise RuntimeError(UNSUPPORTED_PLATFORM)


_RUNNER_CLS: Any = None


def _runner_cls() -> Any:
    """The main-thread hop helper, defined exactly once.

    PyObjC registers NSObject subclasses globally: defining the class inside
    the call (as an earlier revision did) crashes the second recording with
    "overriding existing Objective-C class".
    """
    global _RUNNER_CLS
    if _RUNNER_CLS is None:
        from Foundation import NSObject  # type: ignore[import-not-found]

        class _Runner(NSObject):  # type: ignore[no-redef]
            def run_(self, _sender: Any) -> None:
                func, args, box = self._call
                try:
                    box["value"] = func(*args)
                except Exception as exc:
                    box["error"] = exc

        _RUNNER_CLS = _Runner
    return _RUNNER_CLS


def _call_on_main_thread(func: Any, *args: Any) -> Any:
    """Run ``func(*args)`` on the main thread and return its result.

    AVFoundation objects must be created and driven from the main thread;
    the desktop server thread is not it. Foundation ships with the bundled
    cocoa backend, so unlike PyObjCTools this hop works in the frozen app.
    Already on the main thread, the call runs directly (this also keeps the
    hop deadlock-free, since waitUntilDone would block forever on itself).
    """
    if threading.current_thread() is threading.main_thread():
        return func(*args)
    runner_cls = _runner_cls()
    box: dict[str, Any] = {}
    runner = runner_cls.alloc().init()
    runner._call = (func, args, box)
    runner.performSelectorOnMainThread_withObject_waitUntilDone_("run:", None, True)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _mac_file_url(path: str) -> Any:
    from Foundation import NSURL  # type: ignore[import-not-found]

    return NSURL.fileURLWithPath_(path)


def _make_mac_recorder(path: str) -> Any:
    """Create (not start) an AVAudioRecorder writing AAC/m4a to ``path``."""
    import AVFoundation  # type: ignore[import-not-found]

    url = _mac_file_url(path)
    settings = {
        AVFoundation.AVFormatIDKey: AVFoundation.kAudioFormatMPEG4AAC,
        AVFoundation.AVSampleRateKey: float(_SAMPLE_RATE),
        AVFoundation.AVNumberOfChannelsKey: _CHANNELS,
        AVFoundation.AVEncoderAudioQualityKey: (AVFoundation.AVAudioQualityHigh),
    }
    recorder, error = AVFoundation.AVAudioRecorder.alloc().initWithURL_settings_error_(
        url, settings, None
    )
    if recorder is None:
        raise RuntimeError(f"Could not create audio recorder: {error}")
    return recorder


class MacRecorder:
    """Single-flight macOS recorder writing AAC/m4a to a temp file."""

    def __init__(self) -> None:
        self._recorder: Any = None
        self._path: str | None = None

    @property
    def recording(self) -> bool:
        return self._recorder is not None

    def start(self) -> None:
        """Begin recording. Raises RuntimeError when already recording."""
        if self._recorder is not None:
            raise RuntimeError("Recording already in progress")
        # delete=False: the platform recorder writes to this path after the
        # handle is closed, so it has to outlive the statement. A `with` block
        # would delete the file the recorder is about to open.
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            suffix=".m4a", prefix="nova-voice-", delete=False
        )
        tmp.close()
        recorder = _call_on_main_thread(_make_mac_recorder, tmp.name)

        def _begin() -> bool:
            if not recorder.prepareToRecord():
                raise RuntimeError("Audio recorder refused to prepare")
            if not recorder.record():
                raise RuntimeError(
                    "Audio recorder refused to start (microphone permission?)"
                )
            return True

        _call_on_main_thread(_begin)
        self._recorder = recorder
        self._path = tmp.name
        logger.info("Voice recording started: %s", tmp.name)

    def stop(self) -> Path:
        """Stop recording and return the audio file path.

        Raises RuntimeError when nothing is recording.
        """
        recorder, path = self._recorder, self._path
        self._recorder = None
        self._path = None
        if recorder is None or path is None:
            raise RuntimeError("No recording in progress")

        def _finish() -> None:
            recorder.stop()

        _call_on_main_thread(_finish)
        logger.info("Voice recording stopped: %s", path)
        return Path(path)


class _WaveFormatEx(Structure):
    """``WAVEFORMATEX`` from mmreg.h; ctypes lays out the padding."""

    _fields_ = [
        ("wFormatTag", c_uint16),
        ("nChannels", c_uint16),
        ("nSamplesPerSec", c_uint32),
        ("nAvgBytesPerSec", c_uint32),
        ("nBlockAlign", c_uint16),
        ("wBitsPerSample", c_uint16),
        ("cbSize", c_uint16),
    ]


class _WaveHeader(Structure):
    """``WAVEHDR``; ``dwUser``/``reserved`` are pointer-sized, not ``DWORD``."""

    _fields_ = [
        ("lpData", c_void_p),
        ("dwBufferLength", c_uint32),
        ("dwBytesRecorded", c_uint32),
        ("dwUser", c_size_t),
        ("dwFlags", c_uint32),
        ("dwLoops", c_uint32),
        ("lpNext", c_void_p),
        ("reserved", c_size_t),
    ]


#: One tenth of a second of 16 kHz mono 16-bit PCM per buffer.
_BUFFER_BYTES = _SAMPLE_RATE * _SAMPLE_WIDTH_BYTES // 10
_BUFFER_COUNT = 4
_POLL_MS = 200

_WAVE_FORMAT_PCM = 1
_WAVE_MAPPER = -1
_NO_ERROR = 0
_CALLBACK_EVENT = 0x00050000
_HEADER_DONE = 0x00000001
_WAIT_OBJECT_0 = 0
#: waveInUnprepareHeader flag: the buffer was not used.
_WHDR_PREPARED = 0x00000001

_HEADER_ARG = POINTER(_WaveHeader)

#: winmm entry points: name -> (argument types, return type).
_WAVEIN_SIGNATURES: dict[str, tuple[list[Any], Any]] = {
    "waveInOpen": (
        [POINTER(c_void_p), c_uint32, c_void_p, c_size_t, c_size_t, c_uint32],
        c_uint32,
    ),
    "waveInClose": ([c_void_p], c_uint32),
    "waveInStart": ([c_void_p, c_uint32], c_uint32),
    "waveInReset": ([c_void_p], c_uint32),
    "waveInPrepareHeader": ([c_void_p, _HEADER_ARG, c_uint32], c_uint32),
    "waveInUnprepareHeader": ([c_void_p, _HEADER_ARG, c_uint32], c_uint32),
    "waveInAddBuffer": ([c_void_p, _HEADER_ARG, c_uint32], c_uint32),
}

_KERNEL_SIGNATURES: dict[str, tuple[list[Any], Any]] = {
    "WaitForSingleObject": ([c_void_p, c_uint32], c_uint32),
    "CreateEventW": ([c_void_p, c_int, c_int, POINTER(c_uint16)], c_void_p),
    "CloseHandle": ([c_void_p], c_int),
}


def _winmm() -> Any:
    """Return winmm.dll with typed signatures, and kernel32 event helpers.

    Raises RuntimeError off Windows, where neither DLL is loadable.
    """
    if sys.platform != "win32":
        raise RuntimeError("winmm recording is available on Windows only")
    dll = _typed_dll("winmm", _WAVEIN_SIGNATURES)
    kernel = _typed_dll("kernel32", _KERNEL_SIGNATURES, use_last_error=True)
    return dll, kernel


def _typed_dll(
    name: str,
    signatures: dict[str, tuple[list[Any], Any]],
    use_last_error: bool = False,
) -> Any:
    """Load a Windows DLL and pin each listed function's signature."""
    dll = ctypes.WinDLL(name, use_last_error=use_last_error)
    for func_name, (argtypes, restype) in signatures.items():
        func = getattr(dll, func_name)
        func.argtypes = argtypes
        func.restype = restype
    return dll


class _WinmmBuffer:
    """One waveIn buffer: owns its samples plus the header describing them."""

    __slots__ = ("data", "header")

    def __init__(self) -> None:
        self.data = ctypes.create_string_buffer(_BUFFER_BYTES)
        self.header = _WaveHeader()
        self.header.lpData = ctypes.cast(self.data, c_void_p)
        self.header.dwBufferLength = _BUFFER_BYTES

    def done(self) -> bool:
        """True once winmm has flagged the buffer as filled."""
        return bool(int(self.header.dwFlags) & _HEADER_DONE)

    def take(self) -> bytes:
        """Return and clear the captured samples, ready to re-queue."""
        recorded = int(self.header.dwBytesRecorded)
        samples = self.data.raw[:recorded]
        self.header.dwBytesRecorded = 0
        self.header.dwFlags = 0
        return samples


class WindowsRecorder:
    """Single-flight Windows recorder writing WAV to a temp file.

    winmm only signals a win32 event when a buffer fills, so a daemon thread
    wakes on that event, harvests the samples, and re-queues the buffer for
    reuse. Writing the WAV header is stdlib ``wave``; there is no third-party
    audio dependency to bundle.
    """

    def __init__(self) -> None:
        self._dll: Any = None
        self._kernel: Any = None
        self._handle: Any = None
        self._event: Any = None
        self._buffers: list[_WinmmBuffer] = []
        self._frames: list[bytes] = []
        self._path: str | None = None
        self._pump: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closing = threading.Event()

    @property
    def recording(self) -> bool:
        return self._handle is not None

    def start(self) -> None:
        """Begin recording. Raises RuntimeError when already recording."""
        if self.recording:
            raise RuntimeError("Recording already in progress")
        dll, kernel = _winmm()
        handle, event, buffers = self._open_device(dll, kernel)
        # delete=False, for the same reason as the macOS path above.
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            suffix=".wav", prefix="nova-voice-", delete=False
        )
        tmp.close()
        self._dll, self._kernel, self._handle, self._event = (
            dll,
            kernel,
            handle,
            event,
        )
        self._buffers, self._frames = buffers, []
        self._path = tmp.name
        self._closing.clear()
        self._pump = threading.Thread(
            target=self._pump_buffers, name="nova-voice-drain", daemon=True
        )
        self._pump.start()
        logger.info("Voice recording started: %s", tmp.name)

    def _open_device(
        self, dll: Any, kernel: Any
    ) -> tuple[Any, Any, list[_WinmmBuffer]]:
        """Open the default capture device and queue its input buffers."""
        fmt = _WaveFormatEx()
        fmt.wFormatTag = _WAVE_FORMAT_PCM
        fmt.nChannels = _CHANNELS
        fmt.nSamplesPerSec = _SAMPLE_RATE
        fmt.wBitsPerSample = _SAMPLE_WIDTH_BYTES * 8
        fmt.nBlockAlign = _CHANNELS * _SAMPLE_WIDTH_BYTES
        fmt.nAvgBytesPerSec = _SAMPLE_RATE * fmt.nBlockAlign

        event = kernel.CreateEventW(None, 0, 0, None)
        handle = c_void_p()
        rc = dll.waveInOpen(
            ctypes.byref(handle),
            _WAVE_MAPPER & 0xFFFFFFFF,
            ctypes.byref(fmt),
            event or 0,
            0,
            _CALLBACK_EVENT,
        )
        if rc != _NO_ERROR or not handle:
            kernel.CloseHandle(event or 0)
            raise RuntimeError(
                f"Could not open the microphone (winmm error {rc}); "
                "check Windows privacy settings for microphone access"
            )
        buffers: list[_WinmmBuffer] = []
        try:
            for _ in range(_BUFFER_COUNT):
                buffer = _WinmmBuffer()
                rc = dll.waveInPrepareHeader(handle, ctypes.byref(buffer.header), 0)
                if rc != _NO_ERROR:
                    raise RuntimeError(
                        f"Could not prepare an input buffer (winmm {rc})"
                    )
                buffers.append(buffer)
                rc = dll.waveInAddBuffer(handle, ctypes.byref(buffer.header), 0)
                if rc != _NO_ERROR:
                    raise RuntimeError(f"Could not queue an input buffer (winmm {rc})")
            rc = dll.waveInStart(handle, 0)
            if rc != _NO_ERROR:
                raise RuntimeError(f"Could not start recording (winmm {rc})")
        except RuntimeError:
            self._close_device(dll, kernel, handle, event, buffers)
            raise
        return handle, event, buffers

    def _pump_buffers(self) -> None:
        """Drain filled buffers on the win32 event until teardown starts."""
        kernel = self._kernel
        while not self._closing.is_set():
            waited = kernel.WaitForSingleObject(self._event, _POLL_MS)
            if waited != _WAIT_OBJECT_0:
                continue
            with self._lock:
                if self._handle is None:
                    return
                for buffer in self._buffers:
                    if not buffer.done():
                        continue
                    self._frames.append(buffer.take())
                    rc = self._dll.waveInAddBuffer(
                        self._handle, ctypes.byref(buffer.header), 0
                    )
                    if rc != _NO_ERROR:
                        logger.warning(
                            "Re-queueing an input buffer failed (winmm %s)", rc
                        )

    @staticmethod
    def _close_device(
        dll: Any,
        kernel: Any,
        handle: Any,
        event: Any,
        buffers: list[_WinmmBuffer],
    ) -> None:
        """Return the device and its buffers, never raising."""
        try:
            dll.waveInReset(handle)
            for buffer in buffers:
                dll.waveInUnprepareHeader(
                    handle, ctypes.byref(buffer.header), _WHDR_PREPARED
                )
        finally:
            dll.waveInClose(handle)
            kernel.CloseHandle(event)

    def stop(self) -> Path:
        """Stop recording, write the WAV file, return its path.

        Raises RuntimeError when nothing is recording.
        """
        with self._lock:
            dll, kernel, handle, event = (
                self._dll,
                self._kernel,
                self._handle,
                self._event,
            )
            buffers, frames, path = self._buffers, self._frames, self._path
            self._dll = self._kernel = self._handle = self._event = None
            self._buffers, self._frames, self._path = [], [], None
        if handle is None or path is None:
            raise RuntimeError("No recording in progress")
        self._closing.set()
        if self._pump is not None:
            self._pump.join(timeout=2.0)
            self._pump = None
        # waveInReset flags every pending buffer done, so the samples the
        # pump thread had not harvested yet are still readable.
        for buffer in buffers:
            if buffer.done():
                frames.append(buffer.take())
        self._close_device(dll, kernel, handle, event, buffers)
        self._write_wav(path, b"".join(frames))
        logger.info("Voice recording stopped: %s", path)
        return Path(path)

    @staticmethod
    def _write_wav(path: str, samples: bytes) -> None:
        """Write 16 kHz mono 16-bit PCM as a WAV file."""
        with wave.open(path, "wb") as wav:
            wav.setnchannels(_CHANNELS)
            wav.setsampwidth(_SAMPLE_WIDTH_BYTES)
            wav.setframerate(_SAMPLE_RATE)
            wav.writeframes(samples)
