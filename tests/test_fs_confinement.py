"""Remote clients can browse only the directories the server is configured to expose.

``/api/fs/list`` used to return any directory the process could read, to anyone who
reached the API. Local clients keep the unrestricted listing they had (they already
run shell commands as this user). A remote client is confined to ``server.fs_roots``,
or to the user's home directory when none is configured, and the check is made on
the resolved path so ``..`` and symlinks cannot leave the tree.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nova.server import create_app
from nova.server.fs_browse import list_directory, remote_fs_roots
from nova.settings import Settings


def _app(monkeypatch, tmp_path, server: dict):
    home = tmp_path / "nova-home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "server": server}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    return create_app(settings=Settings.load_config())


def _local(app):
    return TestClient(app, client=("127.0.0.1", 40000), headers={"host": "127.0.0.1:8765"})


def _remote(app):
    return TestClient(app, client=("203.0.113.9", 40000), headers={"host": "nova.lan"})


def test_list_directory_without_roots_is_unrestricted(tmp_path):
    listing = list_directory(str(tmp_path))

    assert listing.path == str(tmp_path.resolve())


def test_a_path_inside_a_root_is_listed(tmp_path):
    (tmp_path / "project").mkdir()

    listing = list_directory(str(tmp_path), roots=[tmp_path.resolve()])

    assert [entry.name for entry in listing.entries] == ["project"]


def test_a_path_outside_every_root_is_refused(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    with pytest.raises(PermissionError):
        list_directory(str(outside), roots=[allowed.resolve()])


def test_dot_dot_cannot_climb_out_of_a_root(tmp_path):
    allowed = tmp_path / "allowed"
    (allowed / "child").mkdir(parents=True)

    with pytest.raises(PermissionError):
        list_directory(str(allowed / "child" / ".." / ".."), roots=[allowed.resolve()])


def test_a_symlink_inside_a_root_cannot_point_outside_it(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PermissionError):
        list_directory(str(allowed / "link"), roots=[allowed.resolve()])


def test_remote_roots_default_to_home_and_expand_user(monkeypatch, tmp_path):
    monkeypatch.setattr("nova.server.fs_browse.Path.home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert remote_fs_roots(()) == [tmp_path.resolve()]
    assert remote_fs_roots(["~/work"]) == [(tmp_path / "work").resolve()]


def test_a_remote_client_is_refused_outside_home_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr("nova.server.fs_browse.Path.home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    app = _app(monkeypatch, tmp_path, {})

    response = _remote(app).get("/api/fs/list", params={"path": str(tmp_path)})

    assert response.status_code == 403


def test_a_remote_client_can_browse_inside_its_configured_root(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    (projects / "api").mkdir(parents=True)
    app = _app(monkeypatch, tmp_path, {"fs_roots": [str(projects)]})

    response = _remote(app).get("/api/fs/list", params={"path": str(projects)})

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == ["api"]


def test_a_remote_client_cannot_browse_the_filesystem_root(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    app = _app(monkeypatch, tmp_path, {"fs_roots": [str(projects)]})

    response = _remote(app).get("/api/fs/list", params={"path": "/"})

    assert response.status_code == 403


def test_a_local_client_keeps_unrestricted_browsing(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    app = _app(monkeypatch, tmp_path, {"fs_roots": [str(projects)]})

    response = _local(app).get("/api/fs/list", params={"path": str(tmp_path)})

    assert response.status_code == 200


def test_fs_roots_must_be_a_list_of_paths(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="fs_roots"):
        _app(monkeypatch, tmp_path, {"fs_roots": "/Users/andy"})
