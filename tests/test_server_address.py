"""Where the backend records its address, and the address a client can open.

``server.json`` is how a second client finds a backend it did not start. It has
to survive being written by one process and read by another, and it has to be
ignored rather than trusted when it is stale or malformed: a client that
believes a bad record talks to nothing.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from nova.server.app import reachable_host
from nova.server.registration import (
    clear_registration,
    find_running,
    read_registration,
    registration_path,
    wait_for_running,
    write_registration,
)
from nova.settings import get_settings


def test_a_written_record_can_be_read_back():
    settings = get_settings()

    write_registration(settings, "http://127.0.0.1:51914", pid=4242)

    record = read_registration(settings)
    assert record is not None
    assert (record["url"], record["pid"]) == ("http://127.0.0.1:51914", 4242)


def test_the_record_names_the_writing_process_by_default():
    settings = get_settings()

    write_registration(settings, "http://127.0.0.1:51914")

    record = read_registration(settings)
    assert record is not None
    assert record["pid"] > 0


def test_the_record_lives_in_nova_home():
    settings = get_settings()

    path = write_registration(settings, "http://127.0.0.1:51914")

    assert path == settings.home / "server.json"
    assert path == registration_path(settings)


def test_a_missing_record_reads_as_none():
    assert read_registration(get_settings()) is None


def test_a_malformed_record_reads_as_none():
    settings = get_settings()
    registration_path(settings).parent.mkdir(parents=True, exist_ok=True)
    registration_path(settings).write_text("{not json", encoding="utf-8")

    assert read_registration(settings) is None


def test_a_record_that_is_not_an_object_reads_as_none():
    settings = get_settings()
    registration_path(settings).parent.mkdir(parents=True, exist_ok=True)
    registration_path(settings).write_text(json.dumps(["url"]), encoding="utf-8")

    assert read_registration(settings) is None


def test_clearing_removes_the_record():
    settings = get_settings()
    write_registration(settings, "http://127.0.0.1:51914", pid=4242)

    clear_registration(settings, pid=4242)

    assert read_registration(settings) is None


def test_a_stopping_process_leaves_a_record_that_changed_hands():
    settings = get_settings()
    write_registration(settings, "http://127.0.0.1:60000", pid=9999)

    clear_registration(settings, pid=4242)

    record = read_registration(settings)
    assert record is not None
    assert record["pid"] == 9999


@pytest.mark.parametrize("host", ["0.0.0.0", "::", ""])
def test_a_wildcard_bind_is_reported_as_loopback(host):
    # WebKit refuses to navigate to 0.0.0.0 and shows a blank window.
    assert reachable_host(host) == "127.0.0.1"


def test_an_explicit_host_is_reported_as_itself():
    assert reachable_host("192.168.1.20") == "192.168.1.20"


def _listening_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    return listener


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_a_recorded_backend_that_still_listens_is_found():
    settings = get_settings()
    listener = _listening_socket()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    write_registration(settings, url, pid=os.getpid())
    try:
        assert find_running(settings) == url
    finally:
        listener.close()


def test_a_recorded_backend_whose_process_is_gone_is_not_found():
    settings = get_settings()
    write_registration(settings, "http://127.0.0.1:51999", pid=999_999_999)

    assert find_running(settings) is None


def test_a_record_whose_port_nobody_listens_on_is_not_found():
    settings = get_settings()
    write_registration(
        settings, f"http://127.0.0.1:{_free_port()}", pid=os.getpid()
    )

    assert find_running(settings) is None


def test_waiting_for_a_backend_that_never_appears_gives_up():
    assert wait_for_running(get_settings(), timeout=0) is None
