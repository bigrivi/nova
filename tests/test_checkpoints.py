"""Turn checkpoints: capture the pre-image, then put it back.

A rewind that silently overwrites work someone did after the agent ran is worse
than no rewind, so the conflict path gets as much coverage as the happy path.
"""

import json
from pathlib import Path

import pytest

from nova import checkpoints
from nova.tools import checkpoints as capture


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _begin(workspace: Path, checkpoint_id: str = "msg-1") -> None:
    capture.begin_turn(
        session_id="s1",
        checkpoint_id=checkpoint_id,
        label="do the thing",
        workspace=str(workspace),
    )


def test_captures_a_pre_image_and_its_post_hash(workspace: Path) -> None:
    target = workspace / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    _begin(workspace)

    capture.record_write(target, "old\n", "new\n")
    target.write_text("new\n", encoding="utf-8")

    summaries = checkpoints.list_checkpoints("s1")
    assert [item.checkpoint_id for item in summaries] == ["msg-1"]
    assert summaries[0].files == 1
    assert summaries[0].label == "do the thing"


def test_one_pre_image_per_path_per_turn(workspace: Path) -> None:
    target = workspace / "a.txt"
    target.write_text("first\n", encoding="utf-8")
    _begin(workspace)

    capture.record_write(target, "first\n", "second\n")
    capture.record_write(target, "second\n", "third\n")
    target.write_text("third\n", encoding="utf-8")

    report = checkpoints.restore_files("s1", "msg-1")
    assert report.restored == [str(target)]
    # The first pre-image is the one a rewind has to restore.
    assert target.read_text(encoding="utf-8") == "first\n"


def test_creating_a_file_is_undone_by_deleting_it(workspace: Path) -> None:
    target = workspace / "nested" / "new.txt"
    target.parent.mkdir()
    _begin(workspace)

    capture.record_write(target, None, "hello\n")
    target.write_text("hello\n", encoding="utf-8")

    report = checkpoints.restore_files("s1", "msg-1")
    assert report.deleted == [str(target)]
    assert not target.exists()
    # The directory the turn created goes with it.
    assert not target.parent.exists()


def test_binary_and_oversized_content_is_reported_not_dropped(
    workspace: Path,
) -> None:
    binary = workspace / "bin.dat"
    big = workspace / "big.txt"
    binary.write_bytes(b"\x00\x01")
    _begin(workspace)

    capture.record_write(binary, "\x00binary", "x")
    capture.record_write(big, "x" * (capture.MAX_SNAPSHOT_BYTES + 1), "y")

    report = checkpoints.restore_files("s1", "msg-1")
    reasons = {item["path"]: item["reason"] for item in report.skipped}
    assert reasons[str(binary)] == "binary"
    assert reasons[str(big)] == "too-large"


def test_a_file_changed_after_the_agent_is_left_alone(workspace: Path) -> None:
    target = workspace / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    _begin(workspace)
    capture.record_write(target, "old\n", "agent\n")
    target.write_text("agent\n", encoding="utf-8")

    # Someone edits afterwards.
    target.write_text("human\n", encoding="utf-8")

    report = checkpoints.restore_files("s1", "msg-1")
    assert report.restored == []
    assert report.skipped == [{"path": str(target), "reason": "changed-since"}]
    assert target.read_text(encoding="utf-8") == "human\n"

    forced = checkpoints.restore_files("s1", "msg-1", force=True)
    assert forced.restored == [str(target)]
    assert target.read_text(encoding="utf-8") == "old\n"


def test_an_entry_pointing_outside_the_workspace_is_refused(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")
    _begin(workspace)

    directory = capture.checkpoint_root() / "s1" / "msg-1"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps({"checkpoint_id": "msg-1", "workspace": str(workspace)}),
        encoding="utf-8",
    )
    (directory / "entries.jsonl").write_text(
        json.dumps({"path": str(outside), "existed": False, "post_hash": "x"}) + "\n",
        encoding="utf-8",
    )

    report = checkpoints.restore_files("s1", "msg-1")

    assert report.skipped == [{"path": str(outside), "reason": "outside-workspace"}]
    assert outside.read_text(encoding="utf-8") == "keep\n"


def test_missing_checkpoint_raises(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError):
        checkpoints.restore_files("s1", "nope")


def test_dropping_newer_checkpoints(workspace: Path) -> None:
    target = workspace / "a.txt"
    target.write_text("a\n", encoding="utf-8")
    for checkpoint_id in ("msg-1", "msg-2", "msg-3"):
        _begin(workspace, checkpoint_id)
        capture.record_write(target, "a\n", checkpoint_id)

    checkpoints.discard_checkpoints_from("s1", "msg-2")

    remaining = [item.checkpoint_id for item in checkpoints.list_checkpoints("s1")]
    assert remaining == ["msg-1"]
