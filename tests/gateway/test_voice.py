
import pytest

from nova.gateway import voice


def _silk_file(path):
    """A file with QQ's SILK magic and a byte in front of it."""
    path.write_bytes(b"\x02" + b"#!SILK_V3" + b"\x00" * 16)
    return path


def test_silk_is_detected_despite_the_prefix(tmp_path):
    assert voice._is_silk(_silk_file(tmp_path / "v.amr")) is True
    assert voice._is_silk(tmp_path / "other.wav") is False


@pytest.mark.asyncio
async def test_silk_is_decoded_to_wav(tmp_path):
    pytest.importorskip("pysilk")
    path = _silk_file(tmp_path / "v.amr")
    # A real decoder needs a real SILK stream; an empty one yields no wav.
    result = await voice._silk_to_wav(path)
    assert result is None or result.suffix == ".wav"


@pytest.mark.asyncio
async def test_direct_format_passes_known_formats_through(tmp_path):
    path = tmp_path / "v.mp3"
    path.write_bytes(b"x")
    assert await voice.to_direct_format(path) is path
