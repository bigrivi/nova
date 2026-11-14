"""Where the running backend is, for a client that did not start it.

The backend writes this file once it is listening; a client that finds the file,
and finds the process in it alive, talks to that backend instead of starting a
second one. It is a file on purpose: a file cannot be proxied, so a proxy in the
environment cannot hide the backend from the client that needs it.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nova.settings import Settings

log = logging.getLogger(__name__)

FILENAME = "server.json"


def registration_path(settings: Settings) -> Path:
    """Where the record lives, beside the rest of Nova's state."""
    return settings.home / FILENAME


def write_registration(settings: Settings, url: str, pid: int | None = None) -> Path:
    """Record the address this backend is serving.

    Args:
        settings: Loaded settings, for the state directory.
        url: The address the backend is listening on.
        pid: The process that serves it; defaults to this one.

    Returns:
        The path written.
    """
    path = registration_path(settings)
    payload = {
        "url": url,
        "pid": pid if pid is not None else os.getpid(),
        "started_at": int(time.time()),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError:
        # A backend that cannot record itself is still a working backend.
        log.warning("could not write the server record at %s", path, exc_info=True)
    return path


def read_registration(settings: Settings) -> dict[str, Any] | None:
    """The recorded backend, or None when there is none.

    Args:
        settings: Loaded settings, for the state directory.

    Returns:
        The record, or None when it is missing or unreadable.
    """
    try:
        payload = json.loads(registration_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_registration(settings: Settings, pid: int | None = None) -> None:
    """Drop the record, unless it has changed hands.

    Best effort: uvicorn re-raises the signal that stopped it, so the record
    usually outlives a `SIGTERM` shutdown. That is why a reader has to check
    the pid: a record is a hint, never proof that a backend is listening.

    Args:
        settings: Loaded settings, for the state directory.
        pid: The process that is stopping. When it does not match the record,
            the record belongs to someone else and is left alone.
    """
    payload = read_registration(settings)
    if payload is None:
        return
    if pid is not None and int(payload.get("pid") or 0) != pid:
        return
    try:
        registration_path(settings).unlink()
    except OSError:
        pass


def process_alive(pid: int) -> bool:
    """Whether a process still exists. Signal zero only asks the kernel.

    Args:
        pid: The process to ask about.

    Returns:
        True when the process exists and this user may signal it.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, and belongs to someone else: still a live process.
        return True
    except OSError:
        return False
    return True


def accepts_connections(url: str, timeout: float = 0.5) -> bool:
    """Whether something is listening at an address.

    A bare TCP connect, never an HTTP request: a request to a loopback address
    goes through the environment proxy when one is set, and the proxy's answer
    would be read as "no backend".

    Args:
        url: The recorded address.
        timeout: How long the connection attempt may take.

    Returns:
        True when a connection was accepted.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        return False
    if not host or port is None:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_running(settings: Settings, timeout: float = 0.5) -> str | None:
    """The address of a backend that is alive and listening.

    Args:
        settings: Loaded settings, for the state directory.
        timeout: How long the connection attempt may take.

    Returns:
        The address, or None when the record is missing, stale, or points at a
        port nothing answers on.
    """
    payload = read_registration(settings)
    if payload is None:
        return None
    url = payload.get("url")
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if not isinstance(url, str) or pid <= 0:
        return None
    if not process_alive(pid):
        return None
    if not accepts_connections(url, timeout):
        return None
    return url


def wait_for_running(settings: Settings, timeout: float = 10.0) -> str | None:
    """Wait for a backend another process is starting to record itself.

    Args:
        settings: Loaded settings, for the state directory.
        timeout: How long to keep looking.

    Returns:
        The address, or None when none appeared in time.
    """
    deadline = time.monotonic() + timeout
    while True:
        url = find_running(settings)
        if url is not None:
            return url
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)
