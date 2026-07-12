"""Tests for the shell tool."""

from unittest.mock import MagicMock

import pytest

from nova.tools.shell import shell, is_dangerous


def test_is_dangerous():
    assert is_dangerous("rm -rf /") is True
    assert is_dangerous("rm -rf *") is True
    assert is_dangerous("rm -rf .") is True
    assert is_dangerous("mkfs.ext4 /dev/sda1") is True
    assert is_dangerous("ls -la") is False
    assert is_dangerous("echo hello") is False


@pytest.mark.asyncio
async def test_simple_command():
    result = await shell(command="echo hello")
    assert result.success is True
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_empty_output():
    result = await shell(command="true")
    assert result.success is True
    assert result.content == "(no output)"


@pytest.mark.asyncio
async def test_diagnostic_stderr_no_marker():
    """exit(0) with stderr must NOT have [stderr] marker."""
    result = await shell(command="echo diagnostic >&2; echo output")
    assert result.success is True
    assert "output" in result.content
    assert "diagnostic" in result.content
    assert "[stderr]" not in result.content


@pytest.mark.asyncio
async def test_failure_returns_false():
    """Non-zero exit code returns success=False."""
    result = await shell(command="exit 1")
    assert result.success is False


@pytest.mark.asyncio
async def test_failure_prepends_stderr_marker():
    result = await shell(command="echo error >&2; exit 1")
    assert result.success is False
    assert result.content.startswith("[stderr]")


@pytest.mark.asyncio
async def test_dangerous_command_rejected():
    """Shell safety checks moved from shell() to ShellToolBehavior."""
    from nova.tools.behavior import ShellToolBehavior, TurnContext

    mock_approval = MagicMock()
    mock_approval.pre_request.return_value = ""
    behavior = ShellToolBehavior(mock_approval)
    ctx = TurnContext()

    pre_check = await behavior.before_execute({"command": "rm -rf /"}, ctx)
    assert pre_check.allowed is False
    assert "recursive delete" in pre_check.reject_reason

    pre_check = await behavior.before_execute(
        {"command": "dd if=/dev/zero of=/dev/sda"}, ctx
    )
    assert pre_check.allowed is False
    assert pre_check.reject_reason is not None

    pre_check = await behavior.before_execute({"command": "ls -la"}, ctx)
    assert pre_check.allowed is True
    assert pre_check.approval_request is None


@pytest.mark.asyncio
async def test_timeout():
    result = await shell(command="sleep 10", timeout=1)
    assert result.success is False
    assert "Timed out after" in result.content
